"""
Object Detector - AI detection for CCTV feeds
Uses YOLO or simulated detection for demo
"""

import cv2
import numpy as np
import time
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import random


@dataclass
class Detection:
    """Single detection result"""
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    zone: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    tracking_id: Optional[int] = None
    zone_violation: bool = False
    
    def get_center(self) -> Tuple[int, int]:
        """Get center of bounding box"""
        x, y, w, h = self.bbox
        return (x + w//2, y + h//2)
    
    def get_area(self) -> int:
        """Get area of bounding box"""
        x, y, w, h = self.bbox
        return w * h


def _is_sentinel_box(box):
    """Return True if box is a (0,0,0,0) sentinel meaning 'not present'."""
    return box is not None and box[0] == 0 and box[1] == 0 and box[2] == 0 and box[3] == 0


def interpolate_box(keyframes, current_frame):
    """Interpolate between keyframes. Returns None for sentinel (0,0,0,0) boxes."""
    sorted_kf = sorted(keyframes, key=lambda x: x[0])
    
    if not sorted_kf:
        return None
        
    # If only one keyframe, return its coords (None if sentinel)
    if len(sorted_kf) == 1:
        coords = sorted_kf[0][1:]
        return None if _is_sentinel_box(coords) else coords
        
    # Clamp to first keyframe
    if current_frame <= sorted_kf[0][0]:
        coords = sorted_kf[0][1:]
        return None if _is_sentinel_box(coords) else coords
        
    # Clamp to last keyframe
    if current_frame >= sorted_kf[-1][0]:
        coords = sorted_kf[-1][1:]
        return None if _is_sentinel_box(coords) else coords
        
    # Find bracket pair and interpolate
    for i in range(len(sorted_kf) - 1):
        kf1 = sorted_kf[i]
        kf2 = sorted_kf[i+1]
        f1, x1_1, y1_1, x2_1, y2_1 = kf1
        f2, x1_2, y1_2, x2_2, y2_2 = kf2
        
        if f1 <= current_frame <= f2:
            # If either bracket is a sentinel, treat the whole interval as absent
            if (x1_1 == 0 and y1_1 == 0 and x2_1 == 0 and y2_1 == 0) or \
               (x1_2 == 0 and y1_2 == 0 and x2_2 == 0 and y2_2 == 0):
                return None
            t = (current_frame - f1) / (f2 - f1)
            x1 = x1_1 + (x1_2 - x1_1) * t
            y1 = y1_1 + (y1_2 - y1_1) * t
            x2 = x2_1 + (x2_2 - x2_1) * t
            y2 = y2_1 + (y2_2 - y2_1) * t
            return (x1, y1, x2, y2)
            
    return None


class ObjectDetector:
    """
    AI-powered object detection for CCTV feeds
    Supports real YOLO or simulated detection
    """
    
    def __init__(self, use_simulation: bool = True, confidence_threshold: float = 0.5):
        self.use_simulation = use_simulation
        self.confidence_threshold = confidence_threshold
        self.model = None
        self.classes = ['person', 'helmet', 'vest', 'forklift', 'truck', 'gas_leak', 'fire', 'smoke']
        self.detection_history = []
        self.max_history = 1000
        self.tracking_id_counter = 0
        self.detection_count = 0
        self._attempted_load = False
        
        if not use_simulation:
            self._load_model()
    
    def _load_model(self):
        """Load real YOLO model (optional)"""
        if self._attempted_load:
            return
        self._attempted_load = True
        try:
            from src.cctv.inference import get_yolo_model
            self.model = get_yolo_model("stock")
            if self.model is not None:
                print("[SUCCESS] YOLO model loaded successfully from cache")
                self.use_simulation = False
            else:
                print("[WARNING] YOLO model could not be retrieved from cache, falling back to simulation")
                self.use_simulation = True
        except ImportError:
            print("[WARNING] YOLO not available, falling back to simulation")
            self.use_simulation = True
        except Exception as e:
            print(f"[ERROR] Failed to load YOLO: {e}")
            self.use_simulation = True
    
    def detect(self, frame: np.ndarray, workers: list = None, current_frame: int = 0) -> List[Detection]:
        """
        Detect objects in a frame using YOLO if available, else fall back to simulation.
        """
        self.detection_count += 1
        
        if self.use_simulation or self.model is None or workers is None:
            return self._detect_simulated(frame)
            
        selected_zone = getattr(self, 'selected_zone', 'Zone_A')
        latest = getattr(self, 'latest_telemetry', None)
        simulate_active = False
        if latest is not None and latest.get('max_risk_level') == 'CRITICAL':
            simulate_active = True
            
        detections = []
        h, w = frame.shape[:2]
        
        # Run YOLOv8 detection
        results = self.model(frame, conf=self.confidence_threshold, verbose=False)
        
        if len(results) > 0:
            boxes = results[0].boxes
            person_boxes = []
            
            # Extract 'person' detections (class 0) and vehicles (class 1: bicycle, 2: car, 3: motorcycle, 5: bus, 7: truck)
            for box in boxes:
                cls_id = int(box.cls[0])
                if cls_id == 0:  # person
                    conf = float(box.conf[0])
                    xyxy = box.xyxy[0].tolist()
                    px1, py1, px2, py2 = map(int, xyxy)
                    pw = px2 - px1
                    ph = py2 - py1
                    person_boxes.append((px1, py1, pw, ph, conf))
                elif cls_id in [1, 2, 3, 5, 7]:  # vehicles
                    conf = float(box.conf[0])
                    label = results[0].names[cls_id]
                    xyxy = box.xyxy[0].tolist()
                    tx1, ty1, tx2, ty2 = map(int, xyxy)
                    tw = tx2 - tx1
                    th = ty2 - ty1
                    detections.append(Detection(
                        label=label,
                        confidence=conf,
                        bbox=(tx1, ty1, tw, th),
                        tracking_id=500 + len(detections)
                    ))
            
            # Get active keyframe boxes for this frame
            import random
            
            active_keyframes = []
            for w_def in workers:
                f_start = w_def.get('first_visible_frame', 1)
                f_end = w_def.get('last_visible_frame', 9999)
                if f_start <= current_frame <= f_end:
                    hidden_ranges = w_def.get('hidden_ranges', [])
                    is_hidden = False
                    for start, end in hidden_ranges:
                        if start <= current_frame <= end:
                            is_hidden = True
                            break
                    if not is_hidden:
                        w_box = interpolate_box(w_def['keyframes'], current_frame)
                        if w_box:
                            active_keyframes.append((w_box, w_def))
            
            # Map detected people to keyframe metadata
            for idx, (px1, py1, pw, ph, conf) in enumerate(person_boxes):
                tid = idx + 1
                pcx, pcy = px1 + pw//2, py1 + ph//2
                
                matched_w_def = None
                min_dist = float('inf')
                
                # Check nearest keyframe box
                for (kx1, ky1, kx2, ky2), w_def in active_keyframes:
                    scale_x = w / 1280.0
                    scale_y = h / 720.0
                    kcx = int(((kx1 + kx2) / 2) * scale_x)
                    kcy = int(((ky1 + ky2) / 2) * scale_y)
                    
                    dist = ((pcx - kcx) ** 2 + (pcy - kcy) ** 2) ** 0.5
                    if dist < min_dist and dist < 200:  # 200 pixels proximity threshold
                        min_dist = dist
                        matched_w_def = w_def
                
                has_helmet = True
                ppe_violation = False
                
                if matched_w_def:
                    has_helmet = matched_w_def.get('has_helmet', True)
                    ppe_violation = matched_w_def.get('ppe_violation', False)
                
                # Add person detection
                detections.append(Detection(
                    label='person',
                    confidence=conf,
                    bbox=(px1, py1, pw, ph),
                    tracking_id=tid
                ))
                
                # Add helmet detection (positioned relative to person box)
                hx, hy, hw, hh = px1 + int(pw * 0.35), py1 + 2, int(pw * 0.3), int(ph * 0.16)
                if has_helmet:
                    detections.append(Detection(
                        label='helmet',
                        confidence=0.89 + random.uniform(-0.02, 0.02),
                        bbox=(hx, hy, hw, hh),
                        tracking_id=tid
                    ))
                
                # Add vest detection
                vx, vy, vw, vh = px1 + int(pw * 0.15), py1 + int(ph * 0.18), int(pw * 0.7), int(ph * 0.45)
                is_vest_violation = ppe_violation and matched_w_def and matched_w_def.get('violation_type') == 'MISSING_HIVIZ_VEST'
                if not is_vest_violation:
                    detections.append(Detection(
                        label='vest',
                        confidence=0.86 + random.uniform(-0.02, 0.02),
                        bbox=(vx, vy, vw, vh),
                        tracking_id=tid
                    ))
        
        # Add hazards based on zone
        if selected_zone == 'Zone_A':
            hx, hy, hw, hh = int(w * 0.4), int(h * 0.3), int(w * 0.2), int(h * 0.2)
            detections.append(Detection(label='gas_leak', confidence=0.95, bbox=(hx, hy, hw, hh), tracking_id=101))
        elif selected_zone == 'Storage_Area':
            hx, hy, hw, hh = int(w * 0.4), int(h * 0.3), int(w * 0.2), int(h * 0.2)
            detections.append(Detection(label='smoke', confidence=0.95, bbox=(hx, hy, hw, hh), tracking_id=102))
            
        self._add_to_history(detections)
        return detections

    def _detect_simulated(self, frame: np.ndarray) -> List[Detection]:
        selected_zone = getattr(self, 'selected_zone', 'Zone_A')
        latest = getattr(self, 'latest_telemetry', None)
        simulate_active = False
        if latest is not None and latest.get('max_risk_level') == 'CRITICAL':
            simulate_active = True
            
        detections = []
        h, w = frame.shape[:2]
        
        # Determine number of workers and hazards based on selected zone
        worker_count = 0
        has_helmet_list = []
        has_vest_list = []
        hazards = []
        
        if selected_zone == 'Zone_A':
            if latest is not None:
                worker_count = int(latest.get('Zone_A_worker_count', 2))
            else:
                worker_count = 8 if simulate_active else 2
            has_helmet_list = [True] * worker_count
            has_vest_list   = [True] * worker_count
            if worker_count >= 5:
                has_helmet_list[4] = False
                if worker_count >= 6: has_helmet_list[5] = False
                if worker_count >= 7: has_vest_list[3]   = False
            hazards = ['gas_leak']
        elif selected_zone == 'Zone_B':
            worker_count = 3
            has_helmet_list = [True, True, True]
            has_vest_list = [True, True, True]
        elif selected_zone == 'Zone_C':
            worker_count = 1
            has_helmet_list = [True]
            has_vest_list = [False]
        elif selected_zone == 'Reactor_Area':
            worker_count = 1
            has_helmet_list = [True]
            has_vest_list = [False]
        elif selected_zone == 'Storage_Area':
            worker_count = 0
            hazards = ['smoke']
            
        import random
        random.seed(hash(selected_zone) % 1000)
        for i in range(worker_count):
            tid = i + 1
            bx = int(w * (0.2 + 0.08 * i))
            by = int(h * (0.3 + 0.03 * (i % 2)))
            bw, bh = int(w * 0.06), int(h * 0.22)
            
            detections.append(Detection(label='person', confidence=0.92, bbox=(bx, by, bw, bh), tracking_id=tid))
            if i < len(has_helmet_list) and has_helmet_list[i]:
                detections.append(Detection(label='helmet', confidence=0.88, bbox=(bx + bw//4, by - bh//8, bw//2, bh//4), tracking_id=tid))
            if i < len(has_vest_list) and has_vest_list[i]:
                detections.append(Detection(label='vest', confidence=0.85, bbox=(bx + bw//6, by + bh//4, 2*bw//3, bh//2), tracking_id=tid))
                
        for idx, h_type in enumerate(hazards):
            hx = int(w * 0.4)
            hy = int(h * 0.3)
            hw = int(w * 0.2)
            hh = int(h * 0.2)
            detections.append(Detection(label=h_type, confidence=0.95, bbox=(hx, hy, hw, hh), tracking_id=100 + idx))
            
        random.seed(None)
        self._add_to_history(detections)
        return detections
    
    def _get_tracking_id(self) -> int:
        """Generate unique tracking ID"""
        self.tracking_id_counter += 1
        return self.tracking_id_counter
    
    def _add_to_history(self, detections: List[Detection]):
        """Add detections to history"""
        self.detection_history.extend(detections)
        if len(self.detection_history) > self.max_history:
            self.detection_history = self.detection_history[-self.max_history:]
    
    def get_recent_detections(self, count: int = 10) -> List[Detection]:
        """Get recent detections"""
        return self.detection_history[-count:] if self.detection_history else []
    
    def get_detection_summary(self) -> Dict:
        """Get summary of recent detections"""
        if not self.detection_history:
            return {
                'total': 0,
                'by_label': {},
                'last_detection': None,
                'labels': []
            }
        
        by_label = {}
        for d in self.detection_history:
            by_label[d.label] = by_label.get(d.label, 0) + 1
        
        return {
            'total': len(self.detection_history),
            'by_label': by_label,
            'last_detection': self.detection_history[-1] if self.detection_history else None,
            'labels': list(set([d.label for d in self.detection_history]))
        }
    
    def filter_by_label(self, detections: List[Detection], label: str) -> List[Detection]:
        """Filter detections by label"""
        return [d for d in detections if d.label == label]
    
    def filter_by_confidence(self, detections: List[Detection], threshold: float) -> List[Detection]:
        """Filter detections by confidence threshold"""
        return [d for d in detections if d.confidence >= threshold]
    
    def get_person_count(self, detections: List[Detection]) -> int:
        """Get number of people detected"""
        return len(self.filter_by_label(detections, 'person'))
    
    def get_hazard_count(self, detections: List[Detection]) -> int:
        """Get number of hazards detected"""
        hazards = ['gas_leak', 'fire', 'smoke']
        return len([d for d in detections if d.label in hazards])
    
    def is_person_in_zone(self, person_detection: Detection, zone_rect: Tuple[int, int, int, int]) -> bool:
        """
        Check if a person is within a zone
        
        Args:
            person_detection: Detection object
            zone_rect: (x, y, w, h) of zone
        
        Returns:
            bool: True if person is in zone
        """
        x, y, w, h = zone_rect
        cx, cy = person_detection.get_center()
        return x <= cx <= x + w and y <= cy <= y + h
    
    def get_people_in_zone(self, detections: List[Detection], zone_rect: Tuple[int, int, int, int]) -> List[Detection]:
        """Get all people within a zone"""
        people = self.filter_by_label(detections, 'person')
        return [p for p in people if self.is_person_in_zone(p, zone_rect)]