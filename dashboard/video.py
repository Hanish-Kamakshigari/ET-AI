# -*- coding: utf-8 -*-
"""
SurakshaAI Dashboard CCTV Video Streaming and Inference Module
"""

import sys
import os
import types
try:
    import cv2
except ImportError:  # opencv-python-headless not installed in this environment
    cv2: types.ModuleType | None = None
import time
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, List, Any, Optional, Tuple
import streamlit as st
from src.risk_engine import CompoundRiskEngine
from src.alert_system import AlertSystem, AlertManager

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.ui_constants import ZONE_LABELS
from src.ui_components import Colors, render_nominal_card
from src.alert_system import evaluate_alert_conditions, dispatch_alerts, clear_alert_if_safe
from src.utils.video_downloader import get_video

_TRANSPARENT_IMAGE = Image.new("RGBA", (16, 9), (0, 0, 0, 0))

def render_compliance_warning_card(severity: str, hazard: str, description: str, zone_label: str, confidence: int, time_str: str, duration: int) -> str:
    color = "#ef4444" if severity in ("CRITICAL", "HIGH") else "#eab308"
    bg = "rgba(239, 68, 68, 0.04)" if severity in ("CRITICAL", "HIGH") else "rgba(234, 179, 8, 0.03)"
    border_class = "border: 2px solid #ef4444;" if severity in ("CRITICAL", "HIGH") else "border: 1px solid rgba(234, 179, 8, 0.4);"
    pulse_style = "animation: warningPulse 1.5s infinite alternate;" if severity in ("CRITICAL", "HIGH") else ""
    
    countdown = max(0, 180 - duration)
    countdown_str = f"⌛ {countdown // 60:02d}:{countdown % 60:02d}" if countdown > 0 else "⚠️ ESCALATED"

    html = f"""
    <div style="background: {bg};
                {border_class}
                padding: 10px 14px;
                margin: 6px 0;
                border-radius: 8px;
                font-family: 'Outfit', sans-serif;
                color: #fff;
                box-shadow: 0 0 10px {color}22;
                {pulse_style}">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="font-weight: 900; color: {color}; font-size: 11px; letter-spacing: 1px; text-transform: uppercase;">⚠️ {severity} COMPLIANCE ALERT</span>
        <span style="font-size: 10px; color: {color}; font-weight: 700; font-family: monospace;">{countdown_str}</span>
      </div>
      <div style="font-size: 12px; font-weight: 700; margin-bottom: 4px; color: #fff;">{hazard}</div>
      <div style="color: #94a3b8; font-size: 11px; line-height: 1.4; margin-bottom: 6px;">{description}</div>
      <div style="display: flex; gap: 12px; font-size: 9.5px; color: #64748b; border-top: 1px solid rgba(255,255,255,0.04); padding-top: 6px;">
        <span>📍 <b>Zone:</b> {zone_label}</span>
        <span>🎯 <b>Confidence:</b> {confidence}%</span>
        <span>⏱ <b>Time:</b> {time_str}</span>
      </div>
    </div>
    """
    return html

# ════════════════════════════════════════════════════════════════════════════════
# KEYFRAME SIMULATION DATA CONSTANTS
# ════════════════════════════════════════════════════════════════════════════════

WORKER_KEYFRAMES = {
    'Reactor_Area': [
        {   # Worker 1 — Welder, crouching over pipe, left-centre
            # Welding shield + leather coverall = full PPE compliance → green box
            'has_helmet': True,
            'helmet_label': 'Welding Shield ✓',
            'ppe': 'welding_shield+coverall+leather_gloves',
            'first_visible_frame': 0,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (0,   370, 170, 620, 680),
                (38,  345, 195, 600, 695),
                (80,  345, 200, 600, 700),
                (120, 350, 195, 605, 700),
                (160, 355, 200, 605, 695),
                (200, 355, 205, 605, 695),
                (239, 358, 205, 610, 700),
            ],
        },
        {   # Worker 2 — Supervisor/Inspector, standing right, clipboard
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_hiviz_vest+safety_glasses',
            'first_visible_frame': 38,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (38,  790, 155, 1015, 700),
                (80,  790, 155, 1010, 710),
                (120, 790, 160, 1010, 715),
                (160, 795, 155, 1010, 715),
                (200, 790, 155, 1010, 715),
                (239, 790, 160, 1015, 715),
            ],
        },
    ],
    'Battery_4': [
        {   # Worker 1 — kneeling technician, left side, fixing pipe valve
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_coverall+white_gloves+reflective_strips',
            'first_visible_frame': 0,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (0,   310, 260, 570, 590),
                (30,  315, 265, 575, 595),
                (60,  320, 270, 580, 600),
                (90,  318, 268, 578, 598),
                (120, 315, 265, 575, 595),
                (150, 312, 262, 572, 592),
                (180, 315, 265, 575, 595),
                (210, 320, 270, 580, 600),
                (239, 318, 268, 578, 598),
            ],
        },
        {   # Worker 2 — standing supervisor, right side, monitoring
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_coverall+white_gloves+reflective_strips',
            'first_visible_frame': 30,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (30,  750, 120, 975, 690),
                (60,  752, 122, 977, 692),
                (90,  755, 125, 980, 695),
                (120, 752, 122, 977, 692),
                (150, 750, 120, 975, 690),
                (180, 748, 118, 973, 688),
                (210, 750, 120, 975, 690),
                (239, 752, 122, 977, 692),
            ],
        },
    ],
    'Zone_A': [
        {   # Worker-1 — Pipe technician, kneeling at valve, wrench in hand
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_coverall+white_gloves+reflective_strips',
            'first_visible_frame': 0,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (0,   390, 295, 660, 590),
                (20,  385, 300, 655, 595),
                (40,  380, 305, 650, 600),
                (60,  375, 300, 645, 595),
                (80,  370, 295, 640, 590),
                (100, 375, 290, 645, 585),
                (120, 380, 285, 650, 580),
                (140, 375, 295, 645, 590),
                (160, 370, 300, 640, 595),
                (180, 378, 295, 648, 590),
                (200, 382, 290, 652, 585),
                (220, 385, 288, 655, 582),
                (239, 388, 290, 658, 585),
            ],
        },
        {   # Worker-2 — Supervisor, standing upright, right-centre platform
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_coverall+white_gloves+reflective_strips',
            'first_visible_frame': 0,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (0,   755, 75,  970, 580),
                (20,  758, 78,  968, 578),
                (40,  760, 80,  970, 580),
                (60,  758, 78,  968, 582),
                (80,  755, 75,  965, 580),
                (100, 752, 72,  962, 578),
                (120, 750, 70,  960, 575),
                (140, 748, 68,  958, 572),
                (160, 745, 65,  955, 568),
                (180, 750, 70,  960, 575),
                (200, 755, 75,  965, 580),
                (220, 758, 78,  968, 582),
                (239, 760, 80,  970, 583),
            ],
        },
    ],
    'Zone_B': [
        {  # Worker A - back-left, HAS helmet
            'has_helmet': True,
            'first_visible_frame': 30,
            'keyframes': [
                (30,  555, 30,  610, 90),
                (51,  515, 55,  600, 145),
                (111, 490, 58,  615, 225),
                (171, 480, 150, 635, 300),
                (231, 415, 245, 570, 490),
            ]
        },
        {  # Worker B - back-right, HAS helmet
            'has_helmet': True,
            'first_visible_frame': 30,
            'keyframes': [
                (30,  610, 30,  665, 90),
                (51,  630, 55,  720, 145),
                (111, 635, 58,  765, 225),
                (171, 680, 150, 845, 310),
                (231, 745, 225, 895, 470),
            ]
        },
        {  # Worker C - middle-left, NO helmet (PPE violation)
            'has_helmet': False,
            'first_visible_frame': 40,
            'keyframes': [
                (40,  545, 50,  605, 130),
                (111, 450, 175, 615, 415),
                (171, 370, 310, 635, 560),
                (231, 295, 455, 575, 720),
            ]
        },
        {  # Worker D - middle-right, NO helmet (PPE violation)
            'has_helmet': False,
            'first_visible_frame': 40,
            'keyframes': [
                (40,  610, 50,  670, 130),
                (111, 615, 165, 780, 415),
                (171, 650, 300, 860, 560),
                (231, 600, 470, 850, 720),
            ]
        },
        {  # Worker E - front-left, HAS helmet
            'has_helmet': True,
            'first_visible_frame': 1,
            'last_visible_frame': 190,
            'keyframes': [
                (1,   565, 30,  650, 185),
                (51,  535, 75,  625, 300),
                (111, 445, 260, 645, 605),
                (171, 400, 530, 620, 720),
            ]
        },
        {  # Worker F - front-right, HAS helmet
            'has_helmet': True,
            'first_visible_frame': 1,
            'last_visible_frame': 190,
            'keyframes': [
                (1,   660, 30,  740, 185),
                (51,  625, 75,  735, 300),
                (111, 655, 215, 855, 580),
                (171, 690, 430, 900, 720),
            ]
        },
    ],
    'Zone_C': [
        {  # Single worker - walks from standing to panel-check position
            'has_helmet': True,
            'first_visible_frame': 1,
            'last_visible_frame': 240,
            'hidden_ranges': [(95, 130)],
            'keyframes': [
                (1,   565, 195, 690, 615),
                (51,  535, 195, 695, 620),
                (76,  430, 195, 565, 615),
                (91,  370, 195, 500, 595),
                (171, 330, 195, 465, 590),
                (231, 340, 200, 475, 595),
            ],
        },
    ],
    'Storage_Area': [
        {   # Worker-1 — Lone early worker, far-left background, yellow helmet + green vest
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+green_hiviz_vest+blue_coverall+face_mask',
            'first_visible_frame': 50,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (50,  60,  270, 185, 580),
                (80,  55,  265, 200, 590),
                (120, 60,  270, 195, 585),
                (160, 55,  260, 185, 570),
                (200, 50,  255, 175, 555),
                (239, 45,  250, 165, 545),
            ],
        },
        {   # Worker-2 — Group lead, orange hi-vis vest + yellow helmet, enters right door
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_hiviz_vest+blue_coverall+face_mask+yellow_gloves',
            'first_visible_frame': 60,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (60,  840, 250, 995,  640),
                (80,  720, 255, 885,  650),
                (100, 580, 260, 750,  660),
                (120, 490, 265, 660,  665),
                (140, 470, 270, 645,  660),
                (160, 430, 265, 615,  655),
                (200, 380, 260, 570,  650),
                (239, 330, 255, 520,  640),
            ],
        },
        {   # Worker-3 — Green vest + yellow helmet, right side of group
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+green_hiviz_vest+blue_coverall+face_mask+yellow_gloves',
            'first_visible_frame': 60,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (60,  940, 255, 1070, 635),
                (80,  810, 258, 950,  645),
                (100, 665, 260, 820,  655),
                (120, 555, 262, 720,  660),
                (140, 520, 265, 695,  658),
                (160, 490, 260, 670,  650),
                (200, 440, 255, 630,  645),
                (239, 390, 250, 580,  638),
            ],
        },
        {   # Worker-4 — Orange vest + yellow helmet, centre-group
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_hiviz_vest+blue_coverall+face_mask',
            'first_visible_frame': 75,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (75,  760, 258, 910,  648),
                (100, 620, 262, 775,  655),
                (120, 530, 265, 695,  660),
                (140, 560, 268, 730,  658),
                (160, 510, 263, 685,  652),
                (200, 460, 258, 645,  645),
                (239, 410, 252, 600,  638),
            ],
        },
        {   # Worker-5 — Green vest + yellow helmet, left-centre of group
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+green_hiviz_vest+blue_coverall+face_mask+yellow_gloves',
            'first_visible_frame': 75,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (75,  670, 260, 820,  650),
                (100, 520, 263, 680,  655),
                (120, 430, 266, 600,  660),
                (140, 400, 268, 580,  658),
                (160, 365, 263, 545,  652),
                (200, 315, 258, 500,  645),
                (239, 265, 252, 450,  638),
            ],
        },
        {   # Worker-6 — Orange vest + WHITE helmet, right of group
            'has_helmet': True,
            'helmet_label': 'White Hard Hat ✓',
            'ppe': 'white_helmet+orange_hiviz_vest+grey_coverall+face_mask',
            'first_visible_frame': 80,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (80,  900, 258, 1040, 648),
                (100, 750, 262, 900,  655),
                (120, 640, 265, 800,  660),
                (140, 700, 268, 870,  658),
                (160, 720, 263, 890,  652),
                (200, 760, 258, 930,  645),
                (239, 800, 252, 965,  638),
            ],
        },
        {   # Worker-7 — PPE VIOLATION: grey coverall, WHITE helmet, NO hi-vis vest
            'has_helmet': True,
            'helmet_label': 'White Hard Hat ✓',
            'ppe_violation': True,
            'violation_type': 'MISSING_HIVIZ_VEST',
            'ppe': 'white_helmet+NO_hiviz_vest+grey_coverall+face_mask',
            'first_visible_frame': 100,
            'last_visible_frame': 180,
            'hidden_ranges': [],
            'keyframes': [
                (100, 820, 265, 960,  655),
                (120, 710, 268, 855,  660),
                (140, 750, 268, 895,  658),
                (160, 800, 263, 940,  652),
                (180, 840, 260, 975,  648),
            ],
        },
        {   # Worker-8 — Yellow helmet + green vest, rear of group
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+green_hiviz_vest+blue_coverall+face_mask',
            'first_visible_frame': 80,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (80,  590, 262, 730,  648),
                (100, 480, 265, 625,  655),
                (120, 390, 268, 540,  660),
                (140, 350, 270, 500,  658),
                (160, 310, 265, 460,  650),
                (200, 260, 260, 410,  643),
                (239, 210, 254, 360,  636),
            ],
        },
        {   # Worker-9 — Yellow helmet + orange vest, last to enter, right edge
            'has_helmet': True,
            'helmet_label': 'Yellow Hard Hat ✓',
            'ppe': 'yellow_helmet+orange_hiviz_vest+blue_coverall+face_mask+yellow_gloves',
            'first_visible_frame': 100,
            'last_visible_frame': 239,
            'hidden_ranges': [],
            'keyframes': [
                (100, 950,  263, 1085, 650),
                (120, 840,  266, 980,  658),
                (140, 870,  268, 1010, 656),
                (160, 900,  263, 1040, 650),
                (200, 870,  258, 1005, 643),
                (239, 920,  252, 1055, 636),
            ],
        },
    ],
}

GAS_LEAK_KEYFRAMES = [
    (0,    0,   0,   0,   0  ),
    (38,   0,   0,   0,   0  ),
    (40,   490, 60,  720, 200),
    (80,   490, 55,  740, 230),
    (120,  490, 50,  755, 250),
    (160,  480, 40,  760, 270),
    (200,  485, 45,  750, 255),
    (239,  480, 40,  750, 255),
]

SPARKS_KEYFRAMES = [
    (0,    0,   0,   0,   0  ),
    (38,   0,   0,   0,   0  ),
    (40,   490, 400, 720, 560),
    (80,   480, 390, 700, 545),
    (120,  490, 395, 710, 545),
    (160,  475, 390, 700, 540),
    (200,  480, 400, 710, 545),
    (239,  478, 395, 705, 545),
]

WARNING_LIGHT_KEYFRAMES = [
    (0,    0,   0,   0,   0  ),
    (74,   0,   0,   0,   0  ),
    (75,   265, 162, 335, 218),
    (120,  265, 162, 335, 218),
    (160,  265, 162, 335, 218),
    (200,  265, 162, 335, 218),
    (239,  265, 162, 335, 218),
]

STORAGE_HAZE_KEYFRAMES = [
    (0,   350, 0,   950, 280),
    (40,  330, 0,   970, 300),
    (80,  300, 0,   990, 330),
    (120, 280, 0,  1010, 360),
    (160, 290, 0,   995, 345),
    (200, 310, 0,   975, 320),
    (239, 320, 0,   960, 310),
]

GAS_DETECTOR_KEYFRAMES = [
    (0,   578, 448, 692, 642),
    (40,  580, 450, 690, 640),
    (80,  582, 452, 692, 642),
    (120, 580, 530, 688, 660),
    (140, 578, 520, 686, 655),
    (160, 580, 505, 690, 648),
    (200, 580, 480, 690, 642),
    (239, 578, 460, 690, 640),
]

ZONE_A_GAS_KEYFRAMES = [
    (0,   560, 390, 730, 530),
    (20,  545, 360, 760, 555),
    (40,  510, 320, 790, 580),
    (60,  470, 280, 830, 600),
    (80,  420, 240, 870, 620),
    (100, 380, 210, 900, 635),
    (120, 350, 190, 920, 645),
    (140, 300, 200, 880, 640),
    (160, 320, 220, 850, 630),
    (180, 370, 250, 800, 610),
    (200, 420, 290, 750, 585),
    (220, 480, 340, 700, 560),
    (239, 520, 370, 670, 540),
]

ZONE_A_WARNING_LIGHT_KEYFRAMES = [
    (0,   490, 28,  580, 105),
    (40,  490, 28,  580, 105),
    (80,  490, 28,  580, 105),
    (120, 490, 28,  580, 105),
    (160, 490, 28,  580, 105),
    (200, 490, 28,  580, 105),
    (239, 490, 28,  580, 105),
]


# ════════════════════════════════════════════════════════════════════════════════
# HELPER OVERLAY CALCULATIONS AND DRAWERS
# ════════════════════════════════════════════════════════════════════════════════

def _is_sentinel_box(box: Tuple[int, int, int, int]) -> bool:
    return box[0] == 0 and box[1] == 0 and box[2] == 0 and box[3] == 0


def interpolate_box(keyframes: List[Tuple[int, int, int, int, int]], current_frame: int) -> Optional[Tuple[float, float, float, float]]:
    if not keyframes:
        return None
        
    if current_frame <= keyframes[0][0]:
        val = keyframes[0][1:]
        return None if _is_sentinel_box(val) else val
        
    if current_frame >= keyframes[-1][0]:
        val = keyframes[-1][1:]
        return None if _is_sentinel_box(val) else val
        
    for i in range(len(keyframes) - 1):
        f1, x1, y1, x2, y2 = keyframes[i]
        f2, tx1, ty1, tx2, ty2 = keyframes[i+1]
        
        if f1 <= current_frame <= f2:
            span = f2 - f1
            if span == 0:
                val = (x1, y1, x2, y2)
                return None if _is_sentinel_box(val) else val
            t = (current_frame - f1) / span
            interp_x1 = x1 + (tx1 - x1) * t
            interp_y1 = y1 + (ty1 - y1) * t
            interp_x2 = x2 + (tx2 - x2) * t
            interp_y2 = y2 + (ty2 - y2) * t
            val = (interp_x1, interp_y1, interp_x2, interp_y2)
            return None if _is_sentinel_box(val) else val
            
    return None


def draw_labeled_worker(
    draw: ImageDraw.ImageDraw,
    font: Optional[ImageFont.ImageFont],
    px1: float,
    py1: float,
    px2: float,
    py2: float,
    hx1: float,
    hy1: float,
    hx2: float,
    hy2: float,
    vx1: float,
    vy1: float,
    vx2: float,
    vy2: float,
    person_label: str,
    helmet_label: str,
    vest_label: str,
    has_helmet: bool = True,
) -> None:
    draw.rectangle([px1, py1, px2, py2], outline="#22c55e", width=3)
    if has_helmet:
        draw.rectangle([hx1, hy1, hx2, hy2], outline="#00d4ff", width=2)
    draw.rectangle([vx1, vy1, vx2, vy2], outline="#00d4ff", width=2)
    
    p_box = draw.textbbox((0, 0), person_label, font=font)
    p_w = p_box[2] - p_box[0]
    p_h = p_box[3] - p_box[1]
    
    h_box = draw.textbbox((0, 0), helmet_label, font=font)
    h_w = h_box[2] - h_box[0]
    h_h = h_box[3] - h_box[1]
    
    v_box = draw.textbbox((0, 0), vest_label, font=font)
    v_w = v_box[2] - v_box[0]
    v_h = v_box[3] - v_box[1]
    
    max_h = max(p_h, h_h)
    
    p_bg = [px1 - 2, py1 - max_h - 6, px1 + p_w + 4, py1]
    draw.rectangle(p_bg, fill="#0d1220")
    draw.text((px1, py1 - max_h - 4), person_label, fill="#22c55e", font=font)
    
    h_bg = [px1 + p_w + 10, py1 - max_h - 6, px1 + p_w + 10 + h_w + 6, py1]
    draw.rectangle(h_bg, fill="#0d1220")
    h_color = "#00d4ff" if has_helmet else "#ef4444"
    draw.text((px1 + p_w + 12, py1 - max_h - 4), helmet_label, fill=h_color, font=font)
    
    v_bg = [px1 - 2, py2 + 2, px1 + v_w + 4, py2 + v_h + 8]
    draw.rectangle(v_bg, fill="#0d1220")
    draw.text((px1, py2 + 4), vest_label, fill="#00d4ff", font=font)


def draw_pil_overlays(
    frame_np: np.ndarray,
    selected_zone: str,
    latest_telemetry: Dict[str, Any],
    current_frame: int = 0,
    detections: Optional[List[Any]] = None,
) -> Tuple[Image.Image, int, int, List[Any]]:
    if isinstance(frame_np, Image.Image):
        img = frame_np.copy()
    elif cv2 is not None and isinstance(frame_np, np.ndarray):
        try:
            rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
        except Exception:
            img = Image.fromarray(frame_np)
    elif isinstance(frame_np, np.ndarray):
        img = Image.fromarray(frame_np)
    else:
        img = Image.new("RGB", (1280, 720), (10, 14, 23))
    width, height = img.size
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    scale_x = width / 1280.0
    scale_y = height / 720.0
    
    visible_workers_count = 0
    violations_count = 0
    active_detections = []
    
    if detections is not None:
        person_has_violations = {}
        if selected_zone != 'Reactor_Area':
            for d in detections:
                if d.label in ['no_helmet', 'no_vest']:
                    person_has_violations[d.tracking_id] = True
        
        for d in detections:
            if d.label == 'person':
                visible_workers_count += 1
                px1, py1, pw, ph = d.bbox
                px2, py2 = px1 + pw, py1 + ph
                
                has_viol = person_has_violations.get(d.tracking_id, False)
                person_outline = "#f97316" if has_viol else "#22c55e"
                
                draw.rectangle([px1, py1, px2, py2], outline=person_outline, width=3)
                p_label = f"Worker-{d.tracking_id} ({int(d.confidence * 100)}%)"
                p_tbox = draw.textbbox((0, 0), p_label, font=font)
                p_w = p_tbox[2] - p_tbox[0]; p_h = p_tbox[3] - p_tbox[1]
                
                draw.rectangle([px1-2, py1-p_h-6, px1+p_w+4, py1], fill="#0d1220")
                draw.text((px1, py1-p_h-4), p_label, fill=person_outline, font=font)
                
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='person', confidence=d.confidence, bbox=[px1, py1, pw, ph]))
                
            elif d.label == 'helmet':
                hx1, hy1, hw, hh = d.bbox
                hx2, hy2 = hx1 + hw, hy1 + hh
                draw.rectangle([hx1, hy1, hx2, hy2], outline="#00d4ff", width=2)
                
                h_label = f"helmet {int(d.confidence * 100)}%"
                h_tbox = draw.textbbox((0, 0), h_label, font=font)
                h_w = h_tbox[2] - h_tbox[0]; h_h = h_tbox[3] - h_tbox[1]
                
                draw.rectangle([hx1-2, hy1-h_h-4, hx1+h_w+4, hy1], fill="#0d1220")
                draw.text((hx1, hy1-h_h-2), h_label, fill="#00d4ff", font=font)
                
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='helmet', confidence=d.confidence, bbox=[hx1, hy1, hw, hh]))
                
            elif d.label == 'no_helmet':
                hx1, hy1, hw, hh = d.bbox
                hx2, hy2 = hx1 + hw, hy1 + hh
                draw.rectangle([hx1, hy1, hx2, hy2], outline="#ef4444", width=2)
                violations_count += 1
                
                h_label = "⚠ NO HELMET"
                h_tbox = draw.textbbox((0, 0), h_label, font=font)
                h_w = h_tbox[2] - h_tbox[0]; h_h = h_tbox[3] - h_tbox[1]
                
                draw.rectangle([hx1-2, hy1-h_h-4, hx1+h_w+4, hy1], fill="#0d1220")
                draw.text((hx1, hy1-h_h-2), h_label, fill="#ef4444", font=font)
                
            elif d.label == 'vest':
                vx1, vy1, vw, vh = d.bbox
                vx2, vy2 = vx1 + vw, vy1 + vh
                draw.rectangle([vx1, vy1, vx2, vy2], outline="#00d4ff", width=2)
                
                v_label = f"vest {int(d.confidence * 100)}%"
                v_tbox = draw.textbbox((0, 0), v_label, font=font)
                v_w = v_tbox[2] - v_tbox[0]; v_h = v_tbox[3] - v_tbox[1]
                
                draw.rectangle([vx1-2, vy1-v_h-4, vx1+v_w+4, vx1], fill="#0d1220")
                draw.text((vx1, vy1-v_h-2), v_label, fill="#00d4ff", font=font)
                
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='vest', confidence=d.confidence, bbox=[vx1, vy1, vw, vh]))
                
            elif d.label == 'no_vest':
                vx1, vy1, vw, vh = d.bbox
                vx2, vy2 = vx1 + vw, vy1 + vh
                draw.rectangle([vx1, vy1, vx2, vy2], outline="#ef4444", width=2)
                violations_count += 1
                
                v_label = "⚠ NO VEST"
                v_tbox = draw.textbbox((0, 0), v_label, font=font)
                v_w = v_tbox[2] - v_tbox[0]; v_h = v_tbox[3] - v_tbox[1]
                
                draw.rectangle([vx1-2, vy1-v_h-4, vx1+v_w+4, vx1], fill="#0d1220")
                draw.text((vx1, vy1-v_h-2), v_label, fill="#ef4444", font=font)

    else:
        # Fallback Keyframe Drawing Logic (Standard Simulation)
        kf_key = 'Battery_4' if selected_zone == 'Zone_A' else selected_zone
        workers = WORKER_KEYFRAMES.get(kf_key, WORKER_KEYFRAMES['Reactor_Area'])
        
        # Calculate dynamic scenario offsets
        _now = datetime.now()
        _real_elapsed_min = (_now - st.session_state.scenario_start_time).total_seconds() / 60.0
        _scenario_min = _real_elapsed_min + st.session_state.scenario_offset_min
        
        c_za = round(min(max(4.5 + (_scenario_min * 1.2), 3.0), 65.0), 1)
        c_zs = round(min(8.0 + (_scenario_min * 0.55), 48.0), 1)
        
        # Overheat/critical triggers
        is_critical = (latest_telemetry.get("max_risk_level") == "CRITICAL" or st.session_state.simulate_active)
        overpressure_active = (selected_zone == 'Zone_C' and current_frame >= 95)
        
        # Count visible/violating workers
        for idx, w_def in enumerate(workers):
            f_start = w_def.get('first_visible_frame', 0)
            f_end = w_def.get('last_visible_frame', 239)
            
            if not (f_start <= current_frame <= f_end):
                continue
                
            is_hidden = False
            for hr in w_def.get('hidden_ranges', []):
                if hr[0] <= current_frame <= hr[1]:
                    is_hidden = True
                    break
            if is_hidden:
                continue
                
            box_coord = interpolate_box(w_def['keyframes'], current_frame)
            if not box_coord:
                continue
                
            bx1, by1, bx2, by2 = box_coord
            wx1 = bx1 * scale_x; wy1 = by1 * scale_y
            wx2 = bx2 * scale_x; wy2 = by2 * scale_y
            
            # PPE Compliance Flags
            has_helmet = w_def.get('has_helmet', True)
            has_vest = True
            
            # Simulated conditions
            if selected_zone == 'Zone_B':
                if idx in (2, 3) and not st.session_state.simulate_active:
                    continue  # Only visible when critical
                if idx in (4, 5) and st.session_state.simulate_active:
                    continue  # Flee/hidden when critical
            elif selected_zone == 'Zone_C' and overpressure_active:
                continue  # Evacuated/hidden during overpressure
            elif selected_zone == 'Zone_A':
                # Dynamic crew arrival
                if idx == 1 and _scenario_min < 15:
                    continue
                if idx == 2 and _scenario_min < 28:
                    continue
                    
            visible_workers_count += 1
            
            # Bounding box offsets
            px1, py1, px2, py2 = wx1, wy1, wx2, wy2
            pw, ph = px2 - px1, py2 - py1
            hx1, hy1, hx2, hy2 = px1 + (pw * 0.25), py1, px1 + (pw * 0.75), py1 + (ph * 0.2)
            vx1, vy1, vx2, vy2 = px1 + (pw * 0.15), py1 + (ph * 0.25), px1 + (pw * 0.85), py1 + (ph * 0.75)
            
            # Custom labels
            p_lbl = f"Worker-W{idx+1} 94%"
            h_lbl = w_def.get('helmet_label', 'Hard Hat ✓')
            v_lbl = 'Reflective Vest ✓'
            
            if selected_zone == 'Reactor_Area':
                if idx == 0:
                    h_lbl = 'Welding Shield ✓'
                    v_lbl = 'Leather Vest ✓'
                else:
                    h_lbl = 'Yellow Hard Hat ✓'
                    v_lbl = 'Reflective Vest ✓'
            elif selected_zone == 'Storage_Area':
                p_lbl = f"Worker-W{idx+1} 92%"
                if idx == 6:
                    has_vest = False
                    v_lbl = "⚠ NO HIVIZ VEST"
                    violations_count += 1
            elif selected_zone == 'Zone_B':
                p_lbl = f"Worker-W{idx+1} 90%"
                if idx in (2, 3):
                    has_helmet = False
                    h_lbl = "⚠ NO HELMET"
                    violations_count += 1
                    
            draw_labeled_worker(draw, font, px1, py1, px2, py2, hx1, hy1, hx2, hy2, vx1, vy1, vx2, vy2, p_lbl, h_lbl, v_lbl, has_helmet=has_helmet)
            
            from src.cctv.object_detector import Detection
            active_detections.append(Detection(label='person', confidence=0.94, bbox=[px1, py1, pw, ph]))
            if has_helmet:
                active_detections.append(Detection(label='helmet', confidence=0.92, bbox=[hx1, hy1, hx2-hx1, hy2-hy1]))
            else:
                active_detections.append(Detection(label='no_helmet', confidence=0.92, bbox=[hx1, hy1, hx2-hx1, hy2-hy1]))
            if has_vest:
                active_detections.append(Detection(label='vest', confidence=0.91, bbox=[vx1, vy1, vx2-vx1, vy2-vy1]))
            else:
                active_detections.append(Detection(label='no_vest', confidence=0.91, bbox=[vx1, vy1, vx2-vx1, vy2-vy1]))

        # Draw overlays (Reactor/Storage/Zone A)
        if selected_zone == 'Reactor_Area':
            g_box_coord = interpolate_box(GAS_LEAK_KEYFRAMES, current_frame)
            if g_box_coord:
                gx1, gy1, gx2, gy2 = g_box_coord
                draw.rectangle([gx1 * scale_x, gy1 * scale_y, gx2 * scale_x, gy2 * scale_y], outline="#f97316", width=2)
                draw.rectangle([gx1 * scale_x - 2, gy1 * scale_y - 20, gx1 * scale_x + 95, gy1 * scale_y], fill="#0d1220")
                draw.text((gx1 * scale_x, gy1 * scale_y - 18), "welding_fume 88%", fill="#f97316", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='welding_fume', confidence=0.88, bbox=[gx1*scale_x, gy1*scale_y, (gx2-gx1)*scale_x, (gy2-gy1)*scale_y]))
                
            s_box_coord = interpolate_box(SPARKS_KEYFRAMES, current_frame)
            if s_box_coord:
                sx1, sy1, sx2, sy2 = s_box_coord
                draw.rectangle([sx1 * scale_x, sy1 * scale_y, sx2 * scale_x, sy2 * scale_y], outline="#ff9f43", width=2)
                draw.rectangle([sx1 * scale_x - 2, sy1 * scale_y - 20, sx1 * scale_x + 75, sy1 * scale_y], fill="#0d1220")
                draw.text((sx1 * scale_x, sy1 * scale_y - 18), "sparks 95%", fill="#ff9f43", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='sparks', confidence=0.95, bbox=[sx1*scale_x, sy1*scale_y, (sx2-sx1)*scale_x, (sy2-sy1)*scale_y]))
                
            wl_box_coord = interpolate_box(WARNING_LIGHT_KEYFRAMES, current_frame)
            if wl_box_coord:
                wlx1, wly1, wlx2, wly2 = wl_box_coord
                draw.rectangle([wlx1 * scale_x, wly1 * scale_y, wlx2 * scale_x, wly2 * scale_y], outline="#ef4444", width=3)
                draw.rectangle([wlx1 * scale_x - 2, wly1 * scale_y - 20, wlx1 * scale_x + 105, wly1 * scale_y], fill="#0d1220")
                draw.text((wlx1 * scale_x, wly1 * scale_y - 18), "warning_light 99%", fill="#ef4444", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='warning_light', confidence=0.99, bbox=[wlx1*scale_x, wly1*scale_y, (wlx2-wlx1)*scale_x, (wly2-wly1)*scale_y]))
                
        elif selected_zone == 'Storage_Area':
            hz_box = interpolate_box(STORAGE_HAZE_KEYFRAMES, current_frame)
            if hz_box:
                hzx1, hzy1, hzx2, hzy2 = hz_box
                z_hx1 = hzx1 * scale_x; z_hy1 = hzy1 * scale_y
                z_hx2 = hzx2 * scale_x; z_hy2 = hzy2 * scale_y
                draw.rectangle([z_hx1, z_hy1, z_hx2, z_hy2], outline="#eab308", width=3)
                hz_label = f"chemical_haze {c_zs}%"
                hz_tbox = draw.textbbox((0, 0), hz_label, font=font)
                hz_w = hz_tbox[2] - hz_tbox[0]; hz_h = hz_tbox[3] - hz_tbox[1]
                draw.rectangle([z_hx1 - 2, z_hy1 - hz_h - 6, z_hx1 + hz_w + 4, z_hy1], fill="#0d1220")
                draw.text((z_hx1, z_hy1 - hz_h - 4), hz_label, fill="#eab308", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='chemical_haze', confidence=0.92, bbox=[z_hx1, z_hy1, z_hx2-z_hx1, z_hy2-z_hy1]))
                
            gd_box = interpolate_box(GAS_DETECTOR_KEYFRAMES, current_frame)
            if gd_box:
                gdx1, gdy1, gdx2, gdy2 = gd_box
                z_gx1 = gdx1 * scale_x; z_gy1 = gdy1 * scale_y
                z_gx2 = gdx2 * scale_x; z_gy2 = gdy2 * scale_y
                draw.rectangle([z_gx1, z_gy1, z_gx2, z_gy2], outline="#ef4444", width=3)
                gd_label = "🚨 GAS ALARM"
                gd_tbox = draw.textbbox((0, 0), gd_label, font=font)
                gd_w = gd_tbox[2] - gd_tbox[0]; gd_h = gd_tbox[3] - gd_tbox[1]
                draw.rectangle([z_gx1 - 2, z_gy2 + 2, z_gx1 + gd_w + 4, z_gy2 + gd_h + 8], fill="#0d1220")
                draw.text((z_gx1, z_gy2 + 4), gd_label, fill="#ef4444", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='gas_alarm', confidence=0.98, bbox=[z_gx1, z_gy1, z_gx2-z_gx1, z_gy2-z_gy1]))
                
        elif selected_zone == 'Zone_A':
            za_box = interpolate_box(ZONE_A_GAS_KEYFRAMES, current_frame)
            if za_box:
                zx1, zy1, zx2, zy2 = za_box
                z_x1 = zx1 * scale_x; z_y1 = zy1 * scale_y
                z_x2 = zx2 * scale_x; z_y2 = zy2 * scale_y
                draw.rectangle([z_x1, z_y1, z_x2, z_y2], outline="#ef4444", width=3)
                za_label = f"gas_leak {c_za}%"
                za_tbox = draw.textbbox((0, 0), za_label, font=font)
                za_w = za_tbox[2] - za_tbox[0]; za_h = za_tbox[3] - za_tbox[1]
                draw.rectangle([z_x1 - 2, z_y1 - za_h - 6, z_x1 + za_w + 4, z_y1], fill="#0d1220")
                draw.text((z_x1, z_y1 - za_h - 4), za_label, fill="#ef4444", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='gas_leak', confidence=0.95, bbox=[z_x1, z_y1, z_x2-z_x1, z_y2-z_y1]))
                
            zb_box = interpolate_box(ZONE_A_WARNING_LIGHT_KEYFRAMES, current_frame)
            if zb_box:
                bx1, by1, bx2, by2 = zb_box
                b_x1 = bx1 * scale_x; b_y1 = by1 * scale_y
                b_x2 = bx2 * scale_x; b_y2 = by2 * scale_y
                draw.rectangle([b_x1, b_y1, b_x2, b_y2], outline="#ef4444", width=3)
                bl_label = "⚠ EMERGENCY BEACON"
                bl_tbox = draw.textbbox((0, 0), bl_label, font=font)
                bl_w = bl_tbox[2] - bl_tbox[0]; bl_h = bl_tbox[3] - bl_tbox[1]
                draw.rectangle([b_x1 - 2, b_y2 + 2, b_x1 + bl_w + 4, b_y2 + bl_h + 8], fill="#0d1220")
                draw.text((b_x1, b_y2 + 4), bl_label, fill="#ef4444", font=font)
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='warning_light', confidence=0.99, bbox=[b_x1, b_y1, b_x2-b_x1, b_y2-b_y1]))

    return img, visible_workers_count, violations_count, active_detections


class FrameTracker:
    def __init__(self) -> None:
        self.indices: Dict[str, int] = {}

    def get_index(self, zone: str, total_frames: int) -> int:
        idx = self.indices.get(zone, 0)
        if idx >= total_frames or idx < 0:
            idx = 0
        return idx

    def increment(self, zone: str, step: int, total_frames: int) -> None:
        idx = self.indices.get(zone, 0)
        self.indices[zone] = (idx + step) % total_frames

    def reset(self, zone: str) -> None:
        self.indices[zone] = 0


@st.cache_resource
def get_frame_tracker() -> FrameTracker:
    return FrameTracker()


@st.cache_resource
def get_video_capture(video_path: str) -> Optional[Any]:
    """Cache a lightweight VideoCapture object instead of all frames.
    
    This avoids loading the entire video into RAM, which can exceed
    Streamlit Cloud memory limits and cause startup failures.
    """
    if cv2 is None:
        return None
    if not video_path or not os.path.exists(video_path):
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    return cap


def get_video_frame_count(video_path: str) -> int:
    """Return total frame count for a video file without loading frames."""
    if not video_path or not os.path.exists(video_path):
        return 0
    if cv2 is not None:
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.release()
                if total > 0:
                    return total
        except Exception:
            pass
    try:
        import imageio
        reader = imageio.get_reader(video_path)
        meta = reader.get_meta_data()
        total = meta.get('nframes', 240)
        return int(total) if total > 0 and total != float('inf') else 240
    except Exception:
        return 240


def read_mp4_frame(video_path: str, frame_idx: int) -> Tuple[Optional[np.ndarray], int]:
    """Reads a single frame from an MP4 video file using cv2 or imageio fallback."""
    if not video_path or not os.path.exists(video_path):
        return None, 0

    if cv2 is not None:
        try:
            cap = get_video_capture(video_path)
            if cap is not None and cap.isOpened():
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total > 0:
                    target_idx = frame_idx % total
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        return frame, total
        except Exception:
            pass

    try:
        import imageio
        reader = imageio.get_reader(video_path)
        meta = reader.get_meta_data()
        total = meta.get('nframes', 240)
        if total == float('inf') or total <= 0:
            total = 240
        target_idx = frame_idx % int(total)
        frame_rgb = reader.get_data(target_idx)
        return frame_rgb, int(total)
    except Exception as e:
        print(f"[video_reader] ImageIO fallback error for {video_path}: {e}")

    return None, 0


# ════════════════════════════════════════════════════════════════════════════════
# NON-BLOCKING CCTV FEED STREAMING FRAGMENT
# ════════════════════════════════════════════════════════════════════════════════

def _zone_video_path(zone: str) -> str | None:
    footage_files = {
        "Zone_A": "Battery_4.mp4",
        "Zone_B": "Battery_5.mp4",
        "Zone_C": "Battery_6.mp4",
        "Reactor_Area": "Reactor_Block.mp4",
        "Storage_Area": "Storage_Block.mp4",
    }

    filename = footage_files.get(zone)

    if filename is None:
        return None

    return get_video(filename)


@st.fragment
def stream_cctv_feed_fragment(
    placeholders: Dict[str, Any],
    data_dict: Dict[str, Any],
    selected_zone: str,
    engine: CompoundRiskEngine,
    am: AlertManager,
    alert_system: AlertSystem,
) -> None:
    """
    Renders live CCTV streaming panel inside a non-blocking st.fragment.
    """
    video_path = _zone_video_path(selected_zone)
    stream_cctv_feed_raw(
        placeholders=placeholders,
        selected_zone=selected_zone,
        video_path=video_path,
        latest=data_dict['latest'] if data_dict else {},
        alert_system=alert_system,
        am=am,
        data_dict=data_dict
    )


def stream_cctv_feed_headless(
    placeholders: Dict[str, Any],
    selected_zone: str,
    video_path: Optional[str],
    data_dict: Dict[str, Any],
    alert_system: AlertSystem,
    am: AlertManager,
) -> None:
    """
    Runs the CCTV streaming and inference loop headlessly (without rendering elements)
    to keep alerts, notifications, and databases synchronized.
    """
    stream_cctv_feed_raw(
        placeholders=placeholders,
        selected_zone=selected_zone,
        video_path=video_path,
        latest=data_dict['latest'] if data_dict else {},
        alert_system=alert_system,
        am=am,
        data_dict=data_dict
    )


def stream_cctv_feed_raw(
    placeholders: Dict[str, Any],
    selected_zone: str,
    video_path: Optional[str],
    latest: Dict[str, Any],
    alert_system: AlertSystem,
    am: AlertManager,
    data_dict: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Renders live CCTV streaming panel.
    Processes exactly one frame per rerun to avoid blocking Streamlit Cloud startup.
    """
    header_placeholder = placeholders.get('cctv_header')
    frame_placeholder_1 = placeholders.get('cctv_frame_1')
    frame_placeholder_2 = placeholders.get('cctv_frame_2')
    frame_placeholder = placeholders.get('cctv_frame')
    status_bar_placeholder = placeholders.get('cctv_status')
    warnings_placeholder = placeholders.get('warnings')
    selected_zone_name = ZONE_LABELS.get(selected_zone, selected_zone).upper()

    tracker = get_frame_tracker()

    # Reset if selected zone changed
    if st.session_state.get('prev_video_zone') != selected_zone:
        st.session_state.prev_video_zone = selected_zone
        tracker.reset(selected_zone)
        from src.cctv.inference import reset_ppe_buffer
        reset_ppe_buffer()

    frame = None
    frame_idx = 0
    total_frames = 240
    play_active = st.session_state.get('sim_play_active', True)

    if video_path and os.path.exists(video_path):
        frame_idx = tracker.get_index(selected_zone, 240)
        frame, total_frames = read_mp4_frame(video_path, frame_idx)
        if frame is not None and play_active:
            tracker.increment(selected_zone, 2, total_frames if total_frames > 0 else 240)

    if frame is None:
        # Secondary fallback to simulated CCTV frame if video file is missing
        from src.cctv.camera_manager import DemoVideoGenerator
        frame = DemoVideoGenerator.generate_sample_frame(
            zone=selected_zone,
            time=datetime.now(),
            zone_risks=st.session_state.get('zone_risks'),
            latest=latest
        )
        frame_idx = tracker.get_index(selected_zone, 240)
        if play_active:
            tracker.increment(selected_zone, 2, 240)

    # Choose a SINGLE frame slot to avoid double-buffer swap flicker.
    frame_slot = frame_placeholder or frame_placeholder_1
    if frame_placeholder_2:
        try:
            frame_placeholder_2.empty()
        except Exception:
            pass

    st.session_state.cctv_frame_index = frame_idx

    # Run YOLO or Simulated detection
    from src.cctv.inference import run_inference
    pil_img, w_count, viol_count, active_dets = run_inference(
        frame,
        selected_zone,
        latest,
        current_frame=frame_idx,
        draw_fallback_fn=draw_pil_overlays
    )

    # Cache latest detections/worker counts for the rest of the dashboard.
    st.session_state.current_detections = active_dets
    st.session_state.yolo_worker_counts[selected_zone] = w_count
    latest[f"{selected_zone}_worker_count"] = w_count

    # Feed live data to the Safety Intelligence Orchestrator
    try:
        from src.safety_intelligence import get_intelligence_orchestrator
        _orch = get_intelligence_orchestrator()
        _orch.ingest_live_frame(
            zone=selected_zone,
            detections=active_dets,
            telemetry=latest,
            alert_manager=am,
        )
    except Exception:
        pass

    # Render CCTV Frame + Status Bar in place
    if st.session_state.get('active_tab', 'dashboard') in ('dashboard', 'zones'):
        if frame_slot:
            from PIL import ImageOps
            padded_img = ImageOps.expand(pil_img, border=(0, 30), fill='black')
            frame_slot.image(padded_img, width='stretch')
            st.session_state['last_cctv_frame'] = pil_img

        fps_val = 25.0 if play_active else 0.0
        p_count = w_count
        h_count = viol_count

        safe_zones_count = 6
        active_alerts_dict = am.active_alerts if hasattr(am, 'active_alerts') else {}
        active_alert_zones = {a.zone for a in active_alerts_dict.values()}
        safe_zones_count = 6 - len(active_alert_zones)

        if status_bar_placeholder:
            audio_muted = st.session_state.get('audio_muted', False)
            audio_icon = "🔇" if audio_muted else "🔊"
            audio_lbl = "MUTED" if audio_muted else "SOUND ON"
            audio_color = "#ef4444" if audio_muted else "#22c55e"
            status_bar_placeholder.markdown(f"""
            <div style='background:#0a1628; border:1px solid #1e3a5f; border-top:none;
                        border-radius:0 0 8px 8px; padding:8px 16px;
                        display:flex; justify-content:space-around; align-items:center;
                        font-family:"Outfit",sans-serif; font-size:12px;'>
                <span style='color:#94a3b8;'>🎞 FPS: <b style="color:#e2e8f0">{fps_val:.1f}</b></span>
                <span style='color:#94a3b8;'>👷 Workers: <b style="color:#60a5fa">{p_count}</b></span>
                <span style='color:#94a3b8;'>⚠️ Hazards: <b style="color:#ef4444">{h_count}</b></span>
                <span style='color:#94a3b8;'>✅ Safe Zones: <b style="color:#22c55e">{safe_zones_count}</b></span>
                <a href='?toggle_audio=1' target='_self' style='text-decoration:none; display:flex; align-items:center; gap:4px;'>
                    <span style='font-size:12px;'>{audio_icon}</span>
                    <span style='color:{audio_color}; font-weight:800; font-size:10px; letter-spacing:0.5px;'>{audio_lbl}</span>
                </a>
            </div>
            """, unsafe_allow_html=True)
    else:
        if frame_slot:
            frame_slot.empty()
        if status_bar_placeholder:
            status_bar_placeholder.empty()

    # Evaluate alert conditions and drive the FSM + dispatch
    alert_conditions = evaluate_alert_conditions(
        detections=active_dets,
        violations=viol_count,
        zone=selected_zone,
        telemetry=latest
    )

    fsm = st.session_state.get('alert_fsm_state', 'NORMAL')
    stable = st.session_state.get('alert_stable_frames', 0)

    if alert_conditions["should_alert"]:
        severity = alert_conditions.get('severity', 'MEDIUM').upper()

        st.session_state['alert_stable_frames'] = stable + 1

        alert_key = f"alert_active_{selected_zone}"
        current_incident = f"{selected_zone}_{severity}"

        if fsm == 'NORMAL':
            if stable >= 3:
                st.session_state['alert_fsm_state'] = 'DETECTING'
                st.session_state[f"_safe_frames_{selected_zone}"] = 0

        elif fsm == 'DETECTING':
            if stable >= 6:
                st.session_state['alert_fsm_state'] = 'WARNING_ACTIVE'
                st.session_state[alert_key] = True
                st.session_state["_last_incident"] = current_incident
                st.session_state[f"_safe_frames_{selected_zone}"] = 0

        elif fsm == 'WARNING_ACTIVE':
            if not st.session_state.get(alert_key, False) or st.session_state.get("_last_incident") != current_incident:
                st.session_state[alert_key] = True
                st.session_state["_last_incident"] = current_incident
                dispatch_alerts(alert_conditions)
                st.session_state['alert_fsm_state'] = 'DISPATCHING'
            else:
                siren_st = st.session_state.get('siren_status', {})
                if siren_st.get('status') in ('ACTIVE', 'ACTIVE 🔊'):
                    st.session_state['alert_fsm_state'] = 'DELIVERED'

        elif fsm == 'DISPATCHING':
            siren_st = st.session_state.get('siren_status', {})
            if siren_st.get('status') in ('ACTIVE', 'ACTIVE 🔊', 'DELIVERED'):
                st.session_state['alert_fsm_state'] = 'DELIVERED'

        elif fsm == 'DELIVERED':
            st.session_state['alert_fsm_state'] = 'INCIDENT_ACTIVE'

        elif fsm in ('INCIDENT_ACTIVE', 'ACKNOWLEDGED'):
            if fsm == 'INCIDENT_ACTIVE':
                all_active = am.active_alerts
                any_acked = any(
                    getattr(getattr(a, 'status', None), 'name', str(getattr(a, 'status', ''))).upper() in ('ACKNOWLEDGED', 'ACK')
                    for a in all_active.values()
                )
                if any_acked:
                    st.session_state['alert_fsm_state'] = 'ACKNOWLEDGED'

        st.session_state[f"_safe_frames_{selected_zone}"] = 0

    else:
        safe_key = f"_safe_frames_{selected_zone}"
        st.session_state[safe_key] = st.session_state.get(safe_key, 0) + 1
        st.session_state['alert_stable_frames'] = 0

        if st.session_state[safe_key] >= 10:
            if st.session_state.get(f"alert_active_{selected_zone}", False):
                clear_alert_if_safe(selected_zone)
                st.session_state[f"alert_active_{selected_zone}"] = False
                st.session_state["_last_incident"] = None
                if fsm in ('INCIDENT_ACTIVE', 'ACKNOWLEDGED', 'DELIVERED', 'DISPATCHING'):
                    st.session_state['alert_fsm_state'] = 'RESOLVED'
            elif fsm == 'RESOLVED':
                st.session_state['alert_fsm_state'] = 'NORMAL'
            elif fsm in ('DETECTING', 'WARNING_ACTIVE'):
                st.session_state['alert_fsm_state'] = 'NORMAL'

    # Debounce guard
    active_alert_count = len(am.active_alerts)
    siren_state_val = st.session_state.get('siren_status', {}).get('status', 'STANDBY')
    current_fsm = st.session_state.get('alert_fsm_state', 'NORMAL')
    new_ui_hash = f"{active_alert_count}|{siren_state_val}|{current_fsm}|{selected_zone}"
    ui_state_changed = (new_ui_hash != st.session_state.get('alert_ui_hash', ''))
    if ui_state_changed:
        st.session_state['alert_ui_hash'] = new_ui_hash

    if data_dict:
        st.session_state.zone_risks = data_dict.get('zone_risks', {})

    if st.session_state.get('active_tab', 'dashboard') in ('dashboard', 'zones'):
        try:
            from dashboard.layout import render_top_alert_banner
            top_banner_p = placeholders.get('top_banner')
            if top_banner_p:
                render_top_alert_banner(top_banner_p, am, selected_zone=selected_zone)
        except Exception:
            pass

        if ui_state_changed:
            try:
                from dashboard.components import render_notifications_panel
                notifications_p = placeholders.get('notifications')
                if notifications_p:
                    render_notifications_panel(notifications_p, data_dict, selected_zone)
            except Exception:
                pass

            try:
                from dashboard.components import render_risk_analysis_row
                render_risk_analysis_row(placeholders, data_dict, selected_zone, active_dets)
            except Exception:
                pass

            try:
                from dashboard.components import render_decision_telemetry_row
                max_risk = "LOW"
                risk_color = "#22c55e"
                if len(am.active_alerts) > 0:
                    sev_rank = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
                    highest_active = max(
                        am.active_alerts.values(),
                        key=lambda x: sev_rank.get(getattr(x, 'risk_level', 'LOW').upper(), 0)
                    )
                    max_risk = getattr(highest_active, 'risk_level', 'LOW').upper()
                    from src.ui_components import Colors
                    risk_color = Colors.SEVERITY.get(max_risk, "#22c55e")

                data_dict['STATUS']['level'] = max_risk
                data_dict['STATUS']['color'] = risk_color
                data_dict['compound_risk_score'] = len(am.active_alerts) * 4.5 if max_risk in ("HIGH", "CRITICAL") else 1.2

                render_decision_telemetry_row(placeholders, data_dict, selected_zone, active_dets)
            except Exception:
                pass

            try:
                from dashboard.components import render_incident_summary_html
                summary_p = placeholders.get('incident_summary')
                if summary_p:
                    open_inc = len(am.active_alerts)
                    closed_inc = len(am.history)
                    today_inc = open_inc + closed_inc
                    summary_p.markdown(
                        render_incident_summary_html(open_inc, closed_inc, today_inc),
                        unsafe_allow_html=True
                    )
            except Exception:
                pass

    # 3. Render contextual warning cards below the feed
    alerts_list = []
    is_critical = (latest.get("max_risk_level") == "CRITICAL" or st.session_state.get('simulate_active', False))
    overpressure_active = (selected_zone == 'Zone_C' and frame_idx >= 95)

    if selected_zone != 'Reactor_Area':
        no_helmet_count = sum(1 for d in active_dets if d.label == 'no_helmet')
        no_vest_count = sum(1 for d in active_dets if d.label == 'no_vest')

        if no_helmet_count > 0 or no_vest_count > 0:
            msg = ""
            if no_helmet_count > 0 and no_vest_count > 0:
                msg = f"Multiple workers detected missing mandatory Hard Hats and High-Visibility Vests in {selected_zone_name}."
            elif no_helmet_count > 0:
                msg = f"Worker detected missing mandatory protective Hard Hat in {selected_zone_name}."
            else:
                msg = f"Worker detected missing mandatory High-Visibility safety Vest in {selected_zone_name}."

            alerts_list.append(render_compliance_warning_card(
                severity="MEDIUM",
                hazard="PPE VIOLATION",
                description=msg,
                zone_label=selected_zone_name,
                confidence=92,
                time_str=datetime.now().strftime('%H:%M:%S'),
                duration=frame_idx
            ))

    if overpressure_active:
        alerts_list.append(render_compliance_warning_card(
            severity="HIGH",
            hazard="OVERPRESSURE THREAT",
            description="OVERPRESSURE WARNING — Gauge in red zone. Relief valve activation recommended.",
            zone_label=selected_zone_name,
            confidence=96,
            time_str=datetime.now().strftime('%H:%M:%S'),
            duration=frame_idx
        ))

    if selected_zone == 'Reactor_Area':
        alerts_list.append(render_compliance_warning_card(
            severity="HIGH",
            hazard="BYSTANDER FLASH BURNS",
            description="Bystander Flash Burns: Second worker far too close to welding arc without eye/face protection.",
            zone_label=selected_zone_name,
            confidence=89,
            time_str=datetime.now().strftime('%H:%M:%S'),
            duration=frame_idx
        ))

        alerts_list.append(render_compliance_warning_card(
            severity="MEDIUM",
            hazard="INADEQUATE FUME EXTRACTION",
            description="Inadequate Fume Extraction: Yellowish haze indicates poor ventilation and build-up of toxic welding fumes.",
            zone_label=selected_zone_name,
            confidence=91,
            time_str=datetime.now().strftime('%H:%M:%S'),
            duration=frame_idx
        ))

    if selected_zone == 'Storage_Area':
        alerts_list.append(render_compliance_warning_card(
            severity="HIGH",
            hazard="AREA OVERCROWDING",
            description="More than 9 workers detected in the warehouse aisle under hazardous gas telemetry. Immediate shift rotation or aisle clearance required.",
            zone_label=selected_zone_name,
            confidence=94,
            time_str=datetime.now().strftime('%H:%M:%S'),
            duration=frame_idx
        ))

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
            alerts_list.append(render_compliance_warning_card(
                severity="CRITICAL",
                hazard="EQUIPMENT OVERHEATING",
                description="Tank/pipe junction temperature exceeds critical threshold in Zone C. Coolant flow activation required.",
                zone_label=selected_zone_name,
                confidence=98,
                time_str=datetime.now().strftime('%H:%M:%S'),
                duration=frame_idx
            ))
        else:
            alerts_list.append(render_compliance_warning_card(
                severity="CRITICAL",
                hazard="COMPATIBILITY VIOLATION",
                description="Uncontrolled volatile gas cloud detected in close proximity to active hot work permit. Evacuation required.",
                zone_label=selected_zone_name,
                confidence=97,
                time_str=datetime.now().strftime('%H:%M:%S'),
                duration=frame_idx
            ))

    if overpressure_active:
        from src.cctv.object_detector import Detection
        active_dets.append(Detection(label="overpressure", confidence=0.99, bbox=(0,0,0,0)))

    am.update(active_dets, selected_zone)

    if warnings_placeholder:
        if st.session_state.get('active_tab', 'dashboard') in ('dashboard', 'zones'):
            if alerts_list:
                warnings_placeholder.markdown("\n".join(alerts_list), unsafe_allow_html=True)
            else:
                warnings_placeholder.markdown(render_nominal_card(
                    title="Zone Secure",
                    message=f"All telemetry and compliance factors in {selected_zone_name} are nominal."
                ), unsafe_allow_html=True)
        else:
            warnings_placeholder.empty()

    # ═══════════════════════════════════════════════════════════════════════════════
    # AUTO-RERUN FOR SMOOTH PLAYBACK (driven by Autoplay Simulation toggle)
    # ═══════════════════════════════════════════════════════════════════════════════
    # When Autoplay = ON: schedule next fragment rerun at ~25 FPS * speed multiplier
    # When Autoplay = OFF: do not auto-rerun; frame index stays frozen
    # Uses JavaScript setTimeout -> hidden checkbox click for non-blocking, Streamlit-Cloud-safe playback
    # ═══════════════════════════════════════════════════════════════════════════════
    if play_active and st.session_state.get('active_tab', 'dashboard') in ('dashboard', 'zones'):
        # Base ~25 FPS = 40ms per frame; speed multipliers: 1x=40ms, 2x=20ms, 4x=10ms
        speed = st.session_state.get('sim_play_speed', '1x')
        speed_multiplier = {'1x': 1, '2x': 2, '4x': 4}.get(speed, 1)
        base_delay_ms = 40  # ~25 FPS base
        delay_ms = max(10, base_delay_ms // speed_multiplier)  # clamp minimum to 10ms (100 FPS cap)

        # Hidden checkbox widget - when its value changes, the fragment re-runs.
        # We give it a unique key per zone and hide it via CSS.
        rerun_key = f"_cctv_rerun_trigger_{selected_zone}"
        _ = st.checkbox(" ", key=rerun_key, value=False, label_visibility="collapsed")

        # Inject JavaScript that toggles the checkbox after the computed delay.
        # Toggling a widget value inside a fragment triggers a fragment re-run.
        st.markdown(f"""
        <script>
        (function() {{
            if (window._suraksha_cctv_timer) clearTimeout(window._suraksha_cctv_timer);
            window._suraksha_cctv_timer = setTimeout(function() {{
                // Find the hidden checkbox by its test ID (derived from key)
                const checkbox = document.querySelector('input[data-testid="stCheckbox"][aria-label="{rerun_key}"]');
                if (checkbox) {{
                    checkbox.click();  // Toggle checkbox -> widget change -> fragment rerun
                }} else {{
                    // Fallback: try to find by key attribute
                    const fallback = document.querySelector('[data-testid="stCheckbox"] input[id*="{rerun_key}"]');
                    if (fallback) fallback.click();
                }}
            }}, {delay_ms});
        }})();
        </script>
        <style>
        /* Hide the autoplay trigger checkbox visually */
        input[data-testid="stCheckbox"][aria-label="{rerun_key}"] {{
            position: absolute !important;
            opacity: 0 !important;
            pointer-events: none !important;
            width: 1px !important;
            height: 1px !important;
        }}
        input[data-testid="stCheckbox"][aria-label="{rerun_key}"] + div {{
            display: none !important;
        }}
        </style>
        """, unsafe_allow_html=True)

