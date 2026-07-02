# SurakshaAI — YOLO-based CCTV Safety surveillance

SurakshaAI integrates real-time object detection and safety compliance checking into an industrial safety dashboard. It features live CCTV monitoring for PPE violation detection (hard hats, safety vests), restricted area intrusion detection using polygons, and fire/smoke hazard alerts.

---

## Features

1. **PPE Violation Detection** (Trained Model)
   * Detects workers, helmets, no-helmet, vests, and no-vest instances.
   * Generates alerts if workers are missing required safety equipment.
2. **Restricted Zone Intrusion Detection** (Real stock/trained model + Configurable polygons)
   * Evaluates if any worker's bounding-box centroid enters a restricted zone.
   * Fully configurable restricted polygons per CCTV camera stream.
3. **Fire & Smoke Hazard Detection** (Trained Model)
   * Real-time tracking of fire and smoke occurrences.
4. **Fall Detection** (Scripted heuristic)
   * Simple geometric aspect ratio check (`w > 1.2 * h`) to flag potential falls.
   * *Note: Temporal fall detection is currently out of scope for the YOLOv8 model training and is kept as a scripted warning rule.*

---

## Project Structure

* `zones.json`: Configuration file defining the coordinates of restricted area polygons per CCTV feed.
* `train_ppe.py`: Pipeline script to download a Construction PPE dataset from Roboflow and fine-tune YOLOv8n.
* `train_fire_smoke.py`: Pipeline script to download a Fire/Smoke dataset from Roboflow and fine-tune YOLOv8n.
* `src/cctv/inference.py`: Live frame processor performing YOLO model runs, centroid checks, visual rendering, and simulation fallback.
* `models/`: Destination folder for trained weights (`best_ppe.pt`, `best_fire_smoke.pt`).

---

## ⚙️ How to Retrain Models on New Footage

To retrain the models on your custom datasets or new footage from Roboflow Universe, follow these steps:

### 1. Prerequisites & API Key
You will need a Roboflow API key to download datasets programmatically. 
* Sign up or log in at [Roboflow Universe](https://universe.roboflow.com/).
* Navigate to your account settings to copy your **Private API Key**.
* Set it as an environment variable or pass it directly when running the training scripts:
  ```powershell
  $env:ROBOFLOW_API_KEY="your_api_key_here"
  ```

### 2. Fine-tune PPE Violation Model
Run the `train_ppe.py` script. By default, it uses a popular public Construction PPE dataset. You can customize the dataset by specifying your own project name/workspace:
```powershell
.\venv\Scripts\python.exe train_ppe.py --api_key "your_api_key" --workspace "roboflow-universe-open-source" --project "construction-site-safety-f3k7d" --version 1 --epochs 50
```
This will:
* Download the dataset in YOLOv8 format.
* Fine-tune a `yolov8n.pt` model on classes: `helmet`, `no-helmet`, `vest`, `no-vest`, `person`.
* Automatically copy the completed model weights to `models/best_ppe.pt`.

### 3. Fine-tune Fire & Smoke Model
To train the fire and smoke detection model, run the `train_fire_smoke.py` script:
```powershell
.\venv\Scripts\python.exe train_fire_smoke.py --api_key "your_api_key" --workspace "roboflow-universe-open-source" --project "fire-and-smoke-yolomin" --version 1 --epochs 50
```
This will:
* Download the dataset.
* Fine-tune the model.
* Automatically copy the completed model weights to `models/best_fire_smoke.pt`.

---

## 🗺️ Configuring Restricted Zones (`zones.json`)

The coordinates of safety zones and restricted areas are configurable per camera stream in the `zones.json` file in the workspace root. 

Example configuration:
```json
{
  "Zone_B": {
    "name": "Battery-5",
    "restricted_polygons": [
      [[500, 50], [800, 50], [800, 600], [500, 600]]
    ],
    "color": [0, 212, 255]
  }
}
```
* **`restricted_polygons`**: A list of coordinates representing polygon vertices in the `1280x720` resolution reference space. If a worker enters this polygon, an intrusion alert is triggered.
* **`color`**: Visual overlay outline color in BGR format `[Blue, Green, Red]`.

---

## 🛡️ Running the Surveillance Dashboard

Launch the Streamlit application to start the dashboard:
```powershell
.\venv\Scripts\streamlit run dashboard/app.py
```
Go to the **📹 AI CCTV SURVEILLANCE** tab. The dashboard will automatically detect whether custom weights are present:
* If `models/best_ppe.pt` and `models/best_fire_smoke.pt` exist, the dashboard runs **real-time custom YOLO inference** on the CCTV feeds.
* If custom weights are missing, the dashboard runs **live stock YOLOv8 person detection and polygon intrusion checks** while falling back gracefully to simulated overlays for PPE/hazards to keep the demonstration fully operational.
