"""
Camera Manager - Handles video capture from multiple sources
Supports webcam, IP cameras, and video files
"""

import types
try:
    import cv2
except ImportError:  # opencv-python-headless not installed in this environment
    cv2: types.ModuleType | None = None
import threading
import time
from typing import Dict, Optional, List, Tuple, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import matplotlib.axes
from datetime import datetime
import os
import numpy as np


class CameraSource:
    """Represents a single camera source"""
    
    def __init__(self, source_id: str, source_type: str, source_path: str) -> None:
        self.id = source_id
        self.type = source_type  # 'webcam', 'ip_camera', 'video_file'
        self.path = source_path
        self.cap = None
        self.is_running = False
        self.frame = None
        self.fps = 0
        self.last_update = None
        self.error = None
        self.frame_count = 0
        
    def connect(self) -> bool:
        """Connect to the camera source"""
        if cv2 is None:
            self.error = "cv2 (opencv-python-headless) is not installed"
            return False
        try:
            if self.type == 'webcam':
                self.cap = cv2.VideoCapture(int(self.path))
            elif self.type == 'ip_camera':
                self.cap = cv2.VideoCapture(self.path)
            elif self.type == 'video_file':
                self.cap = cv2.VideoCapture(self.path)
            else:
                raise ValueError(f"Unknown source type: {self.type}")
            
            if not self.cap.isOpened():
                raise Exception("Failed to open camera")
            
            self.is_running = True
            self.last_update = datetime.now()
            return True
        except Exception as e:
            self.error = str(e)
            return False
    
    def read_frame(self) -> Optional[np.ndarray]:
        """Read a single frame from the camera"""
        if self.cap and self.is_running:
            ret, frame = self.cap.read()
            if ret:
                self.frame = frame
                self.last_update = datetime.now()
                self.frame_count += 1
                return frame
        return None
    
    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame without reading new one"""
        return self.frame
    
    def release(self) -> None:
        """Release the camera resources"""
        if self.cap:
            self.cap.release()
        self.is_running = False


class CameraManager:
    """
    Manages multiple camera sources
    Supports real-time streaming and frame capture
    """
    
    def __init__(self) -> None:
        self.cameras: Dict[str, CameraSource] = {}
        self.active_cameras: Dict[str, bool] = {}
        self.frame_buffer: Dict[str, list] = {}
        self.buffer_size = 30  # Keep last 30 frames
        self.is_streaming = False
        self.stream_thread = None
        self._lock = threading.Lock()
        
    def add_camera(self, source_id: str, source_type: str, source_path: str) -> bool:
        """
        Add a new camera source
        
        Args:
            source_id: Unique identifier for the camera
            source_type: 'webcam', 'ip_camera', 'video_file'
            source_path: For webcam: '0', '1', etc. For IP: 'rtsp://...', For file: '/path/to/video.mp4'
        
        Returns:
            bool: True if camera was added successfully
        """
        with self._lock:
            camera = CameraSource(source_id, source_type, source_path)
            if camera.connect():
                self.cameras[source_id] = camera
                self.active_cameras[source_id] = True
                self.frame_buffer[source_id] = []
                print(f"✅ Camera {source_id} added successfully")
                return True
            else:
                print(f"❌ Failed to add camera {source_id}: {camera.error}")
                return False
    
    def remove_camera(self, source_id: str) -> None:
        """Remove a camera source"""
        with self._lock:
            if source_id in self.cameras:
                self.cameras[source_id].release()
                del self.cameras[source_id]
                del self.active_cameras[source_id]
                if source_id in self.frame_buffer:
                    del self.frame_buffer[source_id]
                print(f"✅ Camera {source_id} removed")
    
    def start_streaming(self) -> None:
        """Start real-time streaming from all active cameras"""
        if self.is_streaming:
            return
        
        self.is_streaming = True
        self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.stream_thread.start()
        print("✅ Camera streaming started")
    
    def stop_streaming(self) -> None:
        """Stop streaming"""
        self.is_streaming = False
        if self.stream_thread:
            self.stream_thread.join(timeout=2)
        print("⏹️ Camera streaming stopped")
    
    def _stream_loop(self) -> None:
        """Main streaming loop - runs in background thread"""
        while self.is_streaming:
            with self._lock:
                for camera_id, camera in self.cameras.items():
                    if self.active_cameras.get(camera_id, False):
                        frame = camera.read_frame()
                        if frame is not None:
                            # Add to buffer
                            self.frame_buffer[camera_id].append(frame)
                            # Keep buffer size limited
                            if len(self.frame_buffer[camera_id]) > self.buffer_size:
                                self.frame_buffer[camera_id].pop(0)
            
            # Sleep to control FPS (approximately 30 FPS)
            time.sleep(0.033)
    
    def get_latest_frame(self, camera_id: str) -> Optional[np.ndarray]:
        """Get the latest frame from a camera"""
        with self._lock:
            if camera_id in self.frame_buffer and self.frame_buffer[camera_id]:
                return self.frame_buffer[camera_id][-1]
        return None
    
    def get_frame_history(self, camera_id: str, count: int = 10) -> List[np.ndarray]:
        """Get recent frames from a camera"""
        with self._lock:
            if camera_id in self.frame_buffer:
                return self.frame_buffer[camera_id][-count:]
        return []
    
    def get_camera_status(self, camera_id: str) -> Dict:
        """Get status of a camera"""
        with self._lock:
            if camera_id in self.cameras:
                camera = self.cameras[camera_id]
                return {
                    'id': camera.id,
                    'type': camera.type,
                    'is_running': camera.is_running,
                    'fps': camera.fps,
                    'frame_count': camera.frame_count,
                    'last_update': camera.last_update,
                    'error': camera.error,
                    'buffer_size': len(self.frame_buffer.get(camera_id, []))
                }
        return {}
    
    def get_all_camera_status(self) -> Dict:
        """Get status of all cameras"""
        return {cid: self.get_camera_status(cid) for cid in self.cameras.keys()}
    
    def get_available_cameras(self) -> List[str]:
        """Get list of available camera sources"""
        if cv2 is None:
            return []
        sources = []
        
        # Check webcams (0-5)
        for i in range(5):
            try:
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    sources.append(f'webcam_{i}')
                    cap.release()
            except Exception:
                pass
        
        return sources
    
    def toggle_camera(self, camera_id: str, active: bool) -> None:
        """Enable or disable a camera"""
        with self._lock:
            if camera_id in self.active_cameras:
                self.active_cameras[camera_id] = active
                print(f"Camera {camera_id} {'activated' if active else 'deactivated'}")


# ============================================
# DEMO VIDEO GENERATOR (For Hackathon)
# ============================================

class DemoVideoGenerator:
    """
    Generates sample CCTV footage for demo purposes
    Simulates real CCTV feed when no camera is available
    """
    
    @staticmethod
    def generate_sample_frame(zone: str = 'Zone_A', timestamp: Optional[datetime] = None, zone_risks: dict = None, latest: dict = None) -> np.ndarray:
        """
        Generate a simulated CCTV frame with stick figure workers and zones
        
        Args:
            zone: Zone name to display
            timestamp: Timestamp for the frame
            zone_risks: Dictionary containing risk level for each zone
            latest: Current telemetry record dictionary
        
        Returns:
            numpy.ndarray: Generated frame as OpenCV image
        """
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle, Wedge
        from io import BytesIO
        import numpy as np
        import random
        
        if timestamp is None:
            timestamp = datetime.now()
            
        time_str = timestamp.strftime("%H:%M:%S")
        
        # Calculate a frame number for animation seed
        frame_num = int(timestamp.second * 10 + timestamp.microsecond // 100000)
        
        fig, ax = plt.subplots(figsize=(10, 7))
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 70)
        ax.set_facecolor('#0a0e17')
        ax.axis('off')
        
        # Scanline effect (makes it look like real CCTV)
        for y in range(0, 70, 2):
            ax.axhline(y, color='black', alpha=0.08, linewidth=0.5)
            
        # Translate zone parameter to label
        zone_label_display = zone
        if zone == 'Zone_A': zone_label_display = 'Zone_A (Battery-4)'
        elif zone == 'Zone_B': zone_label_display = 'Zone_B (Battery-5)'
        elif zone == 'Zone_C': zone_label_display = 'Zone_C (Battery-6)'
        elif zone == 'Reactor_Area': zone_label_display = 'Reactor Block'
        elif zone == 'Storage_Area': zone_label_display = 'Storage Area'
        
        # Timestamp and zone header
        ax.text(50, 67, f'REC  ●  {time_str}', color='white', 
                ha='center', fontsize=11, fontweight='bold')
        ax.text(2, 67, f'CAM-04 | {zone_label_display}', color='#00ff41', 
                fontsize=9, fontweight='bold')
        ax.text(85, 67, 'LIVE', color='#ff0000', 
                fontsize=10, fontweight='bold')
                
        # Define plant zones with coordinates matching new layout
        zones_def = [
            {'name': 'Zone_A', 'id': 'Zone_A', 'x': 3,  'y': 35, 'w': 28, 'h': 28},
            {'name': 'Zone_B', 'id': 'Zone_B', 'x': 36, 'y': 35, 'w': 28, 'h': 28},
            {'name': 'Zone_C', 'id': 'Zone_C', 'x': 69, 'y': 35, 'w': 28, 'h': 28},
            {'name': 'Reactor', 'id': 'Reactor_Area', 'x': 3,  'y': 5,  'w': 40, 'h': 25},
            {'name': 'Storage', 'id': 'Storage_Area', 'x': 57, 'y': 5,  'w': 40, 'h': 25},
        ]
        
        # Color mapping based on risk status
        risk_colors = {'HIGH': '#ff4444', 'MED': '#f59e0b', 'LOW': '#00ff41'}
        
        safe_count = 0
        warning_count = 0
        danger_count = 0
        
        # Draw each zone with dynamic colors based on active risks
        for z in zones_def:
            risk_level = 'LOW'
            if zone_risks and z['id'] in zone_risks:
                risk_level = zone_risks[z['id']].get('risk_level', 'LOW')
                
            # Map risk levels to LOW, MED, HIGH
            mapped_risk = 'HIGH' if risk_level == 'CRITICAL' or risk_level == 'HIGH' else 'MED' if risk_level == 'MEDIUM' else 'LOW'
            
            # Count safe/warn/danger zones
            if mapped_risk == 'LOW':
                safe_count += 1
            elif mapped_risk == 'MED':
                warning_count += 1
            else:
                danger_count += 1
                
            color = risk_colors[mapped_risk]
            
            # Draw zone rectangle with alpha fill
            rect = Rectangle((z['x'], z['y']), z['w'], z['h'],
                             linewidth=1.5, edgecolor=color, 
                             facecolor=color, alpha=0.05)
            ax.add_patch(rect)
            
            # Label
            ax.text(z['x']+1, z['y']+z['h']-3, z['name'],
                    color=color, fontsize=7, fontweight='bold')
            ax.text(z['x']+1, z['y']+z['h']-6, mapped_risk,
                    color=color, fontsize=6, alpha=0.8)
                    
        # ── STICK FIGURE WORKERS DRAWING FUNCTION (FIXED LIGHTBULB APPEARANCE) ──
        def draw_stick_figure(
            ax: 'matplotlib.axes.Axes',
            cx: float,
            cy: float,
            color: str = '#00d4ff',
            has_helmet: bool = True,
            alert: bool = False,
        ) -> None:
            lw = 1.8
            # Head: solid background fill, color outline, zorder to render cleanly
            head = plt.Circle((cx, cy+5.5), 1.6, 
                              facecolor='#0a0e17', edgecolor=color, fill=True, linewidth=lw, zorder=5)
            ax.add_patch(head)
            
            # Helmet: solid Wedge dome with brim line on top of head circle (no transparency/lightbulb glow)
            if has_helmet:
                helmet = Wedge((cx, cy+5.5), 1.8, 0, 180, 
                               color='#f59e0b', zorder=6)
                ax.add_patch(helmet)
                # Brim line
                ax.plot([cx-2.2, cx+2.2], [cy+5.5, cy+5.5], 
                        color='#f59e0b', linewidth=2.0, solid_capstyle='round', zorder=7)
                        
            # Body
            ax.plot([cx, cx], [cy+3.8, cy+1.5], 
                    color=color, linewidth=lw, solid_capstyle='round', zorder=4)
            # Arms
            ax.plot([cx-2.5, cx+2.5], [cy+2.8, cy+2.8], 
                    color=color, linewidth=lw, solid_capstyle='round', zorder=4)
            # Legs
            ax.plot([cx, cx-2], [cy+1.5, cy-1.5], 
                    color=color, linewidth=lw, solid_capstyle='round', zorder=4)
            ax.plot([cx, cx+2], [cy+1.5, cy-1.5], 
                    color=color, linewidth=lw, solid_capstyle='round', zorder=4)
                    
            # Alert ring if in danger/high-risk zone
            if alert:
                ring = plt.Circle((cx, cy+3), 5, 
                                 color='#ff4444', fill=False, 
                                 linewidth=1, alpha=0.6, linestyle='--', zorder=3)
                ax.add_patch(ring)
                
        # Simulate worker positions dynamically inside the active zones
        total_workers = 0
        total_ppe_violations = 0
        active_gas_zone = None
        
        for z in zones_def:
            # Seed uniquely based on zone name to stabilize placements
            seed_val = int(z['x'] * 100 + z['y'] + frame_num)
            random.seed(seed_val)
            
            num_workers = 0
            if latest is not None:
                num_workers = int(latest.get(f"{z['id']}_worker_count", 0))
                # Check if this zone has gas leak
                gas_ppm = float(latest.get(f"{z['id']}_gas_ppm", 0.0))
                if gas_ppm > 30:
                    active_gas_zone = z['name']
            else:
                num_workers = random.randint(1, 4)
                
            total_workers += num_workers
            
            # Risk status of this zone
            risk_level = 'LOW'
            if zone_risks and z['id'] in zone_risks:
                risk_level = zone_risks[z['id']].get('risk_level', 'LOW')
            alert_active = (risk_level in ['HIGH', 'CRITICAL'])
            
            for i in range(num_workers):
                wx = z['x'] + random.uniform(3, z['w'] - 3)
                wy = z['y'] + random.uniform(3, z['h'] - 8)
                
                # Determine if worker has helmet (recreate same simulation logic)
                has_helmet = True
                if latest is not None and latest.get('max_risk_level') == 'CRITICAL' and z['id'] == 'Zone_A' and i >= 5:
                    has_helmet = False
                elif latest is not None and latest.get('max_risk_level') == 'CRITICAL' and z['id'] == 'Storage_Area' and i == 0:
                    has_helmet = False
                elif latest is None and random.random() < 0.2:
                    has_helmet = False
                    
                if not has_helmet:
                    total_ppe_violations += 1
                    
                worker_color = '#ff4444' if alert_active else '#00d4ff'
                draw_stick_figure(ax, wx, wy, color=worker_color, 
                                 has_helmet=has_helmet, alert=alert_active)
                                 
        # Reset random seed
        random.seed(None)
        
        # Bottom status bar matching user mockup
        ax.add_patch(Rectangle((0, 0), 100, 4, facecolor='black', alpha=0.7))
        ax.text(2,  1.5, f'Workers: {total_workers}', color='white', fontsize=8)
        ax.text(25, 1.5, f'PPE Violations: {total_ppe_violations}', 
                color='#f59e0b', fontsize=8, fontweight='bold')
        
        if active_gas_zone:
            ax.text(55, 1.5, f'Gas Alert: {active_gas_zone}', 
                    color='#ff4444', fontsize=8, fontweight='bold')
        else:
            ax.text(55, 1.5, 'Sensors: Normal', 
                    color='#00ff41', fontsize=8)
                    
        ax.text(82, 1.5, 'AI ACTIVE', color='#00ff41', fontsize=8, fontweight='bold')
        
        # Convert to image
        plt.tight_layout(pad=0)
        fig.patch.set_facecolor('#0a0e17')
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=80, facecolor='#0a0e17', bbox_inches='tight')
        buf.seek(0)
        buf_data = buf.getvalue()
        plt.close()
        
        img_data = np.frombuffer(buf_data, dtype=np.uint8)
        if cv2 is not None:
            img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        else:
            # Fallback: decode via PIL and return as numpy RGB array
            from PIL import Image as _PILImage
            import io as _io
            img = np.array(_PILImage.open(_io.BytesIO(buf_data)).convert('RGB'))
        return img
    
    @staticmethod
    def generate_video_frames(zone: str = 'Zone_A', 
                             duration_seconds: int = 10, 
                             fps: int = 5) -> List[np.ndarray]:
        """
        Generate a sequence of frames for video demo
        
        Args:
            zone: Zone name
            duration_seconds: Duration of video
            fps: Frames per second
        
        Returns:
            List of frames
        """
        from datetime import timedelta
        
        frames = []
        start_time = datetime.now()
        
        for i in range(duration_seconds * fps):
            current_time = start_time + timedelta(seconds=i/fps)
            frame = DemoVideoGenerator.generate_sample_frame(zone, current_time)
            frames.append(frame)
        
        return frames
    
    @staticmethod
    def save_video(frames: List[np.ndarray], output_path: str, fps: int = 5) -> None:
        """Save frames as a video file"""
        if cv2 is None:
            raise RuntimeError("cv2 (opencv-python-headless) is required to save video files")
        if not frames:
            return
        
        h, w = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
        
        for frame in frames:
            out.write(frame)
        
        out.release()
        print(f"✅ Video saved to {output_path}")