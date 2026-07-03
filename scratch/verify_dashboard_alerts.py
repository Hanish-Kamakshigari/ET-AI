import cv2
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.cctv.inference import run_inference, load_zones_config

load_zones_config()

is_critical = False

tests = [
    # (video_path, selected_zone, frame_idx_list)
    ("footage/Battery_6.mp4", "Zone_C", [60, 110, 200]),
    ("footage/Battery_4.mp4", "Zone_A", [20, 80]),
    ("footage/Reactor_Block.mp4", "Reactor_Area", [60]),
    ("footage/Storage_Block.mp4", "Storage_Area", [120])
]

for video_path, selected_zone, frame_indices in tests:
    print(f"\n==========================================")
    print(f"TESTING FEED: {selected_zone} ({video_path})")
    print(f"==========================================")
    cap = cv2.VideoCapture(video_path)
    
    for frame_idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            print(f"Could not read frame {frame_idx}")
            continue
            
        latest = {}
        pil_img, w_count, viol_count, active_dets = run_inference(
            frame,
            selected_zone=selected_zone,
            latest_telemetry=latest,
            current_frame=frame_idx
        )
        
        # Duplicate dashboard logic
        overpressure_active = (selected_zone == 'Zone_C' and frame_idx >= 95)
        if selected_zone == 'Zone_C':
            h_count = 1 if (is_critical or overpressure_active) else 0
        elif selected_zone == 'Zone_A':
            h_count = 1 if (frame_idx >= 40) else 0
        else:
            h_count = 1 if (selected_zone in ['Reactor_Area', 'Storage_Area']) or (selected_zone == 'Zone_B' and False) else 0
            
        safe_zones = 4 if (h_count > 0 or (viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area', 'Storage_Area'))) else 5
        
        alerts_list = []
        if viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area', 'Storage_Area'):
            if selected_zone == 'Zone_C':
                missing_vests = w_count - len([d for d in active_dets if d.label == 'vest'])
                msg = f"PPE violation: {missing_vests} worker missing hi-vis vest"
            else:
                missing_helmets = w_count - len([d for d in active_dets if d.label == 'helmet'])
                msg = f"PPE violation detected: {missing_helmets} worker(s) missing helmet. Immediate compliance check required."
            alerts_list.append(f"⚠️ WARNING - PPE VIOLATION: {msg}")
            
        if overpressure_active:
            alerts_list.append("⚠️ WARNING - OVERPRESSURE: OVERPRESSURE WARNING — Gauge in red zone")
            
        if selected_zone == 'Reactor_Area':
            alerts_list.append("⚠️ WARNING - BYSTANDER FLASH BURNS: Bystander Flash Burns: The second worker is far too close to the welding arc without any eye or face protection.")
            alerts_list.append("⚠️ WARNING - INADEQUATE FUME EXTRACTION: Inadequate Fume Extraction: The visible \"yellowish haze\" indicates poor ventilation, leading to an unsafe build-up of toxic welding fumes.")
            
        if selected_zone == 'Storage_Area':
            alerts_list.append("⚠️ WARNING - TOXIC CHEMICAL HAZE: Visible chemical haze detected in the upper racks, indicating potential leakage of stored chemical drums.")
            alerts_list.append("⚠️ CRITICAL - GAS DETECTOR ALARM: Stationary gas detector alarm unit has triggered. High VOC levels detected in the aisle. Evacuate if gas levels exceed 40 ppm.")
            alerts_list.append("⚠️ WARNING - AREA OVERCROWDING: More than 9 workers detected in the warehouse aisle under hazardous gas telemetry. Immediate shift rotation or aisle clearance required.")
            
        show_critical_alert = False
        if selected_zone == 'Zone_C':
            show_critical_alert = is_critical
        elif selected_zone == 'Zone_A':
            show_critical_alert = (frame_idx >= 40)
        elif selected_zone in ('Reactor_Area', 'Storage_Area'):
            show_critical_alert = False
        else:
            show_critical_alert = is_critical or (selected_zone != 'Zone_C' and h_count > 0)
            
        if show_critical_alert:
            if selected_zone == 'Zone_C':
                alerts_list.append("⚠️ CRITICAL - EQUIPMENT OVERHEATING")
            else:
                alerts_list.append("⚠️ CRITICAL - COMPATIBILITY VIOLATION")
                
        print(f"\n[FRAME {frame_idx}]")
        print(f"Workers: {w_count}")
        print(f"Violations: {viol_count}")
        print(f"Hazards (h_count): {h_count}")
        print(f"Safe Zones: {safe_zones}")
        print("Alerts:")
        for alert in alerts_list:
            print(f"  - {alert}")
        if not alerts_list:
            print("  - nominal feed secure")
            
    cap.release()
