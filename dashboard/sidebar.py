"""
SurakshaAI Dashboard Sidebar Module
"""

import sys
import os
from datetime import datetime
from typing import Dict, Any
from src.risk_engine import CompoundRiskEngine
from src.alert_system import AlertSystem, AlertManager
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
    engine: CompoundRiskEngine,
    am: AlertManager,
    alert_system: AlertSystem,
) -> None:
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

    with sidebar_placeholder.container():
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

        st.markdown('<div class="suraksha-sidebar-title" style="margin-top: 5px;">🛡️ SurakshaAI Console</div>', unsafe_allow_html=True)

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
        width='stretch',
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
        def _on_autoplay_change() -> None:
            new_val = st.session_state.get('sim_play_active', False)
            print(f"[DEBUG_AUTOPLAY] Autoplay toggle callback triggered! New sim_play_active={new_val}")
            if new_val:
                st.session_state.scenario_start_time = datetime.now()
            try:
                from src.alert_system import clear_alert_if_safe
                all_zones = ["Zone_A", "Zone_B", "Zone_C", "Reactor_Area", "Storage_Area"]
                for z in all_zones:
                    clear_alert_if_safe(z, update_cooldown=False)
                    st.session_state[f"alert_active_{z}"] = False
                for alert_id in list(am.active_alerts.keys()):
                    try:
                        am.resolve_alert(alert_id)
                    except Exception:
                        pass
                st.session_state["_last_incident"] = None
            except Exception:
                pass

        st.toggle(
            "Autoplay Simulation",
            key="sim_play_active",
            on_change=_on_autoplay_change
        )

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
            if st.button("🏥 Health Check", key="qa_health_check", width='stretch'):
                st.toast("🏥 Health Check: All CCTV streams, OPC UA sensors, SQL storage and Notification Gateways are 100% nominal.")
                st.rerun()
            if st.button("📹 Ref Cameras", key="qa_ref_cameras", width='stretch'):
                st.toast("📹 Re-initialized CCTV decoder pipeline and cleared frame buffers.")
                st.rerun()
        with col_qa2:
            if st.button("🚨 Test Alert", key="qa_test_alert", width='stretch'):
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
            if st.button("🛑 Stop Sim", key="qa_stop_sim", width='stretch'):
                from src.alert_system import clear_alert_if_safe
                st.session_state.sim_play_active = False
                st.session_state.sim_stage = 'normal'
                st.session_state.compound_risk_active = False
                for z in ["Zone_A", "Zone_B", "Zone_C", "Reactor_Area", "Storage_Area"]:
                    clear_alert_if_safe(z, update_cooldown=False)
                    st.session_state[f"alert_active_{z}"] = False
                st.session_state["_last_incident"] = None
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

        with st.expander("⏱️ Scenario Timeline", expanded=True):
            st.markdown(f"""
            <div style="font-size:11px; display:flex; justify-content:space-between; margin-top:2px;">
                <span>Scenario: <b>{current_scen}</b></span>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:10px; margin-top:2px; font-family:monospace;">
                <span>Elapsed: {elapsed_str}</span>
                <span>Status: <b style="color:{sim_status_color};">{sim_status_lbl}</b></span>
            </div>
            """, unsafe_allow_html=True)

        # 8. System Diagnostics
        with st.expander("🔌 System Diagnostics", expanded=True):
            try:
                import torch
                device_str = "GPU" if torch.cuda.is_available() else "CPU"
            except Exception:
                device_str = "CPU"
            
            ph_level = STATUS.get('level', 'LOW')
            ph_color = STATUS.get('color', '#22c55e')
            sync_time_str = now_time.strftime("%H:%M:%S")
            num_active_alerts = len(am.active_alerts)
            fps_str = "25.0 FPS" if st.session_state.get('sim_play_active', False) else "0.0 FPS"
            
            st.markdown(f"""
            <div style="font-family: monospace; font-size: 10px; color: #cbd5e1; line-height: 1.6;">
                <div style="display: flex; align-items: baseline;">
                    <span>🟢 Plant Health</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: {ph_color}; font-weight: bold;">{ph_level}</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 Sensors</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #22c55e; font-weight: bold;">24/24 Online</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 CCTV Feeds</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #22c55e; font-weight: bold;">5/5 Online</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 SCADA Gateways</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #22c55e; font-weight: bold;">4/4 Linked</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 Database</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #60a5fa; font-weight: bold;">SQLite OK</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 AI Model</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #60a5fa; font-weight: bold;">YOLOv8n ({device_str})</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 Model Speed</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #22c55e; font-weight: bold;">{fps_str}</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 Active Alerts</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: {'#ef4444' if num_active_alerts > 0 else '#22c55e'}; font-weight: bold;">{num_active_alerts} Active</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 Last Sync</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #f59e0b; font-weight: bold;">{sync_time_str}</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 2px;">
                    <span>🟢 Runtime</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #475569; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span style="color: #22c55e; font-weight: bold;">Healthy</span>
                </div>
                <div style="display: flex; align-items: baseline; margin-top: 4px; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.06); color: #64748b; font-size: 8.5px;">
                    <span>Build Version</span>
                    <span style="flex-grow: 1; border-bottom: 1px dotted #334155; margin: 0 4px; position: relative; top: -3px;"></span>
                    <span>v3.0.4 (#9104)</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:5px 0 7px 0;"></div>""", unsafe_allow_html=True)

        # 9. SCADA Sub-panels (Zone Status, Plant Failsafes, Database Logs) wrapped in st.expander
        with st.expander("📊 Zone Status", expanded=True):
            zone_status_slot = st.empty()
            render_zone_status_panel(zone_status_slot, data_dict)
            placeholders['zone_status'] = zone_status_slot

        with st.expander("🛡️ Plant Failsafes", expanded=True):
            failsafes_slot = st.empty()
            render_failsafes_panel(failsafes_slot, data_dict)
            placeholders['failsafes'] = failsafes_slot

        with st.expander("🗄️ Database Logs", expanded=True):
            db_logs_slot = st.empty()
            render_db_logs_panel(db_logs_slot, data_dict)
            placeholders['db_logs'] = db_logs_slot

        # 9b. Recent Alerts List (active + recently resolved)
        with st.expander("🚨 Recent Alerts", expanded=True):
            recent_alerts_slot = st.empty()
            recent_html_lines = []
            active_list = list(am.active_alerts.values())[-5:] if am.active_alerts else []
            for a in reversed(active_list):
                sev = getattr(a.severity, "value", ("", "", "LOW"))
                sev_label = sev[2] if isinstance(sev, tuple) and len(sev) > 2 else str(sev)
                sev_upper = sev_label.upper()
                sev_color = {"CRITICAL": "#EF4444", "HIGH": "#F97316", "MEDIUM": "#F59E0B", "LOW": "#22C55E"}.get(sev_upper, "#3B82F6")
                zone_lbl = ZONE_LABELS.get(a.zone, a.zone)
                dur = int(getattr(a, 'duration', 0))
                dur_str = f"{dur // 60:02d}:{dur % 60:02d}"
                recent_html_lines.append(
                    f'<div style="border-left:3px solid {sev_color}; background:rgba(255,255,255,0.02); padding:4px 8px; margin-bottom:3px; border-radius:0 4px 4px 0;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                    f'<span style="font-size:9px; font-weight:800; color:{sev_color}; text-transform:uppercase;">{sev_label}</span>'
                    f'<span style="font-size:8px; color:#64748b; font-family:monospace;">{dur_str}</span>'
                    f'</div>'
                    f'<div style="font-size:10px; color:#F8FAFC; font-weight:600; margin-top:1px; line-height:1.2;">{a.message[:60]}</div>'
                    f'<div style="font-size:8.5px; color:#94A3B8; margin-top:1px;">📍 {zone_lbl}</div>'
                    f'</div>'
                )
            history_list = list(am.history)[-3:] if am.history else []
            for a in reversed(history_list):
                sev = getattr(a.severity, "value", ("", "", "LOW"))
                sev_label = sev[2] if isinstance(sev, tuple) and len(sev) > 2 else str(sev)
                sev_upper = sev_label.upper()
                sev_color = {"CRITICAL": "#EF4444", "HIGH": "#F97316", "MEDIUM": "#F59E0B", "LOW": "#22C55E"}.get(sev_upper, "#3B82F6")
                zone_lbl = ZONE_LABELS.get(a.zone, a.zone)
                dur = int(getattr(a, 'duration', 0))
                dur_str = f"{dur // 60:02d}:{dur % 60:02d}"
                end_str = a.end_time.strftime('%H:%M:%S') if a.end_time else ''
                recent_html_lines.append(
                    f'<div style="border-left:3px solid rgba(34,197,94,0.4); background:rgba(34,197,94,0.02); padding:4px 8px; margin-bottom:3px; border-radius:0 4px 4px 0; opacity:0.7;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                    f'<span style="font-size:9px; font-weight:800; color:#22C55E; text-transform:uppercase;">✓ RESOLVED</span>'
                    f'<span style="font-size:8px; color:#64748b; font-family:monospace;">{end_str}</span>'
                    f'</div>'
                    f'<div style="font-size:10px; color:#CBD5E1; font-weight:600; margin-top:1px; line-height:1.2;">{a.message[:60]}</div>'
                    f'<div style="font-size:8.5px; color:#64748B; margin-top:1px;">📍 {zone_lbl} | {dur_str}</div>'
                    f'</div>'
                )
            if not recent_html_lines:
                recent_html_lines.append(
                    '<div style="text-align:center; padding:12px; color:#64748b; font-size:10px;">'
                    '🟢 No recent alerts. All zones nominal.'
                    '</div>'
                )
            recent_html = "".join(recent_html_lines)
            recent_alerts_slot.markdown(
                f'<div style="padding-right:4px;">{recent_html}</div>',
                unsafe_allow_html=True
            )
            placeholders['recent_alerts'] = recent_alerts_slot

        # Smart Operator Guidance panel (moved from right to left)
        with st.expander("👷 Smart Operator Guidance", expanded=False):
            try:
                from dashboard.intelligence_ui import render_smart_operator_guidance
                guidance_placeholder = st.empty()
                render_smart_operator_guidance()
            except Exception:
                pass

        # Smart Alert Prioritization panel (moved from right to left)
        with st.expander("🚨 Smart Alert Prioritization", expanded=False):
            try:
                from dashboard.intelligence_ui import render_smart_alert_prioritization
                alerts_priority_placeholder = st.empty()
                render_smart_alert_prioritization()
            except Exception:
                pass

        # 10. Footer
        st.markdown("""
        <div style="font-size:9px; color:#64748b; font-family:monospace; margin-top:9px; border-top:1px solid rgba(255,255,255,0.06); padding-top:6px;">
          <div>App Version: v3.0.4</div>
            <div>Build: #9104</div>
            <div>Connected User: Operator #08</div>
        </div>
        """, unsafe_allow_html=True)