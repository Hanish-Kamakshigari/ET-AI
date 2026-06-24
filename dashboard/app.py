# -*- coding: utf-8 -*-
"""
SurakshaAI v3.0 — Industrial Safety Intelligence Dashboard
Hackathon Edition | Preventing Industrial Tragedies through AI
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import time

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


# ─── SVG HEATMAP ─────────────────────────────────────────────────────────────
def build_heatmap_html(zone_risks: Dict, simulate_active: bool) -> str:
    COLORS = {
        'CRITICAL':{'fill':'#ef4444','stroke':'#dc2626','text':'#ffffff','glow':'rgba(239,68,68,0.7)'},
        'HIGH':    {'fill':'#f59e0b','stroke':'#d97706','text':'#ffffff','glow':'rgba(245,158,11,0.6)'},
        'MEDIUM':  {'fill':'#eab308','stroke':'#ca8a04','text':'#1a1100','glow':'rgba(234,179,8,0.5)'},
        'LOW':     {'fill':'#22c55e','stroke':'#16a34a','text':'#ffffff','glow':'rgba(34,197,94,0.4)'},
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
            label_svg = f'<text x="{cx:.1f}" y="{cy-14:.1f}" text-anchor="middle" fill="{c["text"]}" font-family="Outfit,sans-serif" font-size="12" font-weight="700">{label}</text>'
        else:
            label_svg  = f'<text x="{cx:.1f}" y="{cy-22:.1f}" text-anchor="middle" fill="{c["text"]}" font-family="Outfit,sans-serif" font-size="11" font-weight="700">{parts[0]}</text>'
            label_svg += f'<text x="{cx:.1f}" y="{cy-9:.1f}"  text-anchor="middle" fill="{c["text"]}" font-family="Outfit,sans-serif" font-size="11" font-weight="700">{parts[1]}</text>'

        tooltip = f"{label} | {lvl} | Score {score:.0f}/20 | Gas {gas:.1f}ppm | Temp {temp:.1f}°C | Crew {crew}"
        return f"""<g class="zone" id="z-{zone_id}">
  <title>{tooltip}</title>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" ry="12"
        fill="{c['fill']}" stroke="{c['stroke']}" stroke-width="2"
        style="{pulse}filter:drop-shadow(0 0 8px {c['glow']});"/>
  {label_svg}
  <text x="{cx:.1f}" y="{cy+5:.1f}"  text-anchor="middle" fill="{c['text']}" opacity="0.9" font-family="Outfit,sans-serif" font-size="10" font-weight="600">{lvl}</text>
  <text x="{cx:.1f}" y="{cy+20:.1f}" text-anchor="middle" fill="{c['text']}" opacity="0.65" font-family="Outfit,sans-serif" font-size="9">{score:.0f}/20 · {gas:.0f}ppm</text>
</g>"""

    CW, CH = 880, 345
    PAD = 18
    BW, BH, BGAP = 126, 130, 18
    BAT_Y = 16
    bat_zones = [
        ('Battery-1','Battery-1'), ('Battery-2','Battery-2'), ('Battery-3','Battery-3'),
        ('Zone_A','Battery-4'),    ('Zone_B','Battery-5'),    ('Zone_C','Battery-6'),
    ]
    bat_svg = "\n".join(
        make_zone(zid, lbl, PAD + i*(BW+BGAP), BAT_Y, BW, BH)
        for i, (zid, lbl) in enumerate(bat_zones)
    )

    BOT_Y = BAT_Y + BH + 45
    BOT_H = 130
    bot_zones = [
        ('Reactor_Area', 'Reactor Block', PAD,           220, BOT_H),
        ('Control_Room', 'Control Room',  PAD+220+58,    168, BOT_H),
        ('Storage_Area', 'Storage Area',  PAD+220+58+168+58, 214, BOT_H),
    ]
    bot_svg = "\n".join(make_zone(*args[:2], args[2], BOT_Y, args[3], args[4]) for args in bot_zones)

    LX, LY = CW - 118, 14
    legend  = f'<rect x="{LX-6}" y="{LY-6}" width="116" height="96" rx="8" fill="rgba(10,14,23,0.88)" stroke="rgba(255,255,255,0.1)" stroke-width="1"/>'
    legend += f'<text x="{LX+52}" y="{LY+9}" text-anchor="middle" fill="#64748b" font-family="Outfit,sans-serif" font-size="8" font-weight="700" letter-spacing="1.5">RISK LEVEL</text>'
    for i, (nm, col) in enumerate([('CRITICAL','#ef4444'),('HIGH','#f59e0b'),('MEDIUM','#eab308'),('LOW','#22c55e')]):
        ry = LY + 18 + i*18
        legend += f'<rect x="{LX}" y="{ry}" width="11" height="11" rx="2" fill="{col}"/>'
        legend += f'<text x="{LX+16}" y="{ry+9}" fill="#e2e8f0" font-family="Outfit,sans-serif" font-size="10" font-weight="500">{nm}</text>'

    row_labels = f"""
<text x="7" y="{BAT_Y+BH//2}" text-anchor="middle" fill="#334155" font-family="Outfit,sans-serif" font-size="8" font-weight="700"
  transform="rotate(-90 7 {BAT_Y+BH//2})">BATTERY BANKS</text>
<text x="7" y="{BOT_Y+BOT_H//2}" text-anchor="middle" fill="#334155" font-family="Outfit,sans-serif" font-size="8" font-weight="700"
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
<p style="color:#6b7d94;font-size:10px;margin:4px 0 0 4px;font-family:'Outfit',sans-serif;">
  Click on any zone for detailed sensor information</p>
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
STATIC_ZONES = ['Battery-1','Battery-2','Battery-3','Control_Room']
ALL_ZONES    = STATIC_ZONES + SENSOR_ZONES
ZONE_LABELS  = {
    'Battery-1':'Battery-1','Battery-2':'Battery-2','Battery-3':'Battery-3',
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
    ('Battery-1',    'Battery-1'),
    ('Battery-2',    'Battery-2'),
    ('Battery-3',    'Battery-3'),
]

# ─── INITIALIZATION ───────────────────────────────────────────────────────────
df           = load_data()
engine       = init_engine()
alert_system = init_alerts(engine, df)

# ─── SESSION STATE ────────────────────────────────────────────────────────────
_defaults = {
    'simulate_active':False,'sim_stage':'normal',
    'alert_acknowledged':False,'ack_critical':False,'ack_medium':False,
    'prev_simulate_active':False,'sim_start_time':None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# URL-based acknowledgment
if 'ack_alert' in st.query_params:
    aid = st.query_params['ack_alert']
    if aid == 'ALT-001':
        st.session_state.ack_critical = True
        st.session_state.sim_stage    = 'acknowledged'
        st.toast('✔ ALT-001 Acknowledged. Sirens active.', icon='📣')
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

# ─── DATA INJECTION ───────────────────────────────────────────────────────────
latest = df.iloc[-1].copy()
latest['timestamp'] = datetime.now()

if not st.session_state.simulate_active:
    latest.update({
        'Zone_A_gas_ppm':4.5,'Zone_A_temperature_c':78.5,'Zone_A_pressure_bar':4.0,
        'Zone_A_worker_count':2,'Zone_A_maintenance_active':0,'Zone_A_permit_active':0,
        'Zone_B_gas_ppm':0.9,'Zone_B_temperature_c':45.8,'Zone_B_pressure_bar':3.1,
        'Zone_B_worker_count':3,'Zone_B_maintenance_active':0,'Zone_B_permit_active':1,
        'Zone_C_gas_ppm':5.2,'Zone_C_temperature_c':73.4,'Zone_C_pressure_bar':3.8,
        'Zone_C_worker_count':2,'Zone_C_maintenance_active':0,'Zone_C_permit_active':1,
        'Reactor_Area_gas_ppm':0.85,'Reactor_Area_temperature_c':88.5,'Reactor_Area_pressure_bar':4.7,
        'Reactor_Area_worker_count':4,'Reactor_Area_maintenance_active':0,'Reactor_Area_permit_active':1,
        'Storage_Area_gas_ppm':1.7,'Storage_Area_temperature_c':82.3,'Storage_Area_pressure_bar':2.3,
        'Storage_Area_worker_count':4,'Storage_Area_maintenance_active':0,'Storage_Area_permit_active':0,
    })
    alert_system.alerts = []
else:
    latest.update({
        'Zone_A_gas_ppm':55.4,'Zone_A_temperature_c':98.2,'Zone_A_pressure_bar':4.0,
        'Zone_A_worker_count':8,'Zone_A_maintenance_active':1,'Zone_A_permit_active':1,
        'Zone_B_gas_ppm':0.9,'Zone_B_temperature_c':45.8,'Zone_B_pressure_bar':3.1,
        'Zone_B_worker_count':1,'Zone_B_maintenance_active':0,'Zone_B_permit_active':0,
        'Zone_C_gas_ppm':5.2,'Zone_C_temperature_c':73.4,'Zone_C_pressure_bar':3.8,
        'Zone_C_worker_count':2,'Zone_C_maintenance_active':0,'Zone_C_permit_active':1,
        'Reactor_Area_gas_ppm':0.85,'Reactor_Area_temperature_c':57.8,'Reactor_Area_pressure_bar':4.7,
        'Reactor_Area_worker_count':2,'Reactor_Area_maintenance_active':0,'Reactor_Area_permit_active':1,
        'Storage_Area_gas_ppm':16.0,'Storage_Area_temperature_c':106.0,'Storage_Area_pressure_bar':2.3,
        'Storage_Area_worker_count':2,'Storage_Area_maintenance_active':0,'Storage_Area_permit_active':0,
    })
    alert_system.alerts = [
        {
            'alert_id':'ALT-001','timestamp':latest['timestamp'].strftime('%H:%M:%S'),
            'zone':'Zone_A','zone_label':'Battery-4','risk_level':'CRITICAL','risk_score':15,
            'factors':['GAS_CRITICAL','MAINTENANCE_ACTIVE','TRIPLE_THREAT'],
            'compound_factors':['TRIPLE_THREAT'],
            'message':'Maintenance crew active during 55.4 ppm gas leak. Visakhapatnam triple-threat pattern detected.',
            'teams_notified':'Alpha & Beta Teams','channels':['SMS','PHONE','SIREN','EMAIL'],
            'requires_ack':True,'acknowledged':st.session_state.ack_critical,'resolved':False,
        },
        {
            'alert_id':'ALT-002','timestamp':latest['timestamp'].strftime('%H:%M:%S'),
            'zone':'Storage_Area','zone_label':'Storage Area','risk_level':'MEDIUM','risk_score':5,
            'factors':['TEMPERATURE_CRITICAL'],'compound_factors':[],
            'message':'Storage area temperature elevated to 106°C. Thermal runaway risk.',
            'teams_notified':'Kappa & Lambda Teams','channels':['EMAIL','DASHBOARD'],
            'requires_ack':False,'acknowledged':st.session_state.ack_medium,'resolved':False,
        },
    ]

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
STATIC_GAS = {'Battery-1':0.6,'Battery-2':0.7,'Battery-3':0.9,'Control_Room':0.3}
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
  min-height: 145px;
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
      <div style="font-size:11px;color:#22c55e;opacity:0.8;margin-top:2px;">[Last 24 Hours]</div>
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
        mime="text/markdown", use_container_width=True)

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

    # Simulate button in sidebar
    if sim_on:
        if st.button("🟢 RESET SIMULATION", key="reset_btn", use_container_width=True):
            for k, v in _defaults.items():
                st.session_state[k] = v
            st.rerun()
    else:
        if st.button("🚨 SIMULATE CRITICAL EVENT", type="primary", use_container_width=True, key="sim_btn_sidebar"):
            st.session_state.sim_stage = 'injecting'
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT — wrapped in a padded div
# ════════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="main-content">', unsafe_allow_html=True)

# Simulate button in top-right (mirrored — actual widget)
top_col1, top_col2 = st.columns([6, 1.4])
with top_col2:
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    if sim_on:
        if st.button("🟢 RESET SIMULATION", key="reset_btn2", use_container_width=True):
            for k, v in _defaults.items():
                st.session_state[k] = v
            st.rerun()
    else:
        if st.button("🚨 SIMULATE CRITICAL EVENT", type="primary", use_container_width=True, key="sim_btn_top"):
            st.session_state.sim_stage = 'injecting'
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
    if st.button("🚨 ACKNOWLEDGE INCIDENT & TRIGGER EMERGENCY EVACUATION",
                 type="primary", use_container_width=True, key="ack_btn"):
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
      <div style="font-size:11px;color:#4a8cf7;letter-spacing:1px;">{figures}</div>
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


# ════════════════════════════════════════════════════════════════════════════════
# HEATMAP (70%) + ZONE STATUS (30%)
# ════════════════════════════════════════════════════════════════════════════════
col_map, col_zones = st.columns([7, 3])

with col_map:
    st.markdown('<div class="section-header">🗺️ REAL-TIME RISK HEATMAP</div>', unsafe_allow_html=True)
    heatmap_html = build_heatmap_html(zone_risks, st.session_state.simulate_active)
    components.html(heatmap_html, height=400, scrolling=False)

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


# ════════════════════════════════════════════════════════════════════════════════
# BOTTOM: TREND (3.5) | ALERTS (3.8) | RULES (2.7)
# ════════════════════════════════════════════════════════════════════════════════
col_trend, col_alerts, col_rules = st.columns([3.5, 3.8, 2.7])

# ─── 24-HOUR RISK TREND ───────────────────────────────────────────────────────
with col_trend:
    st.markdown('<div class="section-header">📈 24-HOUR RISK TREND</div>', unsafe_allow_html=True)

    timeline_data = []
    for idx in range(max(0, len(df) - 300), len(df), 10):
        row = df.iloc[idx]
        scores = [engine.analyze_zone(row, z)['risk_score']
                  for z in ['Zone_A','Zone_B','Zone_C','Reactor_Area','Storage_Area']]
        max_risk = max(scores, default=0)
        timeline_data.append({'timestamp': row['timestamp'], 'risk': max_risk})

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
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})


# ─── ACTIVE ALERTS ────────────────────────────────────────────────────────────
with col_alerts:
    # Header row with filter pills
    hdr_left, hdr_right = st.columns([1.5, 2])
    with hdr_left:
        st.markdown('<div class="section-header" style="margin-bottom:0;margin-top:4px;">🔔 ACTIVE ALERTS</div>', unsafe_allow_html=True)
    with hdr_right:
        sev_filter = st.radio("Filter:", ["All","Critical","Medium"],
                              horizontal=True, key="sev_filter", label_visibility="collapsed")

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
        st.markdown("""
        <div style="background:rgba(34,197,94,0.04);border:1px solid rgba(34,197,94,0.15);
        border-left:4px solid #22c55e;border-radius:10px;padding:18px 20px;
        text-align:center;color:#22c55e;font-weight:700;font-size:13px;
        letter-spacing:0.5px;font-family:'Outfit',sans-serif;">
          🟢 ALL SYSTEMS NOMINAL — No active safety alerts.
        </div>""", unsafe_allow_html=True)

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