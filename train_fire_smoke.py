import os
import sys
import argparse
import shutil
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Train YOLOv8 on Fire & Smoke Dataset from Roboflow")
    parser.add_argument(
        "--api_key", 
        type=str, 
        default=os.environ.get("ROBOFLOW_API_KEY"),
        help="Roboflow API Key. Can also be set via ROBOFLOW_API_KEY environment variable."
    )
    parser.add_argument(
        "--workspace", 
        type=str, 
        default="roboflow-universe-open-source",
        help="Roboflow Workspace ID"
    )
    parser.add_argument(
        "--project", 
        type=str, 
        default="fire-and-smoke-yolomin", # A popular public fire/smoke project on Roboflow Universe
        help="Roboflow Project ID (e.g. fire-and-smoke-yolomin)"
    )
    parser.add_argument(
        "--version", 
        type=int, 
        default=1,
        help="Dataset Version Number"
    )
    parser.add_argument(
        "--epochs", 
        type=int, 
        default=50,
        help="Number of epochs to train (default: 50, target: 50-100)"
    )
    parser.add_argument(
        "--imgsz", 
        type=int, 
        default=640,
        help="Image size for training (default: 640)"
    )
    parser.add_argument(
        "--batch", 
        type=int, 
        default=16,
        help="Batch size (default: 16)"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Check for Roboflow API Key
    api_key = args.api_key
    if not api_key:
        print("\n[ERROR] Roboflow API Key is required.")
        print("Please obtain it from https://app.roboflow.com and pass it via --api_key or set ROBOFLOW_API_KEY env variable.")
        api_key = input("Enter your Roboflow API Key: ").strip()
        if not api_key:
            sys.exit(1)
            
    print("\n--- Environment Setup ---")
    # Verify/Install ultralytics and roboflow imports
    try:
        from roboflow import Roboflow
    except ImportError:
        print("[ERROR] roboflow package is not installed. Please run: pip install roboflow")
        sys.exit(1)
        
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] ultralytics package is not installed. Please run: pip install ultralytics")
        sys.exit(1)
        
    print("[SUCCESS] Dependencies verified.")
    
    # Create models directory
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    
    # Download dataset from Roboflow Universe
    print(f"\n--- Sourcing Dataset from Roboflow Universe ---")
    print(f"Workspace: {args.workspace}")
    print(f"Project: {args.project}")
    print(f"Version: {args.version}")
    
    try:
        rf = Roboflow(api_key=api_key)
        project = rf.workspace(args.workspace).project(args.project)
        dataset = project.version(args.version).download("yolov8")
        print(f"[SUCCESS] Dataset downloaded to: {dataset.location}")
    except Exception as e:
        print(f"[ERROR] Failed to download dataset: {e}")
        sys.exit(1)
        
    # Check for data.yaml
    data_yaml_path = Path(dataset.location) / "data.yaml"
    if not data_yaml_path.exists():
        print(f"[ERROR] data.yaml not found at {data_yaml_path}")
        sys.exit(1)
        
    # Start YOLO training
    print(f"\n--- Fine-tuning YOLOv8n Fire & Smoke Model ---")
    print(f"Base Model: yolov8n.pt")
    print(f"Epochs: {args.epochs}")
    print(f"Image Size: {args.imgsz}")
    print(f"Batch Size: {args.batch}")
    
    try:
        # Load stock YOLOv8n model
        model = YOLO("yolov8n.pt")
        
        # Train model
        results = model.train(
            data=str(data_yaml_path.absolute()),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            device="cpu", # Default to CPU, will auto-use GPU if CUDA works in PyTorch
            name="yolov8n_fire"
        )
        
        print("\n--- Training Completed ---")
        
        # Locate best.pt
        run_dir = Path("runs") / "detect" / "yolov8n_fire" / "weights" / "best.pt"
        if not run_dir.exists():
            # Fallback search if different run naming occurred
            run_dir = next(Path("runs").glob("**/weights/best.pt"), None)
            
        if run_dir and run_dir.exists():
            dest_path = models_dir / "best_fire_smoke.pt"
            shutil.copy(run_dir, dest_path)
            print(f"[SUCCESS] Exported best model weights to: {dest_path}")
        else:
            print("[WARNING] Could not locate trained best.pt file automatically.")
            print("Please manually copy your best.pt file from runs/detect to models/best_fire_smoke.pt")
            
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
