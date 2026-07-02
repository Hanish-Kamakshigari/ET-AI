# -*- coding: utf-8 -*-
"""
SurakshaAI v3.0 — Industrial Safety Intelligence Dashboard
Hackathon Edition | Preventing Industrial Tragedies through AI
"""

import sys
import os

# ─── MONKEYPATCH WINDOWS PYTHON 3.14 ASYNCIO BUG ──────────────────────────────
if sys.platform == 'win32':
    try:
        import asyncio.proactor_events
        orig_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost
        
        def patched_connection_lost(self, exc=None):
            try:
                orig_connection_lost(self, exc)
            except (ConnectionResetError, ConnectionAbortedError):
                pass
            except OSError as e:
                if e.errno in (10054, 10038, 9, 10053): # Connection reset/abortion codes
                    pass
                else:
                    raise
                    
        asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = patched_connection_lost
    except Exception:
        pass

    # Fix: Python 3.12+ / Streamlit threading — suppress 'Event loop is closed'
    try:
        import asyncio
        _orig_check_closed = asyncio.BaseEventLoop._check_closed
        def _patched_check_closed(self):
            try:
                _orig_check_closed(self)
            except RuntimeError as e:
                if 'Event loop is closed' in str(e):
                    pass  # Suppress — harmless shutdown race condition
                else:
                    raise
        asyncio.BaseEventLoop._check_closed = _patched_check_closed
    except Exception:
        pass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, cast
from dataclasses import dataclass
import time
from PIL import Image, ImageDraw, ImageFont

from src.cctv.camera_manager import DemoVideoGenerator

@st.cache_resource
def init_frame_processor():
    from src.cctv.frame_processor import FrameProcessor
    return FrameProcessor(use_simulation=True)

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SurakshaAI | Industrial Safety",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🛡️"
)


# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class RiskAlert:
    timestamp: pd.Timestamp
    zone: str
    risk_score: float
    risk_level: str
    factors: List[str]
    compound_factors: List[str]
    message: str
    sensor_data: Dict[str, float]


# ─── COMPOUND RISK ENGINE ─────────────────────────────────────────────────────
class CompoundRiskEngine:
    def __init__(self):
        self.thresholds = {
            'gas_ppm':       {'normal':(0,15),   'elevated':(15,30),  'high':(30,50),   'critical':(50,100)},
            'temperature_c': {'normal':(60,88),  'elevated':(88,95),  'high':(95,105),  'critical':(105,120)},
            'pressure_bar':  {'normal':(3.5,5.8),'elevated':(5.8,6.5),'high':(6.5,7.2),'critical':(7.2,8.0)},
            'worker_count':  {'normal':(0,5),    'elevated':(5,8),    'high':(8,10),    'critical':(10,12)},
        }
        self.compound_rules = [
            {'id':'TRIPLE_THREAT',        'weight':10,
             'condition': lambda row,z: (row.get(f'{z}_maintenance_active',0)==1 and
                                         row.get(f'{z}_gas_ppm',0)>35 and
                                         row.get(f'{z}_temperature_c',0)>95 and
                                         row.get(f'{z}_worker_count',0)>5),
             'severity':'CRITICAL', 'label':'Triple-Threat Evacuation',
             'desc':'Maint + Gas>35ppm + Temp>95°C + Crew>5'},
            {'id':'MAINTENANCE_GAS_LEAK',  'weight':8,
             'condition': lambda row,z: row.get(f'{z}_maintenance_active',0)==1 and row.get(f'{z}_gas_ppm',0)>35,
             'severity':'CRITICAL', 'label':'Maintenance Gas Intersection',
             'desc':'Maint + Gas>35ppm'},
            {'id':'PERMIT_GAS_COMBINATION','weight':6,
             'condition': lambda row,z: row.get(f'{z}_permit_active',0)==1 and row.get(f'{z}_gas_ppm',0)>40,
             'severity':'HIGH', 'label':'Hot Work Permit Gas',
             'desc':'Permit + Gas>40ppm'},
            {'id':'OVERHEATING_WITH_GAS', 'weight':5,
             'condition': lambda row,z: row.get(f'{z}_temperature_c',0)>98 and row.get(f'{z}_gas_ppm',0)>25,
             'severity':'HIGH', 'label':'Overheating Gas Risk',
             'desc':'Temp>98°C + Gas>25ppm'},
            {'id':'WORKER_OVER_CROWDING', 'weight':3,
             'condition': lambda row,z: row.get(f'{z}_worker_count',0)>9 and row.get(f'{z}_gas_ppm',0)>25,
             'severity':'MEDIUM', 'label':'Crew Overcrowding',
             'desc':'Crew>9 + Gas>25ppm'},
            {'id':'SHIFT_CHANGE_RISK',    'weight':4,
             'condition': lambda row,z: row.get('shift_change',0)==1 and row.get(f'{z}_gas_ppm',0)>30,
             'severity':'MEDIUM', 'label':'Shift Change Telemetry',
             'desc':'Shift change + Gas>30ppm'},
        ]
        self.alert_history: List[RiskAlert] = []

    def get_sensor_risk(self, value, sensor_type):
        if sensor_type not in self.thresholds:
            return 0, 'NORMAL'
        t = self.thresholds[sensor_type]
        if value >= t['critical'][0]:   return 4, 'CRITICAL'
        elif value >= t['high'][0]:     return 2, 'HIGH'
        elif value >= t['elevated'][0]: return 1, 'ELEVATED'
        else:                           return 0, 'NORMAL'

    def analyze_zone(self, row, zone):
        zone_cols = {col: row[col] for col in row.index if zone in col}
        base_score = 0
        factors = []
        for sensor in self.thresholds:
            col = f'{zone}_{sensor}'
            if col in row:
                score, level = self.get_sensor_risk(row[col], sensor)
                base_score += score
                if score > 0:
                    factors.append(f'{sensor.upper()}_{level}')
        compound_factors = []
        for rule in self.compound_rules:
            if rule['condition'](row, zone):
                base_score += rule['weight']
                compound_factors.append(rule['id'])
                factors.append(rule['id'])
        final_score = min(base_score, 20)
        if final_score >= 12:   risk_level = 'CRITICAL'
        elif final_score >= 8:  risk_level = 'HIGH'
        elif final_score >= 5:  risk_level = 'MEDIUM'
        else:                   risk_level = 'LOW'
        return {
            'zone': zone, 'risk_score': final_score, 'risk_level': risk_level,
            'factors': factors, 'compound_factors': compound_factors,
            'sensor_data': zone_cols,
        }

    def analyze_timestamp(self, row):
        alerts = []
        zones = {col.replace('_gas_ppm', '') for col in row.index if '_gas_ppm' in col}
        for zone in zones:
            result = self.analyze_zone(row, zone)
            if result['risk_score'] >= 5:
                alert = RiskAlert(
                    timestamp=row['timestamp'], zone=zone,
                    risk_score=result['risk_score'], risk_level=result['risk_level'],
                    factors=result['factors'], compound_factors=result['compound_factors'],
                    message='', sensor_data=result['sensor_data']
                )
                alerts.append(alert)
                self.alert_history.append(alert)
        return alerts


# ─── ALERT SYSTEM ─────────────────────────────────────────────────────────────
class AlertSystem:
    def __init__(self):
        self.alerts = []
        self.esc = {
            'CRITICAL': {'channels':['SMS','PHONE','SIREN','EMAIL'],'required_ack':True},
            'HIGH':     {'channels':['SMS','EMAIL'],               'required_ack':True},
            'MEDIUM':   {'channels':['EMAIL','DASHBOARD'],         'required_ack':False},
            'LOW':      {'channels':['DASHBOARD'],                 'required_ack':False},
        }
        self.teams = {
            'Zone_A':'Alpha & Beta Teams', 'Zone_B':'Gamma & Delta Teams',
            'Zone_C':'Epsilon & Zeta Teams','Reactor_Area':'Theta & Iota Teams',
            'Storage_Area':'Kappa & Lambda Teams',
        }

    def trigger_alert(self, row, result):
        if result['risk_score'] < 5:
            return None
        alert = {
            'alert_id': f"ALT-{datetime.now().strftime('%H%M%S')}",
            'timestamp': str(row['timestamp']),
            'zone': result['zone'],
            'risk_level': result['risk_level'],
            'risk_score': result['risk_score'],
            'factors': result['factors'],
            'compound_factors': result['compound_factors'],
            'teams_notified': self.teams.get(result['zone'], 'Emergency Team'),
            'channels': self.esc[result['risk_level']]['channels'],
            'requires_ack': self.esc[result['risk_level']]['required_ack'],
            'acknowledged': False,
            'resolved': False,
        }
        self.alerts.append(alert)
        return alert

    def get_active_alerts(self):
        return [a for a in self.alerts if not a['resolved']]


# ─── STATUS FUNCTION ──────────────────────────────────────────────────────────
def get_system_status(risk_score: float) -> Dict:
    if risk_score >= 12:
        return {'text':'🔴 CRITICAL ALERT — PLANT EVACUATION REQUIRED',   'level':'CRITICAL','color':'#ef4444',
                'bg':'rgba(239,68,68,0.1)',  'border':'#ef4444','cls':'risk-critical','dot':'dot-critical'}
    elif risk_score >= 8:
        return {'text':'🟠 HIGH RISK — ACTIVE PLANT THREAT IN PROGRESS',  'level':'HIGH',    'color':'#f59e0b',
                'bg':'rgba(245,158,11,0.1)', 'border':'#f59e0b','cls':'risk-high',   'dot':'dot-high'}
    elif risk_score >= 5:
        return {'text':'🟡 ELEVATED RISK — SYSTEM MONITORING SENSORS',    'level':'MEDIUM',  'color':'#eab308',
                'bg':'rgba(234,179,8,0.1)',  'border':'#eab308','cls':'risk-medium', 'dot':'dot-medium'}
    else:
        return {'text':'🟢 ALL SYSTEMS NOMINAL - PLANT OPERATING SAFELY', 'level':'LOW',     'color':'#22c55e',
                'bg':'rgba(34,197,94,0.08)', 'border':'#22c55e','cls':'risk-safe',   'dot':'dot-safe'}


# ─── RENDER ALERT CARD ────────────────────────────────────────────────────────
def render_alert_card(alert, sim_start_time=None):
    SDATA = {
        'CRITICAL': ('#ef4444', 'rgba(239,68,68,0.07)', 'rgba(239,68,68,0.3)', '🔴'),
        'HIGH':     ('#f59e0b', 'rgba(245,158,11,0.07)', 'rgba(245,158,11,0.3)', '🟠'),
        'MEDIUM':   ('#eab308', 'rgba(234,179,8,0.07)',  'rgba(234,179,8,0.3)',  '🟡'),
        'LOW':      ('#22c55e', 'rgba(34,197,94,0.07)',  'rgba(34,197,94,0.3)',  '🟢'),
    }
    color, bg, border_rgba, icon = SDATA.get(alert.risk_level, ('#6b7d94','rgba(107,125,148,0.07)','rgba(107,125,148,0.3)','⚪'))

    is_ack   = False
    alert_id = None
    if alert.zone in ['Zone_A', 'Battery-4'] and alert.risk_level == 'CRITICAL':
        is_ack   = st.session_state.ack_critical
        alert_id = 'ALT-001'
    elif alert.zone in ['Storage_Area', 'Storage'] and alert.risk_level == 'MEDIUM':
        is_ack   = st.session_state.ack_medium
        alert_id = 'ALT-002'

    def gsv(key):
        if not alert.sensor_data: return 0.0
        if key in alert.sensor_data: return float(alert.sensor_data[key])
        for k, v in alert.sensor_data.items():
            if k.endswith(key): return float(v)
        return 0.0

    gas     = gsv('gas_ppm')
    temp    = gsv('temperature_c')
    workers = int(gsv('worker_count'))
    zone_label = ZONE_LABELS.get(alert.zone, alert.zone)

    # "X min ago" time
    now = datetime.now()
    if sim_start_time:
        delta_s = max(0, int((now - sim_start_time).total_seconds()))
        if delta_s < 60:
            time_str = f'{delta_s} sec ago'
        else:
            time_str = f'{delta_s // 60} min ago'
    else:
        time_str = alert.timestamp.strftime('%H:%M:%S')

    # Score pill color
    score_int = int(alert.risk_score)
    score_color = color

    # Message for the alert
    if alert.risk_level == 'CRITICAL':
        msg = 'Maintenance + Gas leak detected. Same as Visakhapatnam pattern.'
    elif alert.risk_level == 'HIGH':
        msg = 'Multiple risk factors active. Investigation required immediately.'
    elif alert.risk_level == 'MEDIUM':
        msg = 'Elevated temperature detected. Investigation recommended.'
    else:
        msg = alert.message or 'Sensor readings above baseline threshold.'

    # Acknowledge button
    if is_ack:
        btn = ('<span style="background:#22c55e;color:#fff;border-radius:5px;'
               'padding:5px 14px;font-size:11px;font-weight:700;'
               'display:inline-block;letter-spacing:0.5px;">✔ ACKNOWLEDGED</span>')
    elif alert_id:
        btn = ('<a href="?ack_alert=' + alert_id + '" target="_self" style="text-decoration:none;">'
               '<span style="background:' + color + ';color:#fff;border-radius:5px;'
               'padding:5px 14px;font-size:11px;font-weight:700;display:inline-block;'
               'cursor:pointer;letter-spacing:0.5px;">ACKNOWLEDGE</span></a>')
    else:
        btn = ('<span style="background:rgba(255,255,255,0.08);color:#6b7d94;'
               'border:1px solid rgba(255,255,255,0.1);border-radius:5px;'
               'padding:5px 14px;font-size:11px;display:inline-block;">Acknowledge</span>')

    html = (
        '<div style="background:' + bg + ';border-left:4px solid ' + color + ';'
        'border-top:1px solid ' + border_rgba + ';border-right:1px solid ' + border_rgba + ';'
        'border-bottom:1px solid ' + border_rgba + ';'
        'border-radius:10px;padding:14px 16px;margin-bottom:10px;'
        'font-family:\'Outfit\',sans-serif;">'

        # Row 1: icon + level - zone | score | time
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
        '<div style="font-size:13px;font-weight:700;">'
        + icon + ' <span style="color:' + color + ';text-transform:uppercase;letter-spacing:0.5px;">'
        + alert.risk_level + ' - ' + zone_label + '</span>'
        + ' <span style="color:#6b7d94;font-size:11px;margin-left:8px;">Score: '
        + str(score_int) + '/20</span>'
        + '</div>'
        '<div style="color:#6b7d94;font-size:11px;">' + time_str + '</div>'
        '</div>'

        # Row 2: message
        '<div style="font-size:12px;color:#a0b4c8;margin-bottom:8px;line-height:1.4;">' + msg + '</div>'

        # Row 3: sensor data | ack button
        '<div style="display:flex;justify-content:space-between;align-items:center;">'
        '<div style="font-size:11px;color:#6b7d94;">'
        'Gas: ' + f'{gas:.1f}' + 'ppm  |  '
        'Temp: ' + f'{temp:.1f}' + '°C  |  '
        'Workers: ' + str(workers)
        + '</div>'
        + btn
        + '</div>'

        '</div>'
    )
    return html


def render_safe_card() -> str:
    html = (
        '<div style="background:rgba(34,197,94,0.04);border-left:4px solid #22c55e;'
        'border-top:1px solid rgba(34,197,94,0.15);border-right:1px solid rgba(34,197,94,0.15);'
        'border-bottom:1px solid rgba(34,197,94,0.15);'
        'border-radius:10px;padding:14px 16px;margin-bottom:10px;'
        'font-family:\'Outfit\',sans-serif;">'
        
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
        '<div style="font-size:13px;font-weight:700;color:#22c55e;text-transform:uppercase;letter-spacing:0.5px;">'
        '🟢 NOMINAL - ALL ZONES SECURE'
        '</div>'
        '<div style="color:#6b7d94;font-size:11px;">SYSTEM OK</div>'
        '</div>'
        
        '<div style="font-size:12px;color:#a0b4c8;margin-bottom:8px;line-height:1.4;">'
        'The compound risk engine is scanning all active zones. No telemetry threshold breaches or hazardous intersections detected.'
        '</div>'
        
        '<div style="font-size:11px;color:#6b7d94;">'
        'Telemetry: OK  |  Safety Rules: 6/6 Compliant  |  Base Risk: 0/20'
        '</div>'
        
        '</div>'
    )
    return html


def draw_labeled_worker(draw, font, px1, py1, px2, py2, hx1, hy1, hx2, hy2, vx1, vy1, vx2, vy2, person_label, helmet_label, vest_label, has_helmet=True):
    # 1. Draw Bounding Boxes
    draw.rectangle([px1, py1, px2, py2], outline="#22c55e", width=3)
    if has_helmet:
        draw.rectangle([hx1, hy1, hx2, hy2], outline="#00d4ff", width=2)
    draw.rectangle([vx1, vy1, vx2, vy2], outline="#00d4ff", width=2)
    
    # 2. Measure text sizes
    p_box = draw.textbbox((0, 0), person_label, font=font)
    p_w = p_box[2] - p_box[0]
    p_h = p_box[3] - p_box[1]
    
    h_box = draw.textbbox((0, 0), helmet_label, font=font)
    h_w = h_box[2] - h_box[0]
    h_h = h_box[3] - h_box[1]
    
    v_box = draw.textbbox((0, 0), vest_label, font=font)
    v_w = v_box[2] - v_box[0]
    v_h = v_box[3] - v_box[1]
    
    # Max text height for alignment
    max_h = max(p_h, h_h)
    
    # 3. Draw Person Label (above top-left)
    p_bg = [px1 - 2, py1 - max_h - 6, px1 + p_w + 4, py1]
    draw.rectangle(p_bg, fill="#0d1220")
    draw.text((px1, py1 - max_h - 4), person_label, fill="#22c55e", font=font)
    
    # 4. Draw Helmet / Warning Label (offset to the right of person, same y-level)
    h_bg = [px1 + p_w + 10, py1 - max_h - 6, px1 + p_w + 10 + h_w + 6, py1]
    draw.rectangle(h_bg, fill="#0d1220")
    h_color = "#00d4ff" if has_helmet else "#ef4444"
    draw.text((px1 + p_w + 12, py1 - max_h - 4), helmet_label, fill=h_color, font=font)
    
    # 5. Draw Vest Label (below bottom-left)
    v_bg = [px1 - 2, py2 + 2, px1 + v_w + 4, py2 + v_h + 8]
    draw.rectangle(v_bg, fill="#0d1220")
    draw.text((px1, py2 + 4), vest_label, fill="#00d4ff", font=font)


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
            'hidden_ranges': [(95, 130)],  # gauge cutaway insert - no worker visible
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

# Welding fume/smoke plume rising from pipe flange joint
# (0,0,0,0) sentinel = not present; interpolate_box returns None for these
GAS_LEAK_KEYFRAMES = [
    (0,    0,   0,   0,   0  ),   # not present
    (38,   0,   0,   0,   0  ),   # not present (arc just starting)
    (40,   490, 60,  720, 200),   # fume first visible, light plume
    (80,   490, 55,  740, 230),   # growing
    (120,  490, 50,  755, 250),   # medium density
    (160,  480, 40,  760, 270),   # heaviest — warning light ON
    (200,  485, 45,  750, 255),   # slightly reducing
    (239,  480, 40,  750, 255),   # persists at end
]

# Welding sparks scattering from arc point at pipe flange
SPARKS_KEYFRAMES = [
    (0,    0,   0,   0,   0  ),
    (38,   0,   0,   0,   0  ),
    (40,   490, 400, 720, 560),   # sparks first frame
    (80,   480, 390, 700, 545),
    (120,  490, 395, 710, 545),
    (160,  475, 390, 700, 540),   # brightest arc
    (200,  480, 400, 710, 545),
    (239,  478, 395, 705, 545),
]

# Red panel indicator light — OFF (sentinel) before frame 75, ON from 75 onward
WARNING_LIGHT_KEYFRAMES = [
    (0,    0,   0,   0,   0  ),   # OFF
    (74,   0,   0,   0,   0  ),   # OFF
    (75,   265, 162, 335, 218),   # ON — red light illuminates
    (120,  265, 162, 335, 218),   # ON
    (160,  265, 162, 335, 218),   # ON — peak fume
    (200,  265, 162, 335, 218),   # ON
    (239,  265, 162, 335, 218),   # ON — stays active to end
]

# Detection metadata for summary grid and compound risk engine
REACTOR_DETECTIONS_META = {
    'worker_count':         2,
    'ppe_violations':       1,          # Worker-1 missing hard hat
    'violation_ids':        ['W1'],
    'has_helmet_workers':   ['W2'],
    'active_hazards':       ['welding_fume', 'sparks', 'warning_light'],
    'gas_leak_present':     True,
    'warning_light_on':     True,
    'hot_work_active':      True,
    'first_hazard_frame':   40,
    'peak_hazard_frame':    160,
    'compound_risk_flags':  ['PERMIT_GAS_COMBINATION', 'OVERHEATING_WITH_GAS'],
}

# ── Storage_Area: ambient chemical haze (separate from Reactor GAS_LEAK_KEYFRAMES) ──
STORAGE_HAZE_KEYFRAMES = [
    (0,   350, 0,   950, 280),    # background haze, full-width upper zone
    (40,  330, 0,   970, 300),
    (80,  300, 0,   990, 330),    # crew entering stirs haze lower
    (120, 280, 0,  1010, 360),    # peak density — crew clustered in it
    (160, 290, 0,   995, 345),
    (200, 310, 0,   975, 320),
    (239, 320, 0,   960, 310),    # persists at end
]

# Standalone red gas detector unit — stationary centre-aisle, flashing alarm throughout
GAS_DETECTOR_KEYFRAMES = [
    (0,   578, 448, 692, 642),
    (40,  580, 450, 690, 640),
    (80,  582, 452, 692, 642),    # workers arriving around it
    (120, 580, 530, 688, 660),    # partially occluded by crowd legs
    (140, 578, 520, 686, 655),
    (160, 580, 505, 690, 648),    # crew moving away, detector re-exposed
    (200, 580, 480, 690, 642),
    (239, 578, 460, 690, 640),
]

# Detection metadata for Storage_Area
STORAGE_DETECTIONS_META = {
    'worker_count':          15,
    'ppe_violations':        1,           # Worker-7 missing hi-vis vest
    'violation_ids':         ['W7'],
    'violation_types':       ['MISSING_HIVIZ_VEST'],
    'has_helmet_workers':    ['W1','W2','W3','W4','W5','W6','W7','W8','W9'],
    'active_hazards':        ['chemical_haze', 'gas_detector_alarm', 'overcrowding'],
    'gas_leak_present':      True,
    'gas_detector_alarming': True,
    'hot_work_active':       False,
    'first_worker_frame':    50,
    'peak_crowd_frame':      120,
    'compound_risk_flags':   ['WORKER_OVER_CROWDING', 'SHIFT_CHANGE_RISK'],
    'hazmat_drums_visible':  True,
    'flammable_diamond_visible': True,
}

# ── Zone_A (Battery-4): valve gas leak — yellow-green vapour expanding toward camera ──
ZONE_A_GAS_KEYFRAMES = [
    (0,   560, 390, 730, 530),   # faint wisp, tight to valve source
    (20,  545, 360, 760, 555),   # growing, drifting left
    (40,  510, 320, 790, 580),   # medium cloud, expanding toward camera
    (60,  470, 280, 830, 600),   # cloud rising and spreading laterally
    (80,  420, 240, 870, 620),   # large billow, encroaching on W1 lower body
    (100, 380, 210, 900, 635),   # peak lateral spread
    (120, 350, 190, 920, 645),   # PEAK — cloud fills left half of frame foreground
    (140, 300, 200, 880, 640),   # cloud extends past left edge
    (160, 320, 220, 850, 630),   # slight dispersal begins
    (180, 370, 250, 800, 610),   # dispersing — shrinking from edges inward
    (200, 420, 290, 750, 585),   # continuing dispersal
    (220, 480, 340, 700, 560),   # nearly back to mid-size
    (239, 520, 370, 670, 540),   # residual cloud persists, never fully clears
]

# Zone_A: red emergency beacon — ON from frame 0 through 239, never turns off
ZONE_A_WARNING_LIGHT_KEYFRAMES = [
    (0,   490, 28,  580, 105),   # ON — red glow, illuminating back wall
    (40,  490, 28,  580, 105),
    (80,  490, 28,  580, 105),
    (120, 490, 28,  580, 105),
    (160, 490, 28,  580, 105),
    (200, 490, 28,  580, 105),
    (239, 490, 28,  580, 105),   # ON — never extinguished in this clip
]

# Detection metadata for Zone_A (Battery-4)
BATTERY4_DETECTIONS_META = {
    'worker_count':          2,
    'ppe_violations':        0,
    'violation_ids':         [],
    'has_helmet_workers':    ['W1', 'W2'],
    'active_hazards':        ['gas_leak_active', 'emergency_beacon_on', 'maintenance_on_live_pipe'],
    'gas_leak_present':      True,
    'gas_leak_source':       'pipe_valve_joint_floor_level',
    'gas_colour':            'yellow_green',
    'emergency_beacon_on':   True,
    'maintenance_active':    True,
    'permit_active':         True,
    'first_hazard_frame':    0,
    'peak_hazard_frame':     120,
    'compound_risk_flags':   ['MAINTENANCE_GAS_LEAK', 'TRIPLE_THREAT'],
    'camera_angle':          'high_diagonal_45deg',
    'platform_type':         'elevated_metal_grating',
}


def _is_sentinel_box(box):
    """Return True if box is a (0,0,0,0) sentinel meaning 'not present'."""
    return box is not None and box[0] == 0 and box[1] == 0 and box[2] == 0 and box[3] == 0


def interpolate_box(keyframes, current_frame):
    """Interpolate between keyframes.  Returns None for sentinel (0,0,0,0) boxes."""
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


def draw_pil_overlays(frame_np, selected_zone: str, latest_telemetry: Dict, current_frame: int = 0, detections: List = None):
    # Convert BGR to RGB
    rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    width, height = img.size
    draw = ImageDraw.Draw(img)
    
    # Load font if possible, else use default
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    # Scale from 1280x720 reference space to actual frame size
    scale_x = width / 1280.0
    scale_y = height / 720.0
    
    visible_workers_count = 0
    violations_count = 0
    active_detections = []
    import random
    
    if detections is not None:
        # Pre-scan detections to find violations per tracking_id
        # Reactor_Area: all workers are compliant (welding shield + coverall = full PPE)
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
                
                draw.rectangle([vx1-2, vy2+2, vx1+v_w+4, vy2+v_h+8], fill="#0d1220")
                draw.text((vx1, vy2+4), v_label, fill="#00d4ff", font=font)
                
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label='vest', confidence=d.confidence, bbox=[vx1, vy1, vw, vh]))
                
            elif d.label == 'no_vest':
                vx1, vy1, vw, vh = d.bbox
                vx2, vy2 = vx1 + vw, vy1 + vh
                draw.rectangle([vx1, vy1, vx2, vy2], outline="#f97316", width=2)
                violations_count += 1
                
                v_label = "⚠ NO HI-VIS VEST"
                v_tbox = draw.textbbox((0, 0), v_label, font=font)
                v_w = v_tbox[2] - v_tbox[0]; v_h = v_tbox[3] - v_tbox[1]
                
                draw.rectangle([vx1-2, vy2+2, vx1+v_w+4, vy2+v_h+8], fill="#0d1220")
                draw.text((vx1, vy2+4), v_label, fill="#f97316", font=font)
                
            elif d.label in ['bicycle', 'car', 'motorcycle', 'bus', 'truck']:
                tx1, ty1, tw, th = d.bbox
                tx2, ty2 = tx1 + tw, ty1 + th
                draw.rectangle([tx1, ty1, tx2, ty2], outline="#00d4ff", width=2)
                t_label = f"{d.label} {int(d.confidence * 100)}%"
                t_tbox = draw.textbbox((0, 0), t_label, font=font)
                t_w = t_tbox[2] - t_tbox[0]; t_h = t_tbox[3] - t_tbox[1]
                draw.rectangle([tx1-2, ty1-t_h-4, tx1+t_w+4, ty1], fill="#0d1220")
                draw.text((tx1, ty1-t_h-2), t_label, fill="#00d4ff", font=font)
                
                from src.cctv.object_detector import Detection
                active_detections.append(Detection(label=d.label, confidence=d.confidence, bbox=[tx1, ty1, tw, th]))
                
    else:
        # Map selected_zone to keyframe key
        if selected_zone == 'Zone_A':
            kf_key = 'Zone_A'
        elif selected_zone == 'Zone_B':
            kf_key = 'Zone_B'
        elif selected_zone == 'Zone_C':
            kf_key = 'Zone_C'
        elif selected_zone == 'Storage_Area':
            kf_key = 'Storage_Area'
        elif selected_zone == 'Battery-4':
            kf_key = 'Battery_4'
        else:
            kf_key = 'Reactor_Area'
            
        workers = WORKER_KEYFRAMES.get(kf_key, WORKER_KEYFRAMES['Reactor_Area'])
    
        for idx, w_def in enumerate(workers):
            f_start = w_def.get('first_visible_frame', 1)
            f_end = w_def.get('last_visible_frame', 9999)
            hidden_ranges = cast(List[Tuple[int, int]], w_def.get('hidden_ranges', []))
            
            # Check if worker is currently in a hidden range (cutaway/insert shots)
            is_hidden = False
            for start, end in hidden_ranges:
                if start <= current_frame <= end:
                    is_hidden = True
                    break
                    
            if is_hidden:
                continue
                
            if f_start <= current_frame <= f_end:
                w_box = interpolate_box(w_def['keyframes'], current_frame)
                if w_box:
                    visible_workers_count += 1
                    has_helmet = w_def.get('has_helmet', True)
                    ppe_violation = w_def.get('ppe_violation', False)
                    # Reactor_Area per-worker PPE logic:
                    # idx==0 = welder: welding mask (helmet✓) + leather coverall (no hi-vis vest)
                    # idx==1 = supervisor: yellow hardhat + hi-vis vest = full PPE
                    is_reactor_welder = (kf_key == 'Reactor_Area' and idx == 0)
                    if kf_key == 'Reactor_Area':
                        has_helmet = True
                        ppe_violation = False
                    # violations only for non-Reactor workers
                    if not has_helmet and kf_key != 'Reactor_Area':
                        violations_count += 1
                    elif ppe_violation:
                        violations_count += 1
                    
                    # Scale to raw video coordinates
                    px1, py1, px2, py2 = w_box
                    px1, py1, px2, py2 = px1 * scale_x, py1 * scale_y, px2 * scale_x, py2 * scale_y
                    
                    # Derive helmet box and vest box
                    pw = px2 - px1
                    ph = py2 - py1
                    hx1, hy1, hx2, hy2 = px1 + pw * 0.35, py1 + 2, px1 + pw * 0.65, py1 + ph * 0.18
                    vest_factor = 0.62 if (kf_key == 'Reactor_Area' and idx == 1) else 0.65
                    vx1, vy1, vx2, vy2 = px1 + pw * 0.15, py1 + ph * 0.18, px1 + pw * 0.85, py1 + ph * vest_factor
                    
                    # Person box always green for Reactor_Area (both workers compliant)
                    person_outline = "#f97316" if ppe_violation else "#22c55e"
                    
                    # Labels
                    p_label = f"Worker-{idx+1} ({random.randint(78, 92)}%)"
                    if is_reactor_welder:
                        h_label = "Welding Mask"
                        v_label = "Leather Coverall"
                    else:
                        h_label = w_def.get('helmet_label', f"helmet {random.randint(85, 91)}%") if has_helmet else w_def.get('helmet_label', "⚠ NO HELMET")
                        v_label = f"vest {random.randint(82, 88)}%"
                    
                    # Draw person box
                    draw.rectangle([px1, py1, px2, py2], outline=person_outline, width=3)
                    
                    # Helmet/mask box (always cyan for Reactor_Area)
                    if has_helmet:
                        draw.rectangle([hx1, hy1, hx2, hy2], outline="#00d4ff", width=2)
                    
                    # Vest box: cyan for supervisor, grey for welder (leather coverall)
                    if is_reactor_welder:
                        draw.rectangle([vx1, vy1, vx2, vy2], outline="#94a3b8", width=2)
                    else:
                        draw.rectangle([vx1, vy1, vx2, vy2],
                                       outline=("#f97316" if ppe_violation else "#00d4ff"), width=2)
                    
                    # Text labels
                    p_tbox = draw.textbbox((0, 0), p_label, font=font)
                    p_w = p_tbox[2] - p_tbox[0]; p_h = p_tbox[3] - p_tbox[1]
                    h_tbox = draw.textbbox((0, 0), h_label, font=font)
                    h_w = h_tbox[2] - h_tbox[0]; h_h = h_tbox[3] - h_tbox[1]
                    v_tbox = draw.textbbox((0, 0), v_label, font=font)
                    v_w = v_tbox[2] - v_tbox[0]; v_h = v_tbox[3] - v_tbox[1]
                    max_h = max(p_h, h_h)
                    # Person label (above top-left)
                    draw.rectangle([px1-2, py1-max_h-6, px1+p_w+4, py1], fill="#0d1220")
                    draw.text((px1, py1-max_h-4), p_label, fill=person_outline, font=font)
                    # Helmet/mask label
                    draw.rectangle([px1+p_w+10, py1-max_h-6, px1+p_w+10+h_w+6, py1], fill="#0d1220")
                    h_color = "#00d4ff" if has_helmet else "#ef4444"
                    draw.text((px1+p_w+12, py1-max_h-4), h_label, fill=h_color, font=font)
                    # Vest / coverall label (below bottom-left)
                    draw.rectangle([px1-2, py2+2, px1+v_w+4, py2+v_h+8], fill="#0d1220")
                    v_color = "#94a3b8" if is_reactor_welder else ("#f97316" if ppe_violation else "#00d4ff")
                    draw.text((px1, py2+4), v_label, fill=v_color, font=font)
                    
                    # Save detection for summary grids
                    from src.cctv.object_detector import Detection
                    active_detections.append(Detection(label='person', confidence=0.92, bbox=[px1, py1, pw, ph]))
                    if has_helmet:
                        active_detections.append(Detection(label='helmet', confidence=0.88, bbox=[hx1, hy1, hx2-hx1, hy2-hy1]))
                    active_detections.append(Detection(label='vest', confidence=0.85, bbox=[vx1, vy1, vx2-vx1, vy2-vy1]))
                            
    # ── Welding fume / gas-leak plume (Reactor_Area only) ───────────────────────
    c_g = random.randint(92, 97)
    g_box_coord = interpolate_box(GAS_LEAK_KEYFRAMES, current_frame)
    if g_box_coord and selected_zone in ('Reactor_Area', 'Battery-4'):
        gx1, gy1, gx2, gy2 = g_box_coord
        g_x1, g_y1, g_x2, g_y2 = gx1 * scale_x, gy1 * scale_y, gx2 * scale_x, gy2 * scale_y
        draw.rectangle([g_x1, g_y1, g_x2, g_y2], outline="#ef4444", width=3)
        g_label = f"gas_leak {c_g}%" if selected_zone == 'Battery-4' else f"welding_fume {c_g}%"
        g_tbox = draw.textbbox((0, 0), g_label, font=font)
        g_w = g_tbox[2] - g_tbox[0]
        g_h = g_tbox[3] - g_tbox[1]
        draw.rectangle([g_x1 - 2, g_y1 - g_h - 6, g_x1 + g_w + 4, g_y1], fill="#0d1220")
        draw.text((g_x1, g_y1 - g_h - 4), g_label, fill="#ef4444", font=font)
        from src.cctv.object_detector import Detection
        active_detections.append(Detection(label='gas_leak', confidence=0.95, bbox=[g_x1, g_y1, g_x2-g_x1, g_y2-g_y1]))

    # ── Welding sparks (Reactor_Area only) ────────────────────────────────────────
    s_box_coord = interpolate_box(SPARKS_KEYFRAMES, current_frame)
    if s_box_coord and selected_zone == 'Reactor_Area':
        sx1, sy1, sx2, sy2 = s_box_coord
        s_x1, s_y1, s_x2, s_y2 = sx1 * scale_x, sy1 * scale_y, sx2 * scale_x, sy2 * scale_y
        draw.rectangle([s_x1, s_y1, s_x2, s_y2], outline="#f97316", width=2)
        s_label = f"sparks {random.randint(88, 95)}%"
        s_tbox = draw.textbbox((0, 0), s_label, font=font)
        s_w = s_tbox[2] - s_tbox[0]
        s_h = s_tbox[3] - s_tbox[1]
        draw.rectangle([s_x1 - 2, s_y1 - s_h - 6, s_x1 + s_w + 4, s_y1], fill="#0d1220")
        draw.text((s_x1, s_y1 - s_h - 4), s_label, fill="#f97316", font=font)
        from src.cctv.object_detector import Detection
        active_detections.append(Detection(label='sparks', confidence=0.91, bbox=[s_x1, s_y1, s_x2-s_x1, s_y2-s_y1]))

    # ── Warning light (Reactor_Area) — label drawn BELOW box ────────────────────
    wl_box_coord = interpolate_box(WARNING_LIGHT_KEYFRAMES, current_frame)
    if wl_box_coord and selected_zone == 'Reactor_Area':
        wx1, wy1, wx2, wy2 = wl_box_coord
        w_x1, w_y1, w_x2, w_y2 = wx1 * scale_x, wy1 * scale_y, wx2 * scale_x, wy2 * scale_y
        draw.rectangle([w_x1, w_y1, w_x2, w_y2], outline="#ef4444", width=3)
        wl_label = "⚠ WARNING LIGHT"
        wl_tbox = draw.textbbox((0, 0), wl_label, font=font)
        wl_w = wl_tbox[2] - wl_tbox[0]
        wl_h = wl_tbox[3] - wl_tbox[1]
        # Place label BELOW the box to avoid overlapping wall-panel UI elements
        draw.rectangle([w_x1 - 2, w_y2 + 2, w_x1 + wl_w + 4, w_y2 + wl_h + 8], fill="#0d1220")
        draw.text((w_x1, w_y2 + 4), wl_label, fill="#ef4444", font=font)
        from src.cctv.object_detector import Detection
        active_detections.append(Detection(label='warning_light', confidence=0.99, bbox=[w_x1, w_y1, w_x2-w_x1, w_y2-w_y1]))

    # ── Equipment overheating warning box (Zone_C, critical/simulation only) ────
    if selected_zone == 'Zone_C' and (latest_telemetry.get("max_risk_level") == "CRITICAL" or st.session_state.simulate_active):
        t_x1, t_y1, t_x2, t_y2 = 780 * scale_x, 280 * scale_y, 1000 * scale_x, 460 * scale_y
        draw.rectangle([t_x1, t_y1, t_x2, t_y2], outline="#ef4444", width=3)
        t_label = "⚠ OVERHEATING DETECTED"
        t_tbox = draw.textbbox((0, 0), t_label, font=font)
        t_w = t_tbox[2] - t_tbox[0]
        t_h = t_tbox[3] - t_tbox[1]
        draw.rectangle([t_x1 - 2, t_y1 - t_h - 6, t_x1 + t_w + 4, t_y1], fill="#0d1220")
        draw.text((t_x1, t_y1 - t_h - 4), t_label, fill="#ef4444", font=font)
        from src.cctv.object_detector import Detection
        active_detections.append(Detection(label='overheating', confidence=0.95, bbox=[t_x1, t_y1, t_x2-t_x1, t_y2-t_y1]))
        
    # ── Watermark logo blackout (all streams) ────────────────────────────────────
    draw.rectangle([1085 * scale_x, 50 * scale_y, 1210 * scale_x, 80 * scale_y], fill="#000000")

    # ── Storage_Area: chemical haze overlay (upper aisle) ────────────────────────
    if selected_zone == 'Storage_Area':
        hz_box = interpolate_box(STORAGE_HAZE_KEYFRAMES, current_frame)
        if hz_box:
            hx1, hy1, hx2, hy2 = hz_box
            h_x1, h_y1, h_x2, h_y2 = hx1*scale_x, hy1*scale_y, hx2*scale_x, hy2*scale_y
            draw.rectangle([h_x1, h_y1, h_x2, h_y2], outline="#a78bfa", width=2)
            hz_label = f"chemical_haze {random.randint(88, 95)}%"
            hz_tbox = draw.textbbox((0, 0), hz_label, font=font)
            hz_w = hz_tbox[2] - hz_tbox[0]; hz_h = hz_tbox[3] - hz_tbox[1]
            draw.rectangle([h_x1-2, h_y1-hz_h-6, h_x1+hz_w+4, h_y1], fill="#0d1220")
            draw.text((h_x1, h_y1-hz_h-4), hz_label, fill="#a78bfa", font=font)
            from src.cctv.object_detector import Detection
            active_detections.append(Detection(label='gas_leak', confidence=0.93,
                                               bbox=[h_x1, h_y1, h_x2-h_x1, h_y2-h_y1]))

        # ── Gas detector alarm unit — always present, pulsing label ───────────────
        gd_box = interpolate_box(GAS_DETECTOR_KEYFRAMES, current_frame)
        if gd_box:
            dx1, dy1, dx2, dy2 = gd_box
            d_x1, d_y1, d_x2, d_y2 = dx1*scale_x, dy1*scale_y, dx2*scale_x, dy2*scale_y
            # Reduce alpha appearance when partially occluded (frames 120-150)
            det_outline = "#ef4444" if not (120 <= current_frame <= 150) else "#991b1b"
            draw.rectangle([d_x1, d_y1, d_x2, d_y2], outline=det_outline, width=3)
            gd_label = "⚠ GAS DETECTOR — ALARM ACTIVE"
            gd_tbox = draw.textbbox((0, 0), gd_label, font=font)
            gd_w = gd_tbox[2] - gd_tbox[0]; gd_h = gd_tbox[3] - gd_tbox[1]
            # Label below the detector box
            draw.rectangle([d_x1-2, d_y2+2, d_x1+gd_w+4, d_y2+gd_h+8], fill="#0d1220")
            draw.text((d_x1, d_y2+4), gd_label, fill="#ef4444", font=font)
            from src.cctv.object_detector import Detection
            active_detections.append(Detection(label='gas_detector', confidence=0.99,
                                               bbox=[d_x1, d_y1, d_x2-d_x1, d_y2-d_y1]))
    # ── Zone_A (Battery-4): valve gas leak + emergency beacon ────────────────────
    if selected_zone == 'Zone_A':
        c_za = random.randint(92, 97)
        za_box = interpolate_box(ZONE_A_GAS_KEYFRAMES, current_frame)
        if za_box:
            zx1, zy1, zx2, zy2 = za_box
            z_x1 = zx1 * scale_x; z_y1 = zy1 * scale_y
            z_x2 = zx2 * scale_x; z_y2 = zy2 * scale_y
            draw.rectangle([z_x1, z_y1, z_x2, z_y2], outline="#ef4444", width=3)
            za_label = f"gas_leak {c_za}%"
            za_tbox = draw.textbbox((0, 0), za_label, font=font)
            za_w = za_tbox[2] - za_tbox[0]; za_h = za_tbox[3] - za_tbox[1]
            # Label at TOP-LEFT corner (cloud expands left, avoids W1 helmet region)
            draw.rectangle([z_x1 - 2, z_y1 - za_h - 6, z_x1 + za_w + 4, z_y1], fill="#0d1220")
            draw.text((z_x1, z_y1 - za_h - 4), za_label, fill="#ef4444", font=font)
            from src.cctv.object_detector import Detection
            active_detections.append(Detection(label='gas_leak', confidence=0.95,
                                               bbox=[z_x1, z_y1, z_x2-z_x1, z_y2-z_y1]))

        # Red emergency beacon — always ON for Zone_A, label below box (near top edge)
        zb_box = interpolate_box(ZONE_A_WARNING_LIGHT_KEYFRAMES, current_frame)
        if zb_box:
            bx1, by1, bx2, by2 = zb_box
            b_x1 = bx1 * scale_x; b_y1 = by1 * scale_y
            b_x2 = bx2 * scale_x; b_y2 = by2 * scale_y
            draw.rectangle([b_x1, b_y1, b_x2, b_y2], outline="#ef4444", width=3)
            bl_label = "⚠ EMERGENCY BEACON"
            bl_tbox = draw.textbbox((0, 0), bl_label, font=font)
            bl_w = bl_tbox[2] - bl_tbox[0]; bl_h = bl_tbox[3] - bl_tbox[1]
            # Place label BELOW box (beacon sits near top of frame, above-label would clip)
            draw.rectangle([b_x1 - 2, b_y2 + 2, b_x1 + bl_w + 4, b_y2 + bl_h + 8], fill="#0d1220")
            draw.text((b_x1, b_y2 + 4), bl_label, fill="#ef4444", font=font)
            from src.cctv.object_detector import Detection
            active_detections.append(Detection(label='warning_light', confidence=0.99,
                                               bbox=[b_x1, b_y1, b_x2-b_x1, b_y2-b_y1]))

    return img, visible_workers_count, violations_count, active_detections


# ─── SVG HEATMAP ─────────────────────────────────────────────────────────────
def build_heatmap_html(zone_risks: Dict, simulate_active: bool) -> str:
    COLORS = {
        'CRITICAL':{'fill':'#ef4444','stroke':'#dc2626','text':'#ffffff','glow':'rgba(239,68,68,0.7)'},
        'HIGH':    {'fill':'#f59e0b','stroke':'#d97706','text':'#ffffff','glow':'rgba(245,158,11,0.6)'},
        'MEDIUM':  {'fill':'#eab308','stroke':'#ca8a04','text':'#1a1100','glow':'rgba(234,179,8,0.5)'},
        'LOW':     {'fill':'#166534','stroke':'#22c55e','text':'#ffffff','glow':'rgba(34,197,94,0.4)'},
        'NOMINAL': {'fill':'#1e293b','stroke':'#334155','text':'#94a3b8','glow':'none'},
    }

    def sensor_val(zone_id, key):
        sd = zone_risks.get(zone_id, {}).get('sensor_data', {})
        for k, v in sd.items():
            if key in k:
                return float(v)
        return 0.0

    def make_zone(zone_id, label, x, y, w, h):
        z   = zone_risks.get(zone_id, {})
        lvl = z.get('risk_level', 'LOW')
        if lvl not in COLORS: lvl = 'NOMINAL'
        score = z.get('risk_score', 0)
        gas   = sensor_val(zone_id, 'gas_ppm')
        temp  = sensor_val(zone_id, 'temperature_c')
        crew  = int(sensor_val(zone_id, 'worker_count'))
        c   = COLORS[lvl]
        cx  = x + w / 2
        cy  = y + h / 2

        pulse = ''
        if lvl == 'CRITICAL': pulse = 'animation:critPulse 1.5s ease-in-out infinite;'
        elif lvl == 'HIGH':   pulse = 'animation:highPulse 2s ease-in-out infinite;'

        parts = label.split(' ', 1)
        if len(parts) == 1:
            label_svg = f'<text x="{cx:.1f}" y="{cy-16:.1f}" text-anchor="middle" fill="{c["text"]}" font-family="Outfit,sans-serif" font-size="14" font-weight="800">{label}</text>'
        else:
            label_svg  = f'<text x="{cx:.1f}" y="{cy-24:.1f}" text-anchor="middle" fill="{c["text"]}" font-family="Outfit,sans-serif" font-size="12" font-weight="800">{parts[0]}</text>'
            label_svg += f'<text x="{cx:.1f}" y="{cy-11:.1f}"  text-anchor="middle" fill="{c["text"]}" font-family="Outfit,sans-serif" font-size="12" font-weight="800">{parts[1]}</text>'

        tooltip = f"{label} | {lvl} | Score {score:.0f}/20 | Gas {gas:.1f}ppm | Temp {temp:.1f}°C | Crew {crew}"
        return f"""<g class="zone" id="z-{zone_id}">
  <title>{tooltip}</title>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" ry="12"
        fill="{c['fill']}" stroke="{c['stroke']}" stroke-width="2"
        style="{pulse}filter:drop-shadow(0 0 8px {c['glow']});"/>
  {label_svg}
  <text x="{cx:.1f}" y="{cy+6:.1f}"  text-anchor="middle" fill="{c['text']}" opacity="0.75" font-family="Outfit,sans-serif" font-size="10" font-weight="600" letter-spacing="0.5">{lvl}</text>
  <text x="{cx:.1f}" y="{cy+21:.1f}" text-anchor="middle" fill="{c['text']}" opacity="0.5" font-family="Outfit,sans-serif" font-size="8.5">{score:.0f}/20 · {gas:.0f}ppm</text>
</g>"""

    CW, CH = 880, 380
    PAD = 18
    BW, BH, BGAP = 200, 140, 28
    BAT_Y = 16
    # Only real zones — no fake Battery-1/2/3
    bat_zones = [
        ('Zone_A', 'Battery-4'),
        ('Zone_B', 'Battery-5'),
        ('Zone_C', 'Battery-6'),
    ]
    bat_svg = "\n".join(
        make_zone(zid, lbl, PAD + i*(BW+BGAP), BAT_Y, BW, BH)
        for i, (zid, lbl) in enumerate(bat_zones)
    )

    BOT_Y = BAT_Y + BH + 50
    BOT_H = 140
    # Bottom row: Reactor Block | Control Room | Storage Area
    BOT_W1, BOT_W2, BOT_W3 = 242, 196, 242
    bot_zones = [
        ('Reactor_Area', 'Reactor Block', PAD,                       BOT_W1, BOT_H),
        ('Control_Room', 'Control Room',  PAD + BOT_W1 + 22,         BOT_W2, BOT_H),
        ('Storage_Area', 'Storage Area',  PAD + BOT_W1 + 22 + BOT_W2 + 22, BOT_W3, BOT_H),
    ]
    bot_svg = "\n".join(make_zone(*args[:2], args[2], BOT_Y, args[3], args[4]) for args in bot_zones)

    LX, LY = CW - 118, 14
    legend  = f'<rect x="{LX-6}" y="{LY-6}" width="116" height="96" rx="8" fill="rgba(10,14,23,0.88)" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>'
    legend += f'<text x="{LX+52}" y="{LY+9}" text-anchor="middle" fill="#64748b" font-family="Outfit,sans-serif" font-size="8" font-weight="700" letter-spacing="1.5">RISK LEVEL</text>'
    for i, (nm, col) in enumerate([('CRITICAL','#ef4444'),('HIGH','#f59e0b'),('MEDIUM','#eab308'),('LOW','#166534')]):
        ry = LY + 18 + i*18
        legend += f'<rect x="{LX}" y="{ry}" width="11" height="11" rx="2" fill="{col}"/>'
        legend += f'<text x="{LX+16}" y="{ry+9}" fill="#e2e8f0" font-family="Outfit,sans-serif" font-size="10" font-weight="500">{nm}</text>'

    row_labels = f"""
<text x="7" y="{BAT_Y+BH//2}" text-anchor="middle" fill="#64748b" font-family="Outfit,sans-serif" font-size="8" font-weight="700"
  transform="rotate(-90 7 {BAT_Y+BH//2})">BATTERY BANKS</text>
<text x="7" y="{BOT_Y+BOT_H//2}" text-anchor="middle" fill="#64748b" font-family="Outfit,sans-serif" font-size="8" font-weight="700"
  transform="rotate(-90 7 {BOT_Y+BOT_H//2})">PROCESS AREAS</text>
<line x1="{PAD}" y1="{BAT_Y+BH+22}" x2="{CW-PAD}" y2="{BAT_Y+BH+22}"
  stroke="rgba(255,255,255,0.06)" stroke-width="1" stroke-dasharray="4,4"/>"""

    sim_badge = (
        f'<rect x="4" y="4" width="165" height="18" rx="4" fill="#ef4444" opacity="0.9"/>'
        f'<text x="86" y="16" text-anchor="middle" fill="#fff" font-family="Outfit,sans-serif" font-size="9" font-weight="700">🚨 SIMULATION ACTIVE</text>'
    ) if simulate_active else ''

    return f"""<!DOCTYPE html><html>
<head><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:transparent;font-family:'Outfit',sans-serif;overflow:hidden;}}
.wrap{{background:rgba(10,14,23,0.55);border:1px solid rgba(255,255,255,0.07);
  border-radius:14px;padding:12px;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);}}
svg{{width:100%;display:block;}}
.zone{{cursor:pointer;}}
.zone rect{{transition:filter .25s,opacity .2s;}}
.zone:hover rect{{filter:brightness(1.18) !important;opacity:0.88;}}
@keyframes critPulse{{0%,100%{{filter:drop-shadow(0 0 6px rgba(239,68,68,0.5));}}50%{{filter:drop-shadow(0 0 22px rgba(239,68,68,1));}}}}
@keyframes highPulse{{0%,100%{{filter:drop-shadow(0 0 4px rgba(245,158,11,0.4));}}50%{{filter:drop-shadow(0 0 18px rgba(245,158,11,0.85));}}}}
</style></head><body>
<div class="wrap">
<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <pattern id="g" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0L0 0 0 28" fill="none" stroke="rgba(255,255,255,0.022)" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="{CW}" height="{CH}" fill="url(#g)"/>
  {row_labels}
  {bat_svg}
  {bot_svg}
  {legend}
  {sim_badge}
</svg>
</div>
</body></html>"""


# ─── DATA LOADING ─────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    return pd.read_csv('data/plant_data.csv', parse_dates=['timestamp'])

@st.cache_resource
def init_engine():
    return CompoundRiskEngine()

@st.cache_resource
def init_alerts(_engine, _df):
    sys_obj = AlertSystem()
    for i in range(max(0, len(_df)-50), len(_df)):
        row = _df.iloc[i]
        for alert in _engine.analyze_timestamp(row):
            sys_obj.trigger_alert(row, {
                'zone': alert.zone, 'risk_level': alert.risk_level,
                'risk_score': alert.risk_score, 'factors': alert.factors,
                'compound_factors': alert.compound_factors, 'message': alert.message,
            })
    return sys_obj


# ─── CONSTANTS ────────────────────────────────────────────────────────────────
SENSOR_ZONES = ['Zone_A','Zone_B','Zone_C','Reactor_Area','Storage_Area']
STATIC_ZONES = ['Control_Room']
ALL_ZONES    = STATIC_ZONES + SENSOR_ZONES
ZONE_LABELS  = {
    'Zone_A':'Battery-4','Zone_B':'Battery-5','Zone_C':'Battery-6',
    'Reactor_Area':'Reactor Block','Control_Room':'Control Room','Storage_Area':'Storage Area',
}

# Ordered zone list for the Zone Status panel (matches screenshot)
ZONE_STATUS_ORDER = [
    ('Zone_A',       'Battery-4'),
    ('Zone_B',       'Battery-5'),
    ('Zone_C',       'Battery-6'),
    ('Reactor_Area', 'Reactor Block'),
    ('Storage_Area', 'Storage Area'),
    ('Control_Room', 'Control Room'),
]

# ─── INITIALIZATION ───────────────────────────────────────────────────────────
df           = load_data()
engine       = init_engine()
alert_system = init_alerts(engine, df)
frame_processor = init_frame_processor()

# ─── SESSION STATE ────────────────────────────────────────────────────────────
_defaults = {
    'simulate_active':False,'sim_stage':'normal',
    'alert_acknowledged':False,'ack_critical':False,'ack_medium':False,
    'prev_simulate_active':False,'sim_start_time':None,
    # Realistic scenario tracking
    'scenario_start_time': None,      # real wall-clock when session began
    'scenario_offset_min': 20,        # offset so CRITICAL fires within ~5 real min
    'compound_risk_active': False,    # auto-set when thresholds breach
    'compound_risk_first_seen': None, # when compound risk was first detected
    'ack_time': None,                 # when operator acknowledged CRITICAL
    'alert_log': [],                  # persistent timestamped alert history
    'recovering': False,              # gas declining post-ack
    'sim_play_active': False,         # Play/Pause autoplay simulation state
    'cctv_frame_index': 0,            # Track current CCTV video frame index
    'video_played_this_run': False,   # Check if video was rendered during this rerun
    'yolo_worker_counts': {},         # Track dynamic YOLO worker counts per zone
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Start scenario clock on first load
if st.session_state.scenario_start_time is None:
    st.session_state.scenario_start_time = datetime.now()

# URL-based acknowledgment
if 'ack_alert' in st.query_params:
    aid = st.query_params['ack_alert']
    if aid == 'ALT-001':
        st.session_state.ack_critical = True
        st.session_state.sim_stage    = 'acknowledged'
        st.session_state.ack_time     = datetime.now()  # start recovery clock
        st.toast('✔ ALT-001 Acknowledged. Sirens active. Recovery initiated.', icon='📣')
    elif aid == 'ALT-002':
        st.session_state.ack_medium = True
        st.toast('✔ ALT-002 Acknowledged.', icon='✔')
    del st.query_params['ack_alert']
    st.rerun()

# ─── SIMULATION INJECTION LOADING SCREEN ─────────────────────────────────────
if st.session_state.sim_stage == 'injecting':
    st.markdown("""
    <div style="background:#06090f;border:1px solid rgba(255,255,255,0.06);border-radius:16px;
    padding:40px;text-align:center;margin:40px 0 20px 0;">
      <h2 style="background:linear-gradient(90deg,#00d4ff,#7c3aed);-webkit-background-clip:text;
      -webkit-text-fill-color:transparent;margin-bottom:12px;">⚙️ Injecting Simulation Payload…</h2>
      <p style="color:#a0b4c8;margin-bottom:24px;font-size:14px;">
        Connecting to telemetry broker &amp; triggering compound risk scenario
      </p>
      <div style="background:#020408;border:1px solid rgba(239,68,68,0.25);border-radius:10px;
      padding:20px;font-family:'Courier New',monospace;font-size:12px;color:#10b981;
      text-align:left;max-width:620px;margin:0 auto;line-height:1.8;">
        <div style="color:#ef4444;font-weight:bold;border-bottom:1px solid rgba(239,68,68,0.2);
        padding-bottom:6px;margin-bottom:8px;">⚠️ SIMULATION VECTOR INJECTION</div>
        <div>[INFO]  Connecting to Plant Safety Mesh… OK</div>
        <div>[INFO]  Spawning virtual crew (8 workers) in Battery-4 (Zone A)… OK</div>
        <div>[WARN]  Gas levels rising: 4.5 ppm → 55.4 ppm… DETECTED</div>
        <div>[WARN]  Active HOT WORK permit during volatile state… FLAGGED</div>
        <div style="color:#ef4444;font-weight:bold;margin-top:8px;">
          [CRITICAL] TRIPLE-THREAT MATCH — Visakhapatnam Disaster Signature!</div>
        <div style="color:#ef4444;">[ALERT]   SMS + SIREN escalation protocols activated… LIVE</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    prog = st.progress(0)
    for pct in range(100):
        time.sleep(0.012)
        prog.progress(pct + 1)
    st.session_state.sim_stage       = 'active'
    st.session_state.simulate_active = True
    st.session_state.sim_start_time  = datetime.now()
    st.rerun()

# Toast on state change
if st.session_state.simulate_active != st.session_state.prev_simulate_active:
    msg = ('🚨 TRIPLE-THREAT COMPOUND RISK SIMULATED IN BATTERY-4!'
           if st.session_state.simulate_active
           else '✅ Telemetry reset. Normal operations restored.')
    st.toast(msg, icon='🚨' if st.session_state.simulate_active else '✅')
    st.session_state.prev_simulate_active = st.session_state.simulate_active

# ─── LIVE-TICKING SENSOR ENGINE ───────────────────────────────────────────────
# Compute how far into the scenario we are (real elapsed + manual offset)
import random as _rand
_now  = datetime.now()
_real_elapsed_min = (_now - st.session_state.scenario_start_time).total_seconds() / 60.0
_scenario_min = _real_elapsed_min + st.session_state.scenario_offset_min

# ── Battery-4 (Zone A) — active pipe maintenance, gas rising ──
# Gas starts at 4 ppm, rises ~1.2 ppm/min due to valve leak
_za_gas_raw  = 4.5 + (_scenario_min * 1.2) + _rand.gauss(0, 0.4)
_za_gas      = round(min(max(_za_gas_raw, 3.0), 65.0), 1)
_za_temp     = round(75.0 + (_scenario_min * 0.35) + _rand.gauss(0, 0.8), 1)
_za_temp     = min(_za_temp, 102.0)
_za_pressure = round(4.0 + _rand.gauss(0, 0.05), 2)
# Workers: 2 doing maintenance, crew grows as gas rises
_za_workers   = 2 if _scenario_min < 15 else 4 if _scenario_min < 28 else 8
_za_maint     = 1 if _scenario_min > 8  else 0
_za_permit    = 1 if _scenario_min > 10 else 0

# ── Battery-5 (Zone B) — normal operations ──
_zb_gas      = round(0.9 + _rand.gauss(0, 0.1), 1)
_zb_temp     = round(45.8 + _rand.gauss(0, 0.5), 1)
_zb_pressure = round(3.1 + _rand.gauss(0, 0.04), 2)

# ── Battery-6 (Zone C) — one inspector doing checks ──
_zc_gas      = round(5.2 + _rand.gauss(0, 0.2), 1)
_zc_temp     = round(73.4 + _rand.gauss(0, 0.4), 1)
_zc_pressure = round(3.8 + _rand.gauss(0, 0.04), 2)

# ── Reactor Block — stable, slight pressure variation ──
_zr_gas      = round(0.85 + _rand.gauss(0, 0.07), 2)
_zr_temp     = round(88.5 + _rand.gauss(0, 0.6), 1)
_zr_pressure = round(4.7 + _rand.gauss(0, 0.06), 2)

# ── Storage Area — smoke/gas building from poor ventilation ──
_zs_gas_raw  = 8.0 + (_scenario_min * 0.55) + _rand.gauss(0, 0.3)
_zs_gas      = round(min(_zs_gas_raw, 48.0), 1)
_zs_temp     = round(82.3 + (_scenario_min * 0.2) + _rand.gauss(0, 0.5), 1)
_zs_temp     = min(_zs_temp, 112.0)
_zs_pressure = round(2.3 + _rand.gauss(0, 0.03), 2)

# ── Post-acknowledgement recovery (gas declines after crew acks) ──
if st.session_state.ack_critical and st.session_state.ack_time is not None:
    _ack_elapsed_min = (_now - st.session_state.ack_time).total_seconds() / 60.0
    _za_gas  = max(3.0, round(_za_gas  - _ack_elapsed_min * 2.5, 1))
    _za_temp = max(70.0, round(_za_temp - _ack_elapsed_min * 1.2, 1))
    _za_workers = max(1, _za_workers - int(_ack_elapsed_min * 0.8))
    if _za_gas < 10 and not st.session_state.recovering:
        st.session_state.recovering = True
        st.toast("✅ Battery-4 gas levels normalising. Recovery in progress.", icon="✅")

# Assemble latest telemetry dict
latest = df.iloc[-1].copy()
latest['timestamp'] = _now
latest.update({
    'Zone_A_gas_ppm':_za_gas,'Zone_A_temperature_c':_za_temp,'Zone_A_pressure_bar':_za_pressure,
    'Zone_A_worker_count':_za_workers,'Zone_A_maintenance_active':_za_maint,'Zone_A_permit_active':_za_permit,
    'Zone_B_gas_ppm':_zb_gas,'Zone_B_temperature_c':_zb_temp,'Zone_B_pressure_bar':_zb_pressure,
    'Zone_B_worker_count':3,'Zone_B_maintenance_active':0,'Zone_B_permit_active':1,
    'Zone_C_gas_ppm':_zc_gas,'Zone_C_temperature_c':_zc_temp,'Zone_C_pressure_bar':_zc_pressure,
    'Zone_C_worker_count':1,'Zone_C_maintenance_active':0,'Zone_C_permit_active':1,
    'Reactor_Area_gas_ppm':_zr_gas,'Reactor_Area_temperature_c':_zr_temp,'Reactor_Area_pressure_bar':_zr_pressure,
    'Reactor_Area_worker_count':1,'Reactor_Area_maintenance_active':0,'Reactor_Area_permit_active':1,
    'Storage_Area_gas_ppm':_zs_gas,'Storage_Area_temperature_c':_zs_temp,'Storage_Area_pressure_bar':_zs_pressure,
    'Storage_Area_worker_count':15,'Storage_Area_maintenance_active':0,'Storage_Area_permit_active':0,
})

# Override telemetry with YOLO worker counts if active (persisted in session state)
if 'yolo_worker_counts' in st.session_state:
    for z_name, yolo_cnt in st.session_state.yolo_worker_counts.items():
        latest[f"{z_name}_worker_count"] = yolo_cnt

# ── Auto Compound Risk Detection (no button needed) ──
_auto_compound = (
    _za_gas    >= 40 and
    _za_workers >= 4  and
    _za_maint  == 1   and
    _za_permit == 1
)
if _auto_compound and not st.session_state.compound_risk_active:
    st.session_state.compound_risk_active = True
    st.session_state.simulate_active      = True
    st.session_state.sim_stage            = 'active'
    st.session_state.compound_risk_first_seen = _now
    st.toast("🚨 AI DETECTED COMPOUND RISK — Battery-4 auto-escalated to CRITICAL!", icon="🚨")
    # Add to persistent alert log
    st.session_state.alert_log.insert(0, {
        'id':'ALT-AUTO-001', 'time': _now.strftime('%H:%M:%S'),
        'zone':'Battery-4', 'level':'CRITICAL',
        'msg': f'AI AUTO-DETECTED: Gas {_za_gas}ppm + {_za_workers} workers + HOT WORK PERMIT. Visakhapatnam pattern.',
    })

# Keep simulate_active in sync with compound_risk_active
if st.session_state.compound_risk_active and not st.session_state.simulate_active:
    st.session_state.simulate_active = True
    st.session_state.sim_stage       = 'active'

# Set max_risk_level on latest so object_detector can read it
if st.session_state.compound_risk_active:
    latest['max_risk_level'] = 'CRITICAL'
    alert_system.alerts = [
        {
            'alert_id':'ALT-001','timestamp': _now.strftime('%H:%M:%S'),
            'zone':'Zone_A','zone_label':'Battery-4','risk_level':'CRITICAL','risk_score':15,
            'factors':['GAS_CRITICAL','MAINTENANCE_ACTIVE','TRIPLE_THREAT'],
            'compound_factors':['TRIPLE_THREAT'],
            'message':f'Maintenance crew ({_za_workers} workers) active during {_za_gas} ppm gas leak. Visakhapatnam triple-threat pattern auto-detected.',
            'teams_notified':'Alpha & Beta Teams','channels':['SMS','PHONE','SIREN','EMAIL'],
            'requires_ack':True,'acknowledged':st.session_state.ack_critical,'resolved':False,
        },
        {
            'alert_id':'ALT-002','timestamp': _now.strftime('%H:%M:%S'),
            'zone':'Storage_Area','zone_label':'Storage Area','risk_level':'MEDIUM','risk_score':5,
            'factors':['GAS_RISING'],'compound_factors':[],
            'message':f'Storage area gas at {_zs_gas} ppm. Smoke build-up detected. Evacuate if above 40 ppm.',
            'teams_notified':'Kappa & Lambda Teams','channels':['EMAIL','DASHBOARD'],
            'requires_ack':False,'acknowledged':st.session_state.ack_medium,'resolved':False,
        },
    ]
else:
    latest['max_risk_level'] = 'LOW'
    alert_system.alerts = []

# ─── ZONE RISK EVALUATION ─────────────────────────────────────────────────────
zone_risks = {}
for zone in ALL_ZONES:
    if zone in SENSOR_ZONES:
        r = engine.analyze_zone(latest, zone)
        zone_risks[zone] = {
            'risk_level': r['risk_level'], 'risk_score': r['risk_score'],
            'sensor_data': r['sensor_data'], 'compound_factors': r['compound_factors'],
            'label': ZONE_LABELS.get(zone, zone),
        }
    else:
        zone_risks[zone] = {
            'risk_level':'LOW','risk_score':0,
            'sensor_data':{f'{zone}_gas_ppm':1.2,f'{zone}_temperature_c':71.0,
                           f'{zone}_pressure_bar':4.5,f'{zone}_worker_count':0},
            'compound_factors':[],'label':ZONE_LABELS.get(zone, zone),
        }

# Assign specific gas values for static zones to match screenshot
STATIC_GAS = {'Control_Room':0.3}
for z, g in STATIC_GAS.items():
    if z in zone_risks:
        zone_risks[z]['sensor_data'][f'{z}_gas_ppm'] = g

max_score = max(z['risk_score'] for z in zone_risks.values())
STATUS    = get_system_status(max_score)

total_workers = sum(int(latest.get(f'{z}_worker_count', 0)) for z in SENSOR_ZONES)
permit_zones  = [ZONE_LABELS.get(z,z) for z in SENSOR_ZONES if latest.get(f'{z}_permit_active',0)==1]
permit_count  = len(permit_zones)
active_compounds = [(z, f) for z in SENSOR_ZONES
                    for f in engine.analyze_zone(latest, z)['compound_factors']]
compound_detected = bool(active_compounds)


# ════════════════════════════════════════════════════════════════════════════════
# CSS
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

:root {
  --bg:     #0a0e17;
  --bg2:    #131b2b;
  --glass:  rgba(255,255,255,0.035);
  --border: rgba(255,255,255,0.07);
  --shadow: rgba(0,0,0,0.45);
  --text:   #ffffff;
  --muted:  #a0b4c8;
  --faint:  #6b7d94;
  --cyan:   #00d4ff;
}

html, body, [class*="css"], .stApp {
  font-family: 'Outfit', sans-serif !important;
  color: var(--text) !important;
  background: #0a0e17 !important;
}
.stApp { background: linear-gradient(135deg, #0a0e17, #131b2b) !important; }
#MainMenu, footer { visibility: hidden; }

/* Hide Streamlit's default header */
header[data-testid="stHeader"] { display: none !important; }

.block-container { padding: 0 !important; max-width: 100% !important; }

/* ── Top navbar ── */
.top-navbar {
  background: #0d1220;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  padding: 0 24px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 999;
}

/* ── Content padding ── */
.main-content { padding: 16px 20px 24px 20px; }

/* ── Status banner ── */
.status-banner {
  border-radius: 10px; padding: 13px 24px; text-align: center;
  font-size: 15px; font-weight: 700; letter-spacing: 0.5px;
  text-transform: uppercase; margin: 0 0 14px 0;
  border: 1px solid;
}

/* ── Emergency banner ── */
.emergency-banner {
  background: linear-gradient(135deg,#7f1d1d,#ef4444);
  border: 2px solid #ef4444; border-radius: 14px; padding: 20px;
  margin: 6px 0 16px 0; animation: emergPulse 2s infinite;
}
@keyframes emergPulse {
  0%,100% { box-shadow: 0 0 15px rgba(239,68,68,0.35); }
  50%     { box-shadow: 0 0 40px rgba(239,68,68,0.75); }
}

/* ── Metric cards ── */
.metric-card {
  background: rgba(255,255,255,0.035);
  border: 1px solid rgba(255,255,255,0.08);
  border-top: 1px solid rgba(255,255,255,0.1);
  border-radius: 14px; padding: 18px 20px;
  box-shadow: 0 6px 24px rgba(0,0,0,0.45);
  transition: all 0.3s ease;
  height: 162px;
  position: relative; overflow: hidden;
}
.metric-card:hover { transform: translateY(-2px); }
.metric-card-critical {
  border-color: rgba(239,68,68,0.5) !important;
  animation: critBorder 1.5s infinite;
}
@keyframes critBorder {
  0%,100% { box-shadow: 0 0 10px rgba(239,68,68,0.15); }
  50%     { box-shadow: 0 0 28px rgba(239,68,68,0.55); }
}
.metric-label { color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 10px; }
.metric-value { font-size: 32px; font-weight: 800; letter-spacing: -1px; margin: 4px 0 2px 0; line-height: 1; }
.metric-sub   { color: var(--muted); font-size: 11px; font-weight: 500; }

/* ── Risk text ── */
.risk-critical { color: #ef4444 !important; font-weight: 800; animation: critText 1.5s infinite alternate; }
.risk-high     { color: #f59e0b !important; font-weight: 700; }
.risk-medium   { color: #eab308 !important; font-weight: 700; }
.risk-safe, .risk-low { color: #22c55e !important; font-weight: 700; }
@keyframes critText { 0%{text-shadow:0 0 8px rgba(239,68,68,0.4);} 100%{text-shadow:0 0 20px rgba(239,68,68,0.9);} }

/* ── Status dots ── */
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.dot-critical { background:#ef4444; box-shadow:0 0 8px #ef4444; animation:dotPulse 1.2s infinite alternate; }
.dot-high     { background:#f59e0b; box-shadow:0 0 6px #f59e0b; animation:dotPulse 1.8s infinite alternate; }
.dot-medium   { background:#eab308; box-shadow:0 0 5px #eab308; }
.dot-safe, .dot-low { background:#22c55e; box-shadow:0 0 5px #22c55e; }
@keyframes dotPulse { 0% { transform:scale(0.8); } 100% { transform:scale(1.35); } }

/* ── Scrollbar ── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:var(--bg); }
::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.1); border-radius:3px; }

/* ── Disable video controls and clicks ── */
video::-webkit-media-controls {
  display: none !important;
}
video {
  pointer-events: none !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: #0d1220 !important;
  border-right: 1px solid rgba(255,255,255,0.06) !important;
}
[data-testid="stSidebar"] .block-container { padding: 16px !important; }

/* ── Simulate button ── */
div.stButton > button[kind="primary"] {
  background: linear-gradient(135deg,#dc2626,#ef4444) !important;
  color: #fff !important; font-weight: 800 !important; font-size: 12px !important;
  border: none !important; border-radius: 8px !important;
  padding: 8px 16px !important;
  text-transform: uppercase !important; letter-spacing: 0.5px !important;
  animation: btnGlow 2s ease-in-out infinite;
  transition: all 0.25s ease !important;
}
div.stButton > button[kind="primary"]:hover {
  background: linear-gradient(135deg,#b91c1c,#dc2626) !important;
  box-shadow: 0 6px 30px rgba(239,68,68,0.7) !important;
  transform: translateY(-1px) !important;
}
@keyframes btnGlow {
  0%,100% { box-shadow: 0 4px 16px rgba(239,68,68,0.45); }
  50%     { box-shadow: 0 4px 28px rgba(239,68,68,0.85); }
}
div.stButton > button[kind="secondary"] {
  border-radius: 8px !important; font-weight: 600 !important;
  background: rgba(255,255,255,0.06) !important; color: #fff !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
}

/* ── Filter radio (pill style) ── */
div[data-testid="stRadio"] > div {
  display: flex; flex-direction: row; gap: 6px; flex-wrap: nowrap;
}
div[data-testid="stRadio"] label {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px; padding: 3px 14px;
  font-size: 12px; font-weight: 600; cursor: pointer;
  transition: all 0.2s;
}
div[data-testid="stRadio"] label:has(input:checked) {
  background: #00d4ff22; border-color: #00d4ff; color: #00d4ff;
}

/* ── Section headers ── */
.section-header {
  font-size: 13px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1px; color: #a0b4c8; margin-bottom: 14px;
  display: flex; align-items: center; gap: 8px;
}

/* ── Slide-up animation ── */
@keyframes slideUp { from{opacity:0;transform:translateY(8px);} to{opacity:1;transform:translateY(0);} }
.stApp { animation: slideUp 0.35s ease; }

/* ── Remove streamlit padding ── */
.stMarkdown { margin: 0 !important; }

section[data-testid="stSidebar"] > div { padding-top: 0 !important; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# TOP NAVBAR  (pure HTML, full-width)
# ════════════════════════════════════════════════════════════════════════════════
now_str = datetime.now().strftime('%H:%M:%S')
sim_on  = st.session_state.simulate_active or st.session_state.sim_stage in ['active','acknowledged']

# Navbar rendered as HTML (visual only — button is still a Streamlit widget below)
secure_color = '#ef4444' if sim_on else '#22c55e'
secure_label = 'CRITICAL' if sim_on else 'SECURE'
live_dot     = '#ef4444' if sim_on else '#00d4ff'

st.markdown(f"""
<div class="top-navbar">
  <div style="display:flex;align-items:center;gap:14px;">
    <span style="font-size:22px;">🛡️</span>
    <span style="font-size:20px;font-weight:800;background:linear-gradient(90deg,#00d4ff,#7c3aed);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-0.5px;">
      SURAKSHAAI</span>
    <span style="color:rgba(255,255,255,0.15);font-size:18px;">|</span>
    <span style="color:#6b7d94;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;">
      INDUSTRIAL SAFETY INTELLIGENCE</span>
  </div>
  <div style="display:flex;align-items:center;gap:18px;">
    <span style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:#00d4ff;">
      <span style="width:8px;height:8px;border-radius:50%;background:{live_dot};
        box-shadow:0 0 6px {live_dot};display:inline-block;"></span>LIVE</span>
    <span style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:{secure_color};">
      <span style="font-size:14px;">🛡️</span>{secure_label}</span>
    <span style="color:#6b7d94;font-size:12px;">🕐 {now_str}</span>
  </div>
</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="padding:12px 4px 8px 4px;">
      <div style="font-size:14px;font-weight:800;color:#fff;margin-bottom:2px;">🛡️ SurakshaAI Console</div>
    </div>""", unsafe_allow_html=True)

    # Uptime card
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
    border-radius:10px;padding:16px;text-align:center;margin-bottom:14px;">
      <div style="font-size:10px;color:#6b7d94;text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:4px;">
        SYSTEM UPTIME</div>
      <div style="font-size:36px;font-weight:800;color:#22c55e;line-height:1;">100%</div>
      <div style="font-size:11px;color:#22c55e;opacity:0.8;margin-top:2px;">Last 24 Hours</div>
    </div>""", unsafe_allow_html=True)

    # Compliance report
    report = f"# SURAKSHAAI SAFETY COMPLIANCE REPORT\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nSystem State: {STATUS['level']} (Max Score: {max_score:.0f}/20)\n\n## Zone Health Audit\n"
    for zone, z in zone_risks.items():
        report += f"\n### {z['label']}\n- Level: {z['risk_level']}\n- Score: {z['risk_score']:.0f}/20\n"
    report += "\n## Active Incidents\n"
    for a in alert_system.get_active_alerts():
        report += f"\n### {a['alert_id']}\n- Zone: {a.get('zone_label',a['zone'])}\n- Level: {a['risk_level']}\n- Ack'd: {a['acknowledged']}\n"
    report += "\n---\nSurakshaAI v3.0 | Zero-Harm Operations\n"

    st.download_button("📋 Export Compliance Report", data=report,
        file_name=f"surakshaai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown", width="stretch")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

    # Compound rules list
    st.markdown("""
    <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
    letter-spacing:1px;margin-bottom:10px;">🛡️ Compound Rules Scanned</div>""", unsafe_allow_html=True)

    # Fallback labels/descs for cached engines that predate the 'label'/'desc' fields
    _RULE_META = {
        'TRIPLE_THREAT':         ('Triple-Threat Evacuation',      'Maint + Gas>35ppm + Temp>95°C + Crew>5'),
        'MAINTENANCE_GAS_LEAK':  ('Maintenance Gas Intersection',  'Maint + Gas>35ppm'),
        'PERMIT_GAS_COMBINATION':('Hot Work Permit Gas',           'Permit + Gas>40ppm'),
        'OVERHEATING_WITH_GAS':  ('Overheating Gas Risk',          'Temp>98°C + Gas>25ppm'),
        'WORKER_OVER_CROWDING':  ('Crew Overcrowding',             'Crew>9 + Gas>25ppm'),
        'SHIFT_CHANGE_RISK':     ('Shift Change Telemetry',        'Shift change + Gas>30ppm'),
    }
    rules_html = ""
    for rule in engine.compound_rules:
        rid       = rule.get('id', '')
        _lbl, _desc = _RULE_META.get(rid, (rule.get('label', rid), rule.get('desc', '')))
        triggered = any(rule['condition'](latest, z) for z in SENSOR_ZONES)
        dot_color = '#ef4444' if triggered else '#22c55e'
        rules_html += (
            '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;">'
            '<span style="width:7px;height:7px;border-radius:50%;background:' + dot_color + ';'
            'box-shadow:0 0 4px ' + dot_color + ';margin-top:4px;flex-shrink:0;display:inline-block;"></span>'
            '<div style="font-size:11px;color:#a0b4c8;line-height:1.4;">'
            '<b style="color:#fff;">' + _lbl + '</b>'
            ' — ' + _desc
            + '</div></div>'
        )
    st.markdown(rules_html, unsafe_allow_html=True)

    st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:12px 0;"></div>""", unsafe_allow_html=True)

    # Telemetry status
    telemetry_color = '#ef4444' if sim_on else '#00d4ff'
    telemetry_label = 'CRITICAL' if sim_on else 'SECURE'
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#6b7d94;">
      <span style="width:7px;height:7px;border-radius:50%;background:{telemetry_color};
        box-shadow:0 0 4px {telemetry_color};display:inline-block;"></span>
      Telemetry: <span style="color:{telemetry_color};font-weight:700;">{telemetry_label}</span>
      | {now_str}
    </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── Scenario Controls (replaces manual simulate button) ──
    _scenario_min_now = (_now - st.session_state.scenario_start_time).total_seconds() / 60.0 + st.session_state.scenario_offset_min
    _gas_now = round(min(4.5 + _scenario_min_now * 1.2, 65.0), 1)
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
    border-radius:10px;padding:14px;margin-bottom:12px;">
      <div style="font-size:10px;color:#6b7d94;text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:8px;">
        ⏱️ Scenario Timeline</div>
      <div style="font-size:12px;color:#a0b4c8;line-height:1.8;">
        Elapsed: <b style="color:#fff;">{_scenario_min_now:.1f} min</b><br/>
        Battery-4 Gas: <b style="color:{'#ef4444' if _gas_now>=40 else '#f59e0b' if _gas_now>=20 else '#00ff41'};">{_gas_now} ppm</b><br/>
        Status: <b style="color:{'#ef4444' if st.session_state.compound_risk_active else '#00ff41'};">{'CRITICAL' if st.session_state.compound_risk_active else 'MONITORING'}</b>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Play / Pause Autoplay Toggle
    sim_play = st.toggle("▶️ Autoplay Simulation", value=st.session_state.sim_play_active, key="sim_play_toggle")
    if sim_play != st.session_state.sim_play_active:
        st.session_state.sim_play_active = sim_play
        st.rerun()

    col_ff, col_rst = st.columns(2)
    with col_ff:
        if st.button("⏩ Fast-Forward +20min", key="ff_btn", width="stretch",
                     help="Advance scenario 20 minutes — gas rises rapidly to show realistic escalation"):
            st.session_state.scenario_offset_min += 20
            st.rerun()
    with col_rst:
        if st.button("🔄 Reset Scenario", key="reset_btn", width="stretch",
                     help="Restart from minute 0 — gas returns to baseline"):
            st.session_state.scenario_start_time = datetime.now()
            st.session_state.scenario_offset_min = 20
            st.session_state.compound_risk_active = False
            st.session_state.simulate_active = False
            st.session_state.sim_stage = 'normal'
            st.session_state.ack_critical = False
            st.session_state.ack_medium = False
            st.session_state.ack_time = None
            st.session_state.recovering = False
            st.session_state.compound_risk_first_seen = None
            st.session_state.sim_play_active = False
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT — wrapped in a padded div
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="main-content">', unsafe_allow_html=True)

# Scenario controls in top-right
top_col1, top_col2, top_col3 = st.columns([5.5, 1.2, 1.2])
with top_col2:
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    if st.button("⏩ Fast-Forward", key="ff_btn_top", width="stretch",
                 help="Advance scenario 20 minutes"):
        st.session_state.scenario_offset_min += 20
        st.rerun()
with top_col3:
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    if st.button("🔄 Reset", key="reset_btn2", width="stretch",
                 help="Reset scenario to minute 0"):
        st.session_state.scenario_start_time = datetime.now()
        st.session_state.scenario_offset_min = 20
        st.session_state.compound_risk_active = False
        st.session_state.simulate_active = False
        st.session_state.sim_stage = 'normal'
        st.session_state.ack_critical = False
        st.session_state.ack_medium = False
        st.session_state.ack_time = None
        st.session_state.recovering = False
        st.session_state.compound_risk_first_seen = None
        st.session_state.sim_play_active = False
        st.rerun()

# ─── STATUS BANNER ────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="status-banner"
     style="background:{STATUS['bg']};border-color:{STATUS['border']}55;color:{STATUS['color']};">
  {STATUS['text']}
</div>""", unsafe_allow_html=True)

# ─── EMERGENCY PANEL ──────────────────────────────────────────────────────────
if st.session_state.sim_stage == 'active':
    st.markdown("""
    <div class="emergency-banner">
      <div style="display:flex;align-items:flex-start;gap:16px;">
        <span style="font-size:32px;">🚨</span>
        <div>
          <h3 style="color:#fff;margin:0 0 8px 0;font-size:16px;font-weight:800;letter-spacing:0.5px;">
            TRIPLE-THREAT COMPOUND RISK — VISAKHAPATNAM PATTERN DETECTED
          </h3>
          <p style="color:#fecaca;font-size:13px;margin:0 0 12px 0;line-height:1.6;">
            <b>Battery-4 (Zone A):</b> Gas leak 55.4 ppm + 8 crew + active hot-work maintenance permit.
            This exact combination triggered the <b>2020 Visakhapatnam LG Polymers disaster</b>.
            Immediate evacuation required.
          </p>
          <a href="https://en.wikipedia.org/wiki/Visakhapatnam_gas_leak" target="_blank"
             style="background:rgba(255,255,255,0.15);color:#fff;padding:5px 12px;border-radius:6px;
             text-decoration:none;font-size:11px;font-weight:600;border:1px solid rgba(255,255,255,0.25);">
            📖 Case Study
          </a>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)
    # Acknowledge checklist expander
    checklist_keys = ['chk_evacuate', 'chk_isolate', 'chk_notify']
    for ck in checklist_keys:
        if ck not in st.session_state:
            st.session_state[ck] = False

    with st.expander("🚨 ACKNOWLEDGE INCIDENT & TRIGGER EMERGENCY EVACUATION", expanded=True):
        st.markdown(
            '<div style="color:#fecaca;font-size:12px;font-weight:600;margin-bottom:8px;">'
            'Complete all steps before confirming:</div>',
            unsafe_allow_html=True
        )
        st.session_state.chk_evacuate = st.checkbox(
            "✅ Initiate crew evacuation from Battery-4",
            value=st.session_state.chk_evacuate, key="cb_evacuate"
        )
        st.session_state.chk_isolate = st.checkbox(
            "✅ Isolate gas supply valve for Zone A",
            value=st.session_state.chk_isolate, key="cb_isolate"
        )
        st.session_state.chk_notify = st.checkbox(
            "✅ Notify emergency response team (Alpha & Beta)",
            value=st.session_state.chk_notify, key="cb_notify"
        )
        all_checked = all(st.session_state[k] for k in checklist_keys)
        if st.button(
            "🔴 CONFIRM EMERGENCY EVACUATION" if all_checked else "Complete checklist above to confirm",
            type="primary" if all_checked else "secondary",
            width="stretch",
            key="ack_btn",
            disabled=not all_checked,
        ):
            st.session_state.ack_critical       = True
            st.session_state.sim_stage          = 'acknowledged'
            st.session_state.alert_acknowledged = True
            st.toast("✔ ALT-001 Acknowledged. Emergency sirens activated.", icon="📣")
            st.rerun()

elif st.session_state.sim_stage == 'acknowledged':
    st.markdown("""
    <div style="background:rgba(34,197,94,0.07);border:1px solid rgba(34,197,94,0.3);border-radius:12px;
    padding:13px 20px;margin:0 0 14px 0;display:flex;align-items:center;justify-content:space-between;">
      <div style="display:flex;align-items:center;gap:12px;">
        <span class="dot dot-safe"></span>
        <div>
          <b style="color:#22c55e;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">
            Compound Threat Acknowledged</b>
          <p style="color:#6b7d94;font-size:12px;margin:2px 0 0 0;">
            Emergency teams notified. Sirens active in Battery-4.</p>
        </div>
      </div>
      <span style="background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3);
      border-radius:6px;padding:3px 10px;font-size:11px;font-weight:700;">ACKNOWLEDGED</span>
    </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# KPI CARDS (4 columns)
# ════════════════════════════════════════════════════════════════════════════════
crit_cls = "metric-card metric-card-critical" if STATUS['level'] == 'CRITICAL' else "metric-card"
m1, m2, m3, m4 = st.columns(4)

with m1:
    sparkline_path = "M0,15 L10,18 L20,12 L30,16 L40,8 L50,14 L60,5"
    if STATUS['level'] == 'CRITICAL':
        sparkline_path = "M0,20 L10,5 L20,22 L30,5 L40,22 L50,5 L60,25"
    elif STATUS['level'] == 'HIGH':
        sparkline_path = "M0,18 L10,10 L20,15 L30,8 L40,12 L50,5 L60,18"
    st.markdown(f"""
    <div class="{crit_cls}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div class="metric-label">🌡️ CURRENT RISK</div>
        <svg width="60" height="25" style="margin-top:-2px;opacity:0.7;">
          <path d="{sparkline_path}" fill="none" stroke="{STATUS['color']}" stroke-width="2"/>
        </svg>
      </div>
      <div class="metric-value {STATUS['cls']}">{STATUS['level']}</div>
      <div style="font-size:12px;color:#fff;font-weight:600;margin-bottom:4px;">Score: {max_score:.0f}/20</div>
      <div class="metric-sub">Overall plant safety state</div>
    </div>""", unsafe_allow_html=True)

with m2:
    figures = "".join("👤" for _ in range(min(total_workers, 15)))
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">👥 CREW COUNT</div>
      <div class="metric-value" style="color:#4a8cf7;">{total_workers}</div>
      <div class="metric-sub" style="margin-bottom:8px;">Active on Floor</div>
      <div style="font-size:16px;color:#4a8cf7;letter-spacing:3px;line-height:1.5;">{figures}</div>
    </div>""", unsafe_allow_html=True)

with m3:
    pc = '#f59e0b' if permit_count > 0 else '#22c55e'
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">📋 WORK PERMITS</div>
      <div class="metric-value" style="color:{pc};">{permit_count}</div>
      <div class="metric-sub">Active</div>
      <div style="position:absolute;right:14px;bottom:10px;font-size:42px;opacity:0.05;">📋</div>
    </div>""", unsafe_allow_html=True)

with m4:
    cc = '#ef4444' if compound_detected else '#22c55e'
    cv = "DETECTED" if compound_detected else "CLEAR"
    cds = f"{len(active_compounds)}/6 rules matched" if active_compounds else "0/6 rules matched"
    st.markdown(f"""
    <div class="{crit_cls if compound_detected else 'metric-card'}">
      <div class="metric-label">🔗 COMPOUND RISK</div>
      <div class="metric-value" style="color:{cc};">{cv}</div>
      <div class="metric-sub">{cds}</div>
      <div style="position:absolute;right:14px;bottom:10px;font-size:42px;opacity:0.05;">🛡️</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)



tab_map, tab_cctv = st.tabs(["🗺️ RISK HEATMAP", "📹 AI CCTV SURVEILLANCE"])
with tab_map:
    # ════════════════════════════════════════════════════════════════════════════════
    # HEATMAP (70%) + ZONE STATUS (30%)
    # ════════════════════════════════════════════════════════════════════════════════
    col_map, col_zones = st.columns([7, 3])

    with col_map:
        st.markdown('<div class="section-header">🗺️ REAL-TIME RISK HEATMAP</div>', unsafe_allow_html=True)
        st.iframe(build_heatmap_html(zone_risks, st.session_state.simulate_active), height=420)

    with col_zones:
        st.markdown('<div class="section-header">📋 ZONE STATUS</div>', unsafe_allow_html=True)

        COLOR_MAP = {'CRITICAL':'#ef4444','HIGH':'#f59e0b','MEDIUM':'#eab308','LOW':'#22c55e'}
        DOT_MAP   = {'CRITICAL':'dot dot-critical','HIGH':'dot dot-high','MEDIUM':'dot dot-medium','LOW':'dot dot-safe'}

        for zone_id, zone_label in ZONE_STATUS_ORDER:
            z = zone_risks.get(zone_id, {'risk_level':'LOW','risk_score':0,'sensor_data':{}})
            lvl   = z.get('risk_level', 'LOW')
            score = z.get('risk_score', 0)
            c     = COLOR_MAP.get(lvl, '#22c55e')
            d     = DOT_MAP.get(lvl, 'dot dot-safe')

            # Get gas ppm
            gas = 0.0
            sd = z.get('sensor_data', {})
            for k, v in sd.items():
                if 'gas' in k.lower():
                    gas = float(v)
                    break
            if gas == 0.0:
                gas = latest.get(f'{zone_id}_gas_ppm', 0.0)

            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;padding:8px 12px;margin-bottom:6px;
              background:rgba(255,255,255,0.015);border:1px solid rgba(255,255,255,0.06);
              border-radius:8px;font-family:'Outfit',sans-serif;">
              <span class="{d}" style="flex-shrink:0;"></span>
              <span style="color:#fff;font-size:12px;font-weight:600;flex:1;min-width:90px;">{zone_label}</span>
              <span style="color:rgba(255,255,255,0.2);font-size:11px;">|</span>
              <span style="color:{c};font-size:11px;font-weight:700;width:60px;">{lvl}</span>
              <span style="color:rgba(255,255,255,0.2);font-size:11px;">|</span>
              <span style="color:#6b7d94;font-size:11px;width:70px;">Score: {score:.0f}/20</span>
              <span style="color:rgba(255,255,255,0.2);font-size:11px;">|</span>
              <span style="color:#6b7d94;font-size:11px;">Gas: {gas:.1f}ppm</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)



with tab_cctv:
    # ─── HEADER ROW ───
    st.markdown("""
    <div style="display:flex; justify-content:space-between; align-items:center; 
         padding: 8px 16px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); 
         border-radius: 8px; margin-bottom: 15px; font-family:'Outfit',sans-serif;">
        <span style="font-weight: 700; color: #fff; font-size: 16px;">🎥 AI CCTV SURVEILLANCE</span>
        <div style="display:flex; align-items:center; gap:15px;">
            <span style="color:#6b7d94; font-size:12px; font-weight:700; letter-spacing:0.5px;">⏱️ LIVE</span>
            <span style="display:inline-flex; align-items:center; gap:6px; color:#00ff41; font-size:12px; font-weight:700;">
                <span style="width:8px; height:8px; background-color:#00ff41; border-radius:50%; display:inline-block; box-shadow: 0 0 8px #00ff41;"></span>
                SECURE
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ─── CONTROL BAR ROW ───
    selected_zone = st.selectbox(
        "Select CCTV Camera Feed:",
        options=SENSOR_ZONES,
        format_func=lambda z: f"📹 {ZONE_LABELS.get(z, z)} Camera Feed",
        key="cctv_zone_selector"
    )
    run_feed = True
    
    # ─── MAIN CCTV CONTAINER ───
    with st.container(border=True):
        st.markdown(f"""
        <div style="font-family:'Outfit',sans-serif; font-weight:700; color:#fff; font-size:13px; 
             margin-bottom:8px; text-transform:uppercase; letter-spacing:0.5px;">
            📹 LIVE CCTV FEED - {ZONE_LABELS.get(selected_zone, selected_zone)}
        </div>
        """, unsafe_allow_html=True)
        
        frame_placeholder = st.empty()
        status_bar_placeholder = st.empty()
        
    st.markdown("<div style='height:15px;'></div>", unsafe_allow_html=True)
    
    # ─── ALERTS PANEL ───
    st.markdown("""
    <div style="font-weight: 700; color: #a0b4c8; font-size: 11px; letter-spacing: 0.5px; margin-bottom: 8px; text-transform: uppercase;">
        🔔 ALERTS
    </div>
    """, unsafe_allow_html=True)
    alerts_placeholder = st.empty()
    
    st.markdown("<div style='height:15px;'></div>", unsafe_allow_html=True)
    
    # ─── BOTTOM SUMMARY GRID ───
    grid_col1, grid_col2, grid_col3, grid_col4 = st.columns(4)
    detections_placeholder = grid_col1.empty()
    zone_status_placeholder = grid_col2.empty()
    rules_placeholder = grid_col3.empty()
    system_placeholder = grid_col4.empty()

    import cv2
    
    # Load YOLO if needed
    if frame_processor.detector.model is None and not getattr(frame_processor.detector, '_attempted_load', False):
        frame_processor.detector._load_model()
    
    # Set simulation mode dynamically depending on YOLO availability
    if frame_processor.detector.model is not None:
        frame_processor.detector.use_simulation = False
    else:
        frame_processor.detector.use_simulation = True
    
    # Helper to format summary grids
    def render_summary_grids(fps_val, p_count, h_count, rules_count, detections_list, zone_counts_dict):
        # DETECTIONS card
        p_c = max([d.confidence for d in detections_list if d.label == 'person'], default=0.0)
        h_c = max([d.confidence for d in detections_list if d.label == 'helmet'], default=0.0)
        v_c = max([d.confidence for d in detections_list if d.label == 'vest'], default=0.0)
        p_c_str = f"{p_c:.2f}" if p_c > 0 else "N/A"
        h_c_str = f"{h_c:.2f}" if h_c > 0 else "N/A"
        v_c_str = f"{v_c:.2f}" if v_c > 0 else "N/A"
        
        detections_placeholder.markdown(f"""
        <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.06); 
             border-radius:10px; padding:15px; min-height:115px; font-family:'Outfit',sans-serif;">
            <div style="font-size:10px; color:#6b7d94; text-transform:uppercase; letter-spacing:0.5px; font-weight:700; margin-bottom:8px;">
                DETECTIONS
            </div>
            <div style="font-size:12px; color:#fff; line-height:1.6;">
                Person: <span style="color:#00ff41; font-weight:600;">{p_c_str}</span><br/>
                Helmet: <span style="color:#00ff41; font-weight:600;">{h_c_str}</span><br/>
                Vest: <span style="color:#00ff41; font-weight:600;">{v_c_str}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # ZONE STATUS card — show all 5 zones from telemetry
        z_a = zone_counts_dict.get('Zone_A', 0)
        z_b = zone_counts_dict.get('Zone_B', 0)
        z_c = zone_counts_dict.get('Zone_C', 0)
        z_r = zone_counts_dict.get('Reactor_Area', 0)
        z_s = zone_counts_dict.get('Storage_Area', 0)

        def wc(n, alert=False):
            col = '#ef4444' if alert else '#00ff41' if n == 0 else '#fff'
            return f'<span style="font-weight:600;color:{col};">{n}w</span>'

        zone_status_placeholder.markdown(f"""
        <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.06);
             border-radius:10px; padding:15px; min-height:115px; font-family:'Outfit',sans-serif;">
            <div style="font-size:10px; color:#6b7d94; text-transform:uppercase; letter-spacing:0.5px; font-weight:700; margin-bottom:8px;">
                ZONE STATUS
            </div>
            <div style="font-size:11px; color:#a0b4c8; line-height:1.7;">
                Bat-4: {wc(z_a, z_a > 5)}&nbsp;
                Bat-5: {wc(z_b)}&nbsp;
                Bat-6: {wc(z_c)}<br/>
                Reactor: {wc(z_r)}&nbsp;
                Storage: {wc(z_s, z_s > 3)}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # RULES card
        rules_placeholder.markdown(f"""
        <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.06); 
             border-radius:10px; padding:15px; min-height:115px; font-family:'Outfit',sans-serif;">
            <div style="font-size:10px; color:#6b7d94; text-transform:uppercase; letter-spacing:0.5px; font-weight:700; margin-bottom:8px;">
                RULES
            </div>
            <div style="font-size:12px; color:#fff; line-height:1.6;">
                Scanned: <span style="font-weight:600; color:#fff;">6</span><br/>
                Matched: <span style="color:{'#ef4444' if rules_count > 0 else '#00ff41'}; font-weight:600;">{rules_count}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # SYSTEM card
        system_placeholder.markdown(f"""
        <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.06); 
             border-radius:10px; padding:15px; min-height:115px; font-family:'Outfit',sans-serif;">
            <div style="font-size:10px; color:#6b7d94; text-transform:uppercase; letter-spacing:0.5px; font-weight:700; margin-bottom:8px;">
                SYSTEM
            </div>
            <div style="font-size:20px; color:#00ff41; font-weight:800; line-height:1.2;">
                100%
            </div>
            <div style="font-size:10px; color:#6b7d94; margin-top:4px;">
                Last 24 Hours
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Reset frame index if the selected zone changes
    if 'prev_selected_zone' not in st.session_state:
        st.session_state.prev_selected_zone = selected_zone
    if st.session_state.prev_selected_zone != selected_zone:
        st.session_state.cctv_frame_index = 0
        st.session_state.prev_selected_zone = selected_zone
        from src.cctv.inference import reset_ppe_buffer
        reset_ppe_buffer()

    # Map selected zone to corresponding video file in the footage directory
    FOOTAGE_FILES = {
        'Zone_A': 'Battery_4.mp4',
        'Zone_B': 'Battery_5.mp4',
        'Zone_C': 'Battery_6.mp4',
        'Reactor_Area': 'Reactor_Block.mp4',
        'Storage_Area': 'Storage_Block.mp4'
    }
    footage_filename = FOOTAGE_FILES.get(selected_zone)
    video_path = f"footage/{footage_filename}" if footage_filename else None

    # Read and display raw frames with dynamic PIL drawing
    if video_path and os.path.exists(video_path):
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Start from the saved frame index
        start_frame = st.session_state.get('cctv_frame_index', 0)
        if start_frame >= total_frames or start_frame < 0:
            start_frame = 0
            
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        # Play a short chunk of frames per rerun to keep dashboard responsive when autoplay is active
        if st.session_state.get('sim_play_active', False):
            chunk_size = 120  # Increased from 24 to 120 for smoother playback and less visual reloading
        else:
            chunk_size = 240
            
        frame_idx = start_frame
        end_frame = start_frame + chunk_size
        st.session_state.video_played_this_run = True
        
        while cap.isOpened() and frame_idx < end_frame and frame_idx < total_frames:
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_idx += 1
            
            # Skip frames to run at a lower, lightweight update rate (show every 2nd frame)
            if frame_idx % 2 != 0:
                continue
                
            # Run YOLO or Simulated detection
            from src.cctv.inference import run_inference
            pil_img, w_count, viol_count, active_dets = run_inference(
                frame, 
                selected_zone, 
                latest, 
                current_frame=frame_idx, 
                draw_fallback_fn=draw_pil_overlays
            )
            
            # Persist YOLO counts in session state so the entire dashboard updates dynamically
            st.session_state.yolo_worker_counts[selected_zone] = w_count
            latest[f"{selected_zone}_worker_count"] = w_count
            
            frame_placeholder.image(pil_img, width="stretch")
            
            # Render status bar dynamically in sync with the video
            is_critical = (latest.get("max_risk_level") == "CRITICAL" or st.session_state.simulate_active)
            overpressure_active = (selected_zone == 'Zone_C' and frame_idx >= 95)
            if selected_zone == 'Zone_C':
                h_count = 1 if (is_critical or overpressure_active) else 0
            elif selected_zone == 'Zone_A':
                h_count = 1 if (frame_idx >= 40) else 0
            else:
                h_count = 1 if (selected_zone in ['Reactor_Area']) or (selected_zone == 'Zone_B' and st.session_state.simulate_active) else 0
                
            safe_zones = 4 if (h_count > 0 or (viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area'))) else 5
            
            status_bar_placeholder.markdown(f"""
            <div style="display:flex; justify-content:space-between; align-items:center; 
                 padding: 8px 16px; background: rgba(0,0,0,0.4); border-top: 1px solid rgba(255,255,255,0.06); 
                 margin-top: 8px; font-family:'Outfit',sans-serif; font-size: 12px; color: #a0b4c8;">
                <span>📹 FPS: <b>25.0</b></span>
                <span>👷 Workers: <b>{w_count}</b></span>
                <span style="color:{'#ef4444' if h_count > 0 else '#a0b4c8'}; font-weight:{'700' if h_count > 0 else 'normal'};">⚠️ Hazards: <b>{h_count}</b></span>
                <span style="color:#00ff41;">🟢 Safe Zones: <b>{safe_zones}</b></span>
            </div>
            """, unsafe_allow_html=True)
            
            # Render nominal / warning cards
            alerts_list = []
            
            if viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area'):
                if selected_zone == 'Zone_C':
                    missing_vests = w_count - len([d for d in active_dets if d.label == 'vest'])
                    msg = f"PPE violation: {missing_vests} worker missing hi-vis vest"
                else:
                    missing_helmets = w_count - len([d for d in active_dets if d.label == 'helmet'])
                    msg = f"PPE violation detected: {missing_helmets} worker(s) missing helmet. Immediate compliance check required."
                    
                alerts_list.append(f"""
                <div style="background: rgba(255,255,255,0.03); 
                            border-left: 4px solid #eab308;
                            padding: 12px 16px;
                            margin: 4px 0;
                            border-radius: 8px;
                            font-family:'Outfit',sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                        <span style="font-weight: 600; color: #eab308; font-size:12px;">⚠️ WARNING - PPE VIOLATION</span>
                        <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                    </div>
                    <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">{msg}</div>
                </div>
                """)
                
            if overpressure_active:
                alerts_list.append("""
                <div style="background: rgba(255,255,255,0.03); 
                            border-left: 4px solid #eab308;
                            padding: 12px 16px;
                            margin: 4px 0;
                            border-radius: 8px;
                            font-family:'Outfit',sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                        <span style="font-weight: 600; color: #eab308; font-size:12px;">⚠️ WARNING - OVERPRESSURE</span>
                        <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                    </div>
                    <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">OVERPRESSURE WARNING — Gauge in red zone</div>
                </div>
                """)
                
            if selected_zone == 'Reactor_Area':
                alerts_list.append("""
                <div style="background: rgba(255,255,255,0.03); 
                            border-left: 4px solid #eab308;
                            padding: 12px 16px;
                            margin: 4px 0;
                            border-radius: 8px;
                            font-family:'Outfit',sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                        <span style="font-weight: 600; color: #eab308; font-size:12px;">⚠️ WARNING - BYSTANDER FLASH BURNS</span>
                        <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                    </div>
                    <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">Bystander Flash Burns: The second worker is far too close to the welding arc without any eye or face protection.</div>
                </div>
                """)
                alerts_list.append("""
                <div style="background: rgba(255,255,255,0.03); 
                            border-left: 4px solid #eab308;
                            padding: 12px 16px;
                            margin: 4px 0;
                            border-radius: 8px;
                            font-family:'Outfit',sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                        <span style="font-weight: 600; color: #eab308; font-size:12px;">⚠️ WARNING - INADEQUATE FUME EXTRACTION</span>
                        <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                    </div>
                    <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">Inadequate Fume Extraction: The visible "yellowish haze" indicates poor ventilation, leading to an unsafe build-up of toxic welding fumes.</div>
                </div>
                """)
                
            show_critical_alert = False
            if selected_zone == 'Zone_C':
                show_critical_alert = is_critical
            elif selected_zone == 'Zone_A':
                show_critical_alert = (frame_idx >= 40)
            elif selected_zone == 'Reactor_Area':
                # Reactor Block has its own dedicated warning cards (Bystander Flash Burns +
                # Inadequate Fume Extraction) — the generic COMPATIBILITY VIOLATION is not shown here
                show_critical_alert = False
            else:
                show_critical_alert = is_critical or (selected_zone != 'Zone_C' and h_count > 0)
                
            if show_critical_alert:
                if selected_zone == 'Zone_C':
                    alerts_list.append("""
                    <div style="background: rgba(255,255,255,0.03); 
                                border-left: 4px solid #ef4444;
                                padding: 12px 16px;
                                margin: 4px 0;
                                border-radius: 8px;
                                font-family:'Outfit',sans-serif;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                            <span style="font-weight: 600; color: #ef4444; font-size:12px;">⚠️ CRITICAL - EQUIPMENT OVERHEATING</span>
                            <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                        </div>
                        <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">Tank/pipe junction temperature exceeds critical threshold in Zone C. Coolant flow activation required.</div>
                    </div>
                    """)
                else:
                    alerts_list.append("""
                    <div style="background: rgba(255,255,255,0.03); 
                                border-left: 4px solid #ef4444;
                                padding: 12px 16px;
                                margin: 4px 0;
                                border-radius: 8px;
                                font-family:'Outfit',sans-serif;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                            <span style="font-weight: 600; color: #ef4444; font-size:12px;">⚠️ CRITICAL - COMPATIBILITY VIOLATION</span>
                            <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                        </div>
                        <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">Uncontrolled volatile gas cloud detected in close proximity to active hot work permit. Evacuation required.</div>
                    </div>
                    """)
                    
            if not alerts_list:
                alerts_html = """
                <div style="background:rgba(34,197,94,0.04);border-left:4px solid #22c55e;
                     border-top:1px solid rgba(34,197,94,0.15);border-right:1px solid rgba(34,197,94,0.15);
                     border-bottom:1px solid rgba(34,197,94,0.15);
                     border-radius:10px;padding:12px 16px;margin:4px 0;
                     font-family:'Outfit',sans-serif;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <span style="font-weight:600;color:#22c55e;font-size:12px;">🟢 NOMINAL - FEED SECURE</span>
                    <span style="color:#6b7d94;font-size:11px;">MONITORING</span>
                  </div>
                  <div style="color:#a0b4c8;font-size:12px;line-height:1.4;">
                    CCTV feed matches all safety standards. Helmet and vest compliance active. No hazardous smoke, fire, or gas leaks detected.
                  </div>
                </div>
                """
            else:
                alerts_html = "\n".join([item.strip() for item in alerts_list])
            alerts_placeholder.markdown(alerts_html, unsafe_allow_html=True)
            
            # Update summary grids
            render_summary_grids(25.0, w_count, h_count, 1 if (viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area')) else 0, active_dets, {
                'Zone_A': w_count if selected_zone == 'Zone_A' else 0,
                'Zone_B': w_count if selected_zone == 'Zone_B' else 0,
                'Zone_C': w_count if selected_zone == 'Zone_C' else 0,
                'Reactor_Area': w_count if selected_zone == 'Reactor_Area' else 0,
                'Storage_Area': w_count if selected_zone == 'Storage_Area' else 0
            })
            
            # Short sleep to pace the frames smoothly without locking
            time.sleep(0.06)
            
        cap.release()
        
        # Save frame index for the next run (wrap around if video ends)
        if frame_idx >= total_frames:
            frame_idx = 0
        st.session_state.cctv_frame_index = frame_idx
    else:
        # Standby screen when no video is found or feed is stopped
        msg = "Enable the live stream switch above to start real-time AI surveillance."
        if video_path and not os.path.exists(video_path):
            msg = f"CCTV footage file not found: <b>{video_path}</b>"
        frame_placeholder.markdown(f"""
        <div style="background:#0a0e17; height:380px; display:flex; flex-direction:column; justify-content:center; align-items:center; border: 1px dashed rgba(255,255,255,0.1); border-radius:8px;">
            <span style="font-size:32px; margin-bottom:12px;">⚠️</span>
            <span style="font-family:'Outfit',sans-serif; font-weight:700; color:#6b7d94; text-transform:uppercase; letter-spacing:1.5px; font-size:13px;">CCTV Stream Standby</span>
            <span style="font-family:'Outfit',sans-serif; color:#4a5568; font-size:11px; margin-top:4px;">{msg}</span>
        </div>
        """, unsafe_allow_html=True)
        
        status_bar_placeholder.markdown("""
        <div style="display:flex; justify-content:space-between; align-items:center; 
             padding: 8px 16px; background: rgba(0,0,0,0.4); border-top: 1px solid rgba(255,255,255,0.06); 
             margin-top: 8px; font-family:'Outfit',sans-serif; font-size: 12px; color: #a0b4c8;">
            <span>📹 FPS: <b>0.0</b></span>
            <span>👷 Workers: <b>0</b></span>
            <span>⚠️ Hazards: <b>0</b></span>
            <span style="color:#00ff41;">🟢 Safe Zones: <b>6</b></span>
        </div>
        """, unsafe_allow_html=True)
        
        alerts_placeholder.markdown("""
        <div style="background:rgba(34,197,94,0.05);border:1px solid rgba(34,197,94,0.15);padding:12px;border-radius:6px;text-align:center;color:#22c55e;font-size:12px;font-weight:600;">
          🟢 CCTV feed offline. Waiting for video source.
        </div>
        """, unsafe_allow_html=True)
        
        render_summary_grids(0.0, 0, 0, 0, [], {})

# ════════════════════════════════════════════════════════════════════════════════
# BOTTOM: TREND (3.5) | ALERTS (3.8) | RULES (2.7)
# ════════════════════════════════════════════════════════════════════════════════
col_trend, col_alerts, col_rules = st.columns([3.5, 3.8, 2.7])

# ─── 24-HOUR RISK TREND ───────────────────────────────────────────────────────
with col_trend:
    st.markdown('<div class="section-header">📈 24-HOUR RISK TREND</div>', unsafe_allow_html=True)

    # Build a rich synthetic 24h trend from real df + guaranteed visible data
    timeline_data = []

    # Attempt to read real data from CSV
    real_data_ok = False
    for idx in range(max(0, len(df) - 300), len(df), 10):
        row = df.iloc[idx]
        scores = []
        for z in ['Zone_A', 'Zone_B', 'Zone_C', 'Reactor_Area', 'Storage_Area']:
            try:
                s = engine.analyze_zone(row, z)['risk_score']
                scores.append(s)
            except Exception:
                scores.append(0)
        max_risk = max(scores, default=0)
        timeline_data.append({'timestamp': row['timestamp'], 'risk': max_risk})
        if max_risk > 0:
            real_data_ok = True

    # If CSV data is all-zero or missing, build a synthetic 24h baseline
    if not real_data_ok or not timeline_data:
        base_time = datetime.now() - timedelta(hours=24)
        # Synthetic profile: flat LOW → slight bump → return LOW → spike at end if sim active
        synthetic_profile = [
            (0,   1.2), (2,   1.5), (4,   2.1), (5,   3.8), (6,   2.4),
            (8,   1.8), (10,  2.0), (12,  3.5), (13,  5.2), (14,  4.0),
            (15,  3.1), (16,  2.5), (18,  1.9), (20,  2.8), (21,  3.2),
            (22,  2.0), (23,  1.5), (23.5, 1.8),
        ]
        for h, risk in synthetic_profile:
            timeline_data.append({
                'timestamp': base_time + timedelta(hours=h),
                'risk': risk
            })

    # Always append current moment
    if st.session_state.simulate_active:
        timeline_data.append({'timestamp': latest['timestamp'], 'risk': max_score})

    if timeline_data:
        tdf = pd.DataFrame(timeline_data)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=tdf['timestamp'], y=tdf['risk'],
            mode='lines', name='Risk Score',
            line=dict(color='#00d4ff', width=1.5),
            fill='tozeroy', fillcolor='rgba(0,212,255,0.06)'
        ))
        for threshold, label, col_t in [(12,'CRITICAL (12)','#ef4444'),(8,'HIGH (8)','#f59e0b'),(5,'MEDIUM (5)','#eab308')]:
            fig.add_hline(y=threshold, line_dash="dash", line_color=col_t, line_width=1,
                annotation_text=label, annotation_position="right",
                annotation_font=dict(color=col_t, size=9, family="Outfit"))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font_color='#a0b4c8', height=220,
            margin=dict(l=0, r=55, t=8, b=0),
            showlegend=False,
            xaxis=dict(showgrid=False, tickformat='%H:%M', tickfont=dict(size=9, family="Outfit")),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.04)',
                       range=[0, 22], tickfont=dict(size=9, family="Outfit"),
                       title=dict(text='RISK SCORE', font=dict(size=9, color='#6b7d94')))
        )
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})


# ─── ACTIVE ALERTS ────────────────────────────────────────────────────────────
with col_alerts:
    # Header row with filter pills
    hdr_left, hdr_right = st.columns([1, 1])
    with hdr_left:
        st.markdown('<div class="section-header" style="margin-bottom:0;margin-top:4px;">🔔 ACTIVE ALERTS</div>', unsafe_allow_html=True)
    with hdr_right:
        sev_filter = st.selectbox(
            "Filter:",
            options=["All", "Critical", "Medium"],
            key="sev_filter",
            label_visibility="collapsed"
        )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # Build alerts list from RiskAlert objects
    sim_start = st.session_state.get('sim_start_time', None)
    alerts_list: List[RiskAlert] = []

    if st.session_state.simulate_active:
        for a in alert_system.alerts:
            lvl   = a['risk_level']
            zone  = a['zone']
            score = a['risk_score']
            sd = {
                'gas_ppm':     55.4 if zone == 'Zone_A' else 16.0,
                'temperature_c': 98.2 if zone == 'Zone_A' else 106.0,
                'worker_count':  8   if zone == 'Zone_A' else 2,
            }
            alerts_list.append(RiskAlert(
                timestamp=pd.Timestamp(latest['timestamp']),
                zone=zone, risk_score=score, risk_level=lvl,
                factors=a.get('factors', []),
                compound_factors=a.get('compound_factors', []),
                message=a.get('message', ''),
                sensor_data=sd
            ))

    for hist_alert in engine.alert_history:
        if not any(a.zone == hist_alert.zone and
                   abs((a.timestamp - hist_alert.timestamp).total_seconds()) < 5
                   for a in alerts_list):
            alerts_list.append(hist_alert)

    if sev_filter == "Critical":
        alerts_list = [a for a in alerts_list if a.risk_level == "CRITICAL"]
    elif sev_filter == "Medium":
        alerts_list = [a for a in alerts_list if a.risk_level in ["MEDIUM","HIGH"]]

    alerts_list = alerts_list[-5:]

    if alerts_list:
        for alert in reversed(alerts_list):
            st.markdown(render_alert_card(alert, sim_start), unsafe_allow_html=True)
    else:
        st.markdown(render_safe_card(), unsafe_allow_html=True)

    st.markdown("""
    <div style="display:flex;justify-content:space-between;align-items:center;
    margin-top:10px;font-size:11px;font-family:'Outfit',sans-serif;">
      <span style="color:#6b7d94;">Showing latest 5 alerts</span>
      <a href="#" style="color:#00d4ff;text-decoration:none;font-weight:600;">View All Alerts →</a>
    </div>""", unsafe_allow_html=True)


# ─── SAFETY RULES MONITOR ────────────────────────────────────────────────────
with col_rules:
    st.markdown('<div class="section-header">🛡️ SAFETY RULES MONITOR</div>', unsafe_allow_html=True)

    _RULE_META2 = {
        'TRIPLE_THREAT':         'Triple-Threat Evacuation',
        'MAINTENANCE_GAS_LEAK':  'Maintenance Gas Intersection',
        'PERMIT_GAS_COMBINATION':'Hot Work Permit Gas',
        'OVERHEATING_WITH_GAS':  'Overheating Gas Risk',
        'WORKER_OVER_CROWDING':  'Crew Overcrowding',
        'SHIFT_CHANGE_RISK':     'Shift Change Telemetry',
    }
    for rule in engine.compound_rules:
        rid       = rule.get('id', '')
        rule_name = _RULE_META2.get(rid, rule.get('label', rid))
        triggered = any(rule['condition'](latest, z) for z in SENSOR_ZONES)
        c   = '#ef4444' if triggered else '#22c55e'
        bg  = 'rgba(239,68,68,0.05)' if triggered else 'rgba(255,255,255,0.015)'
        lbl = 'ALERT' if triggered else 'PASS'

        icon_html = (
            '<span style="display:inline-flex;align-items:center;justify-content:center;'
            'width:16px;height:16px;border-radius:50%;background:' + c + ';'
            'color:#fff;font-size:9px;font-weight:800;flex-shrink:0;">'
            + ('!' if triggered else '✓') + '</span>'
        )

        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;align-items:center;
          padding:9px 12px;margin-bottom:7px;background:{bg};
          border:1px solid rgba(255,255,255,0.06);border-radius:8px;
          font-family:'Outfit',sans-serif;">
          <div style="display:flex;align-items:center;gap:8px;">
            {icon_html}
            <span style="color:#fff;font-size:12px;font-weight:600;">{rule_name}</span>
          </div>
          <span style="color:{c};font-size:11px;font-weight:800;text-transform:uppercase;
            letter-spacing:0.5px;">{lbl}</span>
        </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="display:flex;justify-content:flex-end;margin-top:8px;font-size:11px;
    font-family:'Outfit',sans-serif;">
      <a href="#" style="color:#00d4ff;text-decoration:none;font-weight:600;">View All Rules →</a>
    </div>""", unsafe_allow_html=True)


# ─── FOOTER ──────────────────────────────────────────────────────────────────
st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
st.markdown("""
<div style="text-align:center;padding:10px 0;font-size:11px;color:#6b7d94;
letter-spacing:0.5px;font-family:'Outfit',sans-serif;
border-top:1px solid rgba(255,255,255,0.05);margin-top:8px;">
  SurakshaAI v3.0 &nbsp;│&nbsp; Built for Zero-Harm Operations &nbsp;│&nbsp; © 2026 Industrial Safety Intelligence Platform
</div>""", unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)  # close main-content


# ─── AUTOPLAY SIMULATION TICK ─────────────────────────────────────────────────
if st.session_state.sim_play_active:
    if st.session_state.get('video_played_this_run', False):
        # Progress timeline by 1.0 simulation minute after a smooth 120-frame video chunk (~3.6s real-time playback)
        st.session_state.scenario_offset_min += 1.0
        st.session_state.video_played_this_run = False
        st.rerun()
    else:
        # Paced delay for map tab
        time.sleep(1.5)
        st.session_state.scenario_offset_min += 0.5
        st.rerun()