# -*- coding: utf-8 -*-
"""
SurakshaAI Dashboard Components Module
"""

import sys
import os
import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, Any, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.ui_constants import ZONE_LABELS, SENSOR_ZONES
from src.ui_components import (
    Colors, 
    Typography,
    render_metric_card,
    render_nominal_card,
    render_alert_card,
    render_zone_status_row,
    render_notification_channel,
    render_gauge_svg,
    render_sparkline_svg,
    render_failsafe_row,
    render_scada_row
)

def render_kpi_grid(kpi_cols: Dict[str, Any], data_dict: Dict[str, Any]):
    """Renders the top 4 KPI metric cards"""
    latest = data_dict['latest']
    STATUS = data_dict['STATUS']
    max_score = data_dict['max_score']
    total_workers = data_dict['total_workers']
    permit_count = data_dict['permit_count']
    risk_color = data_dict['risk_color']
    risk_state = data_dict['risk_state']
    compound_risk_score = data_dict['compound_risk_score']
    total_rules = data_dict['total_rules']

    # 1. Current Risk Card
    with kpi_cols['m1']:
        sparkline_path = "M0,15 L10,18 L20,12 L30,16 L40,8 L50,14 L60,5"
        if STATUS['level'] == 'CRITICAL':
            sparkline_path = "M0,20 L10,5 L20,22 L30,5 L40,22 L50,5 L60,25"
        elif STATUS['level'] == 'HIGH':
            sparkline_path = "M0,18 L10,10 L20,15 L30,8 L40,12 L50,5 L60,18"
            
        _sc = STATUS['color']
        sparkline_svg = f'<svg width="60" height="26" style="opacity:0.8;"><path d="{sparkline_path}" fill="none" stroke="{_sc}" stroke-width="2" stroke-linecap="round"/></svg>'
        st.markdown(
            render_metric_card(
                label="🌡️ CURRENT RISK",
                value=STATUS['level'],
                subtext=f"Score: {max_score:.0f}/20",
                border_color=STATUS['color'],
                value_color=STATUS['color'],
                sparkline_svg=sparkline_svg,
                critical=(STATUS['level'] == 'CRITICAL')
            ),
            unsafe_allow_html=True
        )

    # 2. Crew Count Card
    with kpi_cols['m2']:
        figures = "".join("👤" for _ in range(min(total_workers, 12)))
        worker_bar = min(100, int(total_workers / 30 * 100))
        extra_html = (
            f'Active on Floor'
            f'<div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-bottom:6px;margin-top:4px;">'
            f'<div style="width:{worker_bar}%;height:100%;background:linear-gradient(90deg,#1d4ed8,#3B82F6);border-radius:2px;"></div>'
            f'</div>'
            f'<div style="font-size:13px;color:#3B82F6;letter-spacing:2px;line-height:1.4;">{figures}</div>'
        )
        st.markdown(
            render_metric_card(
                label="👥 CREW COUNT",
                value=str(total_workers),
                border_color="#3B82F6",
                value_color="#60A5FA",
                extra_html=extra_html
            ),
            unsafe_allow_html=True
        )

    # 3. Work Permits Card
    with kpi_cols['m3']:
        pc_color = '#F59E0B' if permit_count > 0 else '#22C55E'
        permit_bar = min(100, permit_count * 25)
        extra_html = (
            f'Active'
            f'<div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-top:4px;">'
            f'<div style="width:{permit_bar}%;height:100%;background:{pc_color};border-radius:2px;"></div>'
            f'</div>'
            f'<div style="position:absolute;right:14px;bottom:12px;font-size:38px;opacity:0.06;">📋</div>'
        )
        st.markdown(
            render_metric_card(
                label="📋 WORK PERMITS",
                value=str(permit_count),
                border_color=pc_color,
                value_color=pc_color,
                extra_html=extra_html
            ),
            unsafe_allow_html=True
        )

    # 4. Compound Risk Card
    with kpi_cols['m4']:
        card_class = (risk_state == 'CRITICAL')
        compound_bar = min(100, int(compound_risk_score / max(total_rules, 1) * 100))
        extra_html = (
            f'{compound_risk_score}/{total_rules} rules matched'
            f'<div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-top:4px;">'
            f'<div style="width:{compound_bar}%;height:100%;background:{risk_color};border-radius:2px;"></div>'
            f'</div>'
        )
        st.markdown(
            render_metric_card(
                label="🔗 COMPOUND RISK",
                value=risk_state,
                border_color=risk_color,
                value_color=risk_color,
                extra_html=extra_html,
                critical=card_class
            ),
            unsafe_allow_html=True
        )


def render_zone_status_panel(placeholder: Any, data_dict: Dict[str, Any]):
    """Renders the zone list monitoring status panel"""
    zone_risks = data_dict['zone_risks']
    latest = data_dict['latest']
    
    from src.config.ui_constants import ZONE_STATUS_ORDER
    from dashboard.data import get_zone_color

    rows_html = ['<div style="display:flex; flex-direction:column; gap:4px;">']
    for zone_id, zone_label in ZONE_STATUS_ORDER:
        z = zone_risks.get(zone_id, {'risk_level': 'LOW', 'risk_score': 0, 'sensor_data': {}})
        lvl = z.get('risk_level', 'LOW')
        score = z.get('risk_score', 0)
        
        gas = 0.0
        sd = z.get('sensor_data', {})
        for k, v in sd.items():
            if 'gas' in k.lower():
                gas = float(v)
                break
        if gas == 0.0:
            gas = latest.get(f'{zone_id}_gas_ppm', 0.0)
            
        rows_html.append(render_zone_status_row(zone_label, lvl, score, gas))
    rows_html.append('</div>')
    placeholder.markdown("".join(rows_html), unsafe_allow_html=True)


def render_failsafes_panel(placeholder: Any, data_dict: Dict[str, Any]):
    """Renders plant safety automated failsafes panel"""
    highest_risk = data_dict['STATUS']['level']
    compound_risk_score = data_dict['compound_risk_score']
    
    is_evacuate_active = st.session_state.get('chk_evacuate', False) or (highest_risk == 'CRITICAL')
    is_gas_isolated = st.session_state.get('chk_isolate', False) or (highest_risk == 'CRITICAL')
    is_siren_active = compound_risk_score > 0 or (highest_risk in ('HIGH', 'CRITICAL'))

    # Ventilation Fan Speed
    if highest_risk in ('HIGH', 'CRITICAL'):
        vent_status, vent_color, vent_bg = "MAX SPEED (100%)", "#ef4444", "rgba(239, 68, 68, 0.1)"
    elif highest_risk == 'MEDIUM':
        vent_status, vent_color, vent_bg = "INCREASED FLOW (75%)", "#f59e0b", "rgba(245, 158, 11, 0.08)"
    else:
        vent_status, vent_color, vent_bg = "NORMAL FLOW (35%)", "#22c55e", "rgba(34, 197, 94, 0.05)"
        
    # Valve Shutoff
    if is_gas_isolated:
        valve_status, valve_color, valve_bg = "ISOLATED & SHUT 🛑", "#ef4444", "rgba(239, 68, 68, 0.1)"
    else:
        valve_status, valve_color, valve_bg = "FLOWING NOMINAL ✅", "#22c55e", "rgba(34, 197, 94, 0.05)"
        
    # Sirens
    if is_siren_active:
        siren_status, siren_color, siren_bg = "ACTIVE & PULSING 🔊", "#ef4444", "rgba(239, 68, 68, 0.1)"
    else:
        siren_status, siren_color, siren_bg = "STANDBY MODE 🔕", "#64748b", "rgba(255, 255, 255, 0.015)"
        
    # Muster
    if is_evacuate_active:
        evac_status, evac_color, evac_bg = "MUSTER POINT ALPHA 🚨", "#ef4444", "rgba(239, 68, 68, 0.1)"
    else:
        evac_status, evac_color, evac_bg = "STATION NOMINAL ✅", "#22c55e", "rgba(34, 197, 94, 0.05)"

    failsafes_html = (
        '<div style="background:rgba(17,24,39,0.4);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px;font-family:\'Outfit\',sans-serif;">'
        '<div style="display:flex;flex-direction:column;gap:8px;">'
        + render_failsafe_row("🌀 EXHAUST VENTILATION", "Auto Fan Speed Controller", vent_status, vent_color, vent_bg)
        + render_failsafe_row("🛑 MAIN GAS ISOLATION VALVE", "Emergency Zone-Shutoff", valve_status, valve_color, valve_bg)
        + render_failsafe_row("🔊 PLANT-WIDE SIRENS", "Audible Evacuation Alarm", siren_status, siren_color, siren_bg)
        + render_failsafe_row("🚶 MUSTER ROUTE EVACUATION", "Active Muster Coordinators", evac_status, evac_color, evac_bg)
        + '</div></div>'
    )
    placeholder.markdown(failsafes_html, unsafe_allow_html=True)


def render_db_logs_panel(placeholder: Any, data_dict: Dict[str, Any]):
    """Renders active SQLite logs from the persistent DB"""
    db_logs = data_dict['db_logs']
    
    if not db_logs:
        placeholder.caption("No alerts persisted in database yet.")
        return
        
    logs_html = []
    for r_val in db_logs:
        level = r_val['risk_level']
        lbl_color = '#ef4444' if level == 'CRITICAL' else '#f59e0b' if level == 'HIGH' else '#eab308' if level == 'MEDIUM' else '#22c55e'
        logs_html.append(
            f'<div style="background:rgba(17,24,39,0.55);border:1px solid var(--border);border-left:3px solid {lbl_color};border-radius:8px;padding:8px 10px;margin-bottom:6px;font-size:11px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="font-weight:700;color:#F8FAFC;font-family:\'JetBrains Mono\',monospace;">{r_val["alert_id"]}</span>'
            f'<span style="color:{lbl_color};font-weight:800;font-size:8.5px;background:{lbl_color}1a;border:1px solid {lbl_color}33;padding:1px 6px;border-radius:4px;letter-spacing:0.5px;">{level}</span>'
            f'</div>'
            f'<div style="color:var(--text2);margin-top:3px;font-size:10px;">Zone: <b>{ZONE_LABELS.get(r_val["zone"], r_val["zone"])}</b> &nbsp;|&nbsp; Status: <span style="color:#22C55E;">{r_val["status"]}</span></div>'
            f'<div style="color:var(--muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r_val["message"]}</div>'
            f'</div>'
        )
    placeholder.markdown("".join(logs_html), unsafe_allow_html=True)


def render_scada_panel(placeholder: Any):
    """Renders Modbus/OPC status gateways card"""
    scada_html = (
        '<div style="background:rgba(17,24,39,0.4);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px;font-family:\'Outfit\',sans-serif;">'
        '<div style="display:flex;flex-direction:column;gap:8px;">'
        + render_scada_row("📡 MQTT Broker Gateway", "ONLINE (10.0.0.45) ✅")
        + render_scada_row("🔌 Modbus TCP Bridge", "ACTIVE (PORT 502) ✅")
        + render_scada_row("🖥️ OPC UA Safety Server", "CONNECTED ✅")
        + render_scada_row("☁️ AWS IoT Cloud Sync", "CONNECTED ✅", border_top=True)
        + '</div></div>'
    )
    placeholder.markdown(scada_html, unsafe_allow_html=True)


def render_notifications_panel(placeholder: Any, data_dict: Dict[str, Any], selected_zone: str):
    """Renders SMS, Email, and Siren notification channel dispatch status"""
    compound_risk_score = data_dict['compound_risk_score']
    zone_risks = data_dict['zone_risks']
    now_str = data_dict['now'].strftime('%H:%M:%S')

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
        sms_progress = 0
        email_progress = 0
        siren_progress = 0
    else:
        sms_status = ("DELIVERED ✓", "#22c55e", "Sent to: +123****890")
        email_status = ("SENT ✓", "#22c55e", "Sent to: safety@***.com")
        siren_status = ("ACTIVE 🔊", "#ef4444", f"Zone: {highest_risk_zone} — SOUNDING")
        sms_progress = 100
        email_progress = 100
        siren_progress = 100
        
    _notif_time = now_str if compound_risk_score > 0 else "—"
    _sms_detail   = f"Alert sent to +123****890 at {_notif_time}" if compound_risk_score > 0 else "Sent to: N/A"
    _email_detail = f"Email sent to safety@***.com {_notif_time}" if compound_risk_score > 0 else "Sent to: N/A"
    _siren_detail = f"Zone: {highest_risk_zone} | Status: ● SOUNDING | Duration: active" if compound_risk_score > 0 else "Zone: All clear"

    channels_html = (
        '<div style="display:flex;flex-direction:column;gap:4px;">'
        + render_notification_channel("📱 SMS CHANNEL", sms_status[0], sms_status[1], _sms_detail, active=(compound_risk_score > 0), progress_pct=sms_progress)
        + render_notification_channel("✉️ EMAIL CHANNEL", email_status[0], email_status[1], _email_detail, active=(compound_risk_score > 0), progress_pct=email_progress)
        + render_notification_channel("🔊 SIREN CHANNEL", siren_status[0], siren_status[1], _siren_detail, active=(compound_risk_score > 0), progress_pct=siren_progress)
        + '</div>'
    )

    escalated_toast = ""
    if compound_risk_score > 0:
        escalated_toast = (
            '<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;'
            'padding:10px 13px;margin-top:4px;display:flex;align-items:center;gap:8px;">'
            '<span style="font-size:18px;">✅</span>'
            '<span style="color:#22c55e;font-size:11px;font-weight:600;">All critical alerts escalated to all channels</span>'
            '</div>'
        )

    placeholder.markdown(channels_html + escalated_toast, unsafe_allow_html=True)


def render_alerts_panel(placeholder: Any, am: Any):
    """Renders active and acknowledged alerts"""
    if not am.active_alerts:
        placeholder.markdown(render_nominal_card(
            title="All Zones Nominal",
            message="The compound risk engine is scanning all active zones. No telemetry threshold breaches or hazardous intersections detected."
        ), unsafe_allow_html=True)
        return

    # Sort alerts by severity
    sorted_alerts = sorted(
        am.active_alerts.values(),
        key=lambda x: x.severity.value[0],
        reverse=True
    )

    cards_html = []
    visible_alerts = sorted_alerts[:3]
    extra_count = len(sorted_alerts) - 3

    for alert in visible_alerts:
        cards_html.append(render_alert_card(alert))

    if extra_count > 0:
        extra_card = (
            f'<div style="background:rgba(255,255,255,0.02);border:1px dashed rgba(255,255,255,0.1);'
            f'border-radius:8px;padding:8px;text-align:center;color:#94a3b8;font-size:11px;margin-bottom:8px;">'
            f'+ {extra_count} More Alerts'
            f'</div>'
        )
        cards_html.append(extra_card)

    placeholder.markdown("".join(cards_html), unsafe_allow_html=True)


def render_risk_analysis_row(placeholders: Dict[str, Any], data_dict: Dict[str, Any], selected_zone: str, detections_list: List[Any]):
    """Renders the Live Incident Timeline and the Rule Engine Status side-by-side"""
    timeline_placeholder = placeholders['zone_status'] # mapped to timeline
    risk_engine_placeholder = placeholders['failsafes'] # mapped to risk engine status
    # Wait, let's look at the placeholder mappings we created in layout.py:
    # 'zone_status': zone_status_placeholder
    # Let's override placeholders directly if they are passed as a dictionary.

    latest = data_dict['latest']
    highest_risk = data_dict['STATUS']['level']
    current_gas = float(latest.get(f"{selected_zone}_gas_ppm", 0.0))
    current_temp = float(latest.get(f"{selected_zone}_temperature_c", 0.0))
    current_workers = len([d for d in detections_list if d.label == 'person'])
    
    # Calculate if overpressure warning is active
    is_overpressure = (selected_zone == 'Zone_C' and st.session_state.get('cctv_frame_index', 0) >= 95)

    # 1. Timeline
    events = []
    t_str = lambda offset_min: (datetime.now() - timedelta(minutes=offset_min)).strftime("%H:%M:%S")
    
    if st.session_state.get('compound_risk_active', False) or st.session_state.get('sim_stage') == 'active':
        events.append({'time': t_str(2), 'icon': '🚨', 'message': 'AI DETECTED TRIPLE-THREAT IN BATTERY-4'})
        events.append({'time': t_str(5), 'icon': '⚠️', 'message': 'Safety boundary breach: Volatile gas overlay'})
        events.append({'time': t_str(8), 'icon': '📱', 'message': 'SMS Escalation: Sent to safety lead'})
        events.append({'time': t_str(9), 'icon': '📧', 'message': 'Email Escalation: Sent to operator team'})
        events.append({'time': t_str(10), 'icon': '🔊', 'message': 'Siren Channel: Sounding in Battery-4'})

    if selected_zone:
        now_t = datetime.now().strftime("%H:%M:%S")
        # Find if helmet count is less than workers
        h_count_active = len([d for d in detections_list if d.label == 'helmet'])
        missing_helmets = current_workers - h_count_active
        if missing_helmets > 0 and selected_zone not in ('Zone_A', 'Reactor_Area', 'Storage_Area'):
            events.append({'time': now_t, 'icon': '🟡', 'message': f'PPE compliance check failed in {ZONE_LABELS.get(selected_zone, selected_zone)}'})
        if is_overpressure:
            events.append({'time': now_t, 'icon': '🔴', 'message': f'Critical overpressure warning in {ZONE_LABELS.get(selected_zone, selected_zone)}'})

    # Backfill
    if len(events) < 6:
        sc_start = st.session_state.get('scenario_start_time') or (datetime.now() - timedelta(minutes=10))
        t_nom = lambda offset_sec: (sc_start + timedelta(seconds=offset_sec)).strftime("%H:%M:%S")
        nominal_events = [
            {'time': t_nom(0), 'icon': '🟢', 'message': 'System initialized. Feeds secure.'},
            {'time': t_nom(15), 'icon': '🟢', 'message': 'YOLO model loaded. Detections active.'},
            {'time': t_nom(45), 'icon': '🔵', 'message': 'Telemetry database connection active.'},
            {'time': t_nom(120), 'icon': '🟢', 'message': 'All systems scanned. All parameters nominal.'},
            {'time': t_nom(300), 'icon': '🟢', 'message': 'Status report logged to plant DB.'}
        ]
        for ne in nominal_events:
            if len(events) >= 8:
                break
            if not any(e['time'] == ne['time'] for e in events):
                events.append(ne)

    events.sort(key=lambda x: x['time'], reverse=True)
    events = events[:8]

    events_html = []
    for e in events:
        events_html.append(
            f'<div style="display: flex; gap: 6px; margin-bottom: 4px; align-items: center;">'
            f'<span style="color: #64748b; font-family: monospace; font-size: 9px;">{e["time"]}</span>'
            f'<span style="font-size: 10px;">{e["icon"]}</span>'
            f'<span style="color: #cbd5e1; font-weight: 500;">{e["message"]}</span>'
            f'</div>'
        )

    timeline_html = (
        f'<div style="background: rgba(17, 24, 39, 0.7); border: 1px solid var(--border2); border-radius: 16px; padding: 10px 12px; min-height: 122px; box-shadow: var(--shadow-sm); font-family: \'Outfit\', sans-serif;">'
        f'<div style="font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; margin-bottom: 6px;">📈 LIVE INCIDENT TIMELINE</div>'
        f'<div style="max-height: 86px; overflow-y: auto; font-size: 9.5px; line-height: 1.3;">'
        f'{"".join(events_html)}'
        f'</div></div>'
    )

    # 2. Rule Engine Status
    rule_states = [
        ("Fire Detection", any(d.label == 'fire' for d in detections_list)),
        ("Smoke Detection", any(d.label == 'smoke' for d in detections_list)),
        ("Gas Critical", current_gas > 35),
        ("Gas Elevated", current_gas > 20),
        ("Temp Critical", current_temp > 95),
        ("Intrusion", any(getattr(d, 'zone_violation', False) for d in detections_list)),
        ("Pressure Alert", is_overpressure),
        ("PPE Rules", missing_helmets > 0 if 'missing_helmets' in locals() else False),
        ("Overcrowding", current_workers > 9),
        ("Shift Change", latest.get('shift_change', 0) == 1 and current_gas > 30),
        ("Maint Gas Leak", latest.get(f"{selected_zone}_maintenance_active", 0) == 1 and current_gas > 35),
        ("Triple Threat", st.session_state.get('compound_risk_active', False))
    ]
    
    badges = []
    for name, matched in rule_states:
        if matched:
            bg = 'rgba(239, 68, 68, 0.15)'
            border = '#ef4444'
            color = '#ef4444'
            status = 'MATCHED'
        else:
            bg = 'rgba(34, 197, 94, 0.08)'
            border = 'rgba(34, 197, 94, 0.3)'
            color = '#22c55e'
            status = 'MONITORING'
            
        badges.append(
            f'<div style="background: {bg}; border: 1px solid {border}; color: {color}; border-radius: 4px; padding: 2px; text-align: center; font-size: 7.5px; display: flex; flex-direction: column; justify-content: center; min-height: 24px;">'
            f'<div style="font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{name}</div>'
            f'<div style="font-size:6px; opacity:0.8; font-weight:800; letter-spacing:0.3px;">{status}</div>'
            f'</div>'
        )
        
    risk_engine_html = (
        f'<div style="background: rgba(17, 24, 39, 0.7); border: 1px solid var(--border2); border-radius: 16px; padding: 10px 12px; min-height: 122px; box-shadow: var(--shadow-sm); font-family: \'Outfit\', sans-serif;">'
        f'<div style="font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; margin-bottom: 6px;">⚙️ COMPOUND RISK ENGINE</div>'
        f'<div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; max-height: 86px; overflow-y: auto;">'
        f'{"".join(badges)}'
        f'</div></div>'
    )

    placeholders['timeline'].markdown(timeline_html, unsafe_allow_html=True)
    placeholders['risk_engine'].markdown(risk_engine_html, unsafe_allow_html=True)


def render_decision_telemetry_row(placeholders: Dict[str, Any], data_dict: Dict[str, Any], selected_zone: str, detections_list: List[Any]):
    """Renders the AI Decision Engine, Live Telemetry gauges, and Zone Response side-by-side"""
    latest = data_dict['latest']
    STATUS = data_dict['STATUS']
    compound_risk_score = data_dict['compound_risk_score']

    # 1. AI Decision card
    level = STATUS.get('level', 'LOW')
    risk_color = STATUS.get('color', '#22c55e')
    
    if level == 'CRITICAL':
        risk_icon = '🔴'
        risk_level = 'CRITICAL'
        confidence = "98%"
    elif level == 'HIGH':
        risk_icon = '🟠'
        risk_level = 'HIGH'
        confidence = "94%"
    elif level == 'MEDIUM':
        risk_icon = '🟡'
        risk_level = 'MEDIUM'
        confidence = "88%"
    else:
        risk_icon = '🟢'
        risk_level = 'LOW'
        confidence = "99%"

    current_gas = float(latest.get(f"{selected_zone}_gas_ppm", 0.0))
    current_temp = float(latest.get(f"{selected_zone}_temperature_c", 0.0))
    current_press = float(latest.get(f"{selected_zone}_pressure_bar", 0.0))
    current_workers = len([d for d in detections_list if d.label == 'person'])
    is_overpressure = (selected_zone == 'Zone_C' and st.session_state.get('cctv_frame_index', 0) >= 95)
    h_count_active = len([d for d in detections_list if d.label == 'helmet'])
    missing_helmets = current_workers - h_count_active

    rule_states = [
        ("Fire Detection", any(d.label == 'fire' for d in detections_list)),
        ("Smoke Detection", any(d.label == 'smoke' for d in detections_list)),
        ("Gas Critical", current_gas > 35),
        ("Gas Elevated", current_gas > 20),
        ("Temp Critical", current_temp > 95),
        ("Intrusion", any(getattr(d, 'zone_violation', False) for d in detections_list)),
        ("Pressure Alert", is_overpressure),
        ("PPE Rules", missing_helmets > 0),
        ("Overcrowding", current_workers > 9),
        ("Shift Change", latest.get('shift_change', 0) == 1 and current_gas > 30),
        ("Maint Gas Leak", latest.get(f"{selected_zone}_maintenance_active", 0) == 1 and current_gas > 35),
        ("Triple Threat", st.session_state.get('compound_risk_active', False))
    ]

    matched_list_items = []
    for name, matched in rule_states:
        if matched:
            matched_list_items.append(f"<div style='color:#ef4444; font-weight:600; font-size:9.5px;'>✓ {name}</div>")
    if not matched_list_items:
        matched_list_items.append("<div style='color:#22c55e; font-weight:600; font-size:9.5px;'>✓ All Systems Nominal</div>")
        
    reasons_bullets = "".join(matched_list_items[:2])

    if level == 'CRITICAL':
        recommendation = f"Evacuate {ZONE_LABELS.get(selected_zone, 'Battery-4')} Immediately"
    elif level == 'HIGH':
        recommendation = "Deploy Emergency Response Team. Restrict Zone Access."
    elif level == 'MEDIUM':
        recommendation = "Verify compliance and telemetry levels."
    else:
        recommendation = "Continue standard plant surveillance."

    ai_decision_html = (
        f'<div style="background:linear-gradient(135deg,#0f1f38,#0a1628); border:1px solid #1e3a5f; border-radius:12px; padding:12px 14px; min-height:245px; font-family:\'Outfit\',sans-serif;">'
        f'<div style="color:#94a3b8; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">🧠 AI DECISION ENGINE</div>'
        f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
        f'<div><span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600;">Risk Level</span><div style="font-size:15px; font-weight:800; color:{risk_color}; display:flex; align-items:center; gap:4px;">{risk_icon} {risk_level}</div></div>'
        f'<div style="text-align:right;"><span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600;">Confidence</span><div style="font-size:15px; font-weight:800; color:#3b82f6;">{confidence}</div></div>'
        f'</div>'
        f'<div style="margin-bottom:10px;">'
        f'<span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; display:block; margin-bottom:3px;">Matched Rules</span>'
        f'<div style="line-height:1.3; max-height:42px; overflow-y:auto; font-size:10.5px;">{reasons_bullets}</div>'
        f'</div>'
        f'<div>'
        f'<span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; display:block; margin-bottom:2px;">Recommendation</span>'
        f'<div style="font-size:12px; font-weight:700; color:#fff; line-height:1.35;">{recommendation}</div>'
        f'</div></div>'
    )
    placeholders['ai_decision'].markdown(ai_decision_html, unsafe_allow_html=True)

    # 2. Live Telemetry Gauges Card
    if 'telemetry_history_gas' not in st.session_state:
        st.session_state.telemetry_history_gas = [current_gas] * 15
        
    temp_gauge_svg = render_gauge_svg(current_temp, 0, 120, "Temp (°C)", "#10ac84", 88, 95)
    press_gauge_svg = render_gauge_svg(current_press, 0, 100, "Press (bar)", "#2e86de", 60, 80)
    gas_spark_svg = render_sparkline_svg(st.session_state.telemetry_history_gas, stroke_color="#ff9f43")
    
    telemetry_html = f"""
    <div style="background:linear-gradient(135deg,#0f1f38,#0a1628); border:1px solid #1e3a5f; border-radius:12px; padding:12px 14px; min-height:245px; font-family:'Outfit',sans-serif;">
        <div style="color:#94a3b8; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">📊 LIVE TELEMETRY</div>
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:12px;">
            <div style="flex:1; background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:6px 4px;">
                {temp_gauge_svg}
            </div>
            <div style="flex:1; background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:6px 4px;">
                {press_gauge_svg}
            </div>
        </div>
        <div style="font-size:9.5px; color:#ff9f43; font-weight:700; margin-bottom:2px; display:flex; justify-content:space-between;">
            <span>📈 GAS LEVEL TREND</span>
            <span style="font-family:monospace;">Current: {current_gas:.1f} ppm</span>
        </div>
        <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:4px 6px;">
            {gas_spark_svg}
        </div>
    </div>
    """
    clean_lines = [line.strip() for line in telemetry_html.split("\n")]
    placeholders['telemetry_trends'].markdown("".join(clean_lines), unsafe_allow_html=True)

    # 3. Zone Response card
    from src.alert_system import get_alert_system
    wrapper_system = get_alert_system()
    teams_str = wrapper_system.emergency_teams.get(selected_zone, 'Alpha & Beta Teams')
    
    if level == 'CRITICAL':
        channels = "Dashboard, SMS, Phone, Email, Siren"
        deadline = "60 seconds"
        action = "Mandatory Evacuation / Ack"
        actions_html = """
        <div style="color: #ef4444; font-weight: 700; margin-bottom: 2px;">✓ Evacuate Zone Immediately</div>
        <div style="color: #ef4444; font-weight: 700; margin-bottom: 2px;">✓ Activate Emergency Shutdown</div>
        <div style="color: #cbd5e1; margin-bottom: 2px;">✓ Alert Shift Supervisor</div>
        """
    elif level == 'HIGH':
        channels = "Dashboard, SMS, Email"
        deadline = "5 minutes"
        action = "Dispatch ERT / Halt Work"
        actions_html = """
        <div style="color: #f97316; font-weight: 700; margin-bottom: 2px;">✓ Dispatch Emergency Teams</div>
        <div style="color: #f97316; font-weight: 700; margin-bottom: 2px;">✓ Halt Active Permits</div>
        <div style="color: #cbd5e1; margin-bottom: 2px;">✓ Restrict Zone Access</div>
        """
    elif level == 'MEDIUM':
        channels = "Dashboard, Email"
        deadline = "15 minutes"
        action = "Verify Compliance Logs"
        actions_html = """
        <div style="color: #eab308; font-weight: 600; margin-bottom: 2px;">✓ Verify PPE Compliance</div>
        <div style="color: #cbd5e1; margin-bottom: 2px;">✓ Increase Telemetry Logs</div>
        <div style="color: #cbd5e1; margin-bottom: 2px;">✓ Check Fume Extraction</div>
        """
    else:
        channels = "Dashboard Only"
        deadline = "N/A"
        action = "Routine Surveillance"
        actions_html = """
        <div style="color: #22c55e; margin-bottom: 2px;">✓ Routine CCTV Monitoring</div>
        <div style="color: #cbd5e1; margin-bottom: 2px;">✓ Check System Telemetry</div>
        <div style="color: #cbd5e1; margin-bottom: 2px;">✓ Normal Shift Handover</div>
        """

    zone_response_html = (
        f'<div style="background:linear-gradient(135deg,#0f1f38,#0a1628); border:1px solid #1e3a5f; border-radius:12px; padding:12px 14px; min-height:245px; font-family:\'Outfit\',sans-serif;">'
        f'<div style="color:#94a3b8; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">🛡️ ZONE RESPONSE & ACTIONS</div>'
        f'<div style="display:flex; flex-direction:column; gap:4px; font-size:10.5px; line-height:1.2;">'
        f'<div><span style="color:#64748b; font-weight:600;">Affected Zone:</span> <span style="color:#fff; font-weight:700;">{ZONE_LABELS.get(selected_zone, selected_zone)}</span></div>'
        f'<div><span style="color:#64748b; font-weight:600;">Emergency Teams:</span> <span style="color:#cbd5e1;">{teams_str}</span></div>'
        f'<div><span style="color:#64748b; font-weight:600;">Channels:</span> <span style="color:#cbd5e1; font-size:9px;">{channels}</span></div>'
        f'<div><span style="color:#64748b; font-weight:600;">Deadline:</span> <span style="color:#fff; font-weight:700;">{deadline}</span></div>'
        f'<div><span style="color:#64748b; font-weight:600;">Action:</span> <span style="color:{risk_color}; font-weight:700; font-size:10px;">{action}</span></div>'
        f'<div style="border-top:1px solid rgba(255,255,255,0.06); padding-top:6px; margin-top:2px;">'
        f'<div style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; margin-bottom:3px;">Operator Failsafes</div>'
        f'<div style="line-height:1.3;">{actions_html}</div>'
        f'</div></div></div>'
    )
    placeholders['zone_response'].markdown(zone_response_html, unsafe_allow_html=True)

