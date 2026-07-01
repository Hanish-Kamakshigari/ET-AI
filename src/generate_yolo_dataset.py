import os
import random
import yaml
from PIL import Image, ImageDraw

def draw_worker(draw, cx_ref, cy_ref, scale, helmet, vest):
    # Apply minor position jitter
    cx = cx_ref + random.randint(-15, 15)
    cy = cy_ref + random.randint(-15, 15)
    
    # Body scale dimensions
    h_body = int(180 * scale)
    w_body = int(80 * scale)
    
    # Frame coordinates for person box
    p_x1 = cx - w_body // 2
    p_x2 = cx + w_body // 2
    p_y1 = cy - h_body // 2
    p_y2 = cy + h_body // 2
    
    # Draw legs (dark blue/gray pants)
    draw.rectangle([cx - int(w_body*0.25), cy + int(h_body*0.1), cx - int(w_body*0.05), cy + int(h_body*0.5)], fill=(35, 55, 95))
    draw.rectangle([cx + int(w_body*0.05), cy + int(h_body*0.1), cx + int(w_body*0.25), cy + int(h_body*0.5)], fill=(35, 55, 95))
    
    # Draw torso (gray shirt)
    draw.rectangle([cx - int(w_body*0.35), cy - int(h_body*0.25), cx + int(w_body*0.35), cy + int(h_body*0.1)], fill=(75, 80, 85))
    
    # Draw arms
    draw.rectangle([cx - int(w_body*0.48), cy - int(h_body*0.23), cx - int(w_body*0.35), cy + int(h_body*0.15)], fill=(75, 80, 85))
    draw.rectangle([cx + int(w_body*0.35), cy - int(h_body*0.23), cx + int(w_body*0.48), cy + int(h_body*0.15)], fill=(75, 80, 85))
    
    # Draw head (skin tone)
    head_r = int(18 * scale)
    hy_c = cy - int(h_body*0.32)
    draw.ellipse([cx - head_r, hy_c - head_r, cx + head_r, hy_c + head_r], fill=(230, 190, 155))
    
    worker_labels = []
    
    # 0: person class
    px1, py1, px2, py2 = p_x1, p_y1, p_x2, p_y2
    worker_labels.append((0, px1, py1, px2, py2))
    
    # Helmet vs No Helmet
    if helmet:
        # Yellow hardhat semi-circle
        hr_h = int(22 * scale)
        hr_w = int(22 * scale)
        draw.chord([cx - hr_w, hy_c - hr_h - int(5*scale), cx + hr_w, hy_c], 180, 360, fill=(255, 215, 0), outline=(220, 180, 0))
        # Brim line
        draw.line([(cx - hr_w - 2, hy_c - int(2*scale)), (cx + hr_w + 2, hy_c - int(2*scale))], fill=(255, 215, 0), width=max(1, int(2*scale)))
        hx1, hy1, hx2, hy2 = cx - hr_w, hy_c - hr_h - int(5*scale), cx + hr_w, hy_c
        worker_labels.append((1, hx1, hy1, hx2, hy2))
    else:
        # Brown hair
        draw.ellipse([cx - head_r, hy_c - head_r - int(2*scale), cx + head_r, hy_c - int(2*scale)], fill=(65, 45, 25))
        hx1, hy1, hx2, hy2 = cx - head_r, hy_c - head_r - int(2*scale), cx + head_r, hy_c
        worker_labels.append((2, hx1, hy1, hx2, hy2))
        
    # Vest vs No Vest
    if vest:
        # Orange hi-vis vest
        vx1 = cx - int(w_body*0.38)
        vx2 = cx + int(w_body*0.38)
        vy1 = cy - int(h_body*0.22)
        vy2 = cy + int(h_body*0.12)
        draw.rectangle([vx1, vy1, vx2, vy2], fill=(255, 110, 0))
        # Silver reflective stripes
        draw.line([(vx1 + 4, vy1 + 6), (vx1 + 4, vy2 - 4)], fill=(225, 255, 0), width=max(1, int(3*scale)))
        draw.line([(vx2 - 4, vy1 + 6), (vx2 - 4, vy2 - 4)], fill=(225, 255, 0), width=max(1, int(3*scale)))
        draw.line([(vx1 + 4, cy - int(h_body*0.05)), (vx2 - 4, cy - int(h_body*0.05))], fill=(225, 255, 0), width=max(1, int(3*scale)))
        worker_labels.append((3, vx1, vy1, vx2, vy2))
    else:
        # Standard shirt dimensions as no_vest boundary
        vx1 = cx - int(w_body*0.38)
        vx2 = cx + int(w_body*0.38)
        vy1 = cy - int(h_body*0.22)
        vy2 = cy + int(h_body*0.12)
        worker_labels.append((4, vx1, vy1, vx2, vy2))
        
    return worker_labels

def to_yolo_format(labels, img_width=640, img_height=640):
    lines = []
    for cls_id, x1, y1, x2, y2 in labels:
        x1 = max(0, min(x1, img_width))
        x2 = max(0, min(x2, img_width))
        y1 = max(0, min(y1, img_height))
        y2 = max(0, min(y2, img_height))
        
        w = (x2 - x1) / img_width
        h = (y2 - y1) / img_height
        cx = ((x1 + x2) / 2) / img_width
        cy = ((y1 + y2) / 2) / img_height
        
        lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines

def generate_dataset():
    base_dir = "data/battery5_ppe"
    for split in ["train", "val"]:
        os.makedirs(f"{base_dir}/images/{split}", exist_ok=True)
        os.makedirs(f"{base_dir}/labels/{split}", exist_ok=True)
        
    # Write data.yaml configuration
    data_yaml = {
        "path": os.path.abspath(base_dir).replace("\\", "/"),
        "train": "images/train",
        "val": "images/val",
        "nc": 5,
        "names": ["person", "helmet", "no_helmet", "vest", "no_vest"]
    }
    
    with open(f"{base_dir}/data.yaml", "w") as f:
        yaml.dump(data_yaml, f, default_flow_style=False)
        
    print("[SUCCESS] Labeled data folders and data.yaml configured.")
    
    # Generate 30 images
    total_images = 30
    for idx in range(total_images):
        split = "train" if idx < 24 else "val"
        
        # Base image
        img = Image.new("RGB", (640, 640), color=(45, 45, 48))
        draw = ImageDraw.Draw(img)
        
        # Overhead lighting variation
        lighting_val = random.randint(180, 240)
        light_color = (lighting_val, lighting_val, lighting_val - 15)
        
        # Perspective corridor geometry
        # Ceiling
        draw.polygon([(0, 0), (640, 0), (380, 180), (260, 180)], fill=(75, 75, 80))
        # Floor
        draw.polygon([(0, 640), (640, 640), (380, 480), (260, 480)], fill=(38, 38, 40))
        # Left wall
        draw.polygon([(0, 0), (260, 180), (260, 480), (0, 640)], fill=(55, 58, 62))
        # Right wall
        draw.polygon([(640, 0), (380, 180), (380, 480), (640, 640)], fill=(55, 58, 62))
        # Far background wall
        draw.rectangle([260, 180, 380, 480], fill=(28, 28, 30))
        
        #perspective grid lines
        draw.line([(0, 640), (260, 480)], fill=(18, 18, 20), width=3)
        draw.line([(640, 640), (380, 480)], fill=(18, 18, 20), width=3)
        draw.line([(0, 0), (260, 180)], fill=(95, 95, 100), width=2)
        draw.line([(640, 0), (380, 180)], fill=(95, 95, 100), width=2)
        
        # Ceiling fluorescent lamp tubes
        for ly in [30, 80, 130]:
            lx1 = int(280 + (ly / 180.0) * (0 - 280))
            lx2 = int(360 + (ly / 180.0) * (640 - 360))
            draw.line([(lx1, ly), (lx2, ly)], fill=light_color, width=6)
            
        labels = []
        
        # Layer 3 (Background: 2 workers, yellow helmet + orange vest)
        labels.extend(draw_worker(draw, cx_ref=290, cy_ref=240, scale=0.45, helmet=True, vest=True))
        labels.extend(draw_worker(draw, cx_ref=350, cy_ref=240, scale=0.45, helmet=True, vest=True))
        
        # Layer 2 (Middle: 2 workers, NO helmet + orange vest)
        labels.extend(draw_worker(draw, cx_ref=200, cy_ref=360, scale=0.70, helmet=False, vest=True))
        labels.extend(draw_worker(draw, cx_ref=440, cy_ref=360, scale=0.70, helmet=False, vest=True))
        
        # Layer 1 (Foreground: 2 workers, yellow helmet + orange vest)
        labels.extend(draw_worker(draw, cx_ref=120, cy_ref=500, scale=1.10, helmet=True, vest=True))
        labels.extend(draw_worker(draw, cx_ref=520, cy_ref=500, scale=1.10, helmet=True, vest=True))
        
        # Save image and annotations
        img_path = f"{base_dir}/images/{split}/battery5_{idx}.jpg"
        img.save(img_path)
        
        yolo_annots = to_yolo_format(labels)
        label_path = f"{base_dir}/labels/{split}/battery5_{idx}.txt"
        with open(label_path, "w") as lf:
            lf.write("\n".join(yolo_annots))
            
    print(f"[SUCCESS] Generated 30 labeled corridor images inside: {base_dir}")

if __name__ == "__main__":
    generate_dataset()
