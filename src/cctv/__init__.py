"""
CCTV + AI Integration Module
Real-time video analysis and detection
"""

if __name__ == "__main__" or __package__ is None:
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
    from src.cctv.camera_manager import CameraManager, DemoVideoGenerator
    from src.cctv.object_detector import ObjectDetector, Detection
    from src.cctv.frame_processor import FrameProcessor
    from src.cctv.inference import run_inference
else:
    from .camera_manager import CameraManager, DemoVideoGenerator
    from .object_detector import ObjectDetector, Detection
    from .frame_processor import FrameProcessor
    from .inference import run_inference

__all__ = [
    'CameraManager',
    'DemoVideoGenerator',
    'ObjectDetector',
    'Detection',
    'FrameProcessor',
    'run_inference'
]