"""
Frame Processor - Processes frames and generates alerts
"""

import cv2
import numpy as np
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
import time
from collections import deque

if __name__ == "__main__" or __package__ is None:
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
    from src.cctv.object_detector import ObjectDetector, Detection
    from src.risk_engine import CompoundRiskEngine
    from src.alert_system import AlertSystem
else:
    from .object_detector import ObjectDetector, Detection
    from src.risk_engine import CompoundRiskEngine
    from src.alert_system import AlertSystem


class FrameProcessor:
    """
    Processes CCTV frames, runs detection, and generates alerts
    """
    
    def __init__(self, use_simulation: bool = True):
        self.detector = ObjectDetector(use_simulation=use_simulation)
        self.risk_engine = CompoundRiskEngine()
        self.alert_system = AlertSystem()
        self.alert_callback = None
        self.alert_history = []
        self.alert_history_max = 100
        
        # Zone configuration (normalized coordinates 0-100, y up to 70)
        self.zone_config = {
            'Zone_A': {'x': 3, 'y': 35, 'w': 28, 'h': 28, 'color': (0, 212, 255)},
            'Zone_B': {'x': 36, 'y': 35, 'w': 28, 'h': 28, 'color': (0, 212, 255)},
            'Zone_C': {'x': 69, 'y': 35, 'w': 28, 'h': 28, 'color': (0, 212, 255)},
            'Reactor_Area': {'x': 3, 'y': 5, 'w': 40, 'h': 25, 'color': (245, 158, 11)},
            'Storage_Area': {'x': 57, 'y': 5, 'w': 40, 'h': 25, 'color': (0, 212, 255)}
        }
        
        self.processed_frames = 0
        self.alerts_generated = 0
        self.zone_counts = {zone: 0 for zone in self.zone_config.keys()}
        self.frame_times = deque(maxlen=30)  # For FPS calculation
        self.last_alert_time = None
        self.alert_cooldown = 5  # Seconds between same alert type
        
    def process_frame(self, frame: np.ndarray, selected_zone: str = 'Zone_A', latest_telemetry: dict = None, workers: list = None, current_frame: int = 0) -> Dict:
        """
        Process a single frame
        
        Args:
            frame: OpenCV image
            selected_zone: Active zone name
            latest_telemetry: Current telemetry record dictionary
            workers: Keyframe worker definitions list
            current_frame: Video reader frame number index
            
        Returns:
            Dict with detection results and alerts
        """
        start_time = time.time()
        self.processed_frames += 1
        
        # Inject parameters into the detector
        self.detector.selected_zone = selected_zone
        self.detector.latest_telemetry = latest_telemetry
        
        # Run detection
        detections = self.detector.detect(frame, workers=workers, current_frame=current_frame)
        
        # Count workers by zone
        h, w = frame.shape[:2]
        self._update_zone_counts(detections, w, h)
        
        # Generate alerts
        alerts = self._generate_alerts(frame, detections, selected_zone)
        
        # Calculate FPS
        elapsed = time.time() - start_time
        self.frame_times.append(elapsed)
        
        result = {
            'timestamp': datetime.now(),
            'detections': detections,
            'zone_counts': self.zone_counts.copy(),
            'alerts': alerts,
            'frame_number': self.processed_frames,
            'fps': self._calculate_fps()
        }
        
        return result
    
    def _update_zone_counts(self, detections: List[Detection], frame_w: int, frame_h: int):
        """Update worker counts per zone from telemetry (footage ground truth)"""
        latest = getattr(self.detector, 'latest_telemetry', None)
        if latest is not None:
            self.zone_counts = {
                'Zone_A':       int(latest.get('Zone_A_worker_count', 0)),
                'Zone_B':       int(latest.get('Zone_B_worker_count', 0)),
                'Zone_C':       int(latest.get('Zone_C_worker_count', 0)),
                'Reactor_Area': int(latest.get('Reactor_Area_worker_count', 0)),
                'Storage_Area': int(latest.get('Storage_Area_worker_count', 0)),
            }
        else:
            # Fallback: count 'person' detections from selected zone only
            self.zone_counts = {zone: 0 for zone in self.zone_config.keys()}
            selected_zone = getattr(self.detector, 'selected_zone', 'Zone_A')
            people = self.detector.filter_by_label(detections, 'person')
            self.zone_counts[selected_zone] = len(people)
    
    def _generate_alerts(self, frame: np.ndarray, detections: List[Detection], selected_zone: str = 'Zone_A') -> List[Dict]:
        """Generate alerts from detections"""
        alerts = []
        current_time = datetime.now()
        
        zone_labels = {
            'Zone_A': 'Battery-4',
            'Zone_B': 'Battery-5',
            'Zone_C': 'Battery-6',
            'Reactor_Area': 'Reactor Block',
            'Storage_Area': 'Storage Area',
            'Control_Room': 'Control Room'
        }
        zone_name = zone_labels.get(selected_zone, selected_zone)
        
        people = self.detector.filter_by_label(detections, 'person')
        count = len(people)
        
        # 1. Check for crowding (workers > 5 in selected zone)
        if count > 5:
            alerts.append({
                'type': 'OVER_CROWDING',
                'zone': selected_zone,
                'severity': 'MEDIUM',
                'message': f'{count} workers detected in {zone_name} (Limit: 5)',
                'timestamp': current_time,
                'count': count
            })
        elif count > 3:
            alerts.append({
                'type': 'ELEVATED_WORKERS',
                'zone': selected_zone,
                'severity': 'LOW',
                'message': f'{count} workers in {zone_name} (Monitor closely)',
                'timestamp': current_time,
                'count': count
            })
        
        # 2. Check for hazards
        hazards = self.detector.filter_by_label(detections, 'gas_leak')
        hazards.extend(self.detector.filter_by_label(detections, 'fire'))
        hazards.extend(self.detector.filter_by_label(detections, 'smoke'))
        
        has_hazard = False
        for hazard in hazards:
            has_hazard = True
            alerts.append({
                'type': 'HAZARD_DETECTED',
                'zone': selected_zone,
                'severity': 'HIGH',
                'message': f'⚠️ {hazard.label.upper().replace("_", " ")} detected in {zone_name}!',
                'timestamp': current_time,
                'confidence': hazard.confidence
            })
        
        # 3. Check for compound risk (crowding + gas/hazard)
        has_crowding = count > 5
        
        if has_crowding and has_hazard:
            alerts.append({
                'type': 'COMPOUND_RISK',
                'zone': selected_zone,
                'severity': 'CRITICAL',
                'message': f'Overcrowding ({count} workers) + Gas leak detected. ⚠️ Same pattern as Visakhapatnam tragedy!',
                'timestamp': current_time,
                'compound_factors': ['OVER_CROWDING', 'HAZARD']
            })
        
        # 4. Check for PPE violations
        helmets = self.detector.filter_by_label(detections, 'helmet')
        vests = self.detector.filter_by_label(detections, 'vest')
        
        if len(people) > len(helmets):
            no_helmet_count = len(people) - len(helmets)
            alerts.append({
                'type': 'PPE_VIOLATION',
                'zone': selected_zone,
                'severity': 'HIGH',
                'message': f'{zone_name} has {no_helmet_count} workers without helmets. PPE violation detected. Workers at risk.',
                'timestamp': current_time
            })
        
        if len(people) > len(vests):
            no_vest_count = len(people) - len(vests)
            alerts.append({
                'type': 'PPE_VIOLATION',
                'zone': selected_zone,
                'severity': 'MEDIUM',
                'message': f'{zone_name} has {no_vest_count} workers without vests. PPE violation detected.',
                'timestamp': current_time
            })
        
        # Filter alerts based on cooldown
        filtered_alerts = []
        for alert in alerts:
            alert_key = f"{alert['type']}_{alert['zone']}"
            if self._can_alert(alert_key, alert['severity']):
                filtered_alerts.append(alert)
                self._record_alert(alert_key)
        
        # Store alerts
        for alert in filtered_alerts:
            self.alert_history.append(alert)
            self.alerts_generated += 1
            
            # Keep history limited
            if len(self.alert_history) > self.alert_history_max:
                self.alert_history = self.alert_history[-self.alert_history_max:]
            
            # Call callback if registered
            if self.alert_callback:
                self.alert_callback(alert)
        
        return filtered_alerts
    
    def _can_alert(self, alert_key: str, severity: str) -> bool:
        """Check if an alert can be generated based on cooldown"""
        # Critical alerts bypass cooldown
        if severity == 'CRITICAL':
            return True
        
        # PPE violations and hazard detections are always shown (persistent conditions)
        if any(k in alert_key for k in ['PPE_VIOLATION', 'HAZARD_DETECTED']):
            return True
        
        # Check cooldown for other alert types
        if not hasattr(self, '_last_alert_times'):
            self._last_alert_times = {}
        
        current_time = time.time()
        last_time = self._last_alert_times.get(alert_key, 0)
        
        cooldown = 10 if severity == 'HIGH' else 30 if severity == 'MEDIUM' else 60
        
        if current_time - last_time > cooldown:
            return True
        return False
    
    def _record_alert(self, alert_key: str):
        """Record when an alert was last sent"""
        if not hasattr(self, '_last_alert_times'):
            self._last_alert_times = {}
        self._last_alert_times[alert_key] = time.time()
    
    def _calculate_fps(self) -> float:
        """Calculate current FPS"""
        if len(self.frame_times) < 2:
            return 0
        
        total_time = sum(self.frame_times)
        return len(self.frame_times) / total_time if total_time > 0 else 0
    
    def set_alert_callback(self, callback: Callable):
        """Set callback for when alerts are generated"""
        self.alert_callback = callback
    
    def get_alert_summary(self) -> Dict:
        """Get summary of alerts"""
        return {
            'total_alerts': self.alerts_generated,
            'recent_alerts': self.alert_history[-10:],
            'zone_counts': self.zone_counts,
            'processed_frames': self.processed_frames,
            'fps': self._calculate_fps()
        }
    
    def draw_detections(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """Draw detection boxes on frame"""
        result = frame.copy()
        h, w = result.shape[:2]
        
        for d in detections:
            x, y, bw, bh = d.bbox
            # Ensure coordinates are within frame
            x = max(0, min(w-1, x))
            y = max(0, min(h-1, y))
            bw = min(w - x, bw)
            bh = min(h - y, bh)
            
            # Color coding by detection label
            if d.label in ['gas_leak', 'fire', 'smoke']:
                color = (239, 68, 68)  # Red for hazards (BGR format: 68, 68, 239) -> Wait, BGR is (68, 68, 239). Let's use standard BGR colors: (0, 0, 255) is red.
                # Actually, Streamlit cv2 BGR to RGB conversion means we should stick to OpenCV BGR colors, or just standard colors. Let's use:
                # BGR format: B, G, R
                # Red: (68, 68, 239) or (0, 0, 255)
                # Green: (94, 197, 34) or (0, 255, 0)
                # Cyan: (255, 212, 0) or (255, 255, 0)
                bgr_color = (0, 0, 255)  # Red
            elif d.label in ['helmet', 'vest']:
                bgr_color = (255, 255, 0)  # Cyan
            else:
                bgr_color = (0, 255, 0)  # Green for person/equipment
            
            # Draw rectangle
            cv2.rectangle(result, (x, y), (x + bw, y + bh), bgr_color, 2)
            
            # Draw label with confidence
            label_text = f"{d.label} {int(d.confidence * 100)}%"
            # Background text box
            (text_w, text_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
            cv2.rectangle(result, (x, y - text_h - 6), (x + text_w + 6, y), bgr_color, -1)
            # White text
            cv2.putText(result, label_text, (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            
        return result

    def draw_zone_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Draw safety zone boundaries and labels on frame"""
        result = frame.copy()
        h, w = result.shape[:2]
        
        for zone_name, rect in self.zone_config.items():
            # Convert normalized coordinates (0-100 x, 0-70 y) to pixel bounds in the OpenCV frame
            zx = int((rect['x'] / 100) * w)
            zw = int((rect['w'] / 100) * w)
            # Matplotlib y-axis starts from the bottom (0) up to 70.
            # OpenCV y-axis starts from the top (0) down to h.
            zy = int(((70 - rect['y'] - rect['h']) / 70) * h)
            zh = int((rect['h'] / 70) * h)
            
            # Color (BGR)
            bgr_color = rect['color']
            
            # Draw zone rectangle outline
            cv2.rectangle(result, (zx, zy), (zx + zw, zy + zh), bgr_color, 2)
            
            # Draw label background
            label_text = zone_name.replace('_', ' ')
            (text_w, text_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
            cv2.rectangle(result, (zx, zy), (zx + text_w + 6, zy + text_h + 8), bgr_color, -1)
            # Draw label text in white
            cv2.putText(result, label_text, (zx + 3, zy + text_h + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            
        return result
           