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
    
    # Initialize sidebar collapse state if not already set
    if 'sidebar_collapsed' not in st.session_state:
        st.session_state.sidebar_collapsed = False

    collapsed = st.session_state.get('sidebar_collapsed', False)
    st.markdown(f"""
    <style>
    section[data-testid="stSidebar"] {{
        width: 24rem !important;
        min-width: 24rem !important;
    }}
    {'[data-testid="stSidebar"] { display: none !important; }' if collapsed else ''}
    .suraksha-sidebar-reopen {{
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.5rem 0.8rem;
        margin: 0.75rem 0 1rem 0;
        border-radius: 999px;
        border: 1px solid rgba(0, 212, 255, 0.25);
        background: rgba(5, 11, 22, 0.95);
        color: #fff;
        font-weight: 700;
        font-size: 0.9rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.35);
    }}
    </style>
    """, unsafe_allow_html=True)

    if collapsed:
        if st.button("☰ SurakshaAI Console", key="expand_sidebar_main", use_container_width=False):
            st.session_state.sidebar_collapsed = False
            st.rerun()
        return
    
    with st.sidebar:
        # Sidebar collapse/expand controls
        st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
        
        col1, col2 = st.columns([1, 9])
        with col1:
            if st.button("<<", key="collapse_sidebar"):
                st.session_state.sidebar_collapsed = True
                st.rerun()
        with col2:
            if st.button(">>", key="expand_sidebar"):
                st.session_state.sidebar_collapsed = False
                st.rerun()
        
        # Always keep the logo accessible
        st.markdown("""
        <div style="margin-top:16px;">
            <a href="?sidebar=1" style="text-decoration:none;">
                <img src="assets/logo.png" width="40" style="vertical-align:middle;">
                <span style="font-size:12px;color:#fff;vertical-align:middle;">SurakshaAI Console</span>
            </a>
        </div>
        """, unsafe_allow_html=True)
    
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
            width='stretch'
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
                    matched = True
                    break
            if matched:
                rule_desc = RULE_META.get(rid, ('Unknown', ''))[1]
                st.markdown(f"- {rule.get('label', 'Unknown')} ({rule_desc})")