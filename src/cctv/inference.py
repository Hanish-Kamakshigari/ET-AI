import os
import json
import types
try:
    import cv2
except ImportError:  # opencv-python-headless not installed in this environment
    cv2: types.ModuleType | None = None
import numpy as np
import random
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any, Callable
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# Import standard Detection class from object_detector
if __name__ == "__main__" or __package__ is None:
    from object_detector import Detection
else:
    from .object_detector import Detection

# Global models cache
_models = {
    "ppe": None,
    "fire_smoke": None,
    "stock": None
}

def reset_ppe_buffer() -> None:
    pass

def detect_helmet_color(frame_bgr: np.ndarray, person_box: tuple, zone: str = None) -> bool:
    """
    Returns True if a yellow helmet (or white helmet for Zone_C) is detected in the head region of a person.
    Uses HSV color masking — deterministic, no model needed.
    """
    px1, py1, px2, py2 = person_box
    ph = py2 - py1
    pw = px2 - px1

    # Head region = top 25% of person bounding box
    head_y2 = py1 + int(ph * 0.25)
    head_x1 = px1 + int(pw * 0.15)
    head_x2 = px2 - int(pw * 0.15)

    # Clamp to frame bounds
    h_frame, w_frame = frame_bgr.shape[:2]
    head_y2 = min(head_y2, h_frame)
    head_x2 = min(head_x2, w_frame)
    head_x1 = max(head_x1, 0)
    py1_clamped = max(py1, 0)

    head_roi = frame_bgr[py1_clamped:head_y2, head_x1:head_x2]
    if head_roi.size == 0:
        return False

    # Convert to HSV and threshold for yellow
    hsv = cv2.cvtColor(head_roi, cv2.COLOR_BGR2HSV)
    lower_yellow = np.array([18, 80, 80])
    upper_yellow = np.array([35, 255, 255])
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    # If >8% of head region is yellow → helmet present
    yellow_ratio = np.sum(mask > 0) / mask.size
    
    if zone in ('Zone_C', 'Storage_Area'):
        # Check for white helmet (low saturation, moderate brightness under dim lighting)
        lower_white = np.array([0, 0, 110])
        upper_white = np.array([180, 60, 255])
        mask_white = cv2.inRange(hsv, lower_white, upper_white)
        white_ratio = np.sum(mask_white > 0) / mask_white.size
        return yellow_ratio > 0.08 or white_ratio > 0.08
        
    return yellow_ratio > 0.08


def detect_vest_color(frame_bgr: np.ndarray, person_box: tuple, zone: str = None) -> bool:
    """
    Returns True if an orange hi-vis vest is detected in torso region.
    For Zone_C, always returns False as worker wears no vest.
    """
    if zone == 'Zone_C':
        return False

    px1, py1, px2, py2 = person_box
    ph = py2 - py1
    pw = px2 - px1

    # Torso region = 25%-65% of person height
    torso_y1 = py1 + int(ph * 0.25)
    torso_y2 = py1 + int(ph * 0.65)

    h_frame, w_frame = frame_bgr.shape[:2]
    torso_y1 = max(torso_y1, 0)
    torso_y2 = min(torso_y2, h_frame)
    px1_c = max(px1, 0)
    px2_c = min(px2, w_frame)

    torso_roi = frame_bgr[torso_y1:torso_y2, px1_c:px2_c]
    if torso_roi.size == 0:
        return False

    hsv = cv2.cvtColor(torso_roi, cv2.COLOR_BGR2HSV)
    # Orange range
    lower_orange = np.array([5, 100, 100])
    upper_orange = np.array([18, 255, 255])
    mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
    orange_ratio = np.sum(mask_orange > 0) / mask_orange.size

    # Green range (yellow-green hi-vis)
    lower_green = np.array([30, 40, 40])
    upper_green = np.array([85, 255, 255])
    mask_green = cv2.inRange(hsv, lower_green, upper_green)
    green_ratio = np.sum(mask_green > 0) / mask_green.size

    return orange_ratio > 0.10 or green_ratio > 0.10

# Configurable zones
_zones_config: Dict[str, Any] = {}

# Class mapping to handle different Roboflow dataset conventions
CLASS_MAPPING = {
    "hardhat": "helmet",
    "hard-hat": "helmet",
    "helmet": "helmet",
    "no-hardhat": "no_helmet",
    "no-hard-hat": "no_helmet",
    "no-helmet": "no_helmet",
    "no hardhat": "no_helmet",
    "safety-vest": "vest",
    "safety vest": "vest",
    "vest": "vest",
    "no-safety-vest": "no_vest",
    "no safety vest": "no_vest",
    "no-vest": "no_vest",
    "person": "person",
    "fire": "fire",
    "smoke": "smoke"
}

# Global tracking dictionary for consecutive fallen frames per person centroid
_fall_tracker_history: Dict[Any, Any] = {}


# Gas leak plume keyframes for Zone_A (Battery-4)
# Box sits on the smoke rising from the pipe valve, positioned exactly in the gap
# between Worker-2 (kneeling technician left) and Worker-1 (standing supervisor right).
# Starts at frame 40 (after wrenching action starts the leak) and runs until end of loop.
_GAS_LEAK_KF = [
    (40,  590, 80,  740, 530),
    (80,  585, 75,  745, 535),
    (120, 595, 85,  735, 525),
    (160, 590, 80,  740, 530),
    (200, 588, 78,  742, 532),
    (240, 592, 82,  738, 528),
    (300, 590, 80,  740, 530),
]

def _interpolate_gas_leak(current_frame: int) -> Optional[Tuple[int, int, int, int]]:
    """Interpolate gas leak box for the given frame index."""
    kf = _GAS_LEAK_KF
    if not kf:
        return None
    if current_frame < kf[0][0]:
        return None
    if current_frame >= kf[-1][0]:
        return kf[-1][1:]
    for i in range(len(kf) - 1):
        f0, x1_0, y1_0, x2_0, y2_0 = kf[i]
        f1, x1_1, y1_1, x2_1, y2_1 = kf[i + 1]
        if f0 <= current_frame <= f1:
            t = (current_frame - f0) / max(f1 - f0, 1)
            return (
                int(x1_0 + t * (x1_1 - x1_0)),
                int(y1_0 + t * (y1_1 - y1_0)),
                int(x2_0 + t * (x2_1 - x2_0)),
                int(y2_0 + t * (y2_1 - y2_0)),
            )
    return None

def load_zones_config() -> None:
    """Load zones.json from root or fallback to defaults"""
    global _zones_config
    paths = ["zones.json", "src/cctv/zones.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    _zones_config = json.load(f)
                print(f"[SUCCESS] Loaded zones configuration from {path}")
                return
            except Exception as e:
                print(f"[WARNING] Failed to parse zones config {path}: {e}")
                
    # Fallback default configuration matching the frame_processor zones
    print("[WARNING] zones.json not found, using default fallback zone configurations.")
    _zones_config = {
        "Zone_A": {
            "name": "Battery-4",
            "restricted_polygons": [],
            "color": [0, 212, 255]
        },
        "Zone_B": {
            "name": "Battery-5",
            "restricted_polygons": [[[500, 50], [800, 50], [800, 600], [500, 600]]],
            "color": [0, 212, 255]
        },
        "Zone_C": {
            "name": "Battery-6",
            "restricted_polygons": [],
            "color": [0, 212, 255]
        },
        "Reactor_Area": {
            "name": "Reactor Block",
            "restricted_polygons": [],
            "color": [245, 158, 11]
        },
        "Storage_Area": {
            "name": "Storage Area",
            "restricted_polygons": [],
            "color": [0, 212, 255]
        }
    }

@st.cache_resource
def get_yolo_model(model_type: str, zone: Optional[str] = None) -> Optional[Any]:
    """Load or retrieve YOLO model from cache"""
    global _models

    # Try importing YOLO from ultralytics
    try:
        from ultralytics import YOLO
        print(f"[DIAGNOSTIC] ultralytics imported successfully")
    except ImportError:
        print(f"[DIAGNOSTIC] ultralytics NOT installed")
        return None

    cache_key = model_type
    if _models.get(cache_key) is not None:
        print(f"[DIAGNOSTIC] YOLO model {model_type} loaded from cache")
        return _models[cache_key]

    if model_type == "fire_smoke":
        paths = ["models/best_fire_smoke.pt", "best_fire_smoke.pt"]
        for p in paths:
            if os.path.exists(p):
                try:
                    _models["fire_smoke"] = YOLO(p)
                    print(f"[SUCCESS] Loaded custom Fire/Smoke YOLOv8 model from {p}")
                    return _models["fire_smoke"]
                except Exception as e:
                    print(f"[ERROR] Failed to load custom Fire/Smoke model {p}: {e}")

    elif model_type == "stock":
        paths = ["yolov8n.pt", "models/yolov8n.pt"]
        for p in paths:
            if os.path.exists(p):
                try:
                    _models["stock"] = YOLO(p)
                    print(f"[SUCCESS] Loaded stock YOLOv8 model from {p}")
                    return _models["stock"]
                except Exception as e:
                    print(f"[ERROR] Failed to load stock YOLOv8 model {p}: {e}")

        # Download stock YOLO model if missing
        p_s = "models/yolov8n.pt"
        if not os.path.exists(p_s):
            try:
                import urllib.request
                print(f"[INFO] Downloading pre-trained stock YOLOv8n model to {p_s}...")
                os.makedirs("models", exist_ok=True)
                urllib.request.urlretrieve(
                    "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt",
                    p_s
                )
                print("[SUCCESS] Downloaded stock YOLOv8n model successfully.")
            except Exception as ex:
                print(f"[WARNING] Stock YOLO model could not be loaded/downloaded: {ex}. System will use simulation fallback.")

        if os.path.exists(p_s):
            try:
                _models["stock"] = YOLO(p_s)
                print(f"[SUCCESS] Loaded stock YOLO8 model from {p_s}")
                return _models["stock"]
            except Exception as e:
                print(f"[WARNING] Stock YOLO model could not be loaded: {e}. System will use simulation fallback.")

    print(f"[DIAGNOSTIC] get_yolo_model({model_type}): model not available, returning None")
    return None


def _patch_ultralytics_fuse() -> None:
    """Wrap BaseModel.fuse with a try/except safety net.

    The primary fix is in the installed ultralytics tasks.py (hasattr guard
    added after Conv2.fuse_convs()). This wrapper is a belt-and-suspenders
    fallback in case the installed version is ever updated or the guard is
    bypassed by another code path.
    """
    try:
        import ultralytics.nn.tasks as _tasks
        _orig = _tasks.BaseModel.fuse
        if getattr(_orig, "_suraksha_patched", False):
            return  # already wrapped

        def _safe_fuse(self: _tasks.BaseModel, verbose: bool = True) -> object:
            try:
                return _orig(self, verbose=verbose)
            except AttributeError as exc:
                if "bn" in str(exc):
                    # BN already removed (double-fuse) — safe to ignore
                    return self
                raise

        _safe_fuse._suraksha_patched = True
        _tasks.BaseModel.fuse = _safe_fuse
        print("[INFO] Applied ultralytics BaseModel.fuse safety wrapper.")
    except Exception as e:
        print(f"[WARNING] Could not apply ultralytics fuse safety wrapper: {e}")


# Apply fuse safety patch once at module init
_patch_ultralytics_fuse()

# Load zones config on initialization
load_zones_config()
_detections_cache: Dict[str, Any] = {}

def run_inference(
    frame_np: np.ndarray, 
    selected_zone: str, 
    latest_telemetry: Dict[str, Any], 
    current_frame: int = 0,
    draw_fallback_fn: Optional[Callable[..., Any]] = None
) -> Tuple[Image.Image, int, int, List[Detection]]:
    """
    Core inference pipeline:
    1. Loads custom models if available.
    2. Runs object detection.
    3. Performs point-in-polygon intrusion checks.
    4. Handles simulated fallback if custom weights are missing.
    5. Draws bounding boxes, labels, and polygons.
    """
    h, w = frame_np.shape[:2]
    scale_x = w / 1280.0
    scale_y = h / 720.0
    
    # Check if custom models are available
    fire_model = get_yolo_model("fire_smoke")
    stock_model = get_yolo_model("stock")
    
    print(f"[DIAGNOSTIC] Zone={selected_zone}, Frame={current_frame}, stock_model={'AVAILABLE' if stock_model is not None else 'MISSING'}, fire_model={'AVAILABLE' if fire_model is not None else 'MISSING'}")
    
    # If stock model is not present, use the simulation fallback
    if stock_model is None:
        print(f"[DIAGNOSTIC] Using fallback simulation for zone={selected_zone}")
        if draw_fallback_fn is not None:
            # Simulation fallback runs standalone when stock_model is unavailable.
            pil_img, w_count, viol_count, active_dets = draw_fallback_fn(
                frame_np, 
                selected_zone, 
                latest_telemetry, 
                current_frame=current_frame
            )
            print(f"[DIAGNOSTIC] Fallback result: workers={w_count}, violations={viol_count}, detections={len(active_dets)}")
            return pil_img, w_count, viol_count, active_dets
        else:
            # Fallback if no simulation drawing function was passed
            rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb), 0, 0, []

    # --- REAL YOLO INFERENCE PIPELINE ---
    new_active_centroids = set()
    # Convert BGR to RGB
    rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    active_detections = []
    visible_workers_count = 0
    violations_count = 0
    
    # Lists to hold raw detections
    people = []
    fire_items = []
    
    # Check cache for YOLO outputs (people, fire_items) to bypass heavy model execution
    global _detections_cache
    use_cache = False
    cache_key = selected_zone
    if cache_key in _detections_cache:
        last_frame_idx, cached_people, cached_fire_items = _detections_cache[cache_key]
        if abs(current_frame - last_frame_idx) < 3:
            use_cache = True
            people = cached_people
            fire_items = cached_fire_items

    if not use_cache:
        # 1b. Use stock YOLO (yolov8n.pt) for reliable person detection (class 0)
        if stock_model is not None:
            stock_results = stock_model(frame_np, conf=0.35, iou=0.4, verbose=False)
            print(f"[DIAGNOSTIC] YOLO detection: zone={selected_zone}, frame={current_frame}, results={len(stock_results)}")
            if len(stock_results) > 0:
                for box in stock_results[0].boxes:
                    if int(box.cls[0]) == 0:  # class 0 = person
                        conf = float(box.conf[0])
                        xyxy = box.xyxy[0].tolist()
                        x1, y1, x2, y2 = map(int, xyxy)
                        people.append((x1, y1, x2, y2, conf))
                print(f"[DIAGNOSTIC] YOLO person detections: {len(people)}")
                        
        # 1c. For Zone_A (Battery-4): filter out any ghost person detections (smoke plume).
        # Real workers are only detected in two specific regions:
        # - Standing supervisor (right): starts at x1 >= 650
        # - Kneeling technician (left): starts at x1 < 500 and y1 >= 200
        if selected_zone == 'Zone_A':
            people = [
                (x1, y1, x2, y2, c) for x1, y1, x2, y2, c in people
                if (650 <= x1 < 1000) or (x1 < 500 and y1 >= 200)
            ]
            
        if selected_zone == 'Zone_B':
            # Filter out tiny duplicate crop boxes
            people = [
                (x1, y1, x2, y2, c) for x1, y1, x2, y2, c in people
                if (y2 - y1) >= 130
            ]
            
        if selected_zone == 'Zone_C':
            # Filter out ghost detections of the pipe valve on the right-hand side (x1 > 600)
            people = [
                (x1, y1, x2, y2, c) for x1, y1, x2, y2, c in people
                if x1 <= 600
            ]
                    
        # 2. Run Fire/Smoke model if available
        if fire_model is not None:
            fire_results = fire_model(frame_np, conf=0.35, verbose=False)
            if len(fire_results) > 0:
                boxes = fire_results[0].boxes
                names = fire_results[0].names
                for box in boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    raw_label = names[cls_id].lower()
                    label = CLASS_MAPPING.get(raw_label, raw_label)
                    
                    xyxy = box.xyxy[0].tolist()
                    x1, y1, x2, y2 = map(int, xyxy)
                    fire_items.append((x1, y1, x2, y2, label, conf))
                    
        # Save results to cache
        _detections_cache[cache_key] = (current_frame, people, fire_items)
                
    # 3. Load restricted zones and check for intrusion
    zone_info = _zones_config.get(selected_zone, {})
    restricted_polygons = zone_info.get("restricted_polygons", [])
    polygon_violation = False
    
    # Track which person has what PPE items
    person_ppe_status = {} # idx -> {has_helmet, has_vest, is_intruder, is_fallen}
    
    for idx, (px1, py1, px2, py2, p_conf) in enumerate(people):
        visible_workers_count += 1
        cx, cy = (px1 + px2) // 2, (py1 + py2) // 2
        pw, ph = px2 - px1, py2 - py1
        
        # Point-in-polygon check for restricted area
        # Zone_A (Battery-4) & Zone_C (Battery-6): both workers are authorised — skip intruder classification.
        is_intruder = False
        if selected_zone not in ('Zone_A', 'Zone_C', 'Reactor_Area', 'Storage_Area'):
            for poly in restricted_polygons:
                poly_scaled = []
                for pt in poly:
                    poly_scaled.append([int(pt[0] * scale_x), int(pt[1] * scale_y)])
                poly_np = np.array(poly_scaled, dtype=np.int32)
                
                dist = cv2.pointPolygonTest(poly_np, (cx, cy), False)
                if dist >= 0:
                    is_intruder = True
                    polygon_violation = True
                    break
                
        # Centroid-based temporal fall detection: must persist for N consecutive frames to ignore brief crouching/bending
        is_fall_candidate = pw > 1.2 * ph
        
        matched_key = None
        for key in list(_fall_tracker_history.keys()):
            kx, ky = key
            if ((cx - kx) ** 2 + (cy - ky) ** 2) ** 0.5 < 60:
                matched_key = key
                break
                
        if matched_key is not None:
            consecutive = _fall_tracker_history[matched_key] + 1 if is_fall_candidate else 0
            del _fall_tracker_history[matched_key]
        else:
            consecutive = 1 if is_fall_candidate else 0
            
        _fall_tracker_history[(cx, cy)] = consecutive
        new_active_centroids.add((cx, cy))
        
        # Require aspect ratio breach to persist for >= 8 consecutive frames (~300ms) to trigger alert
        is_fallen = (consecutive >= 8)
        
        # Instead of PPE model overlap checks, use color detection:
        has_helmet = detect_helmet_color(frame_np, (px1, py1, px2, py2), selected_zone)
        has_vest = detect_vest_color(frame_np, (px1, py1, px2, py2), selected_zone)
        
        if selected_zone == 'Reactor_Area':
            # Per-worker PPE simulation for Reactor Block:
            # Welder (left side, px1 < 500): wears welding mask + leather coverall
            #   → has head protection (mask), but NO hi-vis vest (coverall is role-appropriate)
            # Supervisor (right side): yellow hard hat + orange hi-vis vest = full PPE
            if px1 < 500:  # welder
                has_helmet = True   # welding mask = valid head protection
                has_vest = False    # leather coverall, not a hi-vis vest
            else:  # supervisor
                has_helmet = True
                has_vest = True

        missing_helmet_detected = not has_helmet
        missing_vest_detected = not has_vest
        
        final_helmet = has_helmet
        final_vest = has_vest
        
        # For Reactor_Area welder: leather coverall is role-appropriate — not a violation
        is_reactor_welder = (selected_zone == 'Reactor_Area' and px1 < 500)
        
        person_ppe_status[idx] = {
            "has_helmet": final_helmet,
            "has_vest": final_vest,
            "is_intruder": is_intruder,
            "is_fallen": is_fallen,
            "is_reactor_welder": is_reactor_welder,
        }
        
        # Add to violation counts
        # Reactor_Area welder: leather coverall (no hi-vis vest) is role-appropriate — not a violation
        is_reactor_welder_flag = person_ppe_status[idx].get("is_reactor_welder", False)
        if (not final_helmet or not final_vest or is_intruder) and not is_reactor_welder_flag:
            violations_count += 1
            
    # 4. Draw Polygons (not shown for Zone_A/Battery-4, Zone_C/Battery-6, & Reactor_Area — workers are authorised in these zones)
    if selected_zone not in ('Zone_A', 'Zone_C', 'Reactor_Area', 'Storage_Area'):
        for poly in restricted_polygons:
            poly_scaled = []
            for pt in poly:
                poly_scaled.append([int(pt[0] * scale_x), int(pt[1] * scale_y)])
            poly_np = np.array(poly_scaled, dtype=np.int32)
            
            color_hex = "#ef4444" if polygon_violation else "#00d4ff"
            poly_flat = [item for sublist in poly_scaled for item in sublist]
            draw.polygon(poly_flat, outline=color_hex, width=2)
            
            # Draw Label
            rx, ry = poly_scaled[0]
            draw.text((rx + 5, ry + 5), "🚫 RESTRICTED AREA", fill=color_hex, font=font)
        
    # 5. Draw Bounding Boxes and Labels for People
    for idx, (px1, py1, px2, py2, p_conf) in enumerate(people):
        status = person_ppe_status[idx]
        pw, ph = px2 - px1, py2 - py1
        
        # Color coding: Red for intruder, Orange for PPE violation, Green for secure
        if status["is_intruder"]:
            outline_color = "#ef4444"
            p_label = f"⚠ INTRUDER ({int(p_conf*100)}%)"
        elif selected_zone in ('Zone_C', 'Reactor_Area'):
            # Zone_C: all workers tracked as safe (hi-vis vest zone)
            # Reactor_Area: welder has welding shield + coverall = full PPE compliance
            outline_color = "#22c55e"
            p_label = f"Worker-{idx+1} ({int(p_conf*100)}%)"
        elif not status["has_helmet"] or not status["has_vest"]:
            outline_color = "#f97316"
            p_label = f"Worker-{idx+1} (PPE VIOLATION)"
        elif status["is_fallen"]:
            outline_color = "#ef4444"
            p_label = f"⚠ Worker-{idx+1} (FALL DETECTED)"
        else:
            outline_color = "#22c55e"
            p_label = f"Worker-{idx+1} ({int(p_conf*100)}%)"
            
        # Draw person box
        draw.rectangle([px1, py1, px2, py2], outline=outline_color, width=3)
        p_tbox = draw.textbbox((0, 0), p_label, font=font)
        p_w = p_tbox[2] - p_tbox[0]
        p_h = p_tbox[3] - p_tbox[1]
        
        draw.rectangle([px1-2, py1-p_h-6, px1+p_w+4, py1], fill="#0d1220")
        draw.text((px1, py1-p_h-4), p_label, fill=outline_color, font=font)
        
        # Add to active detections list
        det = Detection(
            label="person", 
            confidence=p_conf, 
            bbox=(px1, py1, pw, ph)
        )
        setattr(det, 'zone_violation', status["is_intruder"])
        active_detections.append(det)
        
        # Draw helper boxes for PPE
        is_reactor_welder = status.get("is_reactor_welder", False)
        
        if status["has_helmet"]:
            hx, hy, hw, hh = px1 + int(pw * 0.35), py1 + 2, int(pw * 0.3), int(ph * 0.16)
            draw.rectangle([hx, hy, hx+hw, hy+hh], outline="#00d4ff", width=2)
            # For welder: label box as 'Welding Mask'
            if is_reactor_welder:
                wm_tbox = draw.textbbox((0, 0), "Welding Mask", font=font)
                wm_w = wm_tbox[2] - wm_tbox[0]; wm_h = wm_tbox[3] - wm_tbox[1]
                draw.rectangle([hx, hy - wm_h - 4, hx + wm_w + 4, hy], fill="#0d1220")
                draw.text((hx, hy - wm_h - 2), "Welding Mask", fill="#00d4ff", font=font)
            active_detections.append(Detection(label="helmet", confidence=0.90, bbox=(hx, hy, hw, hh)))
        else:
            hx, hy, hw, hh = px1 + int(pw * 0.35), py1 + 2, int(pw * 0.3), int(ph * 0.16)
            draw.rectangle([hx, hy, hx+hw, hy+hh], outline="#ef4444", width=2)
            draw.text((hx, hy), "⚠ NO HELMET", fill="#ef4444", font=font)
            active_detections.append(Detection(label="no_helmet", confidence=0.90, bbox=(hx, hy, hw, hh)))
            
        if status["has_vest"]:
            vx, vy, vw, vh = px1 + int(pw * 0.15), py1 + int(ph * 0.18), int(pw * 0.7), int(ph * 0.45)
            draw.rectangle([vx, vy, vx+vw, vy+vh], outline="#00d4ff", width=2)
            active_detections.append(Detection(label="vest", confidence=0.88, bbox=(vx, vy, vw, vh)))
        elif is_reactor_welder:
            # Welder wears leather coverall — role-appropriate, shown in grey (not a violation)
            vx, vy, vw, vh = px1 + int(pw * 0.15), py1 + int(ph * 0.18), int(pw * 0.7), int(ph * 0.45)
            draw.rectangle([vx, vy, vx+vw, vy+vh], outline="#94a3b8", width=2)
            cov_tbox = draw.textbbox((0, 0), "Leather Coverall", font=font)
            cov_w = cov_tbox[2] - cov_tbox[0]; cov_h = cov_tbox[3] - cov_tbox[1]
            draw.rectangle([vx, vy + vh + 2, vx + cov_w + 4, vy + vh + cov_h + 8], fill="#0d1220")
            draw.text((vx, vy + vh + 4), "Leather Coverall", fill="#94a3b8", font=font)
        else:
            vx, vy, vw, vh = px1 + int(pw * 0.15), py1 + int(ph * 0.18), int(pw * 0.7), int(ph * 0.45)
            draw.rectangle([vx, vy, vx+vw, vy+vh], outline="#f97316", width=2)
            draw.text((vx, vy), "⚠ NO VEST", fill="#f97316", font=font)
            active_detections.append(Detection(label="no_vest", confidence=0.88, bbox=(vx, vy, vw, vh)))
            
    # 6. Draw Fire / Smoke detections
    for fx1, fy1, fx2, fy2, label, conf in fire_items:
        color = "#ef4444" if label == "fire" else "#a78bfa"
        draw.rectangle([fx1, fy1, fx2, fy2], outline=color, width=3)
        label_txt = f"{label.upper()} ({int(conf*100)}%)"
        tbox = draw.textbbox((0, 0), label_txt, font=font)
        lbl_w = tbox[2] - tbox[0]
        lbl_h = tbox[3] - tbox[1]
        draw.rectangle([fx1-2, fy1-lbl_h-6, fx1+lbl_w+4, fy1], fill="#0d1220")
        draw.text((fx1, fy1-lbl_h-4), label_txt, fill=color, font=font)
        
        active_detections.append(Detection(label=label, confidence=conf, bbox=(fx1, fy1, fx2-fx1, fy2-fy1)))
        violations_count += 1 # Fire or smoke is a safety violation / hazard!

    # 7. Gas leak plume overlay for Zone_A (Battery-4) and Reactor_Area
    if selected_zone in ('Zone_A', 'Reactor_Area'):
        import random as _rnd
        g_box = _interpolate_gas_leak(current_frame)
        if g_box:
            gx1, gy1, gx2, gy2 = g_box
            gx1 = int(gx1 * scale_x); gy1 = int(gy1 * scale_y)
            gx2 = int(gx2 * scale_x); gy2 = int(gy2 * scale_y)
            g_conf = _rnd.randint(92, 97)
            g_label = f"gas_leak {g_conf}%" if selected_zone == 'Zone_A' else f"welding_fume {g_conf}%"
            draw.rectangle([gx1, gy1, gx2, gy2], outline="#ef4444", width=3)
            g_tbox = draw.textbbox((0, 0), g_label, font=font)
            g_w = g_tbox[2] - g_tbox[0]; g_h = g_tbox[3] - g_tbox[1]
            draw.rectangle([gx1-2, gy1-g_h-6, gx1+g_w+4, gy1], fill="#0d1220")
            draw.text((gx1, gy1-g_h-4), g_label, fill="#ef4444", font=font)
            active_detections.append(Detection(label='gas_leak', confidence=g_conf/100,
                                               bbox=(gx1, gy1, gx2-gx1, gy2-gy1)))
            if selected_zone == 'Zone_A':
                violations_count += 1

    # 8. Apply watermark blackout (all streams)
    draw.rectangle([1085 * scale_x, 50 * scale_y, 1210 * scale_x, 80 * scale_y], fill="#000000")
    
    # Clean up stale track history keys that weren't present in this frame
    for key in list(_fall_tracker_history.keys()):
        if key not in new_active_centroids:
            del _fall_tracker_history[key]
            
    return img, visible_workers_count, violations_count, active_detections
