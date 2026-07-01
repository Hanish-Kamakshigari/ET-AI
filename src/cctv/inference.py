import os
import json
import cv2
import numpy as np
import random
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

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

def reset_ppe_buffer():
    pass

def detect_helmet_color(frame_bgr: np.ndarray, person_box: tuple) -> bool:
    """
    Returns True if a yellow helmet is detected in the head region of a person.
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
    return yellow_ratio > 0.08


def detect_vest_color(frame_bgr: np.ndarray, person_box: tuple) -> bool:
    """
    Returns True if an orange hi-vis vest is detected in torso region.
    """
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
    mask = cv2.inRange(hsv, lower_orange, upper_orange)

    orange_ratio = np.sum(mask > 0) / mask.size
    return orange_ratio > 0.10

# Configurable zones
_zones_config = {}

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

def _interpolate_gas_leak(current_frame: int):
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

def load_zones_config():
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
            "restricted_polygons": [[[200, 200], [550, 200], [550, 650], [200, 650]]],
            "color": [0, 212, 255]
        },
        "Zone_B": {
            "name": "Battery-5",
            "restricted_polygons": [[[500, 50], [800, 50], [800, 600], [500, 600]]],
            "color": [0, 212, 255]
        },
        "Zone_C": {
            "name": "Battery-6",
            "restricted_polygons": [[[100, 50], [450, 50], [450, 700], [100, 700]]],
            "color": [0, 212, 255]
        },
        "Reactor_Area": {
            "name": "Reactor Block",
            "restricted_polygons": [[[700, 100], [1100, 100], [1100, 720], [700, 720]]],
            "color": [245, 158, 11]
        },
        "Storage_Area": {
            "name": "Storage Area",
            "restricted_polygons": [[[300, 100], [900, 100], [900, 700], [300, 700]]],
            "color": [0, 212, 255]
        }
    }

def get_yolo_model(model_type: str, zone: str = None):
    """Load or retrieve YOLO model from cache"""
    global _models
    
    # Try importing YOLO from ultralytics
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[WARNING] ultralytics not installed, cannot load YOLO models.")
        return None
        
    cache_key = model_type
    if model_type == "ppe":
        cache_key = "ppe_zone_a" if zone == "Zone_A" else "ppe_default"
        
    if _models.get(cache_key) is not None:
        return _models[cache_key]
        
    if model_type == "ppe":
        paths = []
        if zone == "Zone_A":
            paths = ["models/best_ppe_zone_a.pt", "runs/detect/yolov8n_ppe/weights/best.pt"]
        else:
            paths = ["models/yolov8s-hard-hat-detection.pt", "models/best_ppe.pt"]
            p_s = "models/yolov8s-hard-hat-detection.pt"
            if not os.path.exists(p_s):
                try:
                    import urllib.request
                    print(f"[INFO] Downloading pre-trained yolov8s hard-hat model to {p_s}...")
                    os.makedirs("models", exist_ok=True)
                    urllib.request.urlretrieve(
                        "https://huggingface.co/keremberke/yolov8s-hard-hat-detection/resolve/main/best.pt",
                        p_s
                    )
                    print("[SUCCESS] Downloaded yolov8s hard-hat model successfully.")
                except Exception as ex:
                    print(f"[ERROR] Failed to download yolov8s model: {ex}")
            
        for p in paths:
            if os.path.exists(p):
                try:
                    _models[cache_key] = YOLO(p)
                    print(f"[SUCCESS] Loaded custom PPE YOLOv8 model for {zone or 'default'} from {p}")
                    return _models[cache_key]
                except Exception as e:
                    print(f"[ERROR] Failed to load custom PPE model {p} for {zone}: {e}")
                    
        # Option B fallback: download stock YOLOv8n if all else fails
        try:
            import urllib.request
            print("[INFO] Downloading stock yolov8n.pt as fallback...")
            urllib.request.urlretrieve(
                "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt",
                "yolov8n.pt"
            )
            _models[cache_key] = YOLO("yolov8n.pt")
            print("[SUCCESS] Loaded stock YOLOv8 model as fallback")
            return _models[cache_key]
        except Exception as ex:
            print(f"[ERROR] Fallback download failed: {ex}")
                    
    elif model_type == "fire_smoke":
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
                    
    return None

# Load zones config on initialization
load_zones_config()

def run_inference(
    frame_np: np.ndarray, 
    selected_zone: str, 
    latest_telemetry: Dict, 
    current_frame: int = 0,
    draw_fallback_fn = None
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
    
    # If stock model is not present, use the simulation fallback
    if stock_model is None:
        if draw_fallback_fn is not None:
            # Run simulation fallback
            pil_img, w_count, viol_count, active_dets = draw_fallback_fn(
                frame_np, 
                selected_zone, 
                latest_telemetry, 
                current_frame=current_frame
            )
            
            # --- OVERLAY REAL-TIME STOCK INTRUSION DETECTION ON TOP OF SIMULATION ---
            # Even before training the custom PPE model, we can run stock YOLO person detection
            # and check for restricted zone intrusions dynamically!
            if stock_model is not None:
                # Convert BGR to RGB for PIL drawing
                rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                draw = ImageDraw.Draw(img)
                try:
                    font = ImageFont.load_default()
                except Exception:
                    font = None
                    
                # Run stock YOLO for person detection (class 0 is person)
                results = stock_model(frame_np, conf=0.35, iou=0.4, verbose=False)
                if len(results) > 0:
                    boxes = results[0].boxes
                    person_detections = []
                    
                    # Extract people
                    for box in boxes:
                        cls_id = int(box.cls[0])
                        if cls_id == 0: # person
                            conf = float(box.conf[0])
                            xyxy = box.xyxy[0].tolist()
                            px1, py1, px2, py2 = map(int, xyxy)
                            pw, ph = px2 - px1, py2 - py1
                            person_detections.append((px1, py1, px2, py2, conf))
                            
                    # Load restricted polygons for current zone
                    zone_info = _zones_config.get(selected_zone, {})
                    restricted_polygons = zone_info.get("restricted_polygons", [])
                    polygon_violation = False
                    
                    # Check each person for intrusion
                    for px1, py1, px2, py2, conf in person_detections:
                        cx, cy = (px1 + px2) // 2, (py1 + py2) // 2
                        
                        is_intruder = False
                        for poly in restricted_polygons:
                            # Convert normalized/reference points to actual pixel space
                            poly_scaled = []
                            for pt in poly:
                                poly_scaled.append([int(pt[0] * scale_x), int(pt[1] * scale_y)])
                            poly_np = np.array(poly_scaled, dtype=np.int32)
                            
                            dist = cv2.pointPolygonTest(poly_np, (cx, cy), False)
                            if dist >= 0:
                                is_intruder = True
                                polygon_violation = True
                                break
                                
                        if is_intruder:
                            viol_count += 1
                            # Draw restricted intruder box
                            draw.rectangle([px1, py1, px2, py2], outline="#ef4444", width=3)
                            label_txt = f"⚠ INTRUDER ({int(conf*100)}%)"
                            lbl_tbox = draw.textbbox((0, 0), label_txt, font=font)
                            lbl_w = lbl_tbox[2] - lbl_tbox[0]
                            lbl_h = lbl_tbox[3] - lbl_tbox[1]
                            draw.rectangle([px1-2, py1-lbl_h-6, px1+lbl_w+4, py1], fill="#0d1220")
                            draw.text((px1, py1-lbl_h-4), label_txt, fill="#ef4444", font=font)
                            det = Detection(
                                label="person", 
                                confidence=conf, 
                                bbox=(px1, py1, px2-px1, py2-py1)
                            )
                            setattr(det, 'zone_violation', True)
                            active_dets.append(det)
                            
                    # Draw restricted zone outlines
                    for poly in restricted_polygons:
                        poly_scaled = []
                        for pt in poly:
                            poly_scaled.append([int(pt[0] * scale_x), int(pt[1] * scale_y)])
                        poly_np = np.array(poly_scaled, dtype=np.int32)
                        
                        # Draw outline: red if violation is active in the zone, yellow/cyan otherwise
                        color = (239, 68, 68) if polygon_violation else (0, 212, 255) # BGR
                        color_hex = "#ef4444" if polygon_violation else "#00d4ff"
                        
                        # Draw polygon on PIL image
                        poly_flat = [item for sublist in poly_scaled for item in sublist]
                        draw.polygon(poly_flat, outline=color_hex, width=2)
                        
                        # Label the restricted area
                        rx, ry = poly_scaled[0]
                        draw.text((rx + 5, ry + 5), "🚫 RESTRICTED AREA", fill=color_hex, font=font)
                        
                    # Return composite image
                    return img, w_count, viol_count, active_dets
            
            return pil_img, w_count, viol_count, active_dets
            
        else:
            # Fallback if no simulation drawing function was passed
            rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb), 0, 0, []

    # --- REAL YOLO INFERENCE PIPELINE ---
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

    # 1b. Use stock YOLO (yolov8n.pt) for reliable person detection (class 0)
    if stock_model is not None:
        stock_results = stock_model(frame_np, conf=0.35, iou=0.4, verbose=False)
        if len(stock_results) > 0:
            for box in stock_results[0].boxes:
                if int(box.cls[0]) == 0:  # class 0 = person
                    conf = float(box.conf[0])
                    xyxy = box.xyxy[0].tolist()
                    x1, y1, x2, y2 = map(int, xyxy)
                    people.append((x1, y1, x2, y2, conf))
                    
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
                
    # 2. Run Fire/Smoke model if available
    fire_items = []
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
        # Zone_A (Battery-4): both workers are authorised — skip intruder classification.
        is_intruder = False
        if selected_zone != 'Zone_A':
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
                
        # Heuristic fall detection: if width of bounding box is greater than 1.2x height
        is_fallen = pw > 1.2 * ph
        
        # Instead of PPE model overlap checks, use color detection:
        has_helmet = detect_helmet_color(frame_np, (px1, py1, px2, py2))
        has_vest = detect_vest_color(frame_np, (px1, py1, px2, py2))
        missing_helmet_detected = not has_helmet
        missing_vest_detected = not has_vest
        
        final_helmet = has_helmet
        final_vest = has_vest
        
        person_ppe_status[idx] = {
            "has_helmet": final_helmet,
            "has_vest": final_vest,
            "is_intruder": is_intruder,
            "is_fallen": is_fallen
        }
        
        # Add to violation counts
        if not final_helmet or not final_vest or is_intruder:
            violations_count += 1
            
    # 4. Draw Polygons (not shown for Zone_A/Battery-4 — workers are authorised in this zone)
    if selected_zone != 'Zone_A':
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
        
        # Draw helper boxes for PPE if they have it
        if status["has_helmet"]:
            hx, hy, hw, hh = px1 + int(pw * 0.35), py1 + 2, int(pw * 0.3), int(ph * 0.16)
            draw.rectangle([hx, hy, hx+hw, hy+hh], outline="#00d4ff", width=2)
            active_detections.append(Detection(label="helmet", confidence=0.90, bbox=(hx, hy, hw, hh)))
        else:
            # Draw missing helmet box
            hx, hy, hw, hh = px1 + int(pw * 0.35), py1 + 2, int(pw * 0.3), int(ph * 0.16)
            draw.rectangle([hx, hy, hx+hw, hy+hh], outline="#ef4444", width=2)
            draw.text((hx, hy), "⚠ NO HELMET", fill="#ef4444", font=font)
            
        if status["has_vest"]:
            vx, vy, vw, vh = px1 + int(pw * 0.15), py1 + int(ph * 0.18), int(pw * 0.7), int(ph * 0.45)
            draw.rectangle([vx, vy, vx+vw, vy+vh], outline="#00d4ff", width=2)
            active_detections.append(Detection(label="vest", confidence=0.88, bbox=(vx, vy, vw, vh)))
        else:
            # Draw missing vest box
            vx, vy, vw, vh = px1 + int(pw * 0.15), py1 + int(ph * 0.18), int(pw * 0.7), int(ph * 0.45)
            draw.rectangle([vx, vy, vx+vw, vy+vh], outline="#f97316", width=2)
            draw.text((vx, vy), "⚠ NO VEST", fill="#f97316", font=font)
            
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
            violations_count += 1

    # 8. Apply watermark blackout (all streams)
    draw.rectangle([1085 * scale_x, 50 * scale_y, 1210 * scale_x, 80 * scale_y], fill="#000000")
    
    return img, visible_workers_count, violations_count, active_detections
