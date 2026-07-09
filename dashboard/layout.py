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


def create_layout() -> Tuple[
    st.delta_generator.DeltaGenerator,
    st.delta_generator.DeltaGenerator,
    st.delta_generator.DeltaGenerator,
    st.delta_generator.DeltaGenerator,
    st.delta_generator.DeltaGenerator
]:
    """Creates the structural layout with permanent left sidebar, center monitoring area, and right alert panel.

    Returns:
        auto_banner_placeholder: Top auto-detect alert banner
        sim_banner_placeholder: Simulation injection alert banner
        sidebar_placeholder: Placeholder for the permanent SurakshaAI Console sidebar
        col_center: Center column container (Main monitoring area)
        col_right: Right column container (Notification & Live Alerts)
    """
    # CCTV auto-detect alert banner placeholder
    auto_banner_placeholder = st.empty()

    # Simulation Injection Alert State Banner
    sim_banner_placeholder = st.empty()
    if st.session_state.get('sim_stage') == 'active':
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
    elif st.session_state.get('sim_stage') == 'acknowledged':
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

    # Main layout: permanent sidebar + content
    if 'sidebar_expanded' not in st.session_state:
        st.session_state.sidebar_expanded = True

    is_expanded = st.session_state.sidebar_expanded
    sidebar_width = "300px" if is_expanded else "70px"
    right_width = "420px"

    # Inject dynamic css custom property for sidebar transition
    st.markdown(f"""
    <style>
    :root {{
        --sidebar-width: {sidebar_width} !important;
        --right-width: {right_width} !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    # Always use constant columns ratios to prevent Streamlit from rebuilding columns container
    col_sidebar, col_center, col_right = st.columns([1.8, 5.5, 2.7])

    with col_sidebar:
        sidebar_cls = "suraksha-sidebar-expanded" if is_expanded else "suraksha-sidebar-collapsed"
        st.markdown(f"<div class='suraksha-sidebar-content {sidebar_cls}'>", unsafe_allow_html=True)
        sidebar_placeholder = st.empty()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_center:
        st.markdown("<div class='suraksha-center-panel-flag'></div>", unsafe_allow_html=True)

    with col_right:
        st.markdown("<div class='suraksha-right-panel-flag'></div>", unsafe_allow_html=True)

    return auto_banner_placeholder, sim_banner_placeholder, sidebar_placeholder, col_center, col_right

