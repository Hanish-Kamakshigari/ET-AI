# -*- coding: utf-8 -*-
"""
SurakshaAI Dashboard Layout Module
"""

import sys
import os
from typing import Dict, Any, Tuple
import streamlit as st

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ui_components import render_section_header

def render_auto_banner(placeholder: st.delta_generator.DeltaGenerator, data_dict: Dict[str, Any]):
    """Renders the top alert banner dynamically based on system state"""
    banner_level = data_dict['banner_level']
    banner_color = data_dict['banner_color']
    banner_border = data_dict['banner_border']
    
    if banner_level:
        html = f"""
        <div style="background:{banner_color}; border:2px solid {banner_border}; 
                    border-radius:12px; padding:12px 20px; text-align:center;
                    animation: emergPulse 2.5s ease-in-out infinite;
                    box-shadow:0 0 20px rgba(239,68,68,0.25); margin-bottom:15px; 
                    font-family:'Outfit',sans-serif;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:800; color:#fff; font-size:13px; letter-spacing:1px; text-transform:uppercase;">
                    🚨 {banner_level}
                </span>
                <a href="?ack_auto_alert=1" target="_self" style="text-decoration:none;">
                    <span style="background:#fff; color:{banner_border}; border-radius:6px; 
                                 padding:4px 12px; font-size:10px; font-weight:800; cursor:pointer;">
                        ACKNOWLEDGE BANNER
                    </span>
                </a>
            </div>
        </div>
        """
        placeholder.markdown(html, unsafe_allow_html=True)
    else:
        placeholder.empty()

def create_layout() -> Tuple[st.delta_generator.DeltaGenerator, st.delta_generator.DeltaGenerator, Dict[str, st.delta_generator.DeltaGenerator]]:
    """Creates the structural layout, rows, and columns of the dashboard and returns placeholders"""
    
    # CCTV auto-detect alert banner placeholder
    auto_banner_placeholder = st.empty()

    # Simulation Injection Alert State Banner
    sim_banner_placeholder = st.empty()
    if st.session_state.sim_stage == 'active':
        html = """
        <div class="emergency-banner" style="display:flex;justify-content:space-between;align-items:center;">
          <div style="display:flex;align-items:center;gap:12px;">
            <span class="pulse-red" style="font-size:20px;">🚨</span>
            <div>
              <b style="color:#ef4444;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">
                Critical Threat Incident Active</b>
              <p style="color:#a0b4c8;font-size:12px;margin:2px 0 0 0;">
                Battery-4 (Zone A) gas telemetry has breached critical thresholds during hot work maintenance.</p>
            </div>
          </div>
          <a href="?ack_alert=ALT-001" target="_self" style="text-decoration:none;">
            <span style="background:#ef4444;color:#fff;border-radius:6px;padding:6px 16px;
            font-size:11px;font-weight:700;display:inline-block;cursor:pointer;letter-spacing:0.5px;">
              ACKNOWLEDGE SYSTEM CRITICAL</span></a>
        </div>"""
        sim_banner_placeholder.markdown(html, unsafe_allow_html=True)
    elif st.session_state.sim_stage == 'acknowledged':
        html = """
        <div style="background:rgba(34,197,94,0.07);border:1px solid rgba(34,197,94,0.3);border-radius:12px;
        padding:13px 20px;margin:0 0 14px 0;display:flex;align-items:center;justify-content:space-between;">
          <div style="display:flex;align-items:center;gap:12px;">
            <span class="dot dot-safe"></span>
            <div>
              <b style="color:#22c55e;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">
                Compound Threat Acknowledged</b>
              <p style="color:#6b7d94;font-size:12px;margin:2px 0 0 0;">
                Emergency teams notified. Sirens active in Battery-4.</p>
            </div>
          </div>
          <span style="background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3);
          border-radius:6px;padding:3px 10px;font-size:11px;font-weight:700;">ACKNOWLEDGED</span>
        </div>"""
        sim_banner_placeholder.markdown(html, unsafe_allow_html=True)

    # 4 Columns for KPI Metric cards
    col1, col2, col3, col4 = st.columns(4)
    kpi_cols = {
        'm1': col1.empty(),
        'm2': col2.empty(),
        'm3': col3.empty(),
        'm4': col4.empty()
    }

    # Main dashboard grid splitting
    col_left, col_mid, col_right = st.columns([1.2, 2.5, 1.3])

    # Left Column Placeholders
    with col_left:
        st.markdown(render_section_header("🏪 MONITORING ZONE RISKS"), unsafe_allow_html=True)
        zone_status_placeholder = st.empty()
        
        st.markdown(render_section_header("🛡️ PLANT FAILSAFE SYSTEMS"), unsafe_allow_html=True)
        failsafes_placeholder = st.empty()
        
        st.markdown(render_section_header("🗄️ PERSISTENT DATABASE LOGS"), unsafe_allow_html=True)
        db_logs_placeholder = st.empty()
        
        st.markdown(render_section_header("📡 SCADA GATEWAYS & INTEGRATION"), unsafe_allow_html=True)
        scada_placeholder = st.empty()

    # Mid Column Placeholders (Video & Live Feed & Mid Panels)
    from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS
    with col_mid:
        selected_zone = st.selectbox(
            "Select CCTV Camera Feed:",
            options=SENSOR_ZONES,
            format_func=lambda z: f"📹 {ZONE_LABELS.get(z, z)} Camera Feed",
            key="cctv_zone_selector"
        )
        cctv_header_placeholder = st.empty()
        cctv_frame_placeholder = st.empty()
        cctv_status_placeholder = st.empty()
        
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        col_r1_1, col_r1_2 = st.columns([1.0, 1.0])
        timeline_placeholder = col_r1_1.empty()
        risk_engine_placeholder = col_r1_2.empty()
        
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        col_r2_1, col_r2_2, col_r2_3 = st.columns([1.0, 1.0, 1.0])
        ai_decision_placeholder = col_r2_1.empty()
        telemetry_trends_placeholder = col_r2_2.empty()
        zone_response_placeholder = col_r2_3.empty()
        
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        st.markdown(render_section_header("⚠️ ACTIVE COMPLIANCE WARNINGS"), unsafe_allow_html=True)
        warnings_placeholder = st.empty()

    # Right Column Placeholders (Notifications and Alerts)
    with col_right:
        st.markdown("""
        <style>
        div[data-testid="stVerticalBlock"] > div {
            gap: 0.3rem !important;
        }
        </style>
        """, unsafe_allow_html=True)
        
        st.markdown(render_section_header("📢 NOTIFICATION CHANNELS"), unsafe_allow_html=True)
        notifications_placeholder = st.empty()
        
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
        st.markdown(render_section_header("🔔 LIVE ALERTS"), unsafe_allow_html=True)
        alerts_placeholder = st.empty()

    placeholders = {
        'zone_status': zone_status_placeholder,
        'failsafes': failsafes_placeholder,
        'db_logs': db_logs_placeholder,
        'scada': scada_placeholder,
        'cctv_header': cctv_header_placeholder,
        'cctv_frame': cctv_frame_placeholder,
        'cctv_status': cctv_status_placeholder,
        'timeline': timeline_placeholder,
        'risk_engine': risk_engine_placeholder,
        'ai_decision': ai_decision_placeholder,
        'telemetry_trends': telemetry_trends_placeholder,
        'zone_response': zone_response_placeholder,
        'warnings': warnings_placeholder,
        'notifications': notifications_placeholder,
        'alerts': alerts_placeholder,
    }

    return auto_banner_placeholder, sim_banner_placeholder, kpi_cols, placeholders, selected_zone

