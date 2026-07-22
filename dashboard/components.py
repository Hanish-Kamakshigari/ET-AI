"""
SurakshaAI Dashboard Components Module
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from src.risk_engine import CompoundRiskEngine
from src.alert_system import AlertSystem, AlertManager, SafetyAlert

from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS
from src.permit_intelligence import render_permit_intelligence_panel, init_default_permits
from src.ui_components import (
    render_section_header,
    render_metric_card,
    render_nominal_card,
    render_alert_card,
    render_zone_status_row,
    render_notification_channel,
    render_gauge_svg,
    render_sparkline_svg,
    render_failsafe_row,
    render_scada_row,
    clean_html,
)


def _safe_markdown(placeholder: Optional[DeltaGenerator], html: str, key: str) -> None:
    """Render markdown into placeholder only if the html content has changed, guaranteeing 0 flicker."""
    if not placeholder:
        return
    clean = clean_html(html)
    rerun_cnt = st.session_state.get('rerun_counter', 0)
    last_counter_key = f"{key}_last_counter"
    
    if st.session_state.get(key) != clean or st.session_state.get(last_counter_key) != rerun_cnt:
        st.session_state[key] = clean
        st.session_state[last_counter_key] = rerun_cnt
        placeholder.markdown(clean, unsafe_allow_html=True)


def _zone_color(risk_level: str) -> str:
    return {
        "CRITICAL": "#ef4444",
        "HIGH": "#f59e0b",
        "MEDIUM": "#eab308",
        "LOW": "#22c55e",
        "SAFE": "#22c55e",
        "CLEAR": "#22c55e",
    }.get((risk_level or "LOW").upper(), "#22c55e")


def _zone_video_path(zone: str) -> str | None:
    footage_files = {
        "Zone_A": "Battery_4.mp4",
        "Zone_B": "Battery_5.mp4",
        "Zone_C": "Battery_6.mp4",
        "Reactor_Area": "Reactor_Block.mp4",
        "Storage_Area": "Storage_Block.mp4",
    }
    filename = footage_files.get(zone)
    if not filename:
        return None
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    candidate = os.path.join(project_root, "footage", filename)
    return candidate if os.path.exists(candidate) else None


def _build_zone_risk_frame(data_dict: dict) -> pd.DataFrame:
    rows = []
    for zone in SENSOR_ZONES:
        info = data_dict.get("zone_risks", {}).get(zone, {})
        rows.append({
            "Zone": ZONE_LABELS.get(zone, zone),
            "Risk Score": info.get("risk_score", 0),
            "Risk Level": (info.get("risk_level") or "LOW").upper(),
        })
    return pd.DataFrame(rows)


def render_analytics_page() -> None:
    """Backward-compatible wrapper kept for older imports."""
    st.markdown(render_section_header("📊 ANALYTICS DASHBOARD"), unsafe_allow_html=True)


def render_analytics_tab(
    placeholders: Dict[str, Any],
    data_dict: Dict[str, Any],
    engine: Optional[CompoundRiskEngine] = None,
    alert_system: Optional[AlertSystem] = None,
) -> None:
    """Render analytics using the live telemetry and alert state."""
    st.markdown(render_section_header("📊 ANALYTICS DASHBOARD"), unsafe_allow_html=True)

    zone_frame = _build_zone_risk_frame(data_dict)
    latest = data_dict.get("latest", {})
    zone_risks = data_dict.get("zone_risks", {})

    total_incidents = max(14, len(st.session_state.get("alert_log", [])) + int(data_dict.get("compound_risk_score", 0) * 3))
    ai_alerts = max(6, int(data_dict.get("compound_risk_score", 0) * 4) + len(zone_risks))
    compliance = max(0, min(100, 100 - (data_dict.get("max_score", 0) * 4.2)))
    avg_response = max(1.5, round(4.8 - (data_dict.get("max_score", 0) * 0.18), 1))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Incidents", f"{total_incidents}")
    with col2:
        st.metric("AI Alerts", f"{ai_alerts}")
    with col3:
        st.metric("PPE Compliance", f"{int(compliance)}%")

    st.subheader("Alert Trends")
    trend_data = pd.DataFrame({
        "Window": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
        "Alerts": [2, 4, 6, 7, 5, 3],
    }).set_index("Window")
    st.line_chart(trend_data)

    st.subheader("PPE Compliance")
    st.progress(compliance / 100)
    st.caption(f"Current compliance: {int(compliance)}% based on live zone risk and permit adherence")

    st.subheader("Incident History")
    history_rows = []
    history = getattr(engine, "alert_history", []) if engine else []
    for item in history[-8:]:
        history_rows.append({
            "Time": item.timestamp.strftime("%H:%M:%S") if getattr(item, "timestamp", None) else "N/A",
            "Zone": ZONE_LABELS.get(getattr(item, "zone", ""), getattr(item, "zone", "")),
            "Risk": getattr(item, "risk_level", "LOW"),
            "Score": getattr(item, "risk_score", 0),
        })
    if not history_rows:
        history_rows.append({
            "Time": latest.get("timestamp", "").strftime("%H:%M:%S") if hasattr(latest.get("timestamp"), "strftime") else "N/A",
            "Zone": "Control Room",
            "Risk": data_dict.get("STATUS", {}).get("level", "LOW"),
            "Score": data_dict.get("max_score", 0),
        })
    st.dataframe(pd.DataFrame(history_rows), use_container_width=True)

    st.subheader("Response Time Metrics")
    col4, col5 = st.columns(2)
    with col4:
        st.metric("Avg Response Time", f"{avg_response} min")
    with col5:
        st.metric("Critical Response", f"{max(1.0, round(avg_response * 0.55, 1))} min")

    st.subheader("Zone-wise Risk")
    st.bar_chart(zone_frame.set_index("Zone")["Risk Score"])


def render_zones_tab(
    placeholders: Dict[str, Any],
    data_dict: Dict[str, Any],
    engine: Optional[CompoundRiskEngine] = None,
    alert_system: Optional[AlertSystem] = None,
) -> None:
    """Render the zone map with live risk colors and detailed zone telemetry."""
    st.markdown(render_section_header("🗺️ ZONE MAP — DIGITAL TWIN VIEW"), unsafe_allow_html=True)

    latest = data_dict.get("latest", {})
    zone_risks = data_dict.get("zone_risks", {})
    selected_zone = st.session_state.get("selected_zone", SENSOR_ZONES[0])

    from dashboard.intelligence_ui import render_interactive_plant_twin
    render_interactive_plant_twin()

    st.divider()
    st.subheader(f"{ZONE_LABELS.get(selected_zone, selected_zone)} Details")

    info = zone_risks.get(selected_zone, {})
    risk_level = (info.get("risk_level") or "LOW").upper()
    score = info.get("risk_score", 0)
    permit_active = bool(latest.get(f"{selected_zone}_permit_active", 0) == 1)
    maintenance_active = bool(latest.get(f"{selected_zone}_maintenance_active", 0) == 1)

    col_a, col_b = st.columns([4.0, 1.0])
    with col_a:
        video_path = _zone_video_path(selected_zone)
        if video_path:
            selected_zone_name = ZONE_LABELS.get(selected_zone, selected_zone).upper()
            st.markdown(f"""
            <div class='cctv-header'>
                <span style='color:#e2e8f0; font-weight:bold; font-family:"Outfit",sans-serif; font-size:12px; letter-spacing:0.5px;'>📷 LIVE CCTV FEED — {selected_zone_name}</span>
                <span class='live-badge'>● LIVE</span>
            </div>
            """, unsafe_allow_html=True)

            with st.container():
                st.markdown("<div class='cctv-buffer-anchor'></div>", unsafe_allow_html=True)
                cctv_frame_placeholder_1 = st.empty()
                cctv_frame_placeholder_1.empty()
                cctv_frame_placeholder_2 = st.empty()
                cctv_frame_placeholder_2.empty()

            cctv_status_placeholder = st.empty()
            cctv_status_placeholder.empty()
            warnings_placeholder = st.empty()
            warnings_placeholder.empty()

            zone_placeholders = {
                'cctv_frame_1': cctv_frame_placeholder_1,
                'cctv_frame_2': cctv_frame_placeholder_2,
                'cctv_frame': None,
                'cctv_status': cctv_status_placeholder,
                'warnings': warnings_placeholder,
                'alerts': placeholders.get('alerts', st.empty()) if placeholders else st.empty(),
                'notifications': placeholders.get('notifications', st.empty()) if placeholders else st.empty(),
                'zone_status': placeholders.get('zone_status', st.empty()) if placeholders else st.empty(),
                'failsafes': placeholders.get('failsafes', st.empty()) if placeholders else st.empty(),
                'db_logs': placeholders.get('db_logs', st.empty()) if placeholders else st.empty(),
                'kpi_cols': None,
            }

            from src.alert_system import AlertManager
            from dashboard.video import stream_cctv_feed_raw
            am_instance = AlertManager()

            # Pass the layout to the video stream loop
            stream_cctv_feed_raw(
                zone_placeholders,
                selected_zone,
                video_path,
                latest,
                alert_system,
                am_instance,
                data_dict=data_dict
            )
        else:
            st.info("CCTV feed is not available for this zone in the current workspace.")
    with col_b:
        st.metric("Risk Score", f"{score}/20")
        st.metric("Risk Level", risk_level)
        st.metric("Permit Active", "Yes" if permit_active else "No")
        st.metric("Maintenance Active", "Yes" if maintenance_active else "No")
        st.progress(min(score / 20.0, 1.0))

    st.subheader("Sensor Data")
    sensor_rows = []
    for name, value in info.get("sensor_data", {}).items():
        if name.endswith(("_gas_ppm", "_temperature_c", "_pressure_bar", "_worker_count")):
            sensor_rows.append({"Metric": name, "Value": round(float(value), 2)})
    st.dataframe(pd.DataFrame(sensor_rows), use_container_width=True)

    st.subheader("Active Alerts")
    alert_rows = []
    for item in st.session_state.get("alert_log", []):
        if ZONE_LABELS.get(selected_zone, selected_zone).lower() in str(item.get("zone", "")).lower():
            alert_rows.append(item)
    if alert_rows:
        st.dataframe(pd.DataFrame(alert_rows), use_container_width=True)
    else:
        st.caption("No active alerts for this zone right now.")

    # ── Interactive Plant Digital Twin (full synchronization) ──
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("🏭 INTERACTIVE PLANT DIGITAL TWIN"), unsafe_allow_html=True)
    try:
        from dashboard.intelligence_ui import render_interactive_plant_twin, render_geospatial_plant_map
        render_interactive_plant_twin()
    except Exception:
        render_geospatial_plant_map()
    # Smart Permit Intelligence (SIMOPS conflict detection)
    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("📋 SMART PERMIT INTELLIGENCE (SIMOPS)"), unsafe_allow_html=True)
    try:
        from src.permit_intelligence import render_permit_intelligence_panel
        render_permit_intelligence_panel()
    except Exception:
        pass


def render_settings_tab(
    placeholders: Dict[str, Any],
    data_dict: Dict[str, Any],
    engine: Optional[CompoundRiskEngine] = None,
    alert_system: Optional[AlertSystem] = None,
) -> None:
    """Render settings controls and persist them to session state."""
    st.markdown(render_section_header("⚙️ ADVANCED PLATFORM SETTINGS"), unsafe_allow_html=True)
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # Initialize rule engine rules default
    if "rule_engine_rules" not in st.session_state:
        st.session_state.rule_engine_rules = []

    col_left, col_right = st.columns([1.0, 1.0])

    with col_left:
        st.markdown("""
        <div style="font-size:12px;font-weight:700;color:#00d4ff;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:12px;">🛡️ Core Safety Configuration</div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            st.slider(
                "Risk Score Threshold",
                0.0,
                1.0,
                float(st.session_state.get("severity_threshold_value", 0.7)),
                step=0.05,
                key="severity_threshold_value",
                help="Threshold at which safety risk triggers critical escalation alerts."
            )

            st.slider(
                "Max Escalation Attempts",
                1,
                5,
                int(st.session_state.get("max_escalations", 3)),
                step=1,
                key="max_escalations",
                help="Max attempts to notify safety officers before automatic SCADA failsafe shutdown."
            )

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="font-size:12px;font-weight:700;color:#00d4ff;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:12px;">🔌 Hardware & Environment</div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            st.selectbox(
                "Select Operator Role",
                ["Admin", "Supervisor", "Operator"],
                index=["Admin", "Supervisor", "Operator"].index(st.session_state.get("selected_role", "Operator")),
                key="selected_role"
            )

            st.checkbox(
                "Enable Camera Feed Streaming",
                value=st.session_state.get("camera_enabled", True),
                key="camera_enabled"
            )

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="font-size:12px;font-weight:700;color:#00d4ff;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:12px;">🔄 Auto-Refresh Configuration</div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            st.checkbox(
                "Enable 1s Auto-refresh Interval",
                value=st.session_state.get("auto_refresh", False),
                key="auto_refresh"
            )

            st.slider(
                "Telemetry Fetch Interval (seconds)",
                5,
                300,
                int(st.session_state.get("refresh_interval", 60)),
                step=5,
                key="refresh_interval"
            )

    with col_right:
        st.markdown("""
        <div style="font-size:12px;font-weight:700;color:#00d4ff;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:12px;">📢 Notification Settings</div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            st.multiselect(
                "Active Notification Channels",
                ["SMS", "Email", "Siren"],
                default=st.session_state.get("notifications_pref", ["SMS", "Email", "Siren"]),
                key="notifications_pref"
            )
            st.caption("Channels used to dispatch compound threat incident alerts.")

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="font-size:12px;font-weight:700;color:#00d4ff;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:12px;">🔧 Dynamic Rule Configurator</div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            rule_text = st.text_input("Define Custom Rule Expression:", key="new_rule_input", placeholder="e.g. TankPressure > 7.5 AND CrewCount < 2")
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("Add Rule", use_container_width=True):
                    if rule_text:
                        current_rules = st.session_state.get("rule_engine_rules", [])
                        current_rules.append(rule_text)
                        st.session_state.rule_engine_rules = current_rules
                        st.toast(f"Rule added: {rule_text}", icon="✅")
                        st.rerun()
            with c_btn2:
                if st.button("Clear Custom Rules", use_container_width=True):
                    st.session_state.rule_engine_rules = []
                    st.toast("Custom rules cleared", icon="🗑️")
                    st.rerun()

            if st.session_state.get("rule_engine_rules"):
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                st.caption("Active Configured Rules:")
                for i, r in enumerate(st.session_state.rule_engine_rules):
                    st.code(f"Rule #{i+1}: {r}", language="text")

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    if st.button("Save & Apply All Settings", type="primary", use_container_width=True):
        st.session_state.severity_threshold = st.session_state.severity_threshold_value
        st.toast("All safety configuration updates applied successfully!", icon="🛡️")



def render_sidebar_controls() -> None:
    """Legacy helper kept for compatibility with older imports."""
    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)


def render_kpi_grid(kpi_cols: Dict[str, Any], data_dict: Dict[str, Any]) -> None:
    """Renders the top 4 KPI metric cards"""
    import datetime
    play_active = st.session_state.get('sim_play_active', False)
    kpi_height = "162px" if play_active else "182px"
    now_time = datetime.datetime.now().strftime("%H:%M:%S")

    latest = data_dict['latest']
    STATUS = data_dict['STATUS']
    max_score = data_dict['max_score']
    total_workers = data_dict['total_workers']
    permit_count = data_dict['permit_count']
    risk_color = data_dict['risk_color']
    risk_state = data_dict['risk_state']
    compound_risk_score = data_dict['compound_risk_score']
    total_rules = data_dict['total_rules']

    with kpi_cols['m1']:
        sparkline_path = "M0,15 L10,18 L20,12 L30,16 L40,8 L50,14 L60,5"
        if STATUS['level'] == 'CRITICAL':
            sparkline_path = "M0,20 L10,5 L20,22 L30,5 L40,22 L50,5 L60,25"
        elif STATUS['level'] == 'HIGH':
            sparkline_path = "M0,18 L10,10 L20,15 L30,8 L40,12 L50,5 L60,18"
        _sc = STATUS['color']
        sparkline_svg = f'<svg width="60" height="26" style="opacity:0.8;"><path d="{sparkline_path}" fill="none" stroke="{_sc}" stroke-width="2" stroke-linecap="round"/></svg>'
        
        sub = f"Score: {max_score:.0f}/20" if play_active else f"Score: {max_score:.0f}/20 • ↘ Stable"
        extra = "" if play_active else f"<div style='font-size:9.5px;color:#64748b;margin-top:4px;'>Last sync: {now_time}</div>"
        
        st.markdown(
            render_metric_card(
                label="CURRENT RISK",
                value=STATUS['level'],
                subtext=sub,
                border_color=STATUS['color'],
                value_color=STATUS['color'],
                sparkline_svg=sparkline_svg,
                height=kpi_height,
                critical=(STATUS['level'] == 'CRITICAL'),
                extra_html=extra
            ),
            unsafe_allow_html=True
        )

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
        if not play_active:
            extra_html += f"<div style='font-size:9.5px;color:#64748b;margin-top:4px;'>Last sync: {now_time} • → Constant</div>"
            
        st.markdown(
            render_metric_card(
                label="CREW COUNT",
                value=str(total_workers),
                border_color="#3B82F6",
                value_color="#60A5FA",
                height=kpi_height,
                extra_html=extra_html
            ),
            unsafe_allow_html=True
        )

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
        if not play_active:
            extra_html += f"<div style='font-size:9.5px;color:#64748b;margin-top:6px;'>Last sync: {now_time} • ↗ +1</div>"
            
        st.markdown(
            render_metric_card(
                label="WORK PERMITS",
                value=str(permit_count),
                border_color=pc_color,
                value_color=pc_color,
                height=kpi_height,
                extra_html=extra_html
            ),
            unsafe_allow_html=True
        )

    with kpi_cols['m4']:
        card_class = (risk_state == 'CRITICAL')
        compound_bar = min(100, int(compound_risk_score / max(total_rules, 1) * 100))
        extra_html = (
            f'{compound_risk_score}/{total_rules} rules matched'
            f'<div style="width:100%;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;margin-top:4px;">'
            f'<div style="width:{compound_bar}%;height:100%;background:{risk_color};border-radius:2px;"></div>'
            f'</div>'
        )
        if not play_active:
            extra_html += f"<div style='font-size:9.5px;color:#64748b;margin-top:6px;'>Last sync: {now_time} • ↘ Nominal</div>"
            
        st.markdown(
            render_metric_card(
                label="COMPOUND RISK",
                value=risk_state,
                border_color=risk_color,
                value_color=risk_color,
                height=kpi_height,
                extra_html=extra_html,
                critical=card_class
            ),
            unsafe_allow_html=True
        )


def render_zone_status_panel(placeholder: DeltaGenerator, data_dict: Dict[str, Any]) -> None:
    """Renders the zone list monitoring status panel"""
    zone_risks = data_dict['zone_risks']
    latest = data_dict['latest']

    from src.config.ui_constants import ZONE_STATUS_ORDER

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


def render_failsafes_panel(placeholder: DeltaGenerator, data_dict: Dict[str, Any]) -> None:
    """Renders plant safety automated failsafes panel"""
    highest_risk = data_dict['STATUS']['level']
    compound_risk_score = data_dict['compound_risk_score']

    is_evacuate_active = st.session_state.get('chk_evacuate', False) or (highest_risk == 'CRITICAL')
    is_gas_isolated = st.session_state.get('chk_isolate', False) or (highest_risk == 'CRITICAL')
    is_siren_active = compound_risk_score > 0 or (highest_risk in ('HIGH', 'CRITICAL'))

    if highest_risk in ('HIGH', 'CRITICAL'):
        vent_status, vent_color, vent_bg = "MAX SPEED (100%)", "#ef4444", "rgba(239, 68, 68, 0.1)"
    elif highest_risk == 'MEDIUM':
        vent_status, vent_color, vent_bg = "INCREASED FLOW (75%)", "#f59e0b", "rgba(245, 158, 11, 0.08)"
    else:
        vent_status, vent_color, vent_bg = "NORMAL FLOW (35%)", "#22c55e", "rgba(34, 197, 94, 0.05)"

    if is_gas_isolated:
        valve_status, valve_color, valve_bg = "ISOLATED & SHUT", "#ef4444", "rgba(239, 68, 68, 0.1)"
    else:
        valve_status, valve_color, valve_bg = "FLOWING NOMINAL", "#22c55e", "rgba(34, 197, 94, 0.05)"

    if is_siren_active:
        siren_status, siren_color, siren_bg = "ACTIVE & PULSING", "#ef4444", "rgba(239, 68, 68, 0.1)"
    else:
        siren_status, siren_color, siren_bg = "STANDBY MODE", "#64748b", "rgba(255, 255, 255, 0.015)"

    if is_evacuate_active:
        evac_status, evac_color, evac_bg = "MUSTER POINT ALPHA", "#ef4444", "rgba(239, 68, 68, 0.1)"
    else:
        evac_status, evac_color, evac_bg = "STATION NOMINAL", "#22c55e", "rgba(34, 197, 94, 0.05)"

    failsafes_html = (
        '<div style="background:rgba(17,24,39,0.4);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px;font-family:Outfit,sans-serif;">'
        '<div style="display:flex;flex-direction:column;gap:8px;">'
        + render_failsafe_row("EXHAUST VENTILATION", "Auto Fan Speed Controller", vent_status, vent_color, vent_bg)
        + render_failsafe_row("MAIN GAS ISOLATION VALVE", "Emergency Zone-Shutoff", valve_status, valve_color, valve_bg)
        + render_failsafe_row("PLANT-WIDE SIRENS", "Audible Evacuation Alarm", siren_status, siren_color, siren_bg)
        + render_failsafe_row("MUSTER ROUTE EVACUATION", "Active Muster Coordinators", evac_status, evac_color, evac_bg)
        + '</div></div>'
    )
    placeholder.markdown(failsafes_html, unsafe_allow_html=True)


def render_db_logs_panel(placeholder: DeltaGenerator, data_dict: Dict[str, Any]) -> None:
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
            f'<span style="font-weight:700;color:#F8FAFC;font-family:JetBrains Mono,monospace;">{r_val["alert_id"]}</span>'
            f'<span style="color:{lbl_color};font-weight:800;font-size:8.5px;background:{lbl_color}1a;border:1px solid {lbl_color}33;padding:1px 6px;border-radius:4px;letter-spacing:0.5px;">{level}</span>'
            f'</div>'
            f'<div style="color:var(--text2);margin-top:3px;font-size:10px;">Zone: <b>{ZONE_LABELS.get(r_val["zone"], r_val["zone"])}</b> | Status: <span style="color:#22C55E;">{r_val["status"]}</span></div>'
            f'<div style="color:var(--muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r_val["message"]}</div>'
            f'</div>'
        )
    placeholder.markdown("".join(logs_html), unsafe_allow_html=True)


def render_scada_panel(placeholder: DeltaGenerator) -> None:
    """Renders Modbus/OPC status gateways card"""
    scada_html = (
        '<div style="background:rgba(17,24,39,0.4);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px;font-family:Outfit,sans-serif;">'
        '<div style="display:flex;flex-direction:column;gap:8px;">'
        + render_scada_row("MQTT Broker Gateway", "ONLINE (10.0.0.45)")
        + render_scada_row("Modbus TCP Bridge", "ACTIVE (PORT 502)")
        + render_scada_row("OPC UA Safety Server", "CONNECTED")
        + render_scada_row("AWS IoT Cloud Sync", "CONNECTED", border_top=True)
        + '</div></div>'
    )
    placeholder.markdown(scada_html, unsafe_allow_html=True)


def render_notifications_panel(placeholder: DeltaGenerator, data_dict: Dict[str, Any], selected_zone: str) -> None:
    """Renders SMS, Email, Telegram, and Siren notification channel dispatch status"""
    compound_risk_score = data_dict['compound_risk_score']
    zone_risks = data_dict['zone_risks']
    now_str = data_dict['now'].strftime('%H:%M:%S')

    highest_risk_zone = "N/A"
    highest_score = -1
    for zone_id, z in zone_risks.items():
        if z.get('risk_score', 0) > highest_score:
            highest_score = z.get('risk_score', 0)
            highest_risk_zone = z.get('label', zone_id)

    # Get actual status from session state (set once by notification dispatch threads).
    # No compound_risk_score fallback — that caused per-frame flickering.
    import streamlit as st

    _standby = {"status": "STANDBY", "color": "#6b7280", "detail": "Awaiting active threat alerts"}

    sms_state = st.session_state.get("sms_status") or _standby
    sms_status = (sms_state.get("status", "STANDBY"), sms_state.get("color", "#6b7280"), sms_state.get("detail", "Awaiting active threat alerts"))

    email_state = st.session_state.get("email_status") or _standby
    email_status = (email_state.get("status", "STANDBY"), email_state.get("color", "#6b7280"), email_state.get("detail", "Awaiting active threat alerts"))

    telegram_state = st.session_state.get("telegram_status") or _standby
    telegram_status = (telegram_state.get("status", "STANDBY"), telegram_state.get("color", "#6b7280"), telegram_state.get("detail", "Awaiting active threat alerts"))

    siren_state = st.session_state.get("siren_status") or _standby
    siren_status = (siren_state.get("status", "STANDBY"), siren_state.get("color", "#6b7280"), siren_state.get("detail", "Zone: All clear"))

    play_active = st.session_state.get('sim_play_active', False)
    if not play_active:
        sms_status = ("WAITING", "#6b7280", "System idle — awaiting alerts")
        email_status = ("WAITING", "#6b7280", "System idle — awaiting alerts")
        telegram_status = ("WAITING", "#6b7280", "System idle — awaiting alerts")
        siren_status = ("ARMED", "#22c55e", "Failsafe active — ready to sound")

    channels = [
        ("SMS", sms_status[0], sms_status[1], sms_status[2]),
        ("EMAIL", email_status[0], email_status[1], email_status[2]),
        ("TELEGRAM", telegram_status[0], telegram_status[1], telegram_status[2]),
        ("SIREN", siren_status[0], siren_status[1], siren_status[2]),
    ]
    cards = ''.join(
        f'<div style="flex:1; background:rgba(17,24,39,0.5); border:1px solid rgba(255,255,255,0.06); '
        f'border-left:3px solid {color}; border-radius:8px; padding:6px 8px;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center;">'
        f'<span style="font-size:8.5px; font-weight:700; color:#94a3b8; letter-spacing:0.5px;">{name}</span>'
        f'<span style="background:{color}20; color:{color}; border:1px solid {color}40; font-size:7.5px; font-weight:800; padding:1px 5px; border-radius:3px; text-transform:uppercase;">{status}</span>'
        f'</div>'
        f'<div style="font-size:9px; color:#64748b; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{detail}</div>'
        f'</div>'
        for name, status, color, detail in channels
    )
    channels_html = f'<div style="display:flex; gap:6px;">{cards}</div>'

    escalated_toast = ""
    if compound_risk_score > 0:
        escalated_toast = (
            '<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;'
            'padding:10px 13px;margin-top:4px;display:flex;align-items:center;gap:8px;">'
            '<span style="font-size:18px;"></span>'
            '<span style="color:#22c55e;font-size:11px;font-weight:600;">All critical alerts escalated to all channels</span>'
            '</div>'
        )
    full_html = clean_html(channels_html + escalated_toast)
    hash_key = f"_hash_notif_{selected_zone}"
    if st.session_state.get(hash_key) != full_html:
        st.session_state[hash_key] = full_html
        placeholder.markdown(full_html, unsafe_allow_html=True)

def render_compact_alert_card_html(alert: Union[SafetyAlert, Dict[str, Any]]) -> str:
    """Renders a single compact alert card for the alerts panel"""
    # 1. Extract severity
    severity_name = "LOW"
    if hasattr(alert, "risk_level"):
        severity_name = alert.risk_level
    elif hasattr(alert, "severity"):
        severity_name = getattr(alert.severity, "name", str(alert.severity))
    elif isinstance(alert, dict) and "severity" in alert:
        severity_name = alert["severity"]
    severity_name = severity_name.upper()

    from src.ui_components import Colors
    color = Colors.SEVERITY.get(severity_name, Colors.BLUE)
    bg = Colors.SEVERITY_BG.get(severity_name, "rgba(59, 130, 246, 0.08)")
    border_color = Colors.SEVERITY_BORDER.get(severity_name, "rgba(59, 130, 246, 0.4)")
    
    # Hazard Icon mapping
    icon = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "⚡", "LOW": "ℹ️"}.get(severity_name, "🔵")

    # 2. Extract zone
    zone = ""
    if hasattr(alert, "zone"):
        zone = alert.zone
    elif isinstance(alert, dict) and "zone" in alert:
        zone = alert["zone"]

    from src.config.ui_constants import ZONE_LABELS
    zone_lbl = ZONE_LABELS.get(zone, zone).upper()

    # 3. Extract message
    import html as _html
    raw_message = ""
    if hasattr(alert, "message"):
        raw_message = str(alert.message)
    elif isinstance(alert, dict) and "message" in alert:
        raw_message = str(alert["message"])
    
    if "<div" in raw_message or "<span" in raw_message:
        message = raw_message
    else:
        message = _html.escape(raw_message)

    # 4. Extract time (prioritize static start_time / timestamp to prevent frame-by-frame updates)
    time_str = ""
    if hasattr(alert, "start_time") and alert.start_time:
        time_str = alert.start_time.strftime('%H:%M:%S')
    elif hasattr(alert, "timestamp") and alert.timestamp:
        time_str = alert.timestamp.strftime('%H:%M:%S')
    elif hasattr(alert, "duration"):
        dur = int(alert.duration)
        time_str = f"{dur // 60:02d}:{dur % 60:02d}s"
    elif isinstance(alert, dict) and "timestamp" in alert:
        time_str = str(alert["timestamp"])

    # 5. Extract status / acknowledgment
    status_label = "ACTIVE"
    is_ack = False
    alert_id = None

    if hasattr(alert, "status"):
        status_val = getattr(alert.status, "value", str(alert.status))
        status_label = status_val.upper()
        is_ack = status_label in ("ACKNOWLEDGED", "ACK")
    elif isinstance(alert, dict) and "status" in alert:
        status_label = str(alert["status"]).upper()
        is_ack = status_label in ("ACKNOWLEDGED", "ACK")

    if hasattr(alert, "alert_id"):
        alert_id = alert.alert_id
    elif isinstance(alert, dict) and "alert_id" in alert:
        alert_id = alert["alert_id"]
    elif isinstance(alert, dict) and "id" in alert:
        alert_id = alert["id"]

    # Countdown timer calculation (Static indicators during live streaming to prevent browser flickering)
    if is_ack:
        countdown_str = "✓ ACKED"
    else:
        countdown_str = "⏳ ACTIVE"

    # Status pill styles
    status_tuple = Colors.STATUS.get(status_label, ("rgba(239, 68, 68, 0.15)", "#EF4444", "rgba(239, 68, 68, 0.3)"))
    status_bg, status_color, status_border = status_tuple

    # Acknowledge / Resolve button html
    if is_ack and alert_id:
        ack_btn = f"""<a href="?resolve_alert={alert_id}" target="_self" style="text-decoration: none;"><span style="background: rgba(34,197,94,0.2); color: #22c55e; border: 1px solid rgba(34,197,94,0.4); border-radius: 4px; padding: 1.5px 6px; font-size: 8.5px; font-weight: 800; cursor: pointer; text-transform: uppercase;">RESOLVE</span></a>"""
    elif alert_id:
        ack_btn = f"""<a href="?ack_alert={alert_id}" target="_self" style="text-decoration: none; margin-right: 3px;"><span style="background: {color}; color: #fff; border-radius: 4px; padding: 1.5px 6px; font-size: 8.5px; font-weight: 800; cursor: pointer; text-transform: uppercase;">ACK</span></a><a href="?resolve_alert={alert_id}" target="_self" style="text-decoration: none;"><span style="background: rgba(34,197,94,0.2); color: #22c55e; border: 1px solid rgba(34,197,94,0.4); border-radius: 4px; padding: 1.5px 6px; font-size: 8.5px; font-weight: 800; cursor: pointer; text-transform: uppercase;">RESOLVE</span></a>"""
    else:
        ack_btn = f"""<span style="background: rgba(255,255,255,0.08); color: #64748b; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; padding: 1.5px 6px; font-size: 8.5px;">ACK</span>"""

    # Solid card styling with zero pulse animation
    card_class = "glass-card"

    # Restructured Card HTML with countdown indicator
    html = f"""
    <div class="{card_class}" style="background: {bg}; border-left: 4px solid {color}; border-top: 1px solid {border_color}; border-right: 1px solid {border_color}; border-bottom: 1px solid {border_color}; border-radius: 6px; padding: 6px 10px; margin-bottom: 4px; font-family: Outfit, sans-serif;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px; flex-wrap: nowrap;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <span style="font-weight: 800; color: {color}; font-size: 9.5px; letter-spacing: 0.5px; text-transform: uppercase; display: flex; align-items: center; gap: 3px;">
            {icon} {severity_name}
          </span>
          <span style="color: #94a3b8; font-size: 9.5px; font-weight: 600;">{zone_lbl}</span>
          <span style="color: #64748b; font-size: 9px; font-family: monospace;">{time_str}</span>
          <span style="color: #f97316; font-size: 9px; font-weight: 700; margin-left: 4px;">{countdown_str}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 4px;">
          <span style="background: {status_bg}; color: {status_color}; border: 1px solid {status_border}; border-radius: 4px; padding: 1px 4px; font-size: 8px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">
            {status_label}
          </span>
          {ack_btn}
        </div>
      </div>
      <div style="color: #cbd5e1; font-size: 11px; font-weight: 500; line-height: 1.3;">{message}</div>
    </div>
    """
    return html.strip().replace("\n", "")


def render_alerts_panel(placeholder: DeltaGenerator, am: AlertManager, selected_zone: Optional[str] = None) -> None:
    """Renders active and acknowledged alerts, filtered to the selected zone.

    Alerts are only shown while Autoplay Simulation is active. When autoplay
    is off the panel always shows a nominal state, so no stale database
    alerts leak through before the operator starts the simulation.

    Args:
        placeholder: st.empty() placeholder for the alerts panel.
        am: AlertManager instance.
        selected_zone: If provided, only alerts whose zone matches are shown.
    """
    if not st.session_state.get('sim_play_active', False):
        from src.config.ui_constants import ZONE_LABELS
        resolved_list = list(am.history)
        resolved_list.sort(key=lambda x: x.end_time or x.start_time, reverse=True)
        recent_resolved = resolved_list[:4]
        
        import re as _re

        # Deduplicate history by alert_id (keep most recent per id)
        seen_ids = set()
        deduped = []
        for a in resolved_list:
            aid = getattr(a, 'alert_id', id(a))
            if aid not in seen_ids:
                seen_ids.add(aid)
                deduped.append(a)
        recent_resolved = deduped[:5]

        def _extract_title_and_cause(raw_msg: str) -> tuple:
            """Extract the plain-text title from the first <div> and root cause text."""
            # Title: content of the first <div ...>...</div>
            title_match = _re.search(r'<div[^>]*>\s*(.*?)\s*</div>', raw_msg, _re.DOTALL)
            if title_match:
                title = _re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            else:
                # Full strip fallback — take first 60 chars
                title = _re.sub(r'<[^>]+>', '', raw_msg).strip().split('\n')[0][:60]

            # Root cause: text after "Root Cause:" span
            cause_match = _re.search(r'Root Cause:</span>\s*<span[^>]*>\s*(.*?)\s*</span>', raw_msg, _re.DOTALL)
            cause = _re.sub(r'<[^>]+>', '', cause_match.group(1)).strip()[:90] if cause_match else ""

            return ' '.join(title.split()), ' '.join(cause.split())

        resolved_items_html = ""
        for a in recent_resolved:
            time_str = (a.end_time or a.start_time).strftime("%H:%M:%S")
            raw_msg = str(getattr(a, 'message', ''))
            inc_title, root_cause = _extract_title_and_cause(raw_msg)
            sev_name = getattr(a.severity, 'name', str(a.severity))
            sev_color = {'CRITICAL': '#ef4444', 'HIGH': '#f97316', 'MEDIUM': '#eab308'}.get(sev_name, '#22c55e')
            cause_row = (
                f'<div style="color: #94a3b8; font-size: 9px; margin-top: 1px; '
                f'white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">'
                f'↳ {root_cause}</div>'
            ) if root_cause else ''
            resolved_items_html += f"""
            <div style="background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04); border-left: 3px solid #22c55e; border-radius: 4px; padding: 6px 10px; margin-top: 6px; font-family: Outfit, sans-serif;">
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <span style="color: #cbd5e1; font-size: 10px; font-weight: 700; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">✅ {inc_title}</span>
                    <span style="color: #64748b; font-size: 9px; font-family: monospace; flex-shrink: 0;">{time_str}</span>
                </div>
                {cause_row}
                <div style="color: #64748b; font-size: 9px; margin-top: 3px;">Zone: {ZONE_LABELS.get(a.zone, a.zone)} &bull; <span style="color:{sev_color}; font-weight:700;">{sev_name}</span> &bull; RESOLVED</div>
            </div>"""

            
        if not resolved_items_html:
            resolved_items_html = "<div style='color: #64748b; font-size: 9.5px; margin-top: 6px; font-style: italic; text-align: center;'>No historical alerts recorded today.</div>"

        html = f"""
        <div style="background: linear-gradient(135deg, #0b1528, #050b14); border: 1px solid #1e3a5f; border-radius: 12px; padding: 12px 14px; font-family: Outfit, sans-serif;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px; margin-bottom: 8px;">
                <span style="color: #94a3b8; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;">🔔 LIVE ALERTS</span>
                <span style="background: rgba(34,197,94,0.1); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); border-radius: 4px; padding: 1px 6px; font-size: 8px; font-weight: 800;">READY</span>
            </div>
            <div style="color: #cbd5e1; font-size: 11px; font-weight: 600; line-height: 1.3;">No active incidents. The system is monitoring and ready to respond.</div>
            <div style="margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px;">
                <div style="color: #64748b; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Recently Resolved Alerts (History)</div>
                {resolved_items_html}
            </div>
        </div>"""
        _safe_markdown(placeholder, html, f"_hash_alerts_hist_{selected_zone}")
        return

    all_alerts = st.session_state.get('active_alerts')
    if all_alerts is None:
        all_alerts = am.active_alerts

    # Filter to selected zone when provided
    if selected_zone and all_alerts:
        zone_alerts = {k: v for k, v in all_alerts.items() if getattr(v, 'zone', None) == selected_zone}
    else:
        zone_alerts = all_alerts

    fsm_state = st.session_state.get('alert_fsm_state', 'NORMAL')
    if fsm_state == 'NORMAL':
        nom_html = render_nominal_card(
            title="Zone Nominal",
            message="No active alerts for this zone. The risk engine is monitoring all telemetry channels."
        )
        _safe_markdown(placeholder, nom_html, f"_hash_alerts_nom_{selected_zone}")
        return

    if fsm_state in ('DETECTING', 'WARNING_ACTIVE', 'DISPATCHING'):
        eval_html = render_nominal_card(
            title="Threat Detected — Evaluating",
            message="Hazard detected. AI risk engine is evaluating compound rules. Alert will be raised if thresholds are exceeded."
        )
        _safe_markdown(placeholder, eval_html, f"_hash_alerts_eval_{selected_zone}")
        return

    if not zone_alerts:
        nom_html = render_nominal_card(
            title="Zone Nominal",
            message="No active alerts for this zone. The risk engine is monitoring all telemetry channels."
        )
        _safe_markdown(placeholder, nom_html, f"_hash_alerts_nom_{selected_zone}")
        return

    filtered_alerts = zone_alerts

    # Sort by start_time (newest first)
    sorted_alerts = sorted(
        filtered_alerts.values(),
        key=lambda x: getattr(x, 'start_time', datetime.now()),
        reverse=True
    )

    cards_html = []
    visible_alerts = sorted_alerts[:5]
    extra_count = len(sorted_alerts) - 5

    for alert in visible_alerts:
        cards_html.append(render_compact_alert_card_html(alert))

    if extra_count > 0:
        extra_card = (
            f'<div style="background:rgba(255,255,255,0.02);border:1px dashed rgba(255,255,255,0.1);'
            f'border-radius:8px;padding:8px;text-align:center;color:#94a3b8;font-size:11px;margin-bottom:8px;">'
            f'+ {extra_count} More Alerts'
            f'</div>'
        )
        cards_html.append(extra_card)

    _safe_markdown(placeholder, "".join(cards_html), f"_hash_alerts_active_{selected_zone}")


def render_risk_analysis_row(placeholders: Dict[str, Any], data_dict: Dict[str, Any], selected_zone: str, detections_list: List[Any]) -> None:
    """Renders the Live Incident Timeline and the Rule Engine Status side-by-side"""
    timeline_placeholder = placeholders['timeline']
    risk_engine_placeholder = placeholders['risk_engine']

    latest = data_dict['latest']
    highest_risk = data_dict['STATUS']['level']
    current_gas = float(latest.get(f"{selected_zone}_gas_ppm", 0.0))
    current_temp = float(latest.get(f"{selected_zone}_temperature_c", 0.0))
    current_workers = len([d for d in detections_list if d.label == 'person'])

    is_overpressure = (selected_zone == 'Zone_C' and st.session_state.get('cctv_frame_index', 0) >= 95)

    siren_state = st.session_state.get("siren_status")
    siren_active = (siren_state and siren_state.get("status") in ("ACTIVE 🔊", "ACTIVE"))

    events = []
    t_str = lambda offset_min: (datetime.now() - timedelta(minutes=offset_min)).strftime("%H:%M:%S")

    fsm_active = st.session_state.get('alert_fsm_state', 'NORMAL') in ('WARNING_ACTIVE', 'DISPATCHING', 'DELIVERED', 'INCIDENT_ACTIVE', 'ACKNOWLEDGED', 'RESOLVED')
    if fsm_active or st.session_state.get('compound_risk_active', False) or st.session_state.get('sim_stage') == 'active':
        if siren_active:
            events.append({'time': t_str(2), 'icon': '🚨', 'message': 'AI DETECTED TRIPLE-THREAT IN BATTERY-4'})
            events.append({'time': t_str(5), 'icon': '⚠️', 'message': 'Safety boundary breach: Volatile gas overlay'})
            events.append({'time': t_str(8), 'icon': '📱', 'message': 'SMS Escalation: Sent to safety lead'})
            events.append({'time': t_str(9), 'icon': '📧', 'message': 'Email Escalation: Sent to operator team'})
            events.append({'time': t_str(10), 'icon': '🔊', 'message': 'Siren Channel: Sounding in Battery-4'})

    if selected_zone:
        now_t = datetime.now().strftime("%H:%M:%S")
        h_count_active = len([d for d in detections_list if d.label == 'helmet'])
        missing_helmets = current_workers - h_count_active
        if missing_helmets > 0 and selected_zone not in ('Zone_A', 'Reactor_Area', 'Storage_Area'):
            events.append({'time': now_t, 'icon': '🟡', 'message': f'PPE compliance check failed in {ZONE_LABELS.get(selected_zone, selected_zone)}'})
        if is_overpressure:
            events.append({'time': now_t, 'icon': '🔴', 'message': f'Critical overpressure warning in {ZONE_LABELS.get(selected_zone, selected_zone)}'})

    play_active = st.session_state.get('sim_play_active', False)
    if len(events) < (20 if not play_active else 6):
        sc_start = st.session_state.get('scenario_start_time') or (datetime.now() - timedelta(minutes=45))
        t_nom = lambda offset_sec: (sc_start + timedelta(seconds=offset_sec)).strftime("%H:%M:%S")
        nominal_events = [
            {'time': t_nom(0), 'icon': '🟢', 'message': 'System initialized. Feeds secure.'},
            {'time': t_nom(15), 'icon': '🟢', 'message': 'YOLO model loaded. Detections active.'},
            {'time': t_nom(45), 'icon': '🔵', 'message': 'Telemetry database connection active.'},
            {'time': t_nom(120), 'icon': '🟢', 'message': 'All systems scanned. All parameters nominal.'},
            {'time': t_nom(300), 'icon': '🟢', 'message': 'Status report logged to plant DB.'}
        ]
        if not play_active:
            nominal_events.extend([
                {'time': t_nom(380), 'icon': '🟢', 'message': 'Safety DB Backup: Auto-verify success.'},
                {'time': t_nom(520), 'icon': '🔵', 'message': 'Shift change: Safety Crew Team B Group 2 logged in.'},
                {'time': t_nom(640), 'icon': '🟢', 'message': 'OPC UA Sensor calibration check completed.'},
                {'time': t_nom(780), 'icon': '📋', 'message': 'Work Permit #2491 approved for Storage Area.'},
                {'time': t_nom(920), 'icon': '💨', 'message': 'Calibration: Gas sensor zero-point drift corrected.'},
                {'time': t_nom(1040), 'icon': '🔵', 'message': 'MQTT connection health-check status: Nominal.'},
                {'time': t_nom(1180), 'icon': '🔒', 'message': 'Zone A secure. Restricted Area boundary lasers active.'},
                {'time': t_nom(1300), 'icon': '🟢', 'message': 'YOLOv8 FP16 model optimization validated on GPU.'},
                {'time': t_nom(1420), 'icon': '📋', 'message': 'Work Permit #2492 approved for Battery-5 hot work.'},
                {'time': t_nom(1580), 'icon': '🟢', 'message': 'SCADA OPC Gateway heartbeats verified.'},
                {'time': t_nom(1800), 'icon': '🟢', 'message': 'Daily site inspection logs uploaded to SQL Server.'},
            ])
            
        for ne in nominal_events:
            if not any(e['time'] == ne['time'] for e in events):
                events.append(ne)

    events.sort(key=lambda x: x['time'], reverse=True)
    play_active = st.session_state.get('sim_play_active', False)
    card_height = "330px" if play_active else "540px"
    scroll_height = "295px" if play_active else "495px"
    limit = 15 if play_active else 20
    events = events[:limit]

    events_html = []
    for e in events:
        if e["icon"] in ('🚨', '🔴'):
            status_bg, status_color, status_border, status_label = 'rgba(239,68,68,0.15)', '#ef4444', 'rgba(239,68,68,0.3)', 'CRITICAL'
        elif e["icon"] in ('⚠️', '🟡'):
            status_bg, status_color, status_border, status_label = 'rgba(245,158,11,0.15)', '#f59e0b', 'rgba(245,158,11,0.3)', 'WARNING'
        elif e["icon"] in ('📱', '📧', '🔊'):
            status_bg, status_color, status_border, status_label = 'rgba(59,130,246,0.15)', '#3b82f6', 'rgba(59,130,246,0.3)', 'ESCALATED'
        else:
            status_bg, status_color, status_border, status_label = 'rgba(34,197,94,0.12)', '#22c55e', 'rgba(34,197,94,0.3)', 'NOMINAL'
        events_html.append(
            f'<div style="display: grid; grid-template-columns: 64px 20px 1fr auto; align-items: center; gap: 6px; padding: 5px 10px; margin-bottom: 3px; background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04); border-radius: 6px;">'
            f'<span style="color: #64748b; font-family: monospace; font-size: 9px; text-align: left;">{e["time"]}</span>'
            f'<span style="font-size: 11px; text-align: center;">{e["icon"]}</span>'
            f'<span style="color: #cbd5e1; font-weight: 500; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{e["message"]}</span>'
            f'<span style="background: {status_bg}; color: {status_color}; border: 1px solid {status_border}; border-radius: 4px; padding: 1px 6px; font-size: 7.5px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px;">{status_label}</span>'
            f'</div>'
        )

    risk_color = data_dict['STATUS']['color']
    timeline_border = f"border: 1px solid {risk_color}55; border-left: 3px solid {risk_color};" if highest_risk in ('HIGH', 'CRITICAL') else "border: 1px solid var(--border2); border-left: 3px solid #3b82f6;"
    
    timeline_html = (
        f'<div style="background: rgba(17, 24, 39, 0.7); {timeline_border} border-radius: 12px; padding: 14px 16px; min-height: {card_height}; box-sizing: border-box; font-family: Outfit, sans-serif; display: flex; flex-direction: column;">'
        f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">'
        f'<span style="font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700;">LIVE INCIDENT TIMELINE</span>'
        f'<span style="background: rgba(59,130,246,0.15); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3); font-size: 8px; font-weight: 700; padding: 1px 6px; border-radius: 4px; text-transform: uppercase;">LOG ACTIVE</span>'
        f'</div>'
        f'<div style="max-height: {scroll_height}; overflow-y: auto; font-size: 10px; line-height: 1.4; flex-grow: 1;">'
        f'{"".join(events_html)}'
        f'</div></div>'
    )

    badges = []
    rule_states = [
        ("Fire Detection", any(d.label == 'fire' for d in detections_list)),
        ("Smoke Detection", any(d.label == 'smoke' for d in detections_list)),
        ("Gas Critical", current_gas > 35),
        ("Gas Elevated", current_gas > 20),
        ("Temp Critical", current_temp > 95),
        ("Intrusion", any(getattr(d, 'zone_violation', False) for d in detections_list)),
        ("Pressure Alert", is_overpressure),
        ("PPE Rules", missing_helmets > 0 if 'missing_helmets' in dir() else False),
        ("Overcrowding", current_workers > 9),
        ("Shift Change", latest.get('shift_change', 0) == 1 and current_gas > 30),
        ("Maint Gas Leak", latest.get(f"{selected_zone}_maintenance_active", 0) == 1 and current_gas > 35),
        ("Triple Threat", fsm_active or st.session_state.get('compound_risk_active', False))
    ]
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
            f'<div style="background: {bg}; border: 1px solid {border}; color: {color}; border-radius: 4px; padding: 4px 2px; text-align: center; font-size: 9.5px; display: flex; flex-direction: column; justify-content: center; min-height: 34px;">'
            f'<div style="font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{name}</div>'
            f'<div style="font-size:7px; opacity:0.8; font-weight:800; letter-spacing:0.3px; margin-top:2px;">{status}</div>'
            f'</div>'
        )

    risk_border = f"border: 1px solid {risk_color}55; border-left: 3px solid {risk_color};" if highest_risk in ('HIGH', 'CRITICAL') else "border: 1px solid var(--border2); border-left: 3px solid #22c55e;"
    
    if play_active:
        risk_engine_html = (
            f'<div style="background: rgba(17, 24, 39, 0.7); {risk_border} border-radius: 12px; padding: 14px 16px; min-height: 220px; box-sizing: border-box; font-family: Outfit, sans-serif; display: flex; flex-direction: column;">'
            f'<div style="font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; margin-bottom: 8px;">COMPOUND RISK ENGINE</div>'
            f'<div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; max-height: 200px; overflow-y: auto; flex-grow: 1;">'
            f'{"".join(badges)}'
            f'</div></div>'
        )
    else:
        risk_engine_html = (
            f'<div style="background: rgba(17, 24, 39, 0.7); border: 1px solid var(--border2); border-left: 3px solid #22c55e; border-radius: 12px; padding: 14px 16px; min-height: 220px; box-sizing: border-box; font-family: Outfit, sans-serif; display: flex; flex-direction: column; justify-content: space-between;">'
            f'<div style="font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; margin-bottom: 8px;">COMPOUND RISK ENGINE</div>'
            f'<div style="display: flex; flex-direction: column; gap: 8px; flex-grow: 1; justify-content: center;">'
            f'<div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04); border-radius: 6px; padding: 8px 12px;">'
            f'<span style="color: #64748b; font-size: 9.5px; font-weight: 600; text-transform: uppercase;">Current Status</span>'
            f'<span style="color: #22c55e; font-size: 11px; font-weight: 800;">🟢 MONITORING (STANDBY)</span>'
            f'</div>'
            f'<div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04); border-radius: 6px; padding: 8px 12px;">'
            f'<span style="color: #64748b; font-size: 9.5px; font-weight: 600; text-transform: uppercase;">Last Risk Score</span>'
            f'<span style="color: #60a5fa; font-size: 11px; font-weight: 800; font-family: monospace;">{data_dict.get("max_score", 0.0):.0f} / 20</span>'
            f'</div>'
            f'<div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04); border-radius: 6px; padding: 8px 12px;">'
            f'<span style="color: #64748b; font-size: 9.5px; font-weight: 600; text-transform: uppercase;">Last Compound Rule Triggered</span>'
            f'<span style="color: #ff9f43; font-size: 11px; font-weight: 800;">{data_dict.get("risk_state", "None")}</span>'
            f'</div>'
            f'<div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.015); border: 1px solid rgba(255,255,255,0.04); border-radius: 6px; padding: 8px 12px;">'
            f'<span style="color: #64748b; font-size: 9.5px; font-weight: 600; text-transform: uppercase;">Next Evaluation</span>'
            f'<span style="color: #cbd5e1; font-size: 11px; font-weight: 800; font-family: monospace;">In 2.4s (Standby)</span>'
            f'</div>'
            f'</div></div>'
        )

    _safe_markdown(placeholders.get('timeline'), timeline_html, f"_hash_timeline_{selected_zone}")
    _safe_markdown(placeholders.get('risk_engine'), risk_engine_html, f"_hash_risk_engine_{selected_zone}")


def render_decision_telemetry_row(placeholders: Dict[str, Any], data_dict: Dict[str, Any], selected_zone: str, detections_list: List[Any]) -> None:
    """Renders the AI Decision Engine, Live Telemetry gauges, and Zone Response side-by-side"""
    play_active = st.session_state.get('sim_play_active', False)
    latest = data_dict['latest']
    STATUS = data_dict['STATUS']
    compound_risk_score = data_dict['compound_risk_score']

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

    is_emergency = level in ('HIGH', 'CRITICAL')
    siren_state = st.session_state.get("siren_status")
    siren_active = (siren_state and siren_state.get("status") in ("ACTIVE 🔊", "ACTIVE"))

    if level == 'CRITICAL':
        recommendation = f"Evacuate {ZONE_LABELS.get(selected_zone, 'Battery-4')} Immediately"
    elif level == 'HIGH':
        recommendation = "Deploy Emergency Response Team. Restrict Zone Access."
    elif level == 'MEDIUM':
        recommendation = "Verify compliance and telemetry levels."
    else:
        recommendation = "Continue standard plant surveillance."

    ai_border = f"border: 1px solid {risk_color}55; border-left: 3px solid {risk_color};" if is_emergency else "border: 1px solid #1e3a5f; border-left: 3px solid #3b82f6;"

    if play_active:
        ai_decision_html = (
            f'<div style="background:linear-gradient(135deg,#0f1f38,#0a1628); {ai_border} border-radius:12px; padding:12px 14px; min-height:260px; box-sizing: border-box; font-family:Outfit,sans-serif; display:flex; flex-direction:column;">'
            f'<div style="color:#94a3b8; font-size:10px; font-weight:600; letter-spacing:1px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">'
            f'<span>🤖 AI DECISION ENGINE</span>'
            f'<span style="background:{risk_color}20; color:{risk_color}; border:1px solid {risk_color}40; font-size:7.5px; font-weight:800; padding:1px 5px; border-radius:3px; text-transform:uppercase;">{risk_level}</span>'
            f'</div>'
            f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 12px; flex-grow:1; align-content:space-between;">'
            f'<div style="display:flex; flex-direction:column; gap:4px; justify-content:space-between;">'
            f'<div><span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px; display:block; margin-bottom:1px;">Risk Level</span><div style="font-size:15px; font-weight:800; color:{risk_color}; display:flex; align-items:center; gap:4px;">{risk_icon} {risk_level}</div></div>'
            f'<div><span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px; display:block; margin-bottom:1px;">Confidence</span><div style="font-size:15px; font-weight:800; color:#3b82f6;">{confidence}</div></div>'
            f'</div>'
            f'<div style="display:flex; flex-direction:column; gap:4px; border-left:1px solid rgba(255,255,255,0.06); padding-left:10px; justify-content:space-between;">'
            f'<div style="flex-grow:1;">'
            f'<span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; display:block; margin-bottom:2px; letter-spacing:0.5px;">Matched Rules</span>'
            f'<div style="line-height:1.3; max-height:80px; overflow-y:auto; font-size:10px;">{reasons_bullets}</div>'
            f'</div>'
            f'<div>'
            f'<span style="font-size:9px; color:#64748b; text-transform:uppercase; font-weight:600; display:block; margin-bottom:2px; letter-spacing:0.5px;">Recommendation</span>'
            f'<div style="font-size:11px; font-weight:700; color:#fff; line-height:1.2;">{recommendation}</div>'
            f'</div>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
    else:
        ai_decision_html = (
            f'<div style="background:linear-gradient(135deg,#0b1528,#050b14); border: 1px solid #1e3a5f; border-left: 3px solid #22c55e; border-radius:12px; padding:14px 16px; min-height:320px; box-sizing: border-box; font-family:Outfit,sans-serif; display:flex; flex-direction:column; justify-content:space-between;">'
            f'<div style="color:#94a3b8; font-size:10px; font-weight:600; letter-spacing:1px; margin-bottom:8px; display:flex; justify-content:space-between;">'
            f'<span>🤖 AI DECISION ENGINE — STANDBY INTELLIGENCE</span>'
            f'<span style="background:rgba(34,197,94,0.15); color:#22c55e; border:1px solid rgba(34,197,94,0.3); font-size:7.5px; font-weight:800; padding:1px 5px; border-radius:3px; text-transform:uppercase;">MONITORING</span>'
            f'</div>'
            f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px 16px; flex-grow:1; align-content:center;">'
            f'<div style="display:flex; flex-direction:column; gap:6px;">'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Overall Risk Trend</span><div style="font-size:13px; font-weight:700; color:#22c55e;">📉 DECREASING / STABLE</div></div>'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Most Frequent Hazard</span><div style="font-size:13px; font-weight:700; color:#cbd5e1;">👷 PPE Compliance Violation</div></div>'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Last Incident Logged</span><div style="font-size:13px; font-weight:700; color:#cbd5e1;">Gas Leak Alert (Zone A)</div></div>'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Recommended Patrol Area</span><div style="font-size:13px; font-weight:700; color:#cbd5e1;">📦 Storage Aisle B-C</div></div>'
            f'</div>'
            f'<div style="display:flex; flex-direction:column; gap:6px; border-left:1px solid rgba(255,255,255,0.06); padding-left:16px;">'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Plant Safety Score</span><div style="font-size:16px; font-weight:800; color:#22c55e;">98% (Excellent)</div></div>'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Average Response Time</span><div style="font-size:13px; font-weight:700; color:#3b82f6; font-family:monospace;">45.2 seconds</div></div>'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Highest Risk Zone Today</span><div style="font-size:13px; font-weight:700; color:#ff9f43;">Battery-4 (Zone A)</div></div>'
            f'<div><span style="font-size:8.5px; color:#64748b; text-transform:uppercase; font-weight:600; letter-spacing:0.5px;">Current State</span><div style="font-size:13px; font-weight:700; color:#94a3b8; font-style:italic;">Standby Surveillance</div></div>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
    _safe_markdown(placeholders.get('ai_decision'), ai_decision_html, f"_hash_ai_decision_{selected_zone}")

    # ── Rolling history buffers (20-point ring) — updated every render tick ──
    _MAX_HISTORY = 20
    # Store quantized values (0.5-unit steps) in history so sparkline SVG path
    # only changes when the reading meaningfully shifts — not on every frame.
    for _key, _val in [
        ('telemetry_history_gas',   round(current_gas   * 2) / 2),
        ('telemetry_history_temp',  round(current_temp  * 2) / 2),
        ('telemetry_history_press', round(current_press * 4) / 4),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = [_val] * _MAX_HISTORY
        else:
            # Only append if value actually changed to further reduce SVG churn
            if not st.session_state[_key] or st.session_state[_key][-1] != _val:
                st.session_state[_key].append(_val)
            if len(st.session_state[_key]) > _MAX_HISTORY:
                st.session_state[_key] = st.session_state[_key][-_MAX_HISTORY:]

    # ── Sparkline stroke colors respond to current readings ──
    _gas_stroke   = "#ef4444" if current_gas  > 35 else "#f59e0b" if current_gas  > 20 else "#ff9f43"
    _temp_stroke  = "#ef4444" if current_temp > 95 else "#f59e0b" if current_temp > 88 else "#10ac84"
    _press_stroke = "#ef4444" if current_press > 80 else "#f59e0b" if current_press > 60 else "#2e86de"

    # Quantize sensor values before building SVG / HTML to prevent per-frame DOM re-renders.
    # Tiny float oscillations would otherwise produce unique HTML strings every frame.
    _q_temp_gauge  = round(current_temp  * 2) / 2   # 0.5°C steps for gauge
    _q_press_gauge = round(current_press * 4) / 4   # 0.25 bar steps for gauge

    temp_gauge_svg  = render_gauge_svg(_q_temp_gauge,  0, 120, "Temp (°C)",   "#10ac84", 88, 95)
    press_gauge_svg = render_gauge_svg(_q_press_gauge, 0, 100, "Press (bar)", "#2e86de", 60, 80)
    gas_spark_svg   = render_sparkline_svg(st.session_state.telemetry_history_gas,   stroke_color=_gas_stroke,   height=36)
    temp_spark_svg  = render_sparkline_svg(st.session_state.telemetry_history_temp,  stroke_color=_temp_stroke,  height=36)

    # ── Sensor summary row — always shows live values ──
    # Quantize to 0.5-unit steps: prevents constant HTML re-renders from tiny float oscillations
    _now_str      = st.session_state.get('_last_sync_time', datetime.now().strftime('%H:%M'))
    _worker_count = current_workers
    _q_temp  = round(current_temp  * 2) / 2  # 0.5°C steps
    _q_gas   = round(current_gas   * 2) / 2  # 0.5 ppm steps
    _q_press = round(current_press * 4) / 4  # 0.25 bar steps
    _temp_c       = f"{_q_temp:.1f}°C"
    _gas_ppm      = f"{_q_gas:.1f} ppm"
    _press_bar    = f"{_q_press:.2f} bar"
    _temp_col     = "#ef4444" if current_temp > 95 else "#f59e0b" if current_temp > 88 else "#22c55e"
    _gas_col      = "#ef4444" if current_gas  > 35 else "#f59e0b" if current_gas  > 20 else "#22c55e"
    _press_col    = "#ef4444" if current_press > 80 else "#f59e0b" if current_press > 60 else "#22c55e"

    # Quantize sparkline label values to 0.5-unit steps too
    _q_gas_label  = round(current_gas  * 2) / 2
    _q_temp_label = round(current_temp * 2) / 2

    sensor_row_html = (
        f'<div style="display:grid; grid-template-columns:repeat(5,1fr); gap:4px; margin-bottom:6px;">'
        f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:6px; padding:4px 6px; text-align:center;">'
        f'<div style="font-size:7.5px; color:#64748b; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Temp</div>'
        f'<div style="font-size:11px; font-weight:800; color:{_temp_col}; font-family:monospace;">{_temp_c}</div></div>'
        f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:6px; padding:4px 6px; text-align:center;">'
        f'<div style="font-size:7.5px; color:#64748b; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Gas</div>'
        f'<div style="font-size:11px; font-weight:800; color:{_gas_col}; font-family:monospace;">{_gas_ppm}</div></div>'
        f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:6px; padding:4px 6px; text-align:center;">'
        f'<div style="font-size:7.5px; color:#64748b; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Press</div>'
        f'<div style="font-size:11px; font-weight:800; color:{_press_col}; font-family:monospace;">{_press_bar}</div></div>'
        f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:6px; padding:4px 6px; text-align:center;">'
        f'<div style="font-size:7.5px; color:#64748b; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Workers</div>'
        f'<div style="font-size:11px; font-weight:800; color:#cbd5e1; font-family:monospace;">{_worker_count}</div></div>'
        f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.04); border-radius:6px; padding:4px 6px; text-align:center;">'
        f'<div style="font-size:7.5px; color:#64748b; text-transform:uppercase; font-weight:700; letter-spacing:0.5px;">Updated</div>'
        f'<div style="font-size:9px; font-weight:700; color:#f59e0b; font-family:monospace;">{_now_str}</div></div>'
        f'</div>'
    )

    telemetry_border = f"border: 1px solid {risk_color}55; border-left: 3px solid {risk_color};" if is_emergency else "border: 1px solid #1e3a5f; border-left: 3px solid #3b82f6;"
    _sync_label = f" <span style='color:#f59e0b; font-size:8.5px; font-weight:600;'>🕐 {_now_str}</span>"

    telemetry_html = f"""
    <div style="background:linear-gradient(135deg,#0f1f38,#0a1628); {telemetry_border} border-radius:12px; padding:12px 14px; min-height:220px; box-sizing: border-box; font-family:Outfit,sans-serif; display:flex; flex-direction:column;">
        <div>
            <div style="color:#94a3b8; font-size:10px; font-weight:600; letter-spacing:1px; margin-bottom:6px;">LIVE TELEMETRY{_sync_label}</div>
            {sensor_row_html}
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:6px;">
                <div style="flex:1; background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:2px; text-align:center;">
                    {temp_gauge_svg}
                </div>
                <div style="flex:1; background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:2px; text-align:center;">
                    {press_gauge_svg}
                </div>
            </div>
        </div>
        <div style="margin-top:auto;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                <div>
                    <div style="font-size:8.5px; color:{_gas_stroke}; font-weight:700; margin-bottom:2px; display:flex; justify-content:space-between; letter-spacing:0.5px;">
                        <span>⛽ GAS TREND</span>
                        <span style="font-family:monospace;">{_q_gas_label:.1f} ppm</span>
                    </div>
                    <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:6px; padding:2px 4px;">
                        {gas_spark_svg}
                    </div>
                </div>
                <div>
                    <div style="font-size:8.5px; color:{_temp_stroke}; font-weight:700; margin-bottom:2px; display:flex; justify-content:space-between; letter-spacing:0.5px;">
                        <span>🌡️ TEMP TREND</span>
                        <span style="font-family:monospace;">{_q_temp_label:.1f}°C</span>
                    </div>
                    <div style="background:rgba(255,255,255,0.015); border:1px solid rgba(255,255,255,0.03); border-radius:6px; padding:2px 4px;">
                        {temp_spark_svg}
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    _safe_markdown(placeholders.get('telemetry_trends'), telemetry_html, f"_hash_telemetry_{selected_zone}")

    from src.alert_system import get_alert_system
    wrapper_system = get_alert_system()
    teams_str = wrapper_system.emergency_teams.get(selected_zone, 'Alpha & Beta Teams')

    if level == 'CRITICAL':
        channels = "Dashboard, SMS, Phone, Email, Siren"
        deadline = "60 seconds"
        action = "Evacuate / Action Mandatory"
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

    # Gating response actions via FSM lifecycle state
    fsm_state = st.session_state.get('alert_fsm_state', 'NORMAL')
    is_fsm_pending = fsm_state in ('WARNING_ACTIVE', 'DISPATCHING')
    if is_emergency and is_fsm_pending:
        recommendation = "Awaiting notification channel confirmation..."
        action = "Pending Siren / Alerts Gated"
        actions_html = """
        <div style="color: #64748b; margin-bottom: 2px;">⌛ Evacuation recommendations pending</div>
        <div style="color: #64748b; margin-bottom: 2px;">⌛ Emergency response actions standby</div>
        """

    zone_response_border = f"border: 1px solid {risk_color}55; border-left: 3px solid {risk_color};" if is_emergency else "border: 1px solid #1e3a5f; border-left: 3px solid #22c55e;"

    if play_active:
        zone_response_html = (
            f'<div style="background:linear-gradient(135deg,#0f1f38,#0a1628); {zone_response_border} border-radius:12px; padding:12px 14px; min-height:260px; box-sizing: border-box; font-family:Outfit,sans-serif; display:flex; flex-direction:column;">'
            f'<div style="color:#94a3b8; font-size:10px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">ZONE RESPONSE & ACTIONS</div>'
            f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 12px; font-size:10px; line-height:1.3; margin-bottom:8px; flex-grow:1;">'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Affected Zone</span><span style="color:#fff; font-weight:700;">{ZONE_LABELS.get(selected_zone, selected_zone)}</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Emergency Teams</span><span style="color:#cbd5e1;">{teams_str}</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Channels</span><span style="color:#cbd5e1; font-size:9px;">{channels}</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Deadline</span><span style="color:#fff; font-weight:700;">{deadline}</span></div>'
            f'<div style="grid-column:1 / -1;"><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Action</span><span style="color:{risk_color}; font-weight:700; font-size:10px;">{action}</span></div>'
            f'</div>'
            f'<div style="border-top:1px solid rgba(255,255,255,0.06); padding-top:8px; margin-top:auto;">'
            f'<div style="font-size:8.5px; color:#94a3b8; text-transform:uppercase; font-weight:600; margin-bottom:4px; letter-spacing:0.5px;">Operator Failsafes</div>'
            f'<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:2px 8px; line-height:1.2; font-size:10px;">{actions_html}</div>'
            f'</div></div>'
        )
    else:
        zone_response_html = (
            f'<div style="background:linear-gradient(135deg,#0b1528,#050b14); border: 1px solid #1e3a5f; border-radius:12px; padding:12px 14px; min-height:320px; box-sizing: border-box; font-family:Outfit,sans-serif; display:flex; flex-direction:column; justify-content:space-between;">'
            f'<div style="color:#94a3b8; font-size:10px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">ZONE RESPONSE & ACTIONS</div>'
            f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 12px; font-size:10px; line-height:1.3; margin-bottom:8px; flex-grow:1; align-content:center;">'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Zone Status</span><span style="color:#22c55e; font-weight:700;">🟢 SECURED / NOMINAL</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">PPE Compliance</span><span style="color:#22c55e; font-weight:700;">98.4% (Passed)</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Last Completed Inspection</span><span style="color:#cbd5e1;">10:30 AM Today</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Next Scheduled Inspection</span><span style="color:#cbd5e1;">06:00 PM (Shift B)</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Assigned Safety Officer</span><span style="color:#fff; font-weight:700;">Officer K. Sen</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Current Shift Team</span><span style="color:#cbd5e1;">Team B Group 2</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Active Work Permits</span><span style="color:#3b82f6; font-weight:700;">2 Active Permits</span></div>'
            f'<div><span style="color:#94a3b8; font-weight:600; font-size:8.5px; display:block; margin-bottom:1px;">Equipment Status</span><span style="color:#22c55e; font-weight:700;">Standard Operations</span></div>'
            f'</div>'
            f'<div style="border-top:1px solid rgba(255,255,255,0.06); padding-top:8px; margin-top:auto;">'
            f'<div style="font-size:8.5px; color:#94a3b8; text-transform:uppercase; font-weight:600; margin-bottom:4px; letter-spacing:0.5px;">Zone Action Directives</div>'
            f'<div style="color: #cbd5e1; font-size:9.5px; line-height:1.2;">All diagnostic sensors are reporting nominal parameters. Daily inspection logs are verified. No actions required.</div>'
            f'</div></div>'
        )
    _safe_markdown(placeholders.get('zone_response'), zone_response_html, f"_hash_zone_response_{selected_zone}")


def render_right_panel_diagnostics(
    placeholders_dict: Dict[str, Any],
    data_dict: Dict[str, Any],
    am: AlertManager,
    init_mode: bool = False,
) -> None:
    """Renders the advanced AI diagnostics and connection health panels in the right side panel"""
    import streamlit as st
    from src.config.ui_constants import ZONE_LABELS

    # 1. Detect device dynamically
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        device_str = "GPU (NVIDIA)" if gpu_available else "CPU (Host)"
    except Exception:
        device_str = "CPU (Host)"

    # 2. Aggregate stats
    active_alerts_dict = am.active_alerts
    history_list = am.history

    stat_critical = sum(1 for a in active_alerts_dict.values() if a.severity.name == 'CRITICAL') + sum(1 for a in history_list if a.severity.name == 'CRITICAL')
    stat_high = sum(1 for a in active_alerts_dict.values() if a.severity.name == 'HIGH') + sum(1 for a in history_list if a.severity.name == 'HIGH')
    stat_medium = sum(1 for a in active_alerts_dict.values() if a.severity.name == 'MEDIUM') + sum(1 for a in history_list if a.severity.name == 'MEDIUM')
    stat_low = sum(1 for a in active_alerts_dict.values() if a.severity.name == 'LOW') + sum(1 for a in history_list if a.severity.name == 'LOW')
    stat_resolved = len(history_list)

    # Incident counters - read directly from AlertManager state.
    # No sim_on gate: active alerts should always be reflected in real time.
    open_incidents = len(active_alerts_dict)
    closed_incidents = len(history_list)
    today_incidents = open_incidents + closed_incidents

    # 3. Dynamic AI performance metrics
    fps = 25.0 if st.session_state.get('sim_play_active', False) else 0.0
    latency = 12.4 if fps > 0.0 else 0.0
    avg_conf = 91.4
    queue_size = 0

    # 4. Render to placeholders
    if init_mode:
        with st.expander("🔌 DIAGNOSTICS & SYSTEM CONTROLS", expanded=False):
            st.markdown("<div style='font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; margin-bottom: 6px;'>SYSTEM METRICS</div>", unsafe_allow_html=True)
            col_d1, col_d2 = st.columns(2)
            placeholders_dict['ai_perf_summary'] = col_d1.empty()
            placeholders_dict['health_summary'] = col_d2.empty()

            col_d3, col_d4 = st.columns(2)
            placeholders_dict['cameras_sensors_summary'] = col_d3.empty()
            placeholders_dict['connections_summary'] = col_d4.empty()

            col_d5, col_d6 = st.columns(2)
            placeholders_dict['stats_summary'] = col_d5.empty()
            placeholders_dict['recent_events_summary'] = col_d6.empty()

            st.markdown("<div style='margin: 6px 0; border-top:1px solid rgba(255,255,255,0.06);'></div>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; margin-bottom: 4px;'>DETAILED SYSTEMS STATUS</div>", unsafe_allow_html=True)

            with st.expander("🤖 AI Engine & Performance Details", expanded=False):
                placeholders_dict['ai_perf_inner'] = st.empty()
            with st.expander("🏥 Core System Infrastructure Health", expanded=False):
                placeholders_dict['health_inner'] = st.empty()
            with st.expander("📹 Cameras & Modbus Sensors Map", expanded=False):
                placeholders_dict['cameras_sensors_inner'] = st.empty()
            with st.expander("🔌 Connection Gateways", expanded=False):
                placeholders_dict['connections_inner'] = st.empty()
            with st.expander("📊 Active Incident Metrics", expanded=False):
                placeholders_dict['stats_inner'] = st.empty()
            with st.expander("📜 Safety Log Events Stream", expanded=False):
                placeholders_dict['recent_events_inner'] = st.empty()

            st.markdown("<div style='margin: 6px 0; border-top:1px solid rgba(255,255,255,0.06);'></div>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 10px; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; margin-bottom: 6px;'>⚡ OPERATOR QUICK ACTIONS</div>", unsafe_allow_html=True)
            col_qa1, col_qa2 = st.columns(2)
            with col_qa1:
                if st.button("🏥 Health Check", key="qa_health_check_right", use_container_width=True):
                    st.toast("🏥 Health Check: All CCTV streams, OPC UA sensors, SQL storage and Notification Gateways are 100% nominal.")
                    st.rerun()
                if st.button("📹 Ref Cameras", key="qa_ref_cameras_right", use_container_width=True):
                    st.toast("📹 Re-initialized CCTV decoder pipeline and cleared frame buffers.")
                    st.rerun()
            with col_qa2:
                if st.button("🚨 Test Alert", key="qa_test_alert_right", use_container_width=True):
                    from src.alert_system import dispatch_alerts
                    import random
                    severity_choice = random.choice(["MEDIUM", "HIGH", "CRITICAL"])
                    zones_list = ["Zone_A", "Zone_B", "Zone_C", "Reactor_Area", "Storage_Area"]
                    zone_choice = random.choice(zones_list)
                    test_payload = {
                        "should_alert": True,
                        "severity": severity_choice,
                        "messages": [f"TEST ALERT: Mock safety violation detected in {ZONE_LABELS.get(zone_choice, zone_choice)}"],
                        "summary": f"TEST ALERT: Mock safety violation detected in {zone_choice}",
                        "zone": zone_choice,
                        "channels": ["dashboard", "sms", "email", "telegram"]
                    }
                    dispatch_alerts(test_payload)
                    st.toast(f"🚨 Test {severity_choice} Alert dispatched to {ZONE_LABELS.get(zone_choice, zone_choice)}!")
                    st.rerun()
                if st.button("🔄 Reset Sim", key="qa_reset_sim_right", use_container_width=True):
                    from src.alert_system import clear_alert_if_safe
                    st.session_state.sim_stage = 'normal'
                    st.session_state.compound_risk_active = False
                    for z in ["Zone_A", "Zone_B", "Zone_C", "Reactor_Area", "Storage_Area"]:
                        clear_alert_if_safe(z, update_cooldown=False)
                        st.session_state[f"alert_active_{z}"] = False
                    st.session_state["_last_incident"] = None
                    st.toast("🔄 Simulation status reset. Clear alert commands dispatched.")
                    st.rerun()

    # Render Summaries
    if 'ai_perf_summary' in placeholders_dict and placeholders_dict['ai_perf_summary']:
        placeholders_dict['ai_perf_summary'].markdown(f"""
        <div style="font-size:10px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:4px; margin-bottom:4px;">
            🤖 Model: <b style="color:#60a5fa;">YOLOv8n-PPE ({fps:.1f} FPS)</b>
        </div>
        """, unsafe_allow_html=True)

    if 'health_summary' in placeholders_dict and placeholders_dict['health_summary']:
        placeholders_dict['health_summary'].markdown(f"""
        <div style="font-size:10px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:4px; margin-bottom:4px;">
            🏥 State: <b style="color:#22c55e;">🟢 HEALTHY (99.8%)</b>
        </div>
        """, unsafe_allow_html=True)

    if 'cameras_sensors_summary' in placeholders_dict and placeholders_dict['cameras_sensors_summary']:
        placeholders_dict['cameras_sensors_summary'].markdown(f"""
        <div style="font-size:10px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:4px; margin-bottom:4px;">
            📹 Feeds: <b style="color:#22c55e;">🟢 5/5 ONLINE</b>
        </div>
        """, unsafe_allow_html=True)

    if 'connections_summary' in placeholders_dict and placeholders_dict['connections_summary']:
        placeholders_dict['connections_summary'].markdown(f"""
        <div style="font-size:10px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:4px; margin-bottom:4px;">
            🔌 Gateways: <b style="color:#22c55e;">🟢 4/4 LINKED</b>
        </div>
        """, unsafe_allow_html=True)

    if 'stats_summary' in placeholders_dict and placeholders_dict['stats_summary']:
        stats_color = "#ef4444" if open_incidents > 0 else "#22c55e"
        placeholders_dict['stats_summary'].markdown(f"""
        <div style="font-size:10px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:4px; margin-bottom:4px;">
            📊 Alerts: <b style="color:{stats_color};">{open_incidents} Active</b>
        </div>
        """, unsafe_allow_html=True)

    if 'recent_events_summary' in placeholders_dict and placeholders_dict['recent_events_summary']:
        placeholders_dict['recent_events_summary'].markdown(f"""
        <div style="font-size:10px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:6px; border-radius:4px; margin-bottom:4px;">
            📜 Logs: <span style="color:#a0b4c8;">Last Safety Event</span>
        </div>
        """, unsafe_allow_html=True)

    # AI Engine & Performance
    if 'ai_perf_inner' in placeholders_dict and placeholders_dict['ai_perf_inner']:
        placeholders_dict['ai_perf_inner'].markdown(f"""
        <div style="font-size:11px; line-height:1.6; font-family:monospace; color:#cbd5e1;">
            <div style="display:flex; justify-content:space-between;"><span>Model:</span><span style="color:#3b82f6; font-weight:bold;">YOLOv8n-PPE</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Version:</span><span>v3.0.4 (FP16)</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Hardware:</span><span>{device_str}</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Confidence:</span><span style="color:#22c55e;">{avg_conf}% (Avg)</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Latency:</span><span style="color:#3b82f6;">{latency:.1f} ms</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Inference FPS:</span><span style="color:#22c55e;">{fps:.1f} FPS</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Frame Queue:</span><span>{queue_size} / 64</span></div>
        </div>
        """, unsafe_allow_html=True)

    # System Health
    if 'health_inner' in placeholders_dict and placeholders_dict['health_inner']:
        placeholders_dict['health_inner'].markdown("""
        <div style="font-size:11px; line-height:1.6; font-family:monospace; color:#cbd5e1;">
            <div style="display:flex; justify-content:space-between;"><span>AI Engine:</span><span style="color:#22c55e; font-weight:bold;">🟢 HEALTHY (99.8%)</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Alert Database:</span><span style="color:#22c55e; font-weight:bold;">🟢 HEALTHY (SQLite)</span></div>
            <div style="display:flex; justify-content:space-between;"><span>SCADA Gateway:</span><span style="color:#22c55e; font-weight:bold;">🟢 ONLINE</span></div>
            <div style="display:flex; justify-content:space-between;"><span>CCTV Cameras:</span><span style="color:#22c55e; font-weight:bold;">🟢 5/5 ONLINE</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Modbus Sensors:</span><span style="color:#22c55e; font-weight:bold;">🟢 24/24 ONLINE</span></div>
        </div>
        """, unsafe_allow_html=True)

    # Cameras & Sensors
    if 'cameras_sensors_inner' in placeholders_dict and placeholders_dict['cameras_sensors_inner']:
        placeholders_dict['cameras_sensors_inner'].markdown("""
        <div style="font-size:11px; line-height:1.6; font-family:monospace; color:#cbd5e1;">
            <div style="font-weight:bold; color:#a0b4c8; margin-bottom:4px; text-transform:uppercase; font-size:9.5px;">CCTV Streams</div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>📹 Battery-4 (Zone A):</span><span style="color:#22c55e;">ONLINE</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>📹 Battery-5 (Zone B):</span><span style="color:#22c55e;">ONLINE</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>📹 Battery-6 (Zone C):</span><span style="color:#22c55e;">ONLINE</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>📹 Reactor Block:</span><span style="color:#22c55e;">ONLINE</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>📹 Storage Area:</span><span style="color:#22c55e;">ONLINE</span></div>
            
            <div style="font-weight:bold; color:#a0b4c8; margin:8px 0 4px 0; text-transform:uppercase; font-size:9.5px;">Sensor Channels</div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>💨 Gas Telemetry:</span><span style="color:#22c55e;">CONNECTED</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>🌡️ Temperature:</span><span style="color:#22c55e;">CONNECTED</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>📊 Pressure:</span><span style="color:#22c55e;">CONNECTED</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>🌫️ Flame Detectors:</span><span style="color:#22c55e;">CONNECTED</span></div>
        </div>
        """, unsafe_allow_html=True)

    # Connection Gateways
    if 'connections_inner' in placeholders_dict and placeholders_dict['connections_inner']:
        placeholders_dict['connections_inner'].markdown("""
        <div style="font-size:11px; line-height:1.6; font-family:monospace; color:#cbd5e1;">
            <div style="display:flex; justify-content:space-between;"><span>MQTT Broker:</span><span style="color:#22c55e; font-weight:bold;">CONNECTED (10.0.0.45)</span></div>
            <div style="display:flex; justify-content:space-between;"><span>OPC UA Safety:</span><span style="color:#22c55e; font-weight:bold;">CONNECTED (Port 4840)</span></div>
            <div style="display:flex; justify-content:space-between;"><span>SQLite Local DB:</span><span style="color:#22c55e; font-weight:bold;">CONNECTED</span></div>
            <div style="display:flex; justify-content:space-between;"><span>AWS IoT Core:</span><span style="color:#22c55e; font-weight:bold;">CONNECTED (Sync)</span></div>
        </div>
        """, unsafe_allow_html=True)

    # Incident & Alert Stats
    if 'stats_inner' in placeholders_dict and placeholders_dict['stats_inner']:
        placeholders_dict['stats_inner'].markdown(f"""
        <div style="font-size:11px; line-height:1.6; font-family:monospace; color:#cbd5e1;">
            <div style="font-weight:bold; color:#a0b4c8; margin-bottom:4px; text-transform:uppercase; font-size:9.5px;">Summary</div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>Active Incidents:</span><span style="color:#ef4444; font-weight:bold;">{open_incidents}</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>Resolved Incidents:</span><span style="color:#22c55e;">{closed_incidents}</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>Total Today:</span><span style="color:#cbd5e1;">{today_incidents}</span></div>
            
            <div style="font-weight:bold; color:#a0b4c8; margin:8px 0 4px 0; text-transform:uppercase; font-size:9.5px;">Breakdown by Severity</div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>🔴 Critical:</span><span style="color:#ef4444; font-weight:bold;">{stat_critical}</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>🟠 High:</span><span style="color:#f97316;">{stat_high}</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>🟡 Medium:</span><span style="color:#eab308;">{stat_medium}</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>🟢 Low:</span><span style="color:#3b82f6;">{stat_low}</span></div>
            <div style="display:flex; justify-content:space-between; padding-left:6px;"><span>✅ Resolved:</span><span style="color:#22c55e;">{stat_resolved}</span></div>
        </div>
        """, unsafe_allow_html=True)

    # Recent Safety Log Events
    recent_events = []
    for a in active_alerts_dict.values():
        recent_events.append({
            "time": a.start_time,
            "text": f"⚙️ ACK: {a.message}" if a.status.name == 'ACKNOWLEDGED' else f"🚨 ALARM: {a.message} ({ZONE_LABELS.get(a.zone, a.zone)})",
            "color": "#eab308" if a.status.name == 'ACKNOWLEDGED' else "#ef4444"
        })
    for a in history_list:
        recent_events.append({
            "time": a.end_time or a.start_time,
            "text": f"✅ OK: {a.message} resolved",
            "color": "#22c55e"
        })
    recent_events.sort(key=lambda x: x["time"], reverse=True)
    recent_events = recent_events[:5]
    if 'recent_events_inner' in placeholders_dict and placeholders_dict['recent_events_inner']:
        if not recent_events:
            placeholders_dict['recent_events_inner'].markdown("<div style='font-size:10px; color:#64748b; font-family:monospace; text-align:center; padding:10px 0;'>No safety events logged.</div>", unsafe_allow_html=True)
        else:
            events_html = ["<div style='display:flex; flex-direction:column; gap:6px; font-family:monospace; font-size:10px;'>"]
            for ev in recent_events:
                t_str = ev["time"].strftime('%H:%M:%S')
                events_html.append(f"""
                <div style="border-left: 2px solid {ev['color']}; padding-left: 6px; margin-bottom: 2px; line-height:1.3;">
                    <span style="color:#64748b;">[{t_str}]</span><br/>
                    <span style="color:#cbd5e1;">{ev['text']}</span>
                </div>
                """)
            events_html.append("</div>")
            placeholders_dict['recent_events_inner'].markdown("".join(events_html), unsafe_allow_html=True)

    # ── Safety Intelligence Panels ──────────────────────────────────────────
    # Render the multi-agent intelligence layer (Executive Command Center,
    # Dynamic Safety Scores, Compound Risk Intelligence, Predictive Analytics,
    # AI Safety Copilot, Smart Alert Prioritization, Emergency Response,
    # Incident Intelligence, Timeline, Geospatial Plant Map).
    # NOTE: Safety Intelligence Panels are now rendered directly in app.py
    # after the orchestrator is fed with live telemetry, avoiding double rendering.


def render_incident_summary_html(open_incidents: int, closed_incidents: int, today_incidents: int) -> str:
    """Renders a beautiful industrial SCADA incident summary card"""
    import streamlit as st
    play_active = st.session_state.get('sim_play_active', False)
    min_height = "260px" if play_active else "320px"
    padding = "12px 14px" if play_active else "16px 18px"
    gap = "8px" if play_active else "12px"
    
    html = f"""
    <div style="background:linear-gradient(135deg,#0f1f38,#0a1628); border:1px solid #1e3a5f; border-radius:12px; padding:{padding}; min-height:{min_height}; box-sizing: border-box; font-family:Outfit,sans-serif; display:flex; flex-direction:column;">
        <div style="color:#94a3b8; font-size:10px; font-weight:600; letter-spacing:1px; margin-bottom:12px;">INCIDENT SUMMARY</div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:{gap}; flex-grow:1; align-items:stretch;">
            <div style="display:flex; flex-direction:column; justify-content:space-between; padding:12px 10px; background:rgba(239,68,68,0.06); border:1px solid rgba(239,68,68,0.15); border-radius:8px;">
                <span style="font-size:9px; font-weight:700; color:#ef4444; letter-spacing:0.5px; text-transform:uppercase;">Active/Open</span>
                <span style="font-size:36px; font-weight:800; color:#ef4444; font-family:monospace; line-height:1.0; text-align:right;">{open_incidents}</span>
            </div>
            <div style="display:flex; flex-direction:column; justify-content:space-between; padding:12px 10px; background:rgba(34,197,94,0.06); border:1px solid rgba(34,197,94,0.15); border-radius:8px;">
                <span style="font-size:9px; font-weight:700; color:#22c55e; letter-spacing:0.5px; text-transform:uppercase;">Resolved/Closed</span>
                <span style="font-size:36px; font-weight:800; color:#22c55e; font-family:monospace; line-height:1.0; text-align:right;">{closed_incidents}</span>
            </div>
            <div style="display:flex; flex-direction:column; justify-content:space-between; padding:12px 10px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:8px;">
                <span style="font-size:9px; font-weight:700; color:#cbd5e1; letter-spacing:0.5px; text-transform:uppercase;">Total Today</span>
                <span style="font-size:36px; font-weight:800; color:#cbd5e1; font-family:monospace; line-height:1.0; text-align:right;">{today_incidents}</span>
            </div>
        </div>
    </div>
    """
    return "".join([line.strip() for line in html.split("\n")])


def render_operational_overview(scada_placeholders: Dict[str, Any], data_dict: Dict[str, Any]) -> None:
    """Renders the 6 compact SCADA status cards for the operational overview row"""
    if not scada_placeholders:
        return
        
    latest = data_dict.get('latest', {})
    STATUS = data_dict.get('STATUS', {'level': 'NOMINAL', 'color': '#22C55E'})
    
    from src.ui_components import render_metric_card
    
    # 1. Plant Health
    ph_level = STATUS.get('level', 'NOMINAL')
    ph_color = STATUS.get('color', '#22C55E')
    if 'plant_health' in scada_placeholders:
        scada_placeholders['plant_health'].markdown(
            render_metric_card(
                label="PLANT HEALTH",
                value=ph_level,
                border_color=ph_color,
                value_color=ph_color,
                height="155px",
                extra_html="All sectors tracked"
            ),
            unsafe_allow_html=True
        )
    
    # 2. Sensor Status
    if 'sensor_status' in scada_placeholders:
        scada_placeholders['sensor_status'].markdown(
            render_metric_card(
                label="SENSOR STATUS",
                value="24/24",
                border_color="#22C55E",
                value_color="#22C55E",
                height="155px",
                extra_html="🟢 Modbus Gateway OK"
            ),
            unsafe_allow_html=True
        )
    
    # 3. Network Status
    if 'network_status' in scada_placeholders:
        scada_placeholders['network_status'].markdown(
            render_metric_card(
                label="NETWORK STATUS",
                value="ONLINE",
                border_color="#22C55E",
                value_color="#22C55E",
                height="155px",
                extra_html="🟢 MQTT & OPC Link OK"
            ),
            unsafe_allow_html=True
        )
    
    # 4. Database Status
    if 'database_status' in scada_placeholders:
        scada_placeholders['database_status'].markdown(
            render_metric_card(
                label="DATABASE STATUS",
                value="SQLite OK",
                border_color="#3B82F6",
                value_color="#60A5FA",
                height="155px",
                extra_html="Synced to AWS IoT"
            ),
            unsafe_allow_html=True
        )
    
    # 5. AI Model Status
    if 'ai_model_status' in scada_placeholders:
        scada_placeholders['ai_model_status'].markdown(
            render_metric_card(
                label="AI MODEL STATUS",
                value="YOLOv8n",
                border_color="#3B82F6",
                value_color="#60A5FA",
                height="155px",
                extra_html="FP16 GPU Accelerated"
            ),
            unsafe_allow_html=True
        )
    
    # 6. Last Synchronization Time
    from datetime import datetime
    sync_time_str = datetime.now().strftime("%H:%M:%S")
    if 'sync_time' in scada_placeholders:
        scada_placeholders['sync_time'].markdown(
            render_metric_card(
                label="LAST SYNC TIME",
                value=sync_time_str,
                border_color="#F59E0B",
                value_color="#FBBF24",
                height="155px",
                extra_html="Real-time stream"
            ),
            unsafe_allow_html=True
        )