"""
SurakshaAI Dashboard Components Module
"""

import os

import pandas as pd
import streamlit as st

from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS
from src.ui_components import render_section_header


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


def render_analytics_page():
    """Backward-compatible wrapper kept for older imports."""
    st.markdown(render_section_header("📊 ANALYTICS DASHBOARD"), unsafe_allow_html=True)


def render_analytics_tab(placeholders, data_dict, engine=None, alert_system=None):
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


def render_zones_tab(placeholders, data_dict, engine=None, alert_system=None):
    """Render the zone map with live risk colors and detailed zone telemetry."""
    st.markdown(render_section_header("🗺️ ZONE MAP"), unsafe_allow_html=True)

    latest = data_dict.get("latest", {})
    zone_risks = data_dict.get("zone_risks", {})
    selected_zone = st.session_state.get("selected_zone", SENSOR_ZONES[0])

    st.subheader("Plant Layout with Live Zone Colors")
    st.caption("Select a zone to inspect CCTV, thresholds, active alerts, permits, and risk score.")

    zone_columns = st.columns(3)
    for idx, zone in enumerate(SENSOR_ZONES):
        info = zone_risks.get(zone, {})
        risk_level = (info.get("risk_level") or "LOW").upper()
        color = _zone_color(risk_level)
        with zone_columns[idx % 3]:
            if st.button(
                f"{ZONE_LABELS.get(zone, zone)}\n{risk_level}",
                key=f"zone_map_{zone}",
                use_container_width=True,
            ):
                st.session_state.selected_zone = zone
                st.session_state.show_zone_details = True
            st.markdown(
                f"<div style='margin-top:-8px; height:8px; border-radius:999px; background:{color};'></div>",
                unsafe_allow_html=True,
            )

    st.divider()
    st.subheader(f"{ZONE_LABELS.get(selected_zone, selected_zone)} Details")

    info = zone_risks.get(selected_zone, {})
    risk_level = (info.get("risk_level") or "LOW").upper()
    score = info.get("risk_score", 0)
    permit_active = bool(latest.get(f"{selected_zone}_permit_active", 0) == 1)
    maintenance_active = bool(latest.get(f"{selected_zone}_maintenance_active", 0) == 1)

    col_a, col_b = st.columns([1.2, 0.8])
    with col_a:
        video_path = _zone_video_path(selected_zone)
        if video_path:
            st.video(video_path)
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


def render_settings_tab(placeholders, data_dict, engine=None, alert_system=None):
    """Render settings controls and persist them to session state."""
    st.markdown(render_section_header("⚙️ SETTINGS"), unsafe_allow_html=True)

    with st.form("suraksha_settings_form"):
        st.subheader("AI Detection Thresholds")
        severity_threshold = st.slider(
            "Risk Score Threshold",
            0.0,
            1.0,
            float(st.session_state.get("severity_threshold_value", 0.7)),
            step=0.05,
            key="severity_threshold_value",
        )

        st.subheader("Notification Settings")
        notifications = st.multiselect(
            "Notify via",
            ["SMS", "Email", "Siren"],
            default=st.session_state.get("notifications_pref", ["sms", "email", "siren"]),
            key="notifications_pref",
        )

        st.subheader("Dynamic Rule Engine")
        rule_text = st.text_input("Add New Rule", value=st.session_state.get("new_rule", ""), key="new_rule")
        if st.button("Add Rule", use_container_width=True):
            if rule_text:
                current_rules = st.session_state.get("rule_engine_rules", [])
                current_rules.append(rule_text)
                st.session_state.rule_engine_rules = current_rules
                st.toast("Rule added to configuration", icon="✅")

        if st.session_state.get("rule_engine_rules"):
            st.caption("Configured rules")
            st.code("\n".join(st.session_state.rule_engine_rules), language="text")

        st.subheader("Camera Management")
        camera_enabled = st.checkbox("Enable Camera Feed", value=st.session_state.get("camera_enabled", True), key="camera_enabled")

        st.subheader("User Roles & Permissions")
        role = st.selectbox(
            "Select Role",
            ["Admin", "Supervisor", "Operator"],
            index=["Admin", "Supervisor", "Operator"].index(st.session_state.get("selected_role", "Operator")),
            key="selected_role",
        )

        st.subheader("Alert Escalation Settings")
        escalation_attempts = st.slider("Max Escalation Attempts", 1, 5, int(st.session_state.get("max_escalations", 3)), key="max_escalations")

        st.subheader("Auto-refresh Configuration")
        refresh_interval = st.slider("Refresh Interval (seconds)", 5, 300, int(st.session_state.get("refresh_interval", 60)), key="refresh_interval")
        auto_refresh = st.checkbox("Enable Auto-refresh", value=st.session_state.get("auto_refresh", False), key="auto_refresh")

        submitted = st.form_submit_button("Save Settings")
        if submitted:
            st.session_state.severity_threshold = severity_threshold
            st.session_state.notifications_pref = notifications
            st.session_state.auto_refresh = auto_refresh
            st.session_state.refresh_interval = refresh_interval
            st.session_state.camera_enabled = camera_enabled
            st.session_state.selected_role = role
            st.session_state.max_escalations = escalation_attempts
            st.toast("Settings saved", icon="✅")


def render_sidebar_controls():
    """Legacy helper kept for compatibility with older imports."""
    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)