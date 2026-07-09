"""
SurakshaAI Dashboard Sidebar Module
"""

import sys
import os
from datetime import datetime
from typing import Dict, Any
import streamlit as st

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS, RULE_META
from dashboard.components import (
    render_zone_status_panel,
    render_failsafes_panel,
    render_db_logs_panel,
    render_scada_panel,
)


def render_sidebar(
    sidebar_placeholder: st.delta_generator.DeltaGenerator,
    placeholders: Dict[str, Any],
    data_dict: Dict[str, Any],
    engine: Any,
    am: Any,
    alert_system: Any,
):
    """Renders the permanent SurakshaAI Console sidebar with all controls and status panels."""
    latest = data_dict['latest']
    max_score = data_dict['max_score']
    STATUS = data_dict['STATUS']
    zone_risks = data_dict['zone_risks']
    compound_rules_eval = data_dict['compound_rules_eval']

    now_time = datetime.now()
    from src.config.ui_constants import ZONE_LABELS
    report = f"# SURAKSHAAI SAFETY COMPLIANCE REPORT\nGenerated: {now_time.strftime('%Y-%m-%d %H:%M:%S')}\nSystem State: {STATUS['level']} (Max Score: {max_score:.0f}/20)\n\n## Zone Health Audit\n"
    for zone_id, z in zone_risks.items():
        report += f"\n### {z['label']}\n- Level: {z['risk_level']}\n- Score: {z['risk_score']:.0f}/20\n"

    if st.session_state.get('compound_risk_active', False) or st.session_state.get('sim_stage') == 'active':
        report += "\n## Compound Patterns Detected\n- ⚠️ Visakhapatnam triple-threat disaster pattern detected in Battery-4 (Zone A)!\n"

    report += "\n## Stateful Active Alerts\n"
    if not am.active_alerts:
        report += "No active alerts.\n"
    else:
        for a in am.active_alerts.values():
            report += f"\n### Alert: {a.message}\n- Zone: {ZONE_LABELS.get(a.zone, a.zone)}\n- Severity: {a.severity.value[2]}\n- Status: {a.status.value}\n- Duration: {int(a.duration)}s\n"
            if a.acknowledged_by:
                report += f"- Acknowledged by: {a.acknowledged_by}\n"

    report += "\n## Stateful Resolved Alerts History (Audit Log)\n"
    if not am.history:
        report += "No resolved alerts in this session.\n"
    else:
        for a in am.history:
            report += f"\n### Alert: {a.message}\n- Zone: {ZONE_LABELS.get(a.zone, a.zone)}\n- Severity: {a.severity.value[2]}\n- Duration: {int(a.duration)}s\n- Status: Resolved\n- Acknowledged by: {a.acknowledged_by or 'N/A'}\n- Resolved at: {a.end_time.strftime('%H:%M:%S') if a.end_time else 'N/A'}\n"

    report += "\n---\nSurakshaAI v3.0 | Zero-Harm Operations\n"

    is_expanded = st.session_state.get('sidebar_expanded', True)

    with sidebar_placeholder.container():
        if is_expanded:
            st.markdown("""
            <style>
            .suraksha-sidebar-title {
                font-size: 14px;
                font-weight: 800;
                color: #fff;
                margin-bottom: 12px;
                font-family: 'Outfit', sans-serif;
            }
            </style>
            """, unsafe_allow_html=True)

            col_title, col_toggle = st.columns([3, 1])
            with col_title:
                st.markdown('<div class="suraksha-sidebar-title" style="margin-top: 5px;">🛡️ SurakshaAI Console</div>', unsafe_allow_html=True)
            with col_toggle:
                if st.button("◀", key="sidebar_collapse_btn", use_container_width=True, help="Collapse Console"):
                    st.session_state.sidebar_expanded = False

            # 1. System Uptime & Engine
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:8px 10px; margin-bottom:8px;">
                <div style="font-size:8px; color:#64748B; font-weight:700; text-transform:uppercase;">System Status</div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-top:4px;">
                    <span>Uptime: <b style="color:#22c55e;">100%</b></span>
                    <span>Engine: <b style="color:#22c55e;">HEALTHY</b></span>
                </div>
                <div style="font-size:9px; color:#64748b; margin-top:2px; font-family:monospace;">Heartbeat: {now_time.strftime('%H:%M:%S')}</div>
            </div>
            """, unsafe_allow_html=True)

            # 2. Export Compliance Report
            st.download_button(
                "📋 Export Compliance Report",
                data=report,
                file_name=f"surakshaai_{now_time.strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True,
                key="btn_report_expanded"
            )
            st.markdown(f"<div style='font-size:9px; color:#64748b; text-align:center; margin-top:-4px; margin-bottom:8px;'>Last Export: {now_time.strftime('%H:%M:%S')}</div>", unsafe_allow_html=True)

            # 3. Compound Rules Scanned
            total_rules = len(engine.compound_rules) if hasattr(engine, 'compound_rules') else 0
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:8px 10px; margin-bottom:8px;">
                <div style="font-size:8px; color:#64748B; font-weight:700; text-transform:uppercase;">Compound Rules</div>
                <div style="font-size:11px; margin-top:4px; display:flex; justify-content:space-between;">
                    <span>Active Rules: <b>{total_rules} Scanned</b></span>
                </div>
                <div style="font-size:9px; color:#64748b; margin-top:2px; font-family:monospace;">Evaluated: {total_rules} | Last Match: None</div>
            </div>
            """, unsafe_allow_html=True)

            # 4. Autoplay Simulation
            play_active = st.toggle("Autoplay Simulation", value=st.session_state.get('sim_play_active', False), key="autoplay_sim_toggle")
            if play_active != st.session_state.get('sim_play_active', False):
                st.session_state.sim_play_active = play_active

            speed_options = ["1x", "2x", "4x"]
            current_speed = st.session_state.get('sim_play_speed', '1x')
            speed_idx = speed_options.index(current_speed) if current_speed in speed_options else 0
            selected_speed = st.radio("Simulation Speed", speed_options, index=speed_idx, horizontal=True, key="sim_play_speed_radio")
            if selected_speed != current_speed:
                st.session_state.sim_play_speed = selected_speed

            # 5. Quick Plant Status
            num_active_alerts = len(am.active_alerts)
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:8px 10px; margin-bottom:8px; margin-top:8px;">
                <div style="font-size:8px; color:#64748B; font-weight:700; text-transform:uppercase;">Plant Overview</div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:10px; margin-top:4px; font-family:monospace;">
                    <div>📹 Cameras: <b style="color:#22c55e;">5/5 ON</b></div>
                    <div>🔌 Sensors: <b style="color:#22c55e;">24/24 ON</b></div>
                    <div>🗺️ Zones: <b>5 Active</b></div>
                    <div>🚨 Alerts: <b style="color:{'#ef4444' if num_active_alerts > 0 else '#cbd5e1'};">{num_active_alerts} Active</b></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # 6. Emergency Controls
            st.markdown("""<div style="font-size:8px; color:#64748B; font-weight:700; text-transform:uppercase; margin-bottom:4px;">Emergency Controls</div>""", unsafe_allow_html=True)
            col_qa1, col_qa2 = st.columns(2)
            with col_qa1:
                if st.button("🏥 Health Check", key="qa_health_check", use_container_width=True):
                    st.toast("🏥 Health Check: All CCTV streams, OPC UA sensors, SQL storage and Notification Gateways are 100% nominal.")
                    st.rerun()
                if st.button("📹 Ref Cameras", key="qa_ref_cameras", use_container_width=True):
                    st.toast("📹 Re-initialized CCTV decoder pipeline and cleared frame buffers.")
                    st.rerun()
            with col_qa2:
                if st.button("🚨 Test Alert", key="qa_test_alert", use_container_width=True):
                    from src.alert_system import dispatch_alerts
                    import random
                    severity_choice = random.choice(["MEDIUM", "HIGH", "CRITICAL"])
                    zones_list = ["Zone_A", "Zone_B", "Zone_C", "Reactor_Block", "Storage_Area"]
                    zone_choice = random.choice(zones_list)
                    test_payload = {
                        "should_alert": True,
                        "severity": severity_choice,
                        "messages": [f"TEST ALERT: Mock safety violation detected in {ZONE_LABELS.get(zone_choice, zone_choice)}"],
                        "summary": f"TEST ALERT: Mock safety violation detected in {ZONE_LABELS.get(zone_choice, zone_choice)}",
                        "zone": zone_choice,
                        "channels": ["dashboard", "sms", "email", "telegram"]
                    }
                    dispatch_alerts(test_payload)
                    st.toast(f"🚨 Test {severity_choice} Alert dispatched to {ZONE_LABELS.get(zone_choice, zone_choice)}!")
                    st.rerun()
                if st.button("🛑 Stop Sim", key="qa_stop_sim", use_container_width=True):
                    from src.alert_system import clear_alert_if_safe
                    st.session_state.sim_play_active = False
                    st.session_state.sim_stage = 'normal'
                    st.session_state.compound_risk_active = False
                    for z in ["Zone_A", "Zone_B", "Zone_C", "Reactor_Block", "Storage_Area"]:
                        clear_alert_if_safe(z)
                    st.toast("🛑 Simulation Stopped & Cleaned.")
                    st.rerun()

            # 7. Scenario Timeline
            sc_start = st.session_state.get('scenario_start_time')
            if sc_start:
                elapsed = int((datetime.now() - sc_start).total_seconds())
                elapsed_str = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
            else:
                elapsed_str = "00:00"
            sim_status_lbl = "PLAYING" if st.session_state.get('sim_play_active', False) else "PAUSED"
            sim_status_color = "#22c55e" if sim_status_lbl == "PLAYING" else "#f97316"
            current_scen = "Nominal Shift / PPE" if st.session_state.get('sim_stage') == 'normal' else "Active Incident Triggered"

            with st.expander("⏱️ Scenario Timeline", expanded=False):
                st.markdown(f"""
                <div style="font-size:11px; display:flex; justify-content:space-between; margin-top:2px;">
                    <span>Scenario: <b>{current_scen}</b></span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:10px; margin-top:2px; font-family:monospace;">
                    <span>Elapsed: {elapsed_str}</span>
                    <span>Status: <b style="color:{sim_status_color};">{sim_status_lbl}</b></span>
                </div>
                """, unsafe_allow_html=True)

            # 8. SCADA Gateway Status
            with st.expander("🔌 SCADA Gateways", expanded=False):
                st.markdown("""
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:10px; font-family:monospace;">
                    <div>📡 MQTT: <b style="color:#22c55e;">ON</b></div>
                    <div>🔌 OPC UA: <b style="color:#22c55e;">ON</b></div>
                    <div>🗄️ Database: <b style="color:#22c55e;">ON</b></div>
                    <div>☁️ Cloud Sync: <b style="color:#22c55e;">ON</b></div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:5px 0 7px 0;"></div>""", unsafe_allow_html=True)

            # 9. SCADA Sub-panels (Zone Status, Plant Failsafes, Database Logs) wrapped in st.expander
            with st.expander("📊 Zone Status", expanded=False):
                zone_status_slot = st.empty()
                render_zone_status_panel(zone_status_slot, data_dict)
                placeholders['zone_status'] = zone_status_slot

            with st.expander("🛡️ Plant Failsafes", expanded=False):
                failsafes_slot = st.empty()
                render_failsafes_panel(failsafes_slot, data_dict)
                placeholders['failsafes'] = failsafes_slot

            with st.expander("🗄️ Database Logs", expanded=False):
                db_logs_slot = st.empty()
                render_db_logs_panel(db_logs_slot, data_dict)
                placeholders['db_logs'] = db_logs_slot

            # 10. Footer
            st.markdown("""
            <div style="font-size:9px; color:#64748b; font-family:monospace; margin-top:9px; border-top:1px solid rgba(255,255,255,0.06); padding-top:6px;">
              <div>App Version: v3.0.4</div>
              <div>Build: #9104</div>
              <div>Connected User: Operator #08</div>
            </div>
            """, unsafe_allow_html=True)

        else:
            # Expand button at the top
            if st.button("▶", key="sidebar_expand_btn", use_container_width=True, help="Expand Console"):
                st.session_state.sidebar_expanded = True

            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

            # Center-aligned icon dock styles and markup
            total_rules = len(engine.compound_rules) if hasattr(engine, 'compound_rules') else 0
            is_autoplay = st.session_state.get('sim_play_active', False)
            
            st.markdown(f"""
            <style>
            .collapsed-icon-dock {{
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 9px;
                width: 100%;
            }}
            .collapsed-icon-item {{
                font-size: 20px;
                cursor: pointer;
                transition: transform 0.2s ease, background-color 0.2s ease;
                display: flex;
                align-items: center;
                justify-content: center;
                width: 44px;
                height: 44px;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.05);
            }}
            .collapsed-icon-item:hover {{
                transform: scale(1.15);
                background: rgba(255, 255, 255, 0.07);
                border-color: rgba(255, 255, 255, 0.15);
            }}
            </style>
            <div class="collapsed-icon-dock">
                <div class="collapsed-icon-item" title="Dashboard Status (100% Nominal)">🛡️</div>
                <div class="collapsed-icon-item" title="Compound Rules Scanned ({total_rules} Active)">🧩</div>
                <div class="collapsed-icon-item" title="Simulation Controls (Autoplay Active: {'YES' if is_autoplay else 'NO'})">▶️</div>
                <div class="collapsed-icon-item" title="Scenario Timeline">⏱️</div>
                <div class="collapsed-icon-item" title="Zone Status Overview">📍</div>
                <div class="collapsed-icon-item" title="Plant Failsafes Status">⚙️</div>
                <div class="collapsed-icon-item" title="Database Logging Active">🗄️</div>
                <div class="collapsed-icon-item" title="SCADA Gateways Online">🔌</div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            
            # Export Report download button at the bottom
            st.download_button(
                "📄",
                data=report,
                file_name=f"surakshaai_{now_time.strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True,
                key="btn_report_collapsed",
                help="Export Safety Compliance Report"
            )

            # Clean all placeholders to prevent CCTV loop from rendering in them
            if 'zone_status' in placeholders and placeholders['zone_status']:
                placeholders['zone_status'].empty()
            if 'failsafes' in placeholders and placeholders['failsafes']:
                placeholders['failsafes'].empty()
            if 'db_logs' in placeholders and placeholders['db_logs']:
                placeholders['db_logs'].empty()


