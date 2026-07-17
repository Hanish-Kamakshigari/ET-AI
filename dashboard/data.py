# -*- coding: utf-8 -*-
"""
SurakshaAI Dashboard Data and State Module
"""

import sys
import os
import sqlite3
import random as _rand
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from src.alert_system import AlertSystem, AlertManager
from dataclasses import dataclass
import pandas as pd
import streamlit as st

# Path configuration
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.ui_constants import SENSOR_ZONES, STATIC_ZONES, ALL_ZONES, ZONE_LABELS
from src.ui_components import Colors

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
    def __init__(self) -> None:
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

    def get_sensor_risk(self, value: float, sensor_type: str) -> Tuple[int, str]:
        if sensor_type not in self.thresholds:
            return 0, 'NORMAL'
        t = self.thresholds[sensor_type]
        if value >= t['critical'][0]:   return 4, 'CRITICAL'
        elif value >= t['high'][0]:     return 2, 'HIGH'
        elif value >= t['elevated'][0]: return 1, 'ELEVATED'
        else:                           return 0, 'NORMAL'

    def analyze_zone(self, row: pd.Series, zone: str) -> Dict[str, Any]:
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

    def analyze_timestamp(self, row: pd.Series) -> List[RiskAlert]:
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


# ─── DATA LOADING ─────────────────────────────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    return pd.read_csv('data/plant_data.csv', parse_dates=['timestamp'])


@st.cache_resource
def init_engine() -> CompoundRiskEngine:
    return CompoundRiskEngine()


@st.cache_resource
def init_alerts(_engine: CompoundRiskEngine, _df: pd.DataFrame) -> AlertSystem:
    from src.alert_system import AlertSystem
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


def init_state_defaults() -> None:
    """Initializes Streamlit session state defaults"""
    _defaults = {
        'simulate_active': False,
        'sim_stage': 'normal',
        'alert_acknowledged': False,
        'ack_critical': False,
        'ack_medium': False,
        'prev_simulate_active': False,
        'sim_start_time': None,
        'dev_mode': False,
        'scenario_start_time': None,
        'scenario_offset_min': 20,
        'compound_risk_active': False,
        'compound_risk_first_seen': None,
        'ack_time': None,
        'alert_log': [],
        'recovering': False,
        'sim_play_active': False,  # Feed will render only a single frame until the play control is toggled True
        'cctv_frame_index': 0,
        'video_played_this_run': False,
        'yolo_worker_counts': {},
    }
    for k, v in _defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if st.session_state.scenario_start_time is None:
        st.session_state.scenario_start_time = datetime.now()


def handle_url_actions(alert_system: AlertSystem, am: AlertManager) -> None:
    """Processes URL query parameters for acknowledging alerts"""
    if 'ack_alert' in st.query_params:
        aid = st.query_params['ack_alert']
        am.acknowledge(aid, "Operator")
        alert_system.acknowledge_alert(aid)
        if aid == 'ALT-001':
            st.session_state.ack_critical = True
            st.session_state.sim_stage    = 'acknowledged'
            st.session_state.ack_time     = datetime.now()
            st.toast('✔ ALT-001 Acknowledged. Sirens active. Recovery initiated.', icon='📣')
        elif aid == 'ALT-002':
            st.session_state.ack_medium = True
            st.toast('✔ ALT-002 Acknowledged.', icon='✔')
        else:
            st.toast(f'✔ Alert {aid} Acknowledged.', icon='✔')
        del st.query_params['ack_alert']
        st.rerun()

    if 'ack_auto_alert' in st.query_params:
        st.session_state.banner_visible = False
        st.session_state.active_alert = None
        del st.query_params['ack_auto_alert']
        st.toast("✔ Alert Acknowledged", icon="🚨")
        st.rerun()


# ─── STATUS FUNCTION ──────────────────────────────────────────────────────────
def get_system_status(risk_score: float) -> Dict[str, Any]:
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
        'CRITICAL': '#ef4444',
        'HIGH':     '#f97316',
        'MEDIUM':   '#eab308',
        'LOW':      '#22c55e',
        'SAFE':     '#22c55e',
        'CLEAR':    '#22c55e'
    }.get(status.upper(), "#6b7280")


# ─── TELEMETRY CALCULATIONS ───────────────────────────────────────────────────
def calculate_telemetry(df: pd.DataFrame, engine: CompoundRiskEngine, alert_system: AlertSystem) -> Dict[str, Any]:
    # Toast on state change
    if st.session_state.simulate_active != st.session_state.prev_simulate_active:
        msg = ('🚨 TRIPLE-THREAT COMPOUND RISK SIMULATED IN BATTERY-4!'
               if st.session_state.simulate_active
               else '✅ Telemetry reset. Normal operations restored.')
        st.toast(msg, icon='🚨' if st.session_state.simulate_active else '✅')
        st.session_state.prev_simulate_active = st.session_state.simulate_active

    _now = datetime.now()
    _real_elapsed_min = (_now - st.session_state.scenario_start_time).total_seconds() / 60.0
    _scenario_min = _real_elapsed_min + st.session_state.scenario_offset_min

    # ── Battery-4 (Zone A) ──
    _za_gas_raw  = 4.5 + (_scenario_min * 1.2) + _rand.gauss(0, 0.4)
    _za_gas      = round(min(max(_za_gas_raw, 3.0), 65.0), 1)
    _za_temp     = round(75.0 + (_scenario_min * 0.35) + _rand.gauss(0, 0.8), 1)
    _za_temp     = min(_za_temp, 102.0)
    _za_pressure = round(4.0 + _rand.gauss(0, 0.05), 2)
    _za_workers   = 2 if _scenario_min < 15 else 4 if _scenario_min < 28 else 8
    _za_maint     = 1 if _scenario_min > 8  else 0
    _za_permit    = 1 if _scenario_min > 10 else 0

    # ── Battery-5 (Zone B) ──
    _zb_gas      = round(0.9 + _rand.gauss(0, 0.1), 1)
    _zb_temp     = round(45.8 + _rand.gauss(0, 0.5), 1)
    _zb_pressure = round(3.1 + _rand.gauss(0, 0.04), 2)

    # ── Battery-6 (Zone C) ──
    _zc_gas      = round(5.2 + _rand.gauss(0, 0.2), 1)
    _zc_temp     = round(73.4 + _rand.gauss(0, 0.4), 1)
    _zc_pressure = round(3.8 + _rand.gauss(0, 0.04), 2)

    # ── Reactor Block ──
    _zr_gas      = round(0.85 + _rand.gauss(0, 0.07), 2)
    _zr_temp     = round(88.5 + _rand.gauss(0, 0.6), 1)
    _zr_pressure = round(4.7 + _rand.gauss(0, 0.06), 2)

    # ── Storage Area ──
    _zs_gas_raw  = 8.0 + (_scenario_min * 0.55) + _rand.gauss(0, 0.3)
    _zs_gas      = round(min(_zs_gas_raw, 48.0), 1)
    _zs_temp     = round(82.3 + (_scenario_min * 0.2) + _rand.gauss(0, 0.5), 1)
    _zs_temp     = min(_zs_temp, 112.0)
    _zs_pressure = round(2.3 + _rand.gauss(0, 0.03), 2)

    # Recovery
    if st.session_state.ack_critical and st.session_state.ack_time is not None:
        _ack_elapsed_min = (_now - st.session_state.ack_time).total_seconds() / 60.0
        _za_gas  = max(3.0, round(_za_gas  - _ack_elapsed_min * 2.5, 1))
        _za_temp = max(70.0, round(_za_temp - _ack_elapsed_min * 1.2, 1))
        _za_workers = max(1, _za_workers - int(_ack_elapsed_min * 0.8))
        if _za_gas < 10 and not st.session_state.recovering:
            st.session_state.recovering = True
            st.toast("✅ Battery-4 gas levels normalising. Recovery in progress.", icon="✅")

    # Assemble latest
    latest = df.iloc[-1].copy()
    latest['timestamp'] = _now

    # Store in session state for Digital Twin access
    st.session_state['_last_telemetry'] = dict(latest)
    latest.update({
        'Zone_A_gas_ppm': _za_gas, 'Zone_A_temperature_c': _za_temp, 'Zone_A_pressure_bar': _za_pressure,
        'Zone_A_worker_count': _za_workers, 'Zone_A_maintenance_active': _za_maint, 'Zone_A_permit_active': _za_permit,
        'Zone_B_gas_ppm': _zb_gas, 'Zone_B_temperature_c': _zb_temp, 'Zone_B_pressure_bar': _zb_pressure,
        'Zone_B_worker_count': 3, 'Zone_B_maintenance_active': 0, 'Zone_B_permit_active': 1,
        'Zone_C_gas_ppm': _zc_gas, 'Zone_C_temperature_c': _zc_temp, 'Zone_C_pressure_bar': _zc_pressure,
        'Zone_C_worker_count': 1, 'Zone_C_maintenance_active': 0, 'Zone_C_permit_active': 1,
        'Reactor_Area_gas_ppm': _zr_gas, 'Reactor_Area_temperature_c': _zr_temp, 'Reactor_Area_pressure_bar': _zr_pressure,
        'Reactor_Area_worker_count': 1, 'Reactor_Area_maintenance_active': 0, 'Reactor_Area_permit_active': 1,
        'Storage_Area_gas_ppm': _zs_gas, 'Storage_Area_temperature_c': _zs_temp, 'Storage_Area_pressure_bar': _zs_pressure,
        'Storage_Area_worker_count': 15, 'Storage_Area_maintenance_active': 0, 'Storage_Area_permit_active': 0,
    })

    # Override with YOLO worker counts
    if 'yolo_worker_counts' in st.session_state:
        for z_name, yolo_cnt in st.session_state.yolo_worker_counts.items():
            latest[f"{z_name}_worker_count"] = yolo_cnt

    # Auto Compound Risk Detection
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
        st.session_state.alert_log.insert(0, {
            'id': 'ALT-AUTO-001', 'time': _now.strftime('%H:%M:%S'),
            'zone': 'Battery-4', 'level': 'CRITICAL',
            'msg': f'AI AUTO-DETECTED: Gas {_za_gas}ppm + {_za_workers} workers + HOT WORK PERMIT.',
        })

    if st.session_state.compound_risk_active and not st.session_state.simulate_active:
        st.session_state.simulate_active = True
        st.session_state.sim_stage       = 'active'

    # Set alert system state
    if st.session_state.compound_risk_active:
        latest['max_risk_level'] = 'CRITICAL'
        alert_system.alerts = [
            {
                'alert_id': 'ALT-001', 'timestamp': _now.strftime('%H:%M:%S'),
                'zone': 'Zone_A', 'zone_label': 'Battery-4', 'risk_level': 'CRITICAL', 'risk_score': 15,
                'factors': ['GAS_CRITICAL', 'MAINTENANCE_ACTIVE', 'TRIPLE_THREAT'],
                'compound_factors': ['TRIPLE_THREAT'],
                'message': f'Maintenance crew ({_za_workers} workers) active during {_za_gas} ppm gas leak. Triple-threat pattern auto-detected.',
                'teams_notified': 'Alpha & Beta Teams', 'channels': ['SMS', 'PHONE', 'SIREN', 'EMAIL'],
                'requires_ack': True, 'acknowledged': st.session_state.ack_critical, 'resolved': False,
            },
            {
                'alert_id': 'ALT-002', 'timestamp': _now.strftime('%H:%M:%S'),
                'zone': 'Storage_Area', 'zone_label': 'Storage Area', 'risk_level': 'MEDIUM', 'risk_score': 5,
                'factors': ['GAS_RISING'], 'compound_factors': [],
                'message': f'Storage area gas at {_zs_gas} ppm. Smoke build-up detected. Evacuate if above 40 ppm.',
                'teams_notified': 'Kappa & Lambda Teams', 'channels': ['EMAIL', 'DASHBOARD'],
                'requires_ack': False, 'acknowledged': st.session_state.ack_medium, 'resolved': False,
            },
        ]
    else:
        latest['max_risk_level'] = 'LOW'
        alert_system.alerts = []

    # Zone Risk Evaluation
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
                'risk_level': 'LOW', 'risk_score': 0,
                'sensor_data': {f'{zone}_gas_ppm': 1.2, f'{zone}_temperature_c': 71.0,
                               f'{zone}_pressure_bar': 4.5, f'{zone}_worker_count': 0},
                'compound_factors': [], 'label': ZONE_LABELS.get(zone, zone),
            }

    STATIC_GAS = {'Control_Room': 0.3}
    for z, g in STATIC_GAS.items():
        if z in zone_risks:
            zone_risks[z]['sensor_data'][f'{z}_gas_ppm'] = g

    max_score = max(z['risk_score'] for z in zone_risks.values())
    status_dict = get_system_status(max_score)

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
        banner_level = None
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
    permit_zones  = [ZONE_LABELS.get(z, z) for z in SENSOR_ZONES if latest.get(f'{z}_permit_active', 0) == 1]
    permit_count  = len(permit_zones)
    active_compounds = [(z, f) for z in SENSOR_ZONES
                        for f in engine.analyze_zone(latest, z)['compound_factors']]
    compound_detected = bool(active_compounds)

    # Persistent DB log query using the unified AlertCoordinator adapter
    db_logs = []
    try:
        from src.alert_coordinator import get_alert_coordinator
        raw_history = get_alert_coordinator().dashboard_adapter.get_alert_history(limit=4)
        for item in raw_history:
            db_logs.append({
                'alert_id': item['incident_id'],
                'timestamp': item['start_time'],
                'zone': item['zone'],
                'risk_level': item['severity'],
                'status': item['status'],
                'message': item['message']
            })
    except Exception:
        pass

    return {
        'now': _now,
        'latest': latest,
        'zone_risks': zone_risks,
        'max_score': max_score,
        'STATUS': status_dict,
        'compound_rules_eval': compound_rules_eval,
        'compound_risk_score': compound_risk_score,
        'total_rules': total_rules,
        'risk_state': risk_state,
        'risk_color': risk_color,
        'banner_level': banner_level,
        'banner_color': banner_color,
        'banner_border': banner_border,
        'total_workers': total_workers,
        'permit_zones': permit_zones,
        'permit_count': permit_count,
        'active_compounds': active_compounds,
        'compound_detected': compound_detected,
        'db_logs': db_logs,
    }
