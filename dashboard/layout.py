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


SEVERITY_BANNER_STYLES = {
    "CRITICAL": {
        "bg": "linear-gradient(90deg, rgba(127,7,7,0.95) 0%, rgba(180,15,15,0.88) 100%)",
        "border": "#ef4444",
        "glow": "rgba(239,68,68,0.45)",
        "icon": "🚨",
        "text_color": "#fca5a5",
        "label_color": "#fff",
        "pill_bg": "#ef4444",
        "pill_color": "#fff",
        "ack_bg": "rgba(255,255,255,0.15)",
    },
    "HIGH": {
        "bg": "linear-gradient(90deg, rgba(120,53,15,0.95) 0%, rgba(180,80,20,0.88) 100%)",
        "border": "#f97316",
        "glow": "rgba(249,115,22,0.35)",
        "icon": "⚠️",
        "text_color": "#fed7aa",
        "label_color": "#fff",
        "pill_bg": "#f97316",
        "pill_color": "#fff",
        "ack_bg": "rgba(255,255,255,0.12)",
    },
    "MEDIUM": {
        "bg": "linear-gradient(90deg, rgba(120,100,10,0.95) 0%, rgba(160,130,20,0.88) 100%)",
        "border": "#eab308",
        "glow": "rgba(234,179,8,0.30)",
        "icon": "⚡",
        "text_color": "#fef08a",
        "label_color": "#fff",
        "pill_bg": "#eab308",
        "pill_color": "#000",
        "ack_bg": "rgba(255,255,255,0.10)",
    },
    "LOW": {
        "bg": "linear-gradient(90deg, rgba(15,70,60,0.95) 0%, rgba(20,100,80,0.88) 100%)",
        "border": "#22c55e",
        "glow": "rgba(34,197,94,0.25)",
        "icon": "ℹ️",
        "text_color": "#bbf7d0",
        "label_color": "#fff",
        "pill_bg": "#22c55e",
        "pill_color": "#000",
        "ack_bg": "rgba(255,255,255,0.10)",
    },
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def render_top_alert_banner(placeholder: st.delta_generator.DeltaGenerator, am: Any, selected_zone: str = None) -> None:
    """Renders a dismissible top-of-page alert banner for the highest-severity active alert.

    The banner only appears while Autoplay Simulation is active. When autoplay
    is off it clears itself, so no stale database alerts bleed through on the
    initial page load or after the simulation is stopped.

    Only alerts belonging to ``selected_zone`` are considered, so the banner
    always reflects the currently viewed camera zone.

    Args:
        placeholder: The ``st.empty()`` slot returned by ``create_layout()`` as
            ``auto_banner_placeholder``.
        am: The :class:`~src.alert_system.AlertManager` instance.
        selected_zone: Zone key (e.g. ``'Zone_A'``, ``'Reactor_Area'``). When
            provided, only alerts whose ``zone`` matches are shown.
    """
    # Gate: banner only visible while simulation is running
    if not st.session_state.get('sim_play_active', False):
        placeholder.empty()
        return

    all_active = getattr(am, "active_alerts", {})

    # Filter to selected zone
    if selected_zone and all_active:
        active = {k: v for k, v in all_active.items() if getattr(v, "zone", None) == selected_zone}
    else:
        active = all_active

    if not active:
        placeholder.empty()
        return

    # Pick the highest-severity alert for this zone
    severity_rank = {name: i for i, name in enumerate(SEVERITY_ORDER)}
    top_alert = min(
        active.values(),
        key=lambda a: severity_rank.get(
            getattr(a, "risk_level", getattr(getattr(a, "severity", None), "name", "LOW")).upper(),
            99
        )
    )

    # Resolve fields
    severity_name = getattr(top_alert, "risk_level",
                            getattr(getattr(top_alert, "severity", None), "name", "LOW")).upper()
    message = getattr(top_alert, "message", "")
    alert_id = getattr(top_alert, "alert_id", None)
    zone = getattr(top_alert, "zone", "")
    from src.config.ui_constants import ZONE_LABELS
    zone_lbl = ZONE_LABELS.get(zone, zone).upper()

    style = SEVERITY_BANNER_STYLES.get(severity_name, SEVERITY_BANNER_STYLES["HIGH"])
    is_critical = severity_name == "CRITICAL"
    animation = "animation: emergPulse 2.5s ease-in-out infinite;" if is_critical else ""

    ack_href = f"?ack_alert={alert_id}" if alert_id else "?ack_auto_alert=1"

    total = len(active)
    extra_info = f"<span style='color:{style['text_color']};font-size:10px;margin-left:10px;'>+{total - 1} more alert(s)</span>" if total > 1 else ""

    html = f"""
    <div style="
        background: {style['bg']};
        border: 1px solid {style['border']};
        border-radius: 10px;
        padding: 10px 18px;
        margin-bottom: 10px;
        {animation}
        box-shadow: 0 0 18px {style['glow']}, inset 0 1px 0 rgba(255,255,255,0.08);
        font-family: 'Outfit', sans-serif;
        position: relative;
        overflow: hidden;
    ">
      <!-- Subtle left accent bar -->
      <div style="position:absolute;left:0;top:0;bottom:0;width:4px;background:{style['border']};border-radius:10px 0 0 10px;"></div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding-left:8px;">
        <!-- Left: icon + severity + zone + message -->
        <div style="display:flex;align-items:center;gap:10px;min-width:0;flex:1;">
          <span style="font-size:18px;flex-shrink:0;">{style['icon']}</span>
          <div style="min-width:0;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span style="font-weight:800;color:{style['label_color']};font-size:11px;letter-spacing:1px;text-transform:uppercase;">{severity_name} ALERT</span>
              <span style="background:rgba(255,255,255,0.12);color:{style['text_color']};border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:1px 6px;font-size:9px;font-weight:700;">{zone_lbl}</span>
              {extra_info}
            </div>
            <div style="color:{style['text_color']};font-size:11.5px;margin-top:2px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:600px;">{message}</div>
          </div>
        </div>
        <!-- Right: ACK button -->
        <a href="{ack_href}" target="_self" style="text-decoration:none;flex-shrink:0;">
          <span style="
            background:{style['ack_bg']};
            color:#fff;
            border:1px solid rgba(255,255,255,0.3);
            border-radius:6px;
            padding:5px 14px;
            font-size:10px;
            font-weight:800;
            cursor:pointer;
            letter-spacing:0.5px;
            text-transform:uppercase;
            white-space:nowrap;
          ">✓ ACKNOWLEDGE</span>
        </a>
      </div>
    </div>
    """
    placeholder.markdown(html, unsafe_allow_html=True)


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
    right_width = "380px"

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
    col_sidebar, col_center, col_right = st.columns([1.8, 5.8, 2.4])

    with col_sidebar:
        sidebar_cls = "suraksha-sidebar-expanded" if is_expanded else "suraksha-sidebar-collapsed"
        st.markdown(f"<div class='suraksha-sidebar-content {sidebar_cls}'>", unsafe_allow_html=True)
        sidebar_wrap = st.container(key="left_console_panel")
        with sidebar_wrap:
            sidebar_placeholder = st.empty()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_center:
        st.markdown("<div class='suraksha-center-panel-flag'></div>", unsafe_allow_html=True)

    with col_right:
        st.markdown("<div class='suraksha-right-panel-flag'></div>", unsafe_allow_html=True)
        right_wrap = st.container(key="right_diag_panel")

    return auto_banner_placeholder, sim_banner_placeholder, sidebar_placeholder, col_center, right_wrap

