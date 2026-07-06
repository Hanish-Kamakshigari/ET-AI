# -*- coding: utf-8 -*-
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

def render_sidebar(data_dict: Dict[str, Any], engine: Any, am: Any, alert_system: Any):
    """Renders the SurakshaAI console sidebar controls, statistics, and simulation timeline."""
    latest = data_dict['latest']
    max_score = data_dict['max_score']
    STATUS = data_dict['STATUS']
    zone_risks = data_dict['zone_risks']
    compound_rules_eval = data_dict['compound_rules_eval']
    
    sim_on = st.session_state.simulate_active or st.session_state.sim_stage in ['active', 'acknowledged']

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
        now_time = datetime.now()
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

        st.download_button(
            "📋 Export Compliance Report", 
            data=report,
            file_name=f"surakshaai_{now_time.strftime('%Y%m%d_%H%M%S')}.md",
            mime="text/markdown", 
            use_container_width=True
        )

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:4px 0 12px 0;"></div>""", unsafe_allow_html=True)

        # Compound rules list
        st.markdown("""
        <div style="font-size:12px;font-weight:700;color:#a0b4c8;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:10px;">🛡️ Compound Rules Scanned</div>""", unsafe_allow_html=True)

        rules_html = ""
        for rule in engine.compound_rules:
            rid       = rule.get('id', '')
            _lbl, _desc = RULE_META.get(rid, (rule.get('label', rid), rule.get('desc', '')))
            matched = False
            for rule_eval in compound_rules_eval:
                if rule_eval['id'] == rid:
                    matched = rule_eval['matched']
                    break
            dot_color = '#ef4444' if matched else '#22c55e'
            rules_html += (
                f'<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;">'
                f'<span style="width:7px;height:7px;border-radius:50%;background:{dot_color};'
                f'box-shadow:0 0 4px {dot_color};margin-top:4px;flex-shrink:0;display:inline-block;"></span>'
                f'<div style="font-size:11px;color:#a0b4c8;line-height:1.4;">'
                f'<b style="color:#fff;">{_lbl}</b> — {_desc}'
                f'</div></div>'
            )
        st.markdown(rules_html, unsafe_allow_html=True)

        st.markdown("""<div style="height:1px;background:rgba(255,255,255,0.06);margin:12px 0;"></div>""", unsafe_allow_html=True)

        # Telemetry status
        telemetry_color = '#ef4444' if sim_on else '#00d4ff'
        telemetry_label = 'CRITICAL' if sim_on else 'SECURE'
        now_str = now_time.strftime('%H:%M:%S')
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#6b7d94;">
          <span style="width:7px;height:7px;border-radius:50%;background:{telemetry_color};
            box-shadow:0 0 4px {telemetry_color};display:inline-block;"></span>
          Telemetry: <span style="color:{telemetry_color};font-weight:700;">{telemetry_label}</span>
          | {now_str}
        </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

        # ── Scenario Controls ──
        _scenario_min_now = (now_time - st.session_state.scenario_start_time).total_seconds() / 60.0 + st.session_state.scenario_offset_min
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
            if st.button("⏩ Fast-Forward +20min", key="ff_btn", use_container_width=True,
                         help="Advance scenario 20 minutes — gas rises rapidly to show realistic escalation"):
                st.session_state.scenario_offset_min += 20
                st.rerun()
        with col_rst:
            if st.button("🔄 Reset Scenario", key="reset_btn", use_container_width=True,
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
