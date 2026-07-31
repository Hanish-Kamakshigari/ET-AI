# -*- coding: utf-8 -*-
"""
SurakshaAI — Interactive Plant Digital Twin
Transforms the Zone Map into a true digital twin that synchronizes all operational systems.
"""

import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

import streamlit as st

# Theme constants matching existing dark industrial design
_BG_GRADIENT = "linear-gradient(135deg,#0f1f38,#0a1628)"
_BORDER = "#1e3a5f"
_TEXT_PRIMARY = "#e2e8f0"
_TEXT_MUTED = "#94a3b8"
_TEXT_DIM = "#64748b"
_ACCENT_BLUE = "#3b82f6"
_ACCENT_GREEN = "#22c55e"
_ACCENT_YELLOW = "#eab308"
_ACCENT_ORANGE = "#f97316"
_ACCENT_RED = "#ef4444"
_ACCENT_PURPLE = "#8b5cf6"
_CARD_RADIUS = "12px"
_FONT = "Outfit,sans-serif"


@dataclass
class ZoneDigitalTwin:
    """Complete digital twin state for a single zone."""
    zone_id: str
    zone_label: str
    risk_score: float = 0.0
    risk_level: str = "LOW"
    workers_present: int = 0
    workers_at_risk: int = 0
    worker_details: List[Dict[str, Any]] = field(default_factory=list)
    active_sensors: int = 0
    sensor_status: Dict[str, Any] = field(default_factory=dict)
    gas_ppm: float = 0.0
    temperature: float = 0.0
    pressure: float = 0.0
    camera_online: bool = True
    camera_feed_status: str = "ONLINE"
    detections: List[str] = field(default_factory=list)
    active_permits: int = 0
    permit_types: List[str] = field(default_factory=list)
    permit_conflicts: List[str] = field(default_factory=list)
    equipment_status: Dict[str, str] = field(default_factory=dict)
    equipment_at_risk: List[str] = field(default_factory=list)
    emergency_active: bool = False
    emergency_type: str = ""
    evacuation_required: bool = False


def get_zone_twin_state(zone_id: str, data_dict: Dict[str, Any], detections: List[Any]) -> ZoneDigitalTwin:
    """Calculate the complete digital twin state for a zone from live data."""
    from src.config.ui_constants import ZONE_LABELS

    zone_label = ZONE_LABELS.get(zone_id, zone_id)
    zone_risks = data_dict.get('zone_risks', {}).get(zone_id, {})
    latest = data_dict.get('latest', {})

    twin = ZoneDigitalTwin(zone_id=zone_id, zone_label=zone_label)
    twin.risk_score = zone_risks.get('risk_score', 0)
    twin.risk_level = zone_risks.get('risk_level', 'LOW')
    twin.workers_present = int(latest.get(zone_id + '_worker_count', 0))
    twin.workers_at_risk = sum(1 for d in detections if getattr(d, 'label', '') == 'person')

    worker_idx = 1
    for d in detections:
        if getattr(d, 'label', '') == 'person':
            twin.worker_details.append({
                'id': 'W-' + str(worker_idx),
                'status': 'AT_RISK' if twin.risk_level in ('HIGH', 'CRITICAL') else 'SAFE',
                'ppe_compliant': True
            })
            worker_idx += 1

    twin.gas_ppm = float(latest.get(zone_id + '_gas_ppm', 0))
    twin.temperature = float(latest.get(zone_id + '_temperature_c', 0))
    twin.pressure = float(latest.get(zone_id + '_pressure_bar', 0))

    sensor_count = 4
    twin.active_sensors = sensor_count if twin.risk_level != 'CRITICAL' else sensor_count - 1
    twin.sensor_status = {
        'gas': 'ONLINE' if twin.gas_ppm <= 50 else 'ALERTING',
        'temperature': 'ONLINE' if twin.temperature <= 110 else 'ALERTING',
        'pressure': 'ONLINE' if twin.pressure <= 8.0 else 'ALERTING',
        'flow': 'ONLINE' if twin.pressure > 0 else 'OFFLINE'
    }

    twin.camera_online = True
    twin.camera_feed_status = 'ONLINE' if st.session_state.get('sim_play_active', False) else 'STANDBY'
    twin.detections = [getattr(d, 'label', 'unknown') for d in detections]

    twin.active_permits = 1 if latest.get(zone_id + '_permit_active', 0) == 1 else 0
    twin.permit_types = []
    if twin.active_permits:
        if zone_id == 'Zone_A' and twin.risk_level in ('HIGH', 'CRITICAL'):
            twin.permit_types = ['HOT WORK', 'MAINTENANCE']
        elif zone_id == 'Reactor_Area':
            twin.permit_types = ['WELDING']
        elif zone_id == 'Storage_Area':
            twin.permit_types = ['CONFINED SPACE']
        else:
            twin.permit_types = ['GENERAL WORK']

    twin.permit_conflicts = detect_permit_conflicts(zone_id, twin, latest)

    twin.equipment_status = {
        'ventilation': 'NORMAL' if twin.gas_ppm < 30 else 'MAX_SPEED',
        'fire_suppression': 'STANDBY' if twin.risk_level != 'CRITICAL' else 'ARMED',
        'gas_detection': 'ALERTING' if twin.gas_ppm > 35 else 'MONITORING',
        'cooling_system': 'NORMAL' if twin.temperature < 95 else 'ELEVATED',
        'relief_valves': 'NORMAL' if twin.pressure < 7.0 else 'ACTIVATED'
    }

    twin.emergency_active = twin.risk_level in ('HIGH', 'CRITICAL')
    twin.evacuation_required = twin.risk_level == 'CRITICAL'

    if twin.emergency_active:
        if twin.gas_ppm > 35 and twin.workers_present > 0:
            twin.emergency_type = 'GAS_LEAK_WITH_WORKERS'
        elif twin.temperature > 98:
            twin.emergency_type = 'OVERHEATING'
        elif twin.pressure > 80:
            twin.emergency_type = 'OVERPRESSURE'
        else:
            twin.emergency_type = 'GENERAL_HAZARD'

    return twin


def detect_permit_conflicts(zone_id: str, twin: ZoneDigitalTwin, latest: Dict[str, Any]) -> List[str]:
    """Detect SIMOPS (Simultaneous Operations) conflicts for a zone."""
    conflicts = []
    gas = twin.gas_ppm
    temp = twin.temperature
    workers = twin.workers_present
    maintenance = latest.get(zone_id + '_maintenance_active', 0) == 1

    # Hot Work + Gas Leak
    if twin.active_permits > 0 and any(p in ('HOT WORK', 'WELDING') for p in twin.permit_types):
        if gas > 20:
            conflicts.append('HOT_WORK_GAS_LEAK: Gas ' + str(gas) + 'ppm during hot work')
        if temp > 80:
            conflicts.append('HOT_WORK_HIGH_TEMP: Temperature ' + str(temp) + 'C during hot work')

    # Confined Space + Low Oxygen
    if any(p in ('CONFINED SPACE', 'ENTER') for p in twin.permit_types):
        if gas < 18 or gas > 25:
            conflicts.append('CONFINED_SPACE_OXYGEN: Abnormal gas levels in confined space')

    # Maintenance + Worker Congestion
    if maintenance and workers > 8:
        conflicts.append('MAINTENANCE_OVERCROWDING: ' + str(workers) + ' workers during maintenance')

    return conflicts


def render_digital_twin_panel() -> None:
    """Render the interactive plant digital twin panel in the right sidebar."""
    selected_zone = st.session_state.get('cctv_zone_selector', 'Zone_A')
    latest = st.session_state.get('_last_telemetry', {})
    detections = st.session_state.get('current_detections', [])

    twin = get_zone_twin_state(selected_zone, {'zone_risks': {}, 'latest': latest}, detections)

    pulse_style = "animation: twinPulse 2s infinite;" if twin.emergency_active else ""

    risk_colors = {'CRITICAL': _ACCENT_RED, 'HIGH': _ACCENT_ORANGE, 'MEDIUM': _ACCENT_YELLOW, 'LOW': _ACCENT_GREEN}
    risk_color = risk_colors.get(twin.risk_level, _ACCENT_GREEN)

    # Worker rows
    worker_rows = ""
    for worker in twin.worker_details[:5]:
        status_color = _ACCENT_ORANGE if worker['status'] == 'AT_RISK' else _ACCENT_GREEN
        ppe_icon = "OK" if worker['ppe_compliant'] else "WARN"
        worker_rows = worker_rows + "<div style='display:flex; justify-content:space-between; padding:4px 0;'>" + \
            "<span style='color:" + _TEXT_PRIMARY + "; font-size:10px;'>" + worker['id'] + "</span>" + \
            "<span style='color:" + status_color + "; font-size:9px; font-weight:600;'>" + worker['status'] + "</span>" + \
            "<span style='color:" + status_color + "; font-size:9px;'>" + ppe_icon + "</span>" + \
            "</div>"

    # Sensor rows
    sensor_rows = ""
    for sensor, status in twin.sensor_status.items():
        status_color = _ACCENT_RED if status == 'ALERTING' else _ACCENT_GREEN
        sensor_rows = sensor_rows + "<div style='display:flex; justify-content:space-between; padding:3px 0;'>" + \
            "<span style='color:" + _TEXT_DIM + "; font-size:9px;'>" + sensor + "</span>" + \
            "<span style='color:" + status_color + "; font-size:9px; font-weight:600;'>" + status + "</span>" + \
            "</div>"

    # Equipment rows
    equipment_rows = ""
    for equip, status in twin.equipment_status.items():
        status_color = _ACCENT_ORANGE if status in ('ARMED', 'ACTIVATED', 'MAX_SPEED') else _ACCENT_GREEN
        equipment_rows = equipment_rows + "<div style='display:flex; justify-content:space-between; padding:3px 0;'>" + \
            "<span style='color:" + _TEXT_DIM + "; font-size:9px;'>" + equip + "</span>" + \
            "<span style='color:" + status_color + "; font-size:9px;'>" + status + "</span>" + \
            "</div>"

    # Permit conflicts
    permit_conflicts_html = ""
    if twin.permit_conflicts:
        conflict_items = ""
        for c in twin.permit_conflicts:
            msg = c.split(':')[1] if ':' in c else c
            conflict_items = conflict_items + "<div style='color:" + _ACCENT_ORANGE + "; font-size:9px; margin:2px 0;'>WARN " + msg + "</div>"
        permit_conflicts_html = "<div style='margin-top:6px; padding-top:6px; border-top:1px solid " + _BORDER + ";'>" + \
            "<div style='color:" + _ACCENT_ORANGE + "; font-size:9px; font-weight:600; margin-bottom:4px;'>SIMOPS Conflicts</div>" + \
            conflict_items + "</div>"

        worker_section = "<details open style='margin-bottom:6px;'>" + \
            "<summary style='color:" + _TEXT_MUTED + "; font-size:9px; cursor:pointer;'>Workers (" + \
            str(twin.workers_at_risk) + " at risk)</summary>" + \
            "<div style='max-height:120px; overflow-y:auto;'>" + worker_rows + "</div></details>"

    # Permits section
    permits_list = ""
    if twin.permit_types:
        for p in twin.permit_types:
            permits_list = permits_list + "<div style='color:" + _ACCENT_BLUE + "; font-size:9px; margin:2px 0;'>- " + p + "</div>"
    else:
        permits_list = "<div style='color:" + _TEXT_DIM + "; font-size:9px;'>No active permits</div>"

    permits_section = "<details open style='margin-bottom:6px;'>" + \
        "<summary style='color:" + _TEXT_MUTED + "; font-size:9px; cursor:pointer;'>Permits (" + \
        str(twin.active_permits) + " active)</summary>" + \
        "<div style='margin-top:4px;'>" + permits_list + permit_conflicts_html + "</div></details>"

    # Emergency section
    emergency_section = ""
    if twin.emergency_active:
        emergency_text = "Evacuation Required" if twin.evacuation_required else "Access Restricted"
        emergency_section = "<div style='margin-top:6px; padding:6px; background:rgba(239,68,68,0.1);'>" + \
            "<div style='color:" + risk_color + "; font-size:10px; font-weight:600;'>ALERT " + \
            twin.emergency_type.replace('_', ' ') + "</div>" + \
            "<div style='color:" + _ACCENT_GREEN + "; font-size:9px; margin-top:2px;'>" + emergency_text + "</div>" + \
            "</div>"

    html = "<div style='background:" + _BG_GRADIENT + "; border:1px solid " + risk_color + \
        "; border-left:3px solid " + risk_color + \
        "; border-radius:" + _CARD_RADIUS + "; padding:12px 14px; font-family:" + _FONT + \
        "; margin-bottom:8px;'>" + \
        "<div style='display:flex; justify-content:space-between; margin-bottom:8px;'>" + \
        "<span style='color:" + _TEXT_MUTED + "; font-size:11px; font-weight:600;'>ZONE DIGITAL TWIN - " + \
        twin.zone_label.upper() + "</span>" + \
        "<span style='color:" + risk_color + "; font-size:10px; font-weight:700;'>" + \
        twin.risk_level + " " + str(int(twin.risk_score)) + "/100</span></div>" + \
        "<div style='display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:8px;'>" + \
        "<div style='text-align:center; background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 4px;'>" + \
        "<div style='color:" + _ACCENT_BLUE + "; font-size:14px; font-weight:700;'>" + str(twin.workers_present) + "</div>" + \
        "<div style='color:" + _TEXT_DIM + "; font-size:8px;'>Workers</div></div>" + \
        "<div style='text-align:center; background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 4px;'>" + \
        "<div style='color:" + risk_color + "; font-size:14px; font-weight:700;'>" + f"{twin.gas_ppm:.1f}" + "</div>" + \
        "<div style='color:" + _TEXT_DIM + "; font-size:8px;'>Gas (ppm)</div></div>" + \
        "<div style='text-align:center; background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 4px;'>" + \
        "<div style='color:" + risk_color + "; font-size:14px; font-weight:700;'>" + f"{twin.temperature:.1f}" + "</div>" + \
        "<div style='color:" + _TEXT_DIM + "; font-size:8px;'>Temp (C)</div></div>" + \
        "<div style='text-align:center; background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 4px;'>" + \
        "<div style='color:" + risk_color + "; font-size:14px; font-weight:700;'>" + f"{twin.pressure:.1f}" + "</div>" + \
        "<div style='color:" + _TEXT_DIM + "; font-size:8px;'>Pressure (bar)</div></div></div>" + \
        worker_section + \
        "<details open style='margin-bottom:6px;'><summary style='color:" + _TEXT_MUTED + "; font-size:9px;'>Sensors (" + \
        str(twin.active_sensors) + " active)</summary><div style='margin-top:4px;'>" + sensor_rows + "</div></details>" + \
        "<details open style='margin-bottom:6px;'><summary style='color:" + _TEXT_MUTED + "; font-size:9px;'>Equipment Status</summary>" + \
        "<div style='margin-top:4px;'>" + equipment_rows + "</div></details>" + \
        permits_section + emergency_section + "</div>"

    st.markdown(html, unsafe_allow_html=True)


def render_interactive_zone_map() -> None:
    """Render an interactive plant layout map that syncs all systems on zone click."""
    from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS

    zone_positions = {
        'Zone_A': {'x': 20, 'y': 18, 'label': 'Battery-4', 'icon': 'BAT'},
        'Zone_B': {'x': 50, 'y': 15, 'label': 'Battery-5', 'icon': 'BAT'},
        'Zone_C': {'x': 80, 'y': 18, 'label': 'Battery-6', 'icon': 'BAT'},
        'Reactor_Area': {'x': 35, 'y': 52, 'label': 'Reactor', 'icon': 'RCT'},
        'Storage_Area': {'x': 70, 'y': 80, 'label': 'Storage', 'icon': 'STG'},
    }

    zone_risks = st.session_state.get('zone_risks', {})

    cols = st.columns(5)
    for idx, zone in enumerate(SENSOR_ZONES):
        info = zone_positions.get(zone, {})
        risk_level = zone_risks.get(zone, {}).get('risk_level', 'LOW') if zone_risks else 'LOW'
        color = {'CRITICAL': _ACCENT_RED, 'HIGH': _ACCENT_ORANGE, 'MEDIUM': _ACCENT_YELLOW, 'LOW': _ACCENT_GREEN}.get(risk_level, _ACCENT_GREEN)
        with cols[idx]:
            btn_label = info.get('icon', 'LOC') + "\n" + ZONE_LABELS.get(zone, zone)
            if st.button(btn_label, key="digital_twin_btn_" + zone, width='stretch',
                        help="Focus on " + ZONE_LABELS.get(zone, zone)):
                st.session_state.cctv_zone_selector = zone
                st.session_state.selected_zone = zone
                st.rerun()
            st.markdown("<div style='height:6px; background:" + color + "; border-radius:999px; margin-top:-6px;'></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    zone_markers = ""
    for zone, pos in zone_positions.items():
        risk_level = zone_risks.get(zone, {}).get('risk_level', 'LOW') if zone_risks else 'LOW'
        color = {'CRITICAL': _ACCENT_RED, 'HIGH': _ACCENT_ORANGE, 'MEDIUM': _ACCENT_YELLOW, 'LOW': _ACCENT_GREEN}.get(risk_level, _ACCENT_GREEN)
        pulse = ""
        zone_markers = zone_markers + "<div style='position:absolute; left:" + str(pos['x']) + "%; top:" + str(pos['y']) + \
            "%; transform:translate(-50%,-50%);'>" + \
            "<div style='width:48px; height:48px; border-radius:50%; background:" + color + "22; border:2px solid " + color + \
            "; display:flex; align-items:center; justify-content:center; font-size:14px;'>" + \
            pos['icon'] + "</div>" + \
            "<div style='color:" + color + "; font-size:9px; font-weight:600; text-align:center; margin-top:4px;'>" + pos['label'] + "</div></div>"

    html = "<details open><summary style='color:" + _TEXT_MUTED + "; font-size:11px; cursor:pointer; font-weight:600; margin-bottom:6px;'>Plant Layout</summary>" + \
        "<div style='background:" + _BG_GRADIENT + "; border:1px solid " + _BORDER + "; border-radius:" + _CARD_RADIUS + \
        "; padding:12px; position:relative; height:250px; overflow:hidden;'>" + \
        "<div style='position:absolute; inset:0; opacity:0.1; background-image:linear-gradient(" + _BORDER + \
        " 1px, transparent 1px), linear-gradient(90deg, " + _BORDER + " 1px, transparent 1px); background-size:20px 20px;'></div>" + \
        zone_markers + \
        "<div style='position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.4); border:1px solid " + _BORDER + \
        "; border-radius:6px; padding:4px 8px;'>" + \
        "<div style='color:" + _TEXT_DIM + "; font-size:8px;'>Risk Legend</div>" + \
        "<div style='display:flex; gap:6px; font-size:8px;'>" + \
        "<span style='color:" + _ACCENT_GREEN + ";'>Safe</span>" + \
        "<span style='color:" + _ACCENT_YELLOW + ";'>Caution</span>" + \
        "<span style='color:" + _ACCENT_ORANGE + ";'>Elevated</span>" + \
        "<span style='color:" + _ACCENT_RED + ";'>Critical</span></div></div></div></details>" + \
        "<style>@keyframes mapPulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.12); } }</style>"

    st.markdown(html, unsafe_allow_html=True)


def render_zone_digital_twin_full() -> None:
    """Full digital twin view with synchronization header."""
    import streamlit as _st
    play_active = _st.session_state.get('sim_play_active', False)
    last_sync_str = _st.session_state.get('_last_sync_time', '--:--:--')

    sync_badge = (
        f"<span style='background:rgba(34,197,94,0.1); color:#22c55e; border:1px solid rgba(34,197,94,0.3); "
        f"border-radius:4px; padding:2px 8px; font-size:8px; font-weight:800;'>● LIVE SYNC</span>"
        if play_active else
        f"<span style='background:rgba(245,158,11,0.1); color:#f59e0b; border:1px solid rgba(245,158,11,0.3); "
        f"border-radius:4px; padding:2px 8px; font-size:8px; font-weight:800;'>⏸ CACHED — Last Updated {last_sync_str}</span>"
    )
    subtitle = (
        "Select a zone below to synchronize all live systems"
        if play_active else
        "Displaying last recorded sensor values — start Autoplay to sync live telemetry"
    )

    header_html = (
        "<div style='background:" + _BG_GRADIENT + "; border:1px solid " + _BORDER +
        "; border-radius:" + _CARD_RADIUS + "; padding:12px 14px; font-family:" + _FONT + "; margin-bottom:8px;'>" +
        "<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>" +
        "<div style='color:" + _TEXT_MUTED + "; font-size:11px; font-weight:600; letter-spacing:1px;'>INTERACTIVE PLANT DIGITAL TWIN</div>" +
        sync_badge +
        "</div>" +
        "<div style='color:" + _TEXT_DIM + "; font-size:10px;'>" + subtitle + "</div></div>"
    )
    _st.markdown(header_html, unsafe_allow_html=True)
    render_interactive_zone_map()
    render_digital_twin_panel()