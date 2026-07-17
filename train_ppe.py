import os
import sys
import shutil
from pathlib import Path

def main() -> None:
    print("\n--- Environment Setup ---")
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] ultralytics package is not installed. Please run: pip install ultralytics")
        sys.exit(1)
        
    print("[SUCCESS] Dependencies verified.")
    
    # Create models directory
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    
    # Path to data.yaml
    data_yaml_path = Path("data/battery5_ppe/data.yaml")
    if not data_yaml_path.exists():
        print(f"[ERROR] data.yaml not found at {data_yaml_path}. Please run dataset generation first.")
        sys.exit(1)
        
    # Start YOLO training
    print(f"\n--- Fine-tuning YOLOv8n PPE Model on Battery-5 Dataset ---")
    print(f"Base Model: yolov8n.pt")
    print(f"Epochs: 50")
    print(f"Image Size: 640")
    print(f"Batch Size: 16")
    
    try:
        # Load stock YOLOv8n model
        model = YOLO("yolov8n.pt")
        
        # Train model
        results = model.train(
            data=str(data_yaml_path.absolute()),
            epochs=50,
            imgsz=640,
            batch=16,
            device="cpu", # Default to CPU for maximum portability (will use GPU if PyTorch is set up for CUDA)
            name="yolov8n_ppe"
        )
        
        print("\n--- Training Completed ---")
        
        # Locate best.pt
        run_dir = Path("runs") / "detect" / "yolov8n_ppe" / "weights" / "best.pt"
        if not run_dir.exists():
            # Fallback search
            run_dir = next(Path("runs").glob("**/weights/best.pt"), None)
            
        if run_dir and run_dir.exists():
            dest_path = models_dir / "best_ppe.pt"
            shutil.copy(run_dir, dest_path)
            print(f"[SUCCESS] Exported best model weights to: {dest_path}")
        else:
            print("[WARNING] Could not locate trained best.pt file automatically.")
            
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
