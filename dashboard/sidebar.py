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
                if st.button("◀", key="sidebar_toggle_btn", use_container_width=True, help="Collapse Console"):
                    st.session_state.sidebar_expanded = False
                    st.rerun()

            # System Uptime Card
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

            st.download_button(
                "📋 Export Compliance Report",
                data=report,
                file_name=f"surakshaai_{now_time.strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True,
                key="btn_report_expanded"
            )

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

            st.markdown("""
            <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:10px;">🛡️ Compound Rules Scanned</div>""", unsafe_allow_html=True)

            for rule in engine.compound_rules:
                rid = rule.get('id', '')
                _lbl, _desc = RULE_META.get(rid, (rule.get('label', rid), rule.get('desc', '')))
                matched = False
                for rule_eval in compound_rules_eval:
                    if rule_eval['id'] == rid:
                        matched = True
                        break
                if matched:
                    rule_desc = RULE_META.get(rid, ('Unknown', ''))[1]
                    st.markdown(f"- {rule.get('label', 'Unknown')} ({rule_desc})")

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

            st.markdown("""
            <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:10px;">📊 Zone Status</div>""", unsafe_allow_html=True)
            zone_status_slot = st.empty()
            render_zone_status_panel(zone_status_slot, data_dict)
            placeholders['zone_status'] = zone_status_slot

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

            st.markdown("""
            <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:10px;">🛡️ Plant Failsafes</div>""", unsafe_allow_html=True)
            failsafes_slot = st.empty()
            render_failsafes_panel(failsafes_slot, data_dict)
            placeholders['failsafes'] = failsafes_slot

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

            st.markdown("""
            <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:10px;">🗄️ Database Logs</div>""", unsafe_allow_html=True)
            db_logs_slot = st.empty()
            render_db_logs_panel(db_logs_slot, data_dict)
            placeholders['db_logs'] = db_logs_slot

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

            st.markdown("""
            <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:10px;">📡 SCADA Gateway Status</div>""", unsafe_allow_html=True)
            scada_slot = st.empty()
            render_scada_panel(scada_slot)
            placeholders['scada'] = scada_slot

        else:
            # Shield icon and expand arrow
            if st.button("🛡️ ▶", key="sidebar_toggle_btn", use_container_width=True, help="Expand Console"):
                st.session_state.sidebar_expanded = True
                st.rerun()

            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

            # Compact Uptime Status Dot
            st.markdown("""
            <div style="text-align:center; background:rgba(34,197,94,0.08); border:1px solid rgba(34,197,94,0.2); 
                        border-radius:10px; padding:10px 4px; margin-bottom:12px;" title="System Uptime: 100%">
                <div class="dot dot-safe" style="width:12px; height:12px; margin:0 auto;"></div>
                <div style="font-size:9px; color:#22C55E; font-weight:bold; margin-top:4px;">100%</div>
            </div>
            """, unsafe_allow_html=True)

            # Compact Export Report Icon Button
            st.download_button(
                "📋",
                data=report,
                file_name=f"surakshaai_{now_time.strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True,
                key="btn_report_collapsed",
                help="Export Safety Compliance Report"
            )

            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
            
            # Compact Zone Status overview
            st.markdown("""<div style="font-size:8px; font-weight:bold; color:#64748B; text-align:center; margin-bottom:6px;">ZONES</div>""", unsafe_allow_html=True)
            for zone_id, z in zone_risks.items():
                lvl = z.get('risk_level', 'LOW')
                lbl_color = '#ef4444' if lvl == 'CRITICAL' else '#f59e0b' if lvl == 'HIGH' else '#eab308' if lvl == 'MEDIUM' else '#22c55e'
                short_name = zone_id.replace("Zone_", "").replace("_Area", "")[:3].upper()
                st.markdown(f"""
                <div style="text-align:center; margin-bottom:4px; padding:4px; background:rgba(255,255,255,0.02); border-radius:4px; border-left:2px solid {lbl_color};" title="{z.get('label', zone_id)}: {lvl}">
                    <span style="font-size:8px; font-family:monospace; color:#cbd5e1;">{short_name}</span>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
            st.markdown("""<div style="font-size:8px; font-weight:bold; color:#64748B; text-align:center; margin-bottom:4px;">SCADA</div>""", unsafe_allow_html=True)
            # Compact SCADA Gateway
            st.markdown("""
            <div style="text-align:center;" title="SCADA Gateways Online">
                <span style="font-size:18px;">📡</span>
                <div class="dot dot-safe" style="width:6px; height:6px; margin: 4px auto 0 auto;"></div>
            </div>
            """, unsafe_allow_html=True)


