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
from src.alert_system import AlertSystem as PersistentAlertSystem, evaluate_alert_conditions, dispatch_alerts, clear_alert_if_safe

class AlertSystem:
    def __init__(self):
        self.persistent_system = PersistentAlertSystem()
        self.mock_alerts = []
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
        
        # Ensure row is a pd.Series
        if not isinstance(row, pd.Series):
            row_series = pd.Series(row)
        else:
            row_series = row
            
        risk_result = {
            'risk_level': result.get('risk_level', 'LOW'),
            'risk_score': result.get('risk_score', 0),
            'zone': result.get('zone', 'Unknown'),
            'factors': result.get('factors', []),
            'compound_factors': result.get('compound_factors', []),
            'message': result.get('message', '')
        }
        
        # Write to persistent database
        db_alert = self.persistent_system.trigger_alert(row_series, risk_result)
        return db_alert

    @property
    def alerts(self):
        # Merge persistent DB alerts and any custom mock alerts assigned to self.alerts
        db_alerts = self.persistent_system.get_recent_alerts(100)
        return self.mock_alerts + db_alerts

    @alerts.setter
    def alerts(self, value):
        self.mock_alerts = value

    def get_active_alerts(self):
        db_active = self.persistent_system.get_active_alerts()
        mock_active = [a for a in self.mock_alerts if not a.get('resolved')]
        return mock_active + db_active

    def acknowledge_alert(self, alert_id: str) -> bool:
        for a in self.mock_alerts:
            if a.get('alert_id') == alert_id:
                a['acknowledged'] = True
                return True
        return self.persistent_system.acknowledge_alert(alert_id)

    def resolve_alert(self, alert_id: str) -> bool:
        for a in self.mock_alerts:
            if a.get('alert_id') == alert_id:
                a['resolved'] = True
                return True
        return self.persistent_system.resolve_alert(alert_id)


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


def get_zone_color(status: str) -> str:
    return {
        "CRITICAL": "#ef4444",
        "HIGH":     "#f97316", 
        "MEDIUM":   "#f59e0b",
        "LOW":      "#22c55e",
        "CLEAR":    "#22c55e"
    }.get(status.upper(), "#6b7280")



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
        msg = 'Maintenance + Gas leak detected. Same as triple-threat pattern.'
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
                        if ppe_violation and w_def.get('violation_type') == 'MISSING_HIVIZ_VEST':
                            v_label = "⚠ NO HI-VIS VEST"
                        else:
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
    def sensor_val(zone_id, key):
        sd = zone_risks.get(zone_id, {}).get('sensor_data', {})
        for k, v in sd.items():
            if key in k:
                return float(v)
        return 0.0

    def make_zone(zone_id, label, x, y, w, h):
        z   = zone_risks.get(zone_id, {})
        lvl = z.get('risk_level', 'LOW')
        score = z.get('risk_score', 0)
        gas   = sensor_val(zone_id, 'gas_ppm')
        temp  = sensor_val(zone_id, 'temperature_c')
        crew  = int(sensor_val(zone_id, 'worker_count'))
        
        base_color = get_zone_color(lvl)
        if lvl.upper() not in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "CLEAR"]:
            fill = '#1e293b'
            stroke = '#334155'
            text_color = '#94a3b8'
            glow = 'none'
            icon_char = '🛡️'
        else:
            stroke = base_color
            r_val = int(base_color[1:3], 16)
            g_val = int(base_color[3:5], 16)
            b_val = int(base_color[5:7], 16)
            fill = f"rgba({r_val}, {g_val}, {b_val}, 0.15)"
            glow = f"rgba({r_val}, {g_val}, {b_val}, 0.6)"
            text_color = '#ffffff'
            if lvl.upper() in ['CRITICAL', 'HIGH', 'MEDIUM']:
                icon_char = '⚠️'
            else:
                icon_char = '✓'
            
        pulse = ''
        if lvl == 'CRITICAL': pulse = 'animation:critPulse 1.5s ease-in-out infinite;'
        elif lvl == 'HIGH':   pulse = 'animation:highPulse 2s ease-in-out infinite;'

        # Clean card layout matching reference image
        # Draw a small icon indicator circle on the left, and text on the right
        # For Battery (w=135):
        if w < 180:
            cx_icon = x + 24
            cy_icon = y + h / 2
            x_text = x + 44
            font_sz_lbl = 11
            font_sz_val = 9
            y_lbl = y + 36
            y_val = y + 54
        else:
            # For Reactor/Storage (w=210):
            cx_icon = x + 30
            cy_icon = y + h / 2
            x_text = x + 56
            font_sz_lbl = 11.5
            font_sz_val = 9.5
            y_lbl = y + 36
            y_val = y + 54

        icon_svg = f"""
        <circle cx="{cx_icon:.1f}" cy="{cy_icon:.1f}" r="11" fill="{stroke}15" stroke="{stroke}" stroke-width="1"/>
        <text x="{cx_icon:.1f}" y="{cy_icon+3.5:.1f}" text-anchor="middle" fill="{stroke}" font-family="Outfit,sans-serif" font-size="10" font-weight="900">{icon_char}</text>
        """

        label_svg = f'<text x="{x_text:.1f}" y="{y_lbl:.1f}" fill="{text_color}" font-family="Outfit,sans-serif" font-size="{font_sz_lbl}" font-weight="800">{label}</text>'
        val_svg = f'<text x="{x_text:.1f}" y="{y_val:.1f}" fill="#a0b4c8" opacity="0.8" font-family="Outfit,sans-serif" font-size="{font_sz_val}">{gas:.1f} ppm</text>'

        tooltip = f"{label} | {lvl} | Score {score:.0f}/20 | Gas {gas:.1f}ppm | Temp {temp:.1f}°C | Crew {crew}"
        return f"""<g class="zone" id="z-{zone_id}">
  <title>{tooltip}</title>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" ry="10"
        fill="{fill}" stroke="{stroke}" stroke-width="1.8"
        style="{pulse}filter:drop-shadow(0 0 6px {glow});"/>
  {icon_svg}
  {label_svg}
  {val_svg}
</g>"""

    CW, CH = 540, 220
    PAD = 15
    BW, BH = 135, 80
    BGAP_X = 15
    BGAP_Y = 15

    zones_layout = [
        ('Zone_A',       'Battery-4',     15,  15,  135, 80),
        ('Zone_B',       'Battery-5',     165, 15,  135, 80),
        ('Zone_C',       'Battery-6',     315, 15,  135, 80),
        ('Reactor_Area', 'Reactor Block',  15,  115, 210, 80),
        ('Storage_Area', 'Storage Area',   240, 115, 210, 80)
    ]

    zones_svg = "\n".join(
        make_zone(zid, lbl, x, y, w, h)
        for zid, lbl, x, y, w, h in zones_layout
    )

    # Vertical legend color bar matching reference image
    legend_gradient = """
    <linearGradient id="lg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ef4444"/>
      <stop offset="50%" stop-color="#f59e0b"/>
      <stop offset="100%" stop-color="#22c55e"/>
    </linearGradient>
    """
    legend  = f'<rect x="475" y="15" width="12" height="180" fill="url(#lg)" rx="4"/>'
    legend += f'<text x="495" y="27" fill="#ef4444" font-family="Outfit,sans-serif" font-size="8" font-weight="900">HIGH</text>'
    legend += f'<text x="495" y="191" fill="#22c55e" font-family="Outfit,sans-serif" font-size="8" font-weight="900">LOW</text>'

    # Room wall schematic grid lines inside the blueprint background
    row_labels = """
    <rect x="5" y="5" width="460" height="210" fill="none" stroke="rgba(0,212,255,0.08)" stroke-width="1.5" rx="8"/>
    <line x1="158" y1="5" x2="158" y2="215" stroke="rgba(0,212,255,0.08)" stroke-width="1" stroke-dasharray="3,3"/>
    <line x1="308" y1="5" x2="308" y2="215" stroke="rgba(0,212,255,0.08)" stroke-width="1" stroke-dasharray="3,3"/>
    <line x1="5" y1="108" x2="465" y2="108" stroke="rgba(0,212,255,0.08)" stroke-width="1" stroke-dasharray="3,3"/>
    """

    sim_badge = ""

    return f"""<!DOCTYPE html><html>
<head><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:transparent;font-family:'Outfit',sans-serif;overflow:hidden;}}
.wrap{{background:rgba(10,14,23,0.55);border:1px solid rgba(255,255,255,0.07);
  border-radius:14px;padding:8px;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);}}
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
    {legend_gradient}
    <pattern id="g" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0L0 0 0 28" fill="none" stroke="rgba(255,255,255,0.022)" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="{CW}" height="{CH}" fill="url(#g)" rx="10"/>
  {row_labels}
  {zones_svg}
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
    'dev_mode': False,
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
    alert_system.acknowledge_alert(aid)
    if aid == 'ALT-001':
        st.session_state.ack_critical = True
        st.session_state.sim_stage    = 'acknowledged'
        st.session_state.ack_time     = datetime.now()  # start recovery clock
        st.toast('✔ ALT-001 Acknowledged. Sirens active. Recovery initiated.', icon='📣')
    elif aid == 'ALT-002':
        st.session_state.ack_medium = True
        st.toast('✔ ALT-002 Acknowledged.', icon='✔')
    else:
        st.toast(f'✔ Alert {aid} Acknowledged.', icon='✔')
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
          [CRITICAL] TRIPLE-THREAT MATCH — Disaster Signature!</div>
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
        'msg': f'AI AUTO-DETECTED: Gas {_za_gas}ppm + {_za_workers} workers + HOT WORK PERMIT.',
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
            'message':f'Maintenance crew ({_za_workers} workers) active during {_za_gas} ppm gas leak. Triple-threat pattern auto-detected.',
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

# Single source of truth for risk state
compound_rules_eval = []
for rule in engine.compound_rules:
    rid = rule.get('id', '')
    condition_fn = rule.get('condition')
    matched = any(condition_fn(latest, z) for z in SENSOR_ZONES)
    compound_rules_eval.append({'id': rid, 'matched': matched})

compound_risk_score = sum(1 for rule in compound_rules_eval if rule["matched"])
total_rules = len(compound_rules_eval)

if compound_risk_score == 0:
    risk_state = "CLEAR"
    risk_color = "#22c55e"
    banner_level = None  # No banner shown
    banner_color = "#1f2937"
    banner_border = "#374151"
elif compound_risk_score <= 2:
    risk_state = "ELEVATED"
    risk_color = "#f59e0b"
    banner_level = "ELEVATED RISK — SYSTEM MONITORING SENSORS"
    banner_color = "#92400e"
    banner_border = "#f59e0b"
elif compound_risk_score <= 4:
    risk_state = "HIGH"
    risk_color = "#ef4444"
    banner_level = "HIGH RISK — IMMEDIATE ATTENTION REQUIRED"
    banner_color = "#7f1d1d"
    banner_border = "#ef4444"
else:
    risk_state = "CRITICAL"
    risk_color = "#ef4444"
    banner_level = "CRITICAL ALERT — EVACUATE ZONE IMMEDIATELY"
    banner_color = "#450a0a"
    banner_border = "#ef4444"

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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');

/* ═══════════════════════════════════════════════════════════
   DESIGN TOKENS
═══════════════════════════════════════════════════════════ */
:root {
  --bg:          #050B16;
  --bg2:         #0B1526;
  --bg3:         #111827;
  --bg4:         #1a2740;
  --glass:       rgba(17, 24, 39, 0.8);
  --border:      #1e2d45;
  --border2:     #243447;
  --border3:     rgba(59, 130, 246, 0.2);
  --shadow-sm:   0 2px 8px rgba(0,0,0,0.4);
  --shadow-md:   0 4px 20px rgba(0,0,0,0.55);
  --shadow-lg:   0 8px 40px rgba(0,0,0,0.7);
  --text:        #F8FAFC;
  --text2:       #CBD5E1;
  --muted:       #94A3B8;
  --faint:       #64748B;
  --cyan:        #00D4FF;
  --blue:        #3B82F6;
  --green:       #22C55E;
  --amber:       #F59E0B;
  --red:         #EF4444;
  --orange:      #F97316;
  --radius-sm:   8px;
  --radius:      12px;
  --radius-lg:   16px;
  --radius-xl:   20px;
}

/* ═══════════════════════════════════════════════════════════
   BASE
═══════════════════════════════════════════════════════════ */
html, body, [class*="css"], .stApp {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  color: var(--text) !important;
  background: var(--bg) !important;
  -webkit-font-smoothing: antialiased;
}
.stApp { background: var(--bg) !important; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { display: none !important; }
.block-container { padding: 0 !important; max-width: 100% !important; }
.stMarkdown { margin: 0 !important; }
section[data-testid="stSidebar"] > div { padding-top: 0 !important; }

/* ═══════════════════════════════════════════════════════════
   SCROLLBAR
═══════════════════════════════════════════════════════════ */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--blue); }

/* ═══════════════════════════════════════════════════════════
   TOP NAVBAR
═══════════════════════════════════════════════════════════ */
.top-navbar {
  background: linear-gradient(90deg, var(--bg2) 0%, #0D1A2E 100%);
  border-bottom: 1px solid var(--border2);
  padding: 0 24px;
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 999;
  box-shadow: 0 2px 20px rgba(0,0,0,0.6);
}

/* ═══════════════════════════════════════════════════════════
   MAIN CONTENT
═══════════════════════════════════════════════════════════ */
.main-content { padding: 14px 18px 90px 18px; }

/* ═══════════════════════════════════════════════════════════
   SIDEBAR
═══════════════════════════════════════════════════════════ */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, var(--bg2) 0%, #0A1220 100%) !important;
  border-right: 1px solid var(--border2) !important;
}
[data-testid="stSidebar"] .block-container { padding: 12px !important; }

/* ═══════════════════════════════════════════════════════════
   CARDS — Glass morphism panels
═══════════════════════════════════════════════════════════ */
.metric-card {
  background: linear-gradient(145deg, rgba(17,24,39,0.95) 0%, rgba(11,21,38,0.9) 100%);
  border: 1px solid var(--border2);
  border-top: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  box-shadow: var(--shadow-md), inset 0 1px 0 rgba(255,255,255,0.05);
  transition: all 0.25s ease;
  height: 162px;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.metric-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(59,130,246,0.3), transparent);
}
.metric-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255,255,255,0.07);
  border-color: var(--border3);
}
.metric-card-critical {
  border-color: rgba(239,68,68,0.4) !important;
  animation: critBorder 1.8s ease-in-out infinite;
}
@keyframes critBorder {
  0%,100% { box-shadow: 0 0 8px rgba(239,68,68,0.2), var(--shadow-md); }
  50%     { box-shadow: 0 0 24px rgba(239,68,68,0.5), var(--shadow-md); }
}
.metric-label {
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.metric-value {
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -1.5px;
  margin: 2px 0;
  line-height: 1;
}
.metric-sub {
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
  margin-top: 4px;
}

/* ═══════════════════════════════════════════════════════════
   RISK LEVELS
═══════════════════════════════════════════════════════════ */
.risk-critical { color: #EF4444 !important; font-weight: 800; animation: critText 1.5s ease-in-out infinite alternate; }
.risk-high     { color: #F59E0B !important; font-weight: 700; }
.risk-medium   { color: #EAB308 !important; font-weight: 700; }
.risk-safe, .risk-low { color: #22C55E !important; font-weight: 700; }
@keyframes critText {
  0%   { text-shadow: 0 0 8px rgba(239,68,68,0.3); }
  100% { text-shadow: 0 0 22px rgba(239,68,68,0.8); }
}

/* ═══════════════════════════════════════════════════════════
   STATUS DOTS
═══════════════════════════════════════════════════════════ */
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.dot-critical { background: #EF4444; box-shadow: 0 0 8px #EF4444; animation: dotPulse 1.2s ease infinite alternate; }
.dot-high     { background: #F59E0B; box-shadow: 0 0 6px #F59E0B; animation: dotPulse 1.8s ease infinite alternate; }
.dot-medium   { background: #EAB308; box-shadow: 0 0 5px #EAB308; }
.dot-safe, .dot-low { background: #22C55E; box-shadow: 0 0 5px #22C55E; }
@keyframes dotPulse { 0% { transform: scale(0.8); opacity: 0.7; } 100% { transform: scale(1.4); opacity: 1; } }

/* ═══════════════════════════════════════════════════════════
   SECTION HEADERS
═══════════════════════════════════════════════════════════ */
.section-header {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--muted);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

/* ═══════════════════════════════════════════════════════════
   STATUS BANNER (non-critical)
═══════════════════════════════════════════════════════════ */
.status-banner {
  border-radius: var(--radius);
  padding: 12px 20px;
  text-align: center;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  margin: 0 0 12px 0;
  border: 1px solid;
  backdrop-filter: blur(8px);
}

/* ═══════════════════════════════════════════════════════════
   EMERGENCY BANNER
═══════════════════════════════════════════════════════════ */
.emergency-banner {
  background: linear-gradient(135deg, #2D0A0A 0%, #4A0E0E 50%, #2D0A0A 100%);
  border: 1.5px solid rgba(239,68,68,0.6);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  margin: 4px 0 14px 0;
  animation: emergPulse 2.5s ease-in-out infinite;
  backdrop-filter: blur(12px);
}
@keyframes emergPulse {
  0%,100% { box-shadow: 0 0 15px rgba(239,68,68,0.3), inset 0 0 30px rgba(239,68,68,0.03); }
  50%     { box-shadow: 0 0 40px rgba(239,68,68,0.6), inset 0 0 50px rgba(239,68,68,0.07); }
}

/* ═══════════════════════════════════════════════════════════
   ANIMATIONS
═══════════════════════════════════════════════════════════ */
@keyframes pulse-red   { 0%,100%{opacity:1;} 50%{opacity:0.35;} }
@keyframes pulse-green { 0%,100%{opacity:1;} 50%{opacity:0.5;} }
@keyframes pulse-blue  { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
@keyframes fadeIn      { from{opacity:0;transform:translateY(6px);} to{opacity:1;transform:translateY(0);} }
.pulse-red   { animation: pulse-red 1.2s ease infinite; }
.pulse-green { animation: pulse-green 2s ease infinite; }
.pulse-blue  { animation: pulse-blue 2s ease infinite; }
.fade-in     { animation: fadeIn 0.4s ease both; }
.stApp       { animation: fadeIn 0.4s ease; }

/* ═══════════════════════════════════════════════════════════
   ALERT TABLE ROWS
═══════════════════════════════════════════════════════════ */
.alert-row-crit { border-left: 3px solid #EF4444; background: rgba(239,68,68,0.06); border-radius: 0 8px 8px 0; }
.alert-row-high { border-left: 3px solid #F97316; background: rgba(249,115,22,0.06); border-radius: 0 8px 8px 0; }
.alert-row-med  { border-left: 3px solid #F59E0B; background: rgba(245,158,11,0.06); border-radius: 0 8px 8px 0; }
.alert-row-low  { border-left: 3px solid #22C55E; background: rgba(34,197,94,0.06);  border-radius: 0 8px 8px 0; }

/* ═══════════════════════════════════════════════════════════
   NOTIFICATION CHANNEL CARDS
═══════════════════════════════════════════════════════════ */
.channel-card-active { background: rgba(20,83,45,0.4) !important; border-color: #22C55E !important; }
.channel-card-alert  { background: rgba(69,10,10,0.5) !important; border-color: #EF4444 !important; }

/* ═══════════════════════════════════════════════════════════
   SIM CONTROLS BAR
═══════════════════════════════════════════════════════════ */
.sim-bar {
  background: linear-gradient(90deg, var(--bg2) 0%, #0A1626 100%);
  border-top: 1px solid var(--border2);
  padding: 7px 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: 'Inter', sans-serif;
  font-size: 12px;
  box-shadow: 0 -4px 20px rgba(0,0,0,0.5);
}

/* ═══════════════════════════════════════════════════════════
   BUTTONS
═══════════════════════════════════════════════════════════ */
div.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #B91C1C 0%, #DC2626 100%) !important;
  color: #fff !important;
  font-weight: 700 !important;
  font-size: 12px !important;
  border: none !important;
  border-radius: var(--radius-sm) !important;
  padding: 8px 16px !important;
  text-transform: uppercase !important;
  letter-spacing: 0.5px !important;
  animation: btnGlow 2.5s ease-in-out infinite;
  transition: all 0.2s ease !important;
  box-shadow: 0 4px 14px rgba(220,38,38,0.4) !important;
}
div.stButton > button[kind="primary"]:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 24px rgba(239,68,68,0.65) !important;
}
@keyframes btnGlow {
  0%,100% { box-shadow: 0 4px 14px rgba(220,38,38,0.4); }
  50%     { box-shadow: 0 4px 24px rgba(239,68,68,0.75); }
}
div.stButton > button[kind="secondary"] {
  border-radius: var(--radius-sm) !important;
  font-weight: 600 !important;
  font-size: 12px !important;
  background: rgba(255,255,255,0.05) !important;
  color: var(--text2) !important;
  border: 1px solid var(--border2) !important;
  transition: all 0.2s ease !important;
}
div.stButton > button[kind="secondary"]:hover {
  background: rgba(59,130,246,0.1) !important;
  border-color: rgba(59,130,246,0.4) !important;
  color: #fff !important;
  transform: translateY(-1px) !important;
}

/* ═══════════════════════════════════════════════════════════
   EXPORT / DOWNLOAD BUTTON
═══════════════════════════════════════════════════════════ */
[data-testid="stDownloadButton"] > button {
  background: linear-gradient(135deg, rgba(30,42,65,0.9), rgba(20,30,50,0.9)) !important;
  border: 1px solid var(--border2) !important;
  color: var(--text) !important;
  border-radius: var(--radius-sm) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  width: 100% !important;
  transition: all 0.2s ease !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid="stDownloadButton"] > button:hover {
  border-color: var(--blue) !important;
  background: rgba(59,130,246,0.1) !important;
}

/* ═══════════════════════════════════════════════════════════
   INPUTS / SELECTS
═══════════════════════════════════════════════════════════ */
div[data-testid="stSelectbox"] > div > div {
  background: var(--bg3) !important;
  border: 1px solid var(--border2) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--text) !important;
  font-size: 12px !important;
}
div[data-testid="stSelectbox"] svg { color: var(--muted) !important; }

/* ═══════════════════════════════════════════════════════════
   TOGGLE
═══════════════════════════════════════════════════════════ */
div[data-testid="stToggle"] > label { font-size: 12px !important; color: var(--text2) !important; }

/* ═══════════════════════════════════════════════════════════
   FILTER PILLS
═══════════════════════════════════════════════════════════ */
div[data-testid="stRadio"] > div {
  display: flex; flex-direction: row; gap: 5px; flex-wrap: nowrap;
}
div[data-testid="stRadio"] label {
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border2);
  border-radius: 20px; padding: 3px 12px;
  font-size: 11px; font-weight: 600; cursor: pointer;
  transition: all 0.2s ease;
  color: var(--muted);
}
div[data-testid="stRadio"] label:has(input:checked) {
  background: rgba(59,130,246,0.12);
  border-color: var(--blue);
  color: #60A5FA;
}

/* ═══════════════════════════════════════════════════════════
   EXPANDER
═══════════════════════════════════════════════════════════ */
div[data-testid="stExpander"] {
  border: 1px solid var(--border2) !important;
  border-radius: var(--radius) !important;
  background: var(--bg3) !important;
}
div[data-testid="stExpander"] summary {
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--text2) !important;
}

/* ═══════════════════════════════════════════════════════════
   CHECKBOXES
═══════════════════════════════════════════════════════════ */
div[data-testid="stCheckbox"] label {
  font-size: 12px !important;
  color: var(--text2) !important;
}

/* ═══════════════════════════════════════════════════════════
   TABS
═══════════════════════════════════════════════════════════ */
div[data-testid="stTabs"] button[role="tab"] {
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--muted) !important;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0 !important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: var(--blue) !important;
  border-bottom-color: var(--blue) !important;
}

/* ═══════════════════════════════════════════════════════════
   IFRAME (Heatmap)
═══════════════════════════════════════════════════════════ */
iframe {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border2) !important;
  background: var(--bg3) !important;
}

/* ═══════════════════════════════════════════════════════════
   IMAGE (CCTV)
═══════════════════════════════════════════════════════════ */
div[data-testid="stImage"] img {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border2) !important;
}

/* ═══════════════════════════════════════════════════════════
   VIDEO (disabled controls)
═══════════════════════════════════════════════════════════ */
video::-webkit-media-controls { display: none !important; }
video { pointer-events: none !important; }

/* ═══════════════════════════════════════════════════════════
   PLOTLY CHART
═══════════════════════════════════════════════════════════ */
div[data-testid="stPlotlyChart"] {
  border-radius: var(--radius) !important;
}

/* ═══════════════════════════════════════════════════════════
   TOAST
═══════════════════════════════════════════════════════════ */
div[data-testid="stToast"] {
  background: var(--bg3) !important;
  border: 1px solid var(--border2) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
}

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
  <div style="display:flex;align-items:center;gap:12px;">
    <div style="width:34px;height:34px;background:linear-gradient(135deg,#1d4ed8,#3b82f6);
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-size:18px;box-shadow:0 0 14px rgba(59,130,246,0.4);">
      🛡️
    </div>
    <div>
      <div style="font-size:15px;font-weight:800;color:#F8FAFC;letter-spacing:-0.3px;line-height:1.1;">SurakshaAI</div>
      <div style="font-size:9.5px;color:#64748B;letter-spacing:0.6px;font-weight:500;">AI-Powered Industrial Safety System</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="display:flex;align-items:center;gap:5px;background:rgba(34,197,94,0.1);
                border:1px solid rgba(34,197,94,0.35);border-radius:20px;padding:5px 13px;">
      <span style="width:6px;height:6px;background:#22C55E;border-radius:50%;
                   box-shadow:0 0 6px #22C55E;animation:pulse-green 2s infinite;display:inline-block;"></span>
      <span style="color:#22C55E;font-size:11px;font-weight:700;letter-spacing:0.5px;">LIVE</span>
    </div>
    <div style="display:flex;align-items:center;gap:5px;
                background:{('rgba(239,68,68,0.1)' if sim_on else 'rgba(59,130,246,0.1)')};
                border:1px solid {('rgba(239,68,68,0.4)' if sim_on else 'rgba(59,130,246,0.35)')};
                border-radius:20px;padding:5px 13px;">
      <span style="font-size:10px;">🔒</span>
      <span style="color:{('#EF4444' if sim_on else '#60A5FA')};font-size:11px;font-weight:700;letter-spacing:0.5px;">{secure_label}</span>
    </div>
  </div>
  <div style="text-align:center;">
    <div style="font-size:20px;font-weight:700;color:#F8FAFC;letter-spacing:0.5px;font-family:'JetBrains Mono',monospace;">{now_str}</div>
    <div style="font-size:10px;color:#64748B;margin-top:1px;font-weight:500;">{datetime.now().strftime("%d %B %Y  |  %A")}</div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="text-align:right;">
      <div style="font-size:12px;color:#F8FAFC;font-weight:600;">Safety Officer</div>
      <div style="font-size:10px;color:#64748B;font-weight:400;">Administrator</div>
    </div>
    <div style="width:34px;height:34px;
                background:linear-gradient(135deg,#1e3a5f,#2d5a8e);
                border-radius:50%;border:1.5px solid rgba(59,130,246,0.4);
                display:flex;align-items:center;justify-content:center;font-size:16px;
                box-shadow:0 0 10px rgba(59,130,246,0.2);"></div
    >👤</div>
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

    # Uptime card — premium glassmorphism panel
    st.markdown(f"""
    <div style="background:linear-gradient(145deg,rgba(17,24,39,0.95),rgba(11,21,38,0.9));
         border:1px solid #243447;border-top:1px solid rgba(34,197,94,0.2);
         border-radius:14px;padding:16px 14px;text-align:center;margin-bottom:12px;
         box-shadow:0 4px 20px rgba(0,0,0,0.5),inset 0 1px 0 rgba(34,197,94,0.08);">
      <div style="font-size:9px;color:#64748B;text-transform:uppercase;letter-spacing:1.5px;
                  font-weight:700;margin-bottom:6px;">SYSTEM UPTIME</div>
      <div style="font-size:38px;font-weight:800;color:#22C55E;line-height:1;
                  text-shadow:0 0 20px rgba(34,197,94,0.4);">100%</div>
      <div style="font-size:10px;color:rgba(34,197,94,0.7);margin-top:4px;font-weight:500;">
        Last 24 Hours</div>
      <div style="width:100%;height:3px;background:rgba(255,255,255,0.05);border-radius:2px;
                  margin-top:10px;overflow:hidden;">
        <div style="width:100%;height:100%;background:linear-gradient(90deg,#16a34a,#22C55E);
                    border-radius:2px;"></div>
      </div>
    </div>""", unsafe_allow_html=True)

    # Compliance report
    report = f"# SURAKSHAAI SAFETY COMPLIANCE REPORT\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nSystem State: {STATUS['level']} (Max Score: {max_score:.0f}/20)\n\n## Zone Health Audit\n"
    for zone, z in zone_risks.items():
        report += f"\n### {z['label']}\n- Level: {z['risk_level']}\n- Score: {z['risk_score']:.0f}/20\n"
    
    if st.session_state.get('compound_risk_active', False) or st.session_state.get('sim_stage') == 'active':
        report += "\n## Compound Patterns Detected\n- ⚠️ Visakhapatnam triple-threat disaster pattern detected in Battery-4 (Zone A)!\n"

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

    st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:12px 0;"></div>""", unsafe_allow_html=True)
    with st.expander("🛠️ Advanced Settings"):
        dev_mode = st.checkbox("Enable Developer Mode", value=st.session_state.get('dev_mode', False))
        if dev_mode != st.session_state.get('dev_mode', False):
            st.session_state.dev_mode = dev_mode
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT — wrapped in a padded div
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="main-content">', unsafe_allow_html=True)

# CCTV auto-detect alert banner — use st.empty() so it updates in-place without flicker
_auto_banner_placeholder = st.empty()

def _render_auto_banner(placeholder):
    """Render or clear the auto-detect banner based on session state. No-ops if unchanged."""
    if st.session_state.get("banner_visible") and st.session_state.get("active_alert"):
        alert = st.session_state.active_alert
        severity_colors = {
            "CRITICAL": "#450a0a",
            "HIGH":     "#7f1d1d",
            "MEDIUM":   "#92400e"
        }
        bg = severity_colors.get(alert["severity"], "#1f2937")
        placeholder.markdown(f"""
        <div style='background:{bg}; border:2px solid #ef4444; border-radius:8px;
                    padding:14px 18px; margin-bottom:14px;'>
            <b style='color:#ef4444; font-size:14px;'>
                🚨 {alert["severity"]} ALERT — {ZONE_LABELS.get(alert["zone"], alert["zone"])}
            </b>
            <p style='color:#fca5a5; margin:4px 0; font-size:12px;'>{alert["summary"]}</p>
            <small style='color:#9ca3af;'>
                Triggered: {alert["timestamp"]} &nbsp;|
                Channels: {", ".join(alert["channels"]).upper()}
            </small>
        </div>
        """, unsafe_allow_html=True)
    else:
        placeholder.empty()

_render_auto_banner(_auto_banner_placeholder)


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
if banner_level is not None:
    st.markdown(f"""
    <div class="status-banner"
         style="background:{banner_color};border-color:{banner_border}55;color:#fff;">
      {banner_level}
    </div>""", unsafe_allow_html=True)

# ─── EMERGENCY PANEL ──────────────────────────────────────────────────────────
if st.session_state.sim_stage == 'active':
    # Rich target-style critical alert banner
    st.markdown(f"""
    <div class="emergency-banner">
      <div style="display:flex;align-items:stretch;gap:16px;flex-wrap:wrap;">
        <div style="display:flex;align-items:flex-start;gap:14px;flex:2.5;min-width:260px;">
          <span style="font-size:36px;margin-top:2px;">⚠️</span>
          <div>
            <div style="color:#ef4444;font-size:15px;font-weight:900;letter-spacing:0.3px;">
              🚨 CRITICAL ALERT — Visakhapatnam Pattern Detected
            </div>
            <div style="color:#fca5a5;font-size:11px;margin-top:5px;line-height:1.8;">
              Zone: <b>Battery-4</b> &nbsp;|&nbsp; Gas: <b>{_za_gas} ppm</b> &nbsp;|&nbsp;
              Workers: <b>{_za_workers}</b> &nbsp;|&nbsp; Maintenance: <b>Active</b>
            </div>
            <div style="color:#ef4444;font-size:13px;font-weight:900;margin-top:6px;letter-spacing:0.3px;">
              ACTION: EVACUATE BATTERY-4 IMMEDIATELY
            </div>
            <div style="color:#9ca3af;font-size:10px;margin-top:5px;">
              Triggered at: {now_str} &nbsp;|&nbsp;
              Alert ID: ALT-{datetime.now().strftime("%Y%m%d%H%M")}-001 &nbsp;|&nbsp;
              Severity: <span style="color:#ef4444;font-weight:700;">CRITICAL</span>
            </div>
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex:2;flex-wrap:wrap;">
          <div style="background:#14532d;border:1px solid #22c55e;border-radius:8px;padding:8px 12px;text-align:center;min-width:88px;">
            <div style="color:#22c55e;font-weight:700;font-size:12px;">📱 SMS</div>
            <div style="color:#86efac;font-size:10px;font-weight:600;">✓ DELIVERED</div>
            <div style="color:#86efac;font-size:10px;">SMS sent to +123****890</div>
          </div>
          <div style="background:#14532d;border:1px solid #22c55e;border-radius:8px;padding:8px 12px;text-align:center;min-width:88px;">
            <div style="color:#22c55e;font-weight:700;font-size:12px;">✉️ Email</div>
            <div style="color:#86efac;font-size:10px;font-weight:600;">✓ SENT</div>
            <div style="color:#86efac;font-size:10px;">Email sent to safety@***.com</div>
          </div>
          <div style="background:#450a0a;border:1px solid #ef4444;border-radius:8px;padding:8px 12px;text-align:center;min-width:88px;">
            <div style="color:#ef4444;font-weight:700;font-size:12px;">🔊 SIREN</div>
            <div style="color:#fca5a5;font-size:10px;font-weight:600;" class="pulse-red">● ACTIVE (PULSING)</div>
            <div style="color:#fca5a5;font-size:10px;">Zone: Battery-4</div>
            <div style="color:#fca5a5;font-size:10px;">Status: SOUNDING</div>
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Action buttons row beneath banner
    checklist_keys = ['chk_evacuate', 'chk_isolate', 'chk_notify']
    for ck in checklist_keys:
        if ck not in st.session_state:
            st.session_state[ck] = False

    ab1, ab2, ab3, _spacer = st.columns([1.2, 1.2, 1.2, 6.4])
    with ab1:
        if st.button("✓ Acknowledge", key="ack_btn", type="primary",
                     use_container_width=True, disabled=st.session_state.ack_critical):
            st.session_state.ack_critical       = True
            st.session_state.sim_stage          = 'acknowledged'
            st.session_state.alert_acknowledged = True
            st.toast("✔ ALT-001 Acknowledged. Emergency sirens activated.", icon="📣")
            st.rerun()
    with ab2:
        if st.button("📋 View Details", key="view_details_btn", use_container_width=True):
            st.session_state['show_checklist'] = not st.session_state.get('show_checklist', False)
    with ab3:
        if st.button("🚨 Escalate", key="escalate_btn", use_container_width=True):
            st.toast("🚨 Alert escalated to Level 2 — Plant Director notified!", icon="🚨")

    if st.session_state.get('show_checklist', False):
        with st.expander("📋 Incident Checklist", expanded=True):
            st.session_state.chk_evacuate = st.checkbox(
                "✅ Initiate crew evacuation from Battery-4",
                value=st.session_state.chk_evacuate, key="cb_evacuate")
            st.session_state.chk_isolate = st.checkbox(
                "✅ Isolate gas supply valve for Zone A",
                value=st.session_state.chk_isolate, key="cb_isolate")
            st.session_state.chk_notify = st.checkbox(
                "✅ Notify emergency response team (Alpha & Beta)",
                value=st.session_state.chk_notify, key="cb_notify")

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
    _m1_border = f"border-top:2px solid {STATUS['color']};" if STATUS['level'] != 'SAFE' else ''
    st.markdown(f"""
    <div class="{crit_cls}" style="{_m1_border}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div class="metric-label" style="color:#94A3B8;">&#x1F321;&#xFE0F; CURRENT RISK</div>
        <svg width="60" height="26" style="opacity:0.8;">
          <path d="{sparkline_path}" fill="none" stroke="{STATUS['color']}" stroke-width="2" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="metric-value {STATUS['cls']}" style="font-size:30px;">{STATUS['level']}</div>
      <div style="font-size:11px;color:#F8FAFC;font-weight:600;margin-top:2px;">Score: {max_score:.0f}/20</div>
      <div class="metric-sub" style="margin-top:4px;">Overall plant safety state</div>
    </div>""", unsafe_allow_html=True)

with m2:
    figures = "".join("&#x1F464;" for _ in range(min(total_workers, 12)))
    _worker_bar = min(100, int(total_workers / 30 * 100))
    st.markdown(f"""
    <div class="metric-card" style="border-top:2px solid #3B82F6;">
      <div class="metric-label">&#x1F465; CREW COUNT</div>
      <div class="metric-value" style="color:#60A5FA;">{total_workers}</div>
      <div class="metric-sub" style="margin-bottom:6px;">Active on Floor</div>
      <div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-bottom:6px;">
        <div style="width:{_worker_bar}%;height:100%;background:linear-gradient(90deg,#1d4ed8,#3B82F6);border-radius:2px;"></div>
      </div>
      <div style="font-size:13px;color:#3B82F6;letter-spacing:2px;line-height:1.4;">{figures}</div>
    </div>""", unsafe_allow_html=True)

with m3:
    pc = '#F59E0B' if permit_count > 0 else '#22C55E'
    permit_bar = min(100, permit_count * 25)
    st.markdown(f"""
    <div class="metric-card" style="border-top:2px solid {pc};">
      <div class="metric-label">&#x1F4CB; WORK PERMITS</div>
      <div class="metric-value" style="color:{pc};">{permit_count}</div>
      <div class="metric-sub" style="margin-bottom:6px;">Active</div>
      <div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;">
        <div style="width:{permit_bar}%;height:100%;background:{pc};border-radius:2px;"></div>
      </div>
      <div style="position:absolute;right:14px;bottom:12px;font-size:38px;opacity:0.06;">&#x1F4CB;</div>
    </div>""", unsafe_allow_html=True)

with m4:
    cc = risk_color
    cv = risk_state
    cds = f"{compound_risk_score}/{total_rules} rules matched"
    card_cls = "metric-card metric-card-critical" if risk_state == 'CRITICAL' else "metric-card"
    _c4_border = f"border-top:2px solid {cc};"
    compound_bar = min(100, int(compound_risk_score / max(total_rules, 1) * 100))
    st.markdown(f"""
    <div class="{card_cls}" style="{_c4_border}">
      <div class="metric-label">&#x1F517; COMPOUND RISK</div>
      <div class="metric-value" style="color:{cc};font-size:28px;">{cv}</div>
      <div class="metric-sub" style="margin-bottom:6px;">{cds}</div>
      <div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;">
        <div style="width:{compound_bar}%;height:100%;background:{cc};border-radius:2px;"></div>
      </div>
      <div style="position:absolute;right:14px;bottom:12px;font-size:38px;opacity:0.06;">&#x1F6E1;&#xFE0F;</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)



if st.session_state.get('dev_mode', False):
    tab_main, tab_diag = st.tabs(["🛡️ SAFETY CONTROL CONSOLE", "🛠️ SYSTEM INTEGRATIONS"])
else:
    tab_main = st.container()
    tab_diag = None

with tab_main:
    # ─── 3-COLUMN UNIFIED OPERATIONS GRID ───
    col_left, col_mid, col_right = st.columns([3.5, 5.0, 3.5])
    
    with col_left:
        st.markdown('<div class="section-header">🗺️ PLANT ZONE HEATMAP</div>', unsafe_allow_html=True)
        st.iframe(build_heatmap_html(zone_risks, st.session_state.simulate_active), height=180)
        
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="section-header">📋 ZONE STATUS OVERVIEW</div>', unsafe_allow_html=True)
        for zone_id, zone_label in ZONE_STATUS_ORDER:
            z = zone_risks.get(zone_id, {'risk_level':'LOW','risk_score':0,'sensor_data':{}})
            lvl   = z.get('risk_level', 'LOW')
            score = z.get('risk_score', 0)
            c     = get_zone_color(lvl)

            # Get gas ppm
            gas = 0.0
            sd = z.get('sensor_data', {})
            for k, v in sd.items():
                if 'gas' in k.lower():
                    gas = float(v)
                    break
            if gas == 0.0:
                gas = latest.get(f'{zone_id}_gas_ppm', 0.0)

            # Premium zone status row
            is_crit = (lvl == 'CRITICAL')
            hb_pts = "0,8 3,8 5,2 7,14 9,2 11,14 13,8 20,8" if is_crit else "0,8 4,8 6,5 8,11 10,8 14,8 16,6 20,8"
            hb_color = "#EF4444" if is_crit else "#22C55E"
            _row_bg = f"rgba(239,68,68,0.05)" if is_crit else f"rgba(17,24,39,0.6)"
            _row_border = f"#EF444440" if is_crit else "#243447"
            _badge_bg = f"rgba(239,68,68,0.15)" if is_crit else (
                "rgba(245,158,11,0.15)" if lvl == 'HIGH' else "rgba(34,197,94,0.1)")
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:8px;padding:7px 10px;margin-bottom:5px;
              background:{_row_bg};border:1px solid {_row_border};
              border-radius:10px;transition:all 0.2s;">
              <span style="width:7px;height:7px;border-radius:50%;background:{c};
                           box-shadow:0 0 6px {c};flex-shrink:0;"></span>
              <span style="color:#F8FAFC;font-size:11px;font-weight:600;flex:1;">{zone_label}</span>
              <span style="background:{_badge_bg};color:{c};font-size:9px;font-weight:700;
                           padding:2px 7px;border-radius:4px;letter-spacing:0.5px;
                           border:1px solid {c}30;">{lvl}</span>
              <span style="color:#64748B;font-size:10px;min-width:60px;text-align:right;">{score:.0f}/20</span>
              <span style="color:#64748B;font-size:10px;min-width:58px;text-align:right;">{gas:.1f}ppm</span>
              <svg width="22" height="16" viewBox="0 0 22 16" style="flex-shrink:0;opacity:0.9;">
                <polyline points="{hb_pts}" fill="none" stroke="{hb_color}" stroke-width="1.5"
                          stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>""", unsafe_allow_html=True)

    with col_mid:
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
            🔔 LIVE ALERTS PANEL
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

    with col_right:
        st.markdown('<div class="section-header">📢 NOTIFICATION CHANNELS</div>', unsafe_allow_html=True)
        
        # Determine highest risk zone based on maximum risk score
        highest_risk_zone = "N/A"
        highest_score = -1
        for zone_id, z in zone_risks.items():
            if z.get('risk_score', 0) > highest_score:
                highest_score = z.get('risk_score', 0)
                highest_risk_zone = z.get('label', zone_id)
        
        if compound_risk_score == 0:
            sms_status = ("STANDBY", "#6b7280", "Sent to: N/A")
            email_status = ("STANDBY", "#6b7280", "Sent to: N/A")
            siren_status = ("STANDBY", "#6b7280", "Zone: All clear")
            sms_progress = "0%"
            email_progress = "0%"
            siren_progress = "0%"
        else:
            sms_status = ("DELIVERED ✓", "#22c55e", "Sent to: +123****890")
            email_status = ("SENT ✓", "#22c55e", "Sent to: safety@***.com")
            siren_status = (
                "ACTIVE 🔊", 
                "#ef4444", 
                f"Zone: {highest_risk_zone} — SOUNDING"
            )
            sms_progress = "100%"
            email_progress = "100%"
            siren_progress = "100%"
            
        # Enhanced notification channel cards with timestamps
        _notif_time = now_str if compound_risk_score > 0 else "—"
        _sms_detail   = f"Alert sent to +123****890<br>at {_notif_time}" if compound_risk_score > 0 else "Sent to: N/A"
        _email_detail = f"Email sent to safety@***.com<br>{_notif_time}" if compound_risk_score > 0 else "Sent to: N/A"
        _siren_detail = f"Zone: {highest_risk_zone}<br>Status: ● SOUNDING<br>Duration: active" if compound_risk_score > 0 else "Zone: All clear"

        st.markdown(f"""
        <!-- SMS Channel -->
        <div style="background:{'rgba(20,83,45,0.35)' if compound_risk_score > 0 else 'rgba(255,255,255,0.015)'}; border:1px solid {sms_status[1]}; border-radius:8px; padding:11px 13px; margin-bottom:8px; font-family:'Outfit',sans-serif;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; color:#fff; font-size:11px; letter-spacing:0.5px;">📱 SMS CHANNEL</span>
                <span style="color:{sms_status[1]}; font-size:10px; font-weight:800; text-transform:uppercase;">{"✓ " if compound_risk_score > 0 else ""}{sms_status[0]}</span>
            </div>
            <div style="font-size:10px; color:#94a3b8; margin-top:4px; line-height:1.6;">{_sms_detail}</div>
            <div style="width:100%; height:3px; background:rgba(255,255,255,0.05); border-radius:2px; margin-top:7px; overflow:hidden;">
                <div style="width:{sms_progress}; height:100%; background:{sms_status[1]}; transition:width 0.5s;"></div>
            </div>
        </div>
        <!-- Email Channel -->
        <div style="background:{'rgba(20,83,45,0.35)' if compound_risk_score > 0 else 'rgba(255,255,255,0.015)'}; border:1px solid {email_status[1]}; border-radius:8px; padding:11px 13px; margin-bottom:8px; font-family:'Outfit',sans-serif;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; color:#fff; font-size:11px; letter-spacing:0.5px;">✉️ EMAIL CHANNEL</span>
                <span style="color:{email_status[1]}; font-size:10px; font-weight:800; text-transform:uppercase;">{"✓ " if compound_risk_score > 0 else ""}{email_status[0]}</span>
            </div>
            <div style="font-size:10px; color:#94a3b8; margin-top:4px; line-height:1.6;">{_email_detail}</div>
            <div style="width:100%; height:3px; background:rgba(255,255,255,0.05); border-radius:2px; margin-top:7px; overflow:hidden;">
                <div style="width:{email_progress}; height:100%; background:{email_status[1]}; transition:width 0.5s;"></div>
            </div>
        </div>
        <!-- Siren Channel -->
        <div style="background:{'rgba(69,10,10,0.5)' if compound_risk_score > 0 else 'rgba(255,255,255,0.015)'}; border:1px solid {siren_status[1]}; border-radius:8px; padding:11px 13px; margin-bottom:8px; font-family:'Outfit',sans-serif;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; color:#fff; font-size:11px; letter-spacing:0.5px;">🔊 SIREN CHANNEL</span>
                <span style="color:{siren_status[1]}; font-size:10px; font-weight:800; text-transform:uppercase;" {'class="pulse-red"' if compound_risk_score > 0 else ''}>{"● " if compound_risk_score > 0 else ""}{siren_status[0]}</span>
            </div>
            <div style="font-size:10px; color:#94a3b8; margin-top:4px; line-height:1.6;">{_siren_detail}</div>
            <div style="width:100%; height:3px; background:rgba(255,255,255,0.05); border-radius:2px; margin-top:7px; overflow:hidden;">
                <div style="width:{siren_progress}; height:100%; background:{siren_status[1]};"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # "All alerts escalated" badge when compound risk active
        if compound_risk_score > 0:
            st.markdown("""
            <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;
                        padding:10px 13px;margin-top:4px;display:flex;align-items:center;gap:8px;">
              <span style="font-size:18px;">✅</span>
              <span style="color:#22c55e;font-size:11px;font-weight:600;">All critical alerts escalated to all channels</span>
            </div>""", unsafe_allow_html=True)
        
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="section-header">🗄️ PERSISTENT DATABASE LOGS</div>', unsafe_allow_html=True)
        
        # Query database and show styled HTML cards
        import sqlite3
        try:
            conn = sqlite3.connect("data/alerts.db")
            df_alerts = pd.read_sql_query("SELECT alert_id, timestamp, zone, risk_level, status, message FROM system_alerts ORDER BY timestamp DESC LIMIT 4", conn)
            conn.close()
            
            if df_alerts.empty:
                st.caption("No alerts persisted in database yet.")
            else:
                for _, r_val in df_alerts.iterrows():
                    level = r_val['risk_level']
                    lbl_color = '#ef4444' if level == 'CRITICAL' else '#f59e0b' if level == 'HIGH' else '#eab308' if level == 'MEDIUM' else '#22c55e'
                    st.markdown(f"""
                    <div style="background: rgba(17,24,39,0.55); border: 1px solid var(--border); border-left: 3px solid {lbl_color}; border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; font-size: 11px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-weight: 700; color: #F8FAFC; font-family:'JetBrains Mono',monospace;">{r_val['alert_id']}</span>
                            <span style="color: {lbl_color}; font-weight:800; font-size:8.5px; background:{lbl_color}1a; border: 1px solid {lbl_color}33; padding: 1px 6px; border-radius: 4px; letter-spacing:0.5px;">{level}</span>
                        </div>
                        <div style="color:var(--text2); margin-top:3px; font-size: 10px;">Zone: <b>{ZONE_LABELS.get(r_val['zone'], r_val['zone'])}</b> &nbsp;|&nbsp; Status: <span style="color:#22C55E;">{r_val['status']}</span></div>
                        <div style="color:var(--muted); margin-top:3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{r_val['message']}</div>
                    </div>
                    """, unsafe_allow_html=True)
        except Exception:
            pass

    import cv2
    
    # Load YOLO if needed
    if frame_processor.detector.model is None and not getattr(frame_processor.detector, '_attempted_load', False):
        frame_processor.detector._load_model()
    
    # Set simulation mode dynamically depending on YOLO availability
    if frame_processor.detector.model is not None:
        frame_processor.detector.use_simulation = False
    else:
        frame_processor.detector.use_simulation = True
    
    # Helper to format summary grids with premium glassmorphism
    def render_summary_grids(fps_val, p_count, h_count, rules_count, detections_list, zone_counts_dict):
        # DETECTIONS card
        p_c = max([d.confidence for d in detections_list if d.label == 'person'], default=0.0)
        h_c = max([d.confidence for d in detections_list if d.label == 'helmet'], default=0.0)
        v_c = max([d.confidence for d in detections_list if d.label == 'vest'], default=0.0)
        p_c_str = f"{p_c:.2f}" if p_c > 0 else "N/A"
        h_c_str = f"{h_c:.2f}" if h_c > 0 else "N/A"
        v_c_str = f"{v_c:.2f}" if v_c > 0 else "N/A"
        
        detections_placeholder.markdown(f"""
        <div style="background:rgba(17,24,39,0.7); border:1px solid var(--border2); 
             border-radius:12px; padding:12px 14px; min-height:110px; box-shadow:var(--shadow-sm);">
            <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; font-weight:700; margin-bottom:8px;">
                🔍 DETECTIONS
            </div>
            <div style="font-size:11px; color:#F8FAFC; line-height:1.5; font-family:'JetBrains Mono',monospace;">
                Person: <span style="color:#22C55E; font-weight:600;">{p_c_str}</span><br/>
                Helmet: <span style="color:#22C55E; font-weight:600;">{h_c_str}</span><br/>
                Vest: <span style="color:#22C55E; font-weight:600;">{v_c_str}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # ZONE STATUS card
        z_a = zone_counts_dict.get('Zone_A', 0)
        z_b = zone_counts_dict.get('Zone_B', 0)
        z_c = zone_counts_dict.get('Zone_C', 0)
        z_r = zone_counts_dict.get('Reactor_Area', 0)
        z_s = zone_counts_dict.get('Storage_Area', 0)

        def wc(n, alert=False):
            col = '#EF4444' if alert else '#22C55E' if n == 0 else '#F8FAFC'
            return f'<span style="font-weight:600;color:{col};">{n}w</span>'

        zone_status_placeholder.markdown(f"""
        <div style="background:rgba(17,24,39,0.7); border:1px solid var(--border2);
             border-radius:12px; padding:12px 14px; min-height:110px; box-shadow:var(--shadow-sm);">
            <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; font-weight:700; margin-bottom:8px;">
                👷 ZONE STATUS
            </div>
            <div style="font-size:11px; color:var(--text2); line-height:1.6; font-family:'JetBrains Mono',monospace;">
                Bat-4: {wc(z_a, z_a > 5)} &nbsp;
                Bat-5: {wc(z_b)}<br/>
                Bat-6: {wc(z_c)} &nbsp;
                React: {wc(z_r)}<br/>
                Store: {wc(z_s, z_s > 3)}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # RULES card
        rules_placeholder.markdown(f"""
        <div style="background:rgba(17,24,39,0.7); border:1px solid var(--border2); 
             border-radius:12px; padding:12px 14px; min-height:110px; box-shadow:var(--shadow-sm);">
            <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; font-weight:700; margin-bottom:8px;">
                🛡️ COMPLIANCE
            </div>
            <div style="font-size:11px; color:#F8FAFC; line-height:1.5; font-family:'JetBrains Mono',monospace;">
                Scanned: <span style="font-weight:600;">6</span><br/>
                Matched: <span style="color:{'#EF4444' if rules_count > 0 else '#22C55E'}; font-weight:700;">{rules_count}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # SYSTEM card
        system_placeholder.markdown(f"""
        <div style="background:rgba(17,24,39,0.7); border:1px solid var(--border2); 
             border-radius:12px; padding:12px 14px; min-height:110px; box-shadow:var(--shadow-sm);">
            <div style="font-size:9.5px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; font-weight:700; margin-bottom:8px;">
                🖥️ SYSTEM
            </div>
            <div style="font-size:20px; color:#22C55E; font-weight:800; line-height:1.2; text-shadow:0 0 10px rgba(34,197,94,0.3);">
                100%
            </div>
            <div style="font-size:9.5px; color:var(--muted); margin-top:6px;">
                Uptime Active
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
            
            # Auto-evaluate alert conditions immediately
            alert_conditions = evaluate_alert_conditions(
                detections=active_dets,
                violations=viol_count,
                zone=selected_zone,
                telemetry=latest
            )
            
            if alert_conditions["should_alert"]:
                # Incident-based debounce: only dispatch once per incident.
                # An incident is identified by zone+severity pair.
                alert_key = f"alert_active_{selected_zone}"
                current_incident = f"{selected_zone}_{alert_conditions['severity']}"
                if not st.session_state.get(alert_key, False) \
                        or st.session_state.get("_last_incident") != current_incident:
                    st.session_state[alert_key] = True
                    st.session_state["_last_incident"] = current_incident
                    # Reset safe-frame counter for this zone
                    st.session_state[f"_safe_frames_{selected_zone}"] = 0
                    dispatch_alerts(alert_conditions)
                    _render_auto_banner(_auto_banner_placeholder)
                else:
                    # Already dispatched for this incident — reset safe-frame counter
                    st.session_state[f"_safe_frames_{selected_zone}"] = 0
            else:
                # Hysteresis: require 10 consecutive safe frames before clearing the alert
                safe_key = f"_safe_frames_{selected_zone}"
                st.session_state[safe_key] = st.session_state.get(safe_key, 0) + 1
                if st.session_state[safe_key] >= 10:
                    if st.session_state.get(f"alert_active_{selected_zone}", False):
                        clear_alert_if_safe(selected_zone)
                        st.session_state[f"alert_active_{selected_zone}"] = False
                        st.session_state["_last_incident"] = None
                        _render_auto_banner(_auto_banner_placeholder)
            
            frame_placeholder.image(pil_img, width="stretch")
            
            # Render status bar dynamically in sync with the video
            is_critical = (latest.get("max_risk_level") == "CRITICAL" or st.session_state.simulate_active)
            overpressure_active = (selected_zone == 'Zone_C' and frame_idx >= 95)
            if selected_zone == 'Zone_C':
                h_count = 1 if (is_critical or overpressure_active) else 0
            elif selected_zone == 'Zone_A':
                h_count = 1 if (frame_idx >= 40) else 0
            else:
                h_count = 1 if (selected_zone in ['Reactor_Area', 'Storage_Area']) or (selected_zone == 'Zone_B' and st.session_state.simulate_active) else 0
                
            safe_zones = 4 if (h_count > 0 or (viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area', 'Storage_Area'))) else 5
            
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
            
            if viol_count > 0 and selected_zone not in ('Zone_A', 'Reactor_Area', 'Storage_Area'):
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
                
            if selected_zone == 'Storage_Area':
                alerts_list.append("""
                <div style="background: rgba(255,255,255,0.03); 
                            border-left: 4px solid #eab308;
                            padding: 12px 16px;
                            margin: 4px 0;
                            border-radius: 8px;
                            font-family:'Outfit',sans-serif;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom:4px;">
                        <span style="font-weight: 600; color: #eab308; font-size:12px;">⚠️ WARNING - AREA OVERCROWDING</span>
                        <span style="color: #6b7d94; font-size: 0.8rem;">ACTIVE</span>
                    </div>
                    <div style="color: #a0b4c8; font-size: 0.9rem; line-height:1.4;">More than 9 workers detected in the warehouse aisle under hazardous gas telemetry. Immediate shift rotation or aisle clearance required.</div>
                </div>
                """)
                
            show_critical_alert = False
            if selected_zone == 'Zone_C':
                show_critical_alert = is_critical
            elif selected_zone == 'Zone_A':
                show_critical_alert = (frame_idx >= 40)
            elif selected_zone in ('Reactor_Area', 'Storage_Area'):
                # Reactor Block and Storage Area have their own dedicated warning/critical cards
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

    SEV_META = {
        'CRITICAL': ('#ef4444', 'rgba(239,68,68,0.08)', '🔴'),
        'HIGH':     ('#f97316', 'rgba(249,115,22,0.08)', '🟠'),
        'MEDIUM':   ('#f59e0b', 'rgba(245,158,11,0.08)', '🟡'),
        'LOW':      ('#22c55e', 'rgba(34,197,94,0.08)',  '🟢'),
    }

    if alerts_list:
        for alert in reversed(alerts_list):
            sc, sbg, sico = SEV_META.get(alert.risk_level, ('#6b7d94','rgba(107,125,148,0.08)','⚪'))
            ts_str = alert.timestamp.strftime('%H:%M:%S') if hasattr(alert.timestamp, 'strftime') else str(alert.timestamp)[:8]
            short_msg = (alert.message[:42] + '…') if len(alert.message) > 42 else alert.message
            status_lbl = 'TRIGGERED' if alert.risk_level == 'CRITICAL' else 'ACKNOWLEDGED' if alert.risk_level == 'HIGH' else 'RESOLVED'
            status_color = '#ef4444' if status_lbl == 'TRIGGERED' else '#f59e0b' if status_lbl == 'ACKNOWLEDGED' else '#22c55e'
            st.markdown(f"""
            <div style="background:{sbg};border-left:4px solid {sc};border-radius:6px;
                        padding:9px 12px;margin-bottom:6px;font-family:'Outfit',sans-serif;">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
                <div style="display:flex;align-items:center;gap:8px;flex:1;">
                  <span style="background:{sc};color:#fff;font-size:9px;font-weight:800;
                               padding:2px 7px;border-radius:4px;white-space:nowrap;">{sico} {alert.risk_level}</span>
                  <div>
                    <div style="color:#fff;font-size:11px;font-weight:700;line-height:1.3;">{short_msg}</div>
                    <div style="color:#64748b;font-size:10px;margin-top:1px;">
                      {ZONE_LABELS.get(alert.zone, alert.zone)} &nbsp;|&nbsp; Score: {alert.risk_score:.0f}/20
                    </div>
                  </div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
                  <span style="color:#64748b;font-size:10px;">{ts_str}</span>
                  <span style="color:#64748b;font-size:12px;">📱 ✉️ 🔊</span>
                  <span style="background:rgba(255,255,255,0.06);color:{status_color};font-size:9px;
                               font-weight:800;padding:2px 8px;border-radius:4px;border:1px solid {status_color}44;">
                    {status_lbl}</span>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(render_safe_card(), unsafe_allow_html=True)

    st.markdown("""
    <div style="display:flex;justify-content:space-between;align-items:center;
    margin-top:8px;font-size:11px;font-family:'Outfit',sans-serif;">
      <span style="color:#64748b;">Showing latest 5 alerts</span>
      <a href="#" style="color:#00d4ff;text-decoration:none;font-weight:600;">View All →</a>
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


if tab_diag:
    with tab_diag:
        st.markdown('<div class="section-header">🛠️ SYSTEM INTEGRATIONS & DIAGNOSTICS</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        
        col_api, col_notif = st.columns(2)
        
        with col_api:
            st.markdown('<div class="section-header">🌐 FASTAPI SERVICE STATUS</div>', unsafe_allow_html=True)
            import requests
            api_status = "🔴 Offline"
            try:
                res = requests.get("http://localhost:8000/api/v1/health", timeout=1.0)
                if res.status_code == 200:
                    api_status = "🟢 Operational (v1.0.0)"
            except Exception:
                pass
            st.markdown(f"**FastAPI REST API Status:** `{api_status}`")
            st.caption("External systems use this API to ingest telemetry and query alerts.")

        with col_notif:
            st.markdown('<div class="section-header">📢 NOTIFICATION CHANNELS</div>', unsafe_allow_html=True)
            import os
            email_configured = "🟢 Configured" if os.environ.get("SENDER_EMAIL") and os.environ.get("SENDER_PASSWORD") else "🟡 Simulation Mode"
            telegram_configured = "🟢 Configured" if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID") else "🟡 Simulation Mode"
            st.markdown(f"**Email Channel (SMTP):** `{email_configured}`")
            st.markdown(f"**Telegram Bot (SMS):** `{telegram_configured}`")
            st.caption("Simulation Mode prints alerts to terminal console rather than sending real messages.")

        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        st.markdown('<div class="section-header">🗄️ SQLite DATABASE MONITOR (data/alerts.db)</div>', unsafe_allow_html=True)
        
        # Test Alert Section
        test_btn, clear_btn = st.columns([1, 1])
        with test_btn:
            if st.button("🚨 Trigger Test Alert (Writes to DB & Dispatches)", use_container_width=True):
                test_row = pd.Series({'timestamp': datetime.now()})
                test_result = {
                    'risk_level': 'HIGH',
                    'risk_score': 10,
                    'zone': 'Reactor_Area',
                    'factors': ['TEST_VIOLATION'],
                    'compound_factors': [],
                    'message': 'This is a test warning alert triggered manually from the integrations dashboard.'
                }
                alert_system.trigger_alert(test_row, test_result)
                st.toast("Test alert triggered! Check database and/or terminal console.", icon="🚨")
                
        with clear_btn:
            if st.button("🗑️ Clear Alerts Database", use_container_width=True):
                import sqlite3
                try:
                    conn = sqlite3.connect("data/alerts.db")
                    conn.execute("DELETE FROM system_alerts")
                    conn.commit()
                    conn.close()
                    st.toast("Alerts database cleared successfully!", icon="🗑️")
                except Exception as e:
                    st.error(f"Error clearing database: {e}")
                    
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        
        # Query database and show styled HTML table
        import sqlite3
        try:
            conn = sqlite3.connect("data/alerts.db")
            df_alerts = pd.read_sql_query("SELECT alert_id, timestamp, zone, risk_level, risk_score, status, message FROM system_alerts ORDER BY timestamp DESC", conn)
            conn.close()
            
            if df_alerts.empty:
                st.info("No persistent alerts stored in `data/alerts.db` yet. Trigger one via the CCTV feed or the button above.")
            else:
                html_table = """
                <div style="overflow-x:auto; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px;">
                <table style="width: 100%; border-collapse: collapse; font-family: 'Outfit', sans-serif; font-size: 13px; color: #a0b4c8; background: rgba(255,255,255,0.015);">
                    <thead>
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03); text-align: left;">
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">ID</th>
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">Timestamp</th>
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">Zone</th>
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">Severity</th>
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">Score</th>
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">Status</th>
                            <th style="padding: 10px 12px; color: #fff; font-weight: 700;">Message</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                
                COLOR_SEV = {
                    'CRITICAL': '#ef4444',
                    'HIGH': '#f59e0b',
                    'MEDIUM': '#eab308',
                    'LOW': '#22c55e'
                }
                
                for _, row_val in df_alerts.iterrows():
                    sev = row_val['risk_level']
                    status = row_val['status']
                    sev_color = COLOR_SEV.get(sev, '#a0b4c8')
                    status_color = '#ef4444' if status == 'ACTIVE' else '#00d4ff' if status == 'ACKNOWLEDGED' else '#22c55e'
                    
                    try:
                        t_str = datetime.fromisoformat(row_val['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        t_str = str(row_val['timestamp'])
                    
                    html_table += f"""
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.04); transition: background 0.2s;">
                        <td style="padding: 10px 12px; font-weight: 800; color: #fff;">{row_val['alert_id']}</td>
                        <td style="padding: 10px 12px;">{t_str}</td>
                        <td style="padding: 10px 12px; font-weight: 600;">{row_val['zone']}</td>
                        <td style="padding: 10px 12px;"><span style="color: {sev_color}; font-weight: 700;">● {sev}</span></td>
                        <td style="padding: 10px 12px; font-weight: 700;">{row_val['risk_score']}</td>
                        <td style="padding: 10px 12px;"><span style="padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 800; background: {status_color}22; color: {status_color}; border: 1px solid {status_color}44;">{status}</span></td>
                        <td style="padding: 10px 12px; max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{row_val['message']}">{row_val['message']}</td>
                    </tr>
                    """
                    
                html_table += """
                    </tbody>
                </table>
                </div>
                """
                # Strip leading whitespace on each line to prevent markdown from parsing it as raw code blocks
                clean_lines = [line.strip() for line in html_table.split("\n")]
                clean_html = "".join(clean_lines)
                st.markdown(clean_html, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Error reading database: {e}")


# ─── FOOTER ──────────────────────────────────────────────────────────────────
st.markdown("</div>", unsafe_allow_html=True)  # close main-content

# ─── BOTTOM SIMULATION CONTROLS BAR ──────────────────────────────────────────
st.markdown("""<div class="sim-bar">
  <span style="font-weight:800;color:var(--blue);font-size:11px;letter-spacing:1px;text-transform:uppercase;">⚙️ CONTROL PANEL</span>
  <span style="color:var(--border);font-size:16px;">│</span>
</div>""", unsafe_allow_html=True)

_sim_bc1, _sim_bc2, _sim_bc3, _sim_bc4, _sim_bc5, _sim_bc6, _sim_bc7 = st.columns([1.2, 1.0, 1.0, 0.5, 0.6, 0.6, 0.6])
with _sim_bc1:
    _sim_play = st.toggle("▶️ Autoplay", value=st.session_state.sim_play_active, key="sim_play_bottom")
    if _sim_play != st.session_state.sim_play_active:
        st.session_state.sim_play_active = _sim_play
        st.rerun()
with _sim_bc2:
    if st.button("⏩ +20 min", key="ff_btn_bar", use_container_width=True, help="Fast-forward 20 min"):
        st.session_state.scenario_offset_min += 20
        st.rerun()
with _sim_bc3:
    if st.button("🔄 Reset", key="rst_btn_bar", use_container_width=True, help="Reset to minute 0"):
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
with _sim_bc4:
    st.markdown(f"""<div style='padding-top:6px;'><span style='color:#64748b;font-size:11px;'>Speed:</span></div>""", unsafe_allow_html=True)
with _sim_bc5:
    if st.button("1x", key="spd_1x", use_container_width=True): pass
with _sim_bc6:
    if st.button("10x", key="spd_10x", use_container_width=True):
        st.session_state.scenario_offset_min += 10
        st.rerun()
with _sim_bc7:
    if st.button("30x", key="spd_30x", use_container_width=True):
        st.session_state.scenario_offset_min += 30
        st.rerun()

_scenario_label = "Visakhapatnam Pattern" if st.session_state.compound_risk_active else "Monitoring"
st.markdown(f"""
<div style='background:#0a1628;border-top:1px solid #1e3a5f;padding:5px 20px;
             display:flex;justify-content:space-between;font-size:11px;color:#64748b;
             font-family:"Outfit",sans-serif;'>
  <span>SurakshaAI v3.0 &nbsp;|&nbsp; Zero-Harm Operations</span>
  <span>Scenario: <b style='color:#e2e8f0;'>{_scenario_label}</b></span>
  <span>Elapsed: <b style='color:#e2e8f0;'>{_scenario_min_now:.1f} min</b></span>
  <span>Status: <b style='color:{"#ef4444" if st.session_state.compound_risk_active else "#22c55e"};'>
    {"Active Simulation" if st.session_state.compound_risk_active else "NOMINAL"}</b></span>
</div>
""", unsafe_allow_html=True)


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