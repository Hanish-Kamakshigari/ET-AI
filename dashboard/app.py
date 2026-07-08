# -*- coding: utf-8 -*-
"""
SurakshaAI Industrial Safety Dashboard
Main Streamlit Application Entrypoint
"""

# 1. Patch Windows Event Loop policies to avoid Streamlit process-shutdown exceptions
import asyncio
import sys
import os
import logging
import warnings

# Suppress warnings process-wide
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=DeprecationWarning)

if sys.platform == 'win32':
    # Suppress asyncio noise via log filter only — monkey-patching asyncio internals
    # causes RecursionError on Streamlit reruns because app.py re-executes each run.
    class _SuppressAsyncioFilter(logging.Filter):
        _SUPPRESS = ("Event loop is closed", "ConnectionResetError", "ConnectionAbortedError")
        def filter(self, record):
            msg = record.getMessage()
            return not any(s in msg for s in self._SUPPRESS)

    for _log_name in ("asyncio", "asyncio.proactor_events"):
        _lg = logging.getLogger(_log_name)
        if not any(isinstance(f, _SuppressAsyncioFilter) for f in _lg.filters):
            _lg.addFilter(_SuppressAsyncioFilter())

import streamlit as st
from datetime import datetime

# Import project directories
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load ui helpers and modules
from src.ui_components import inject_global_css, render_navbar, render_section_header
from src.alert_system import get_alert_system, AlertManager
from src.cctv.inference import reset_ppe_buffer

@st.cache_resource
def get_frame_processor():
    from src.cctv.frame_processor import FrameProcessor
    return FrameProcessor(use_simulation=True)

# Dashboard modular sub-components
from dashboard.data import (
    load_data,
    init_engine,
    init_alerts,
    init_state_defaults,
    calculate_telemetry,
    handle_url_actions
)
from dashboard.sidebar import render_sidebar
import importlib
import dashboard.layout
importlib.reload(dashboard.layout)
from dashboard.layout import create_layout
import dashboard.components
importlib.reload(dashboard.components)
from dashboard.components import (
    render_kpi_grid,
    render_notifications_panel,
    render_alerts_panel,
    render_risk_analysis_row,
    render_decision_telemetry_row
)
from dashboard.video import stream_cctv_feed

# ════════════════════════════════════════════════════════════════════════════════
# 1. APPLICATION INITIALIZATION
# ════════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="SurakshaAI Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session State
init_state_defaults()

# Load plant database csv
df = load_data()

# Initialize core services
engine = init_engine()
alert_system = init_alerts(engine, df)
frame_processor = get_frame_processor()
am = AlertManager()

# Handle URL parameters/Operator Action Acknowledges
handle_url_actions(alert_system, am)

# Inject CSS styles
inject_global_css()

# Parse active tab
query_params = st.query_params
active_tab = query_params.get("tab", st.session_state.get("active_tab", "dashboard"))
if isinstance(active_tab, list):
    active_tab = active_tab[0]
if active_tab:
    active_tab = active_tab.lower()
if active_tab not in ("dashboard", "analytics", "zones", "settings"):
    active_tab = "dashboard"
st.session_state.active_tab = active_tab

# Render fixed top navbar
_navbar_risk = st.session_state.get('last_risk_level', 'LOW')
render_navbar(risk_level=_navbar_risk, active_tab=active_tab)

# ════════════════════════════════════════════════════════════════════════════════
# 2. RENDER DASHBOARD LAYOUT & SIDEBAR
# ════════════════════════════════════════════════════════════════════════════════

# Render Loading overlay if injecting compound threat simulation
if st.session_state.get('sim_stage') == 'injecting':
    st.markdown("""
    <div class="injection-overlay">
      <div class="spinner"></div>
      <div style="font-weight:700; font-size:18px; margin-top:20px; color:#fff; text-shadow:0 0 10px rgba(0,0,0,0.5)">
        INJECTING SIMULATED THREAT SCENARIO...
      </div>
      <div style="font-size:11px; margin-top:4px; color:#6b7d94; text-shadow:0 0 5px rgba(0,0,0,0.5)">
        Initializing Modbus overrides & alerting siren loops
      </div>
    </div>
    """, unsafe_allow_html=True)

(
    auto_banner_placeholder,
    sim_banner_placeholder,
    sidebar_placeholder,
    col_main
) = create_layout()

# Calculate telemetry metrics across all zones
data_dict = calculate_telemetry(df, engine, alert_system)

# Persist risk level so navbar status pill updates each rerun cycle
st.session_state['last_risk_level'] = data_dict.get('STATUS', {}).get('level', 'LOW')

# Initialize placeholders dict for sidebar panels
placeholders = {}
render_sidebar(sidebar_placeholder, placeholders, data_dict, engine, am, alert_system)

with col_main:
    # Top KPI Metric Cards (Only shown on operational dashboards: Live Monitor & Analytics)
    if active_tab in ('dashboard', 'analytics'):
        col1, col2, col3, col4 = st.columns(4)
        kpi_cols = {
            'm1': col1.empty(),
            'm2': col2.empty(),
            'm3': col3.empty(),
            'm4': col4.empty()
        }
        render_kpi_grid(kpi_cols, data_dict)
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    else:
        kpi_cols = None

    # Conditionally render page body contents depending on selected navbar tab
    if active_tab == 'dashboard':
        # Balanced 2-column layout to eliminate empty whitespaces and group elements
        col_left, col_right = st.columns([3.5, 2.0])

        with col_left:
            st.markdown("<div class='suraksha-center-panel-flag'></div>", unsafe_allow_html=True)
            from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS
            selected_zone = st.selectbox(
                "Select CCTV Camera Feed:",
                options=SENSOR_ZONES,
                format_func=lambda z: f"📹 {ZONE_LABELS.get(z, z)} Camera Feed",
                key="cctv_zone_selector"
            )

            # Reset CCTV frame loop when selected camera feed changes
            if 'prev_selected_zone' not in st.session_state:
                st.session_state.prev_selected_zone = selected_zone

            if st.session_state.prev_selected_zone != selected_zone:
                st.session_state.cctv_frame_index = 0
                st.session_state.prev_selected_zone = selected_zone
                reset_ppe_buffer()

            cctv_header_placeholder = st.empty()
            cctv_frame_placeholder = st.empty()
            cctv_status_placeholder = st.empty()

            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
            col_r1_1, col_r1_2 = st.columns([1.0, 1.0])
            timeline_placeholder = col_r1_1.empty()
            risk_engine_placeholder = col_r1_2.empty()

            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
            col_r2_1, col_r2_2, col_r2_3 = st.columns([1.0, 1.0, 1.0])
            ai_decision_placeholder = col_r2_1.empty()
            telemetry_trends_placeholder = col_r2_2.empty()
            zone_response_placeholder = col_r2_3.empty()

        with col_right:
            st.markdown("<div class='suraksha-right-panel-flag'></div>", unsafe_allow_html=True)
            st.markdown(render_section_header("⚠️ ACTIVE COMPLIANCE WARNINGS"), unsafe_allow_html=True)
            warnings_placeholder = st.empty()

            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
            st.markdown(render_section_header("📢 NOTIFICATION CHANNELS"), unsafe_allow_html=True)
            notifications_placeholder = st.empty()

            st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
            st.markdown(render_section_header("🔔 LIVE ALERTS"), unsafe_allow_html=True)
            alerts_placeholder = st.empty()

        dashboard_placeholders = {
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
            'zone_status': placeholders.get('zone_status'),
            'failsafes': placeholders.get('failsafes'),
            'db_logs': placeholders.get('db_logs'),
            'kpi_cols': kpi_cols,
        }

        # CCTV Video Streaming inside non-blocking st.fragment callback
        FOOTAGE_FILES = {
            'Zone_A': 'Battery_4.mp4',
            'Zone_B': 'Battery_5.mp4',
            'Zone_C': 'Battery_6.mp4',
            'Reactor_Area': 'Reactor_Block.mp4',
            'Storage_Area': 'Storage_Block.mp4'
        }
        footage_filename = FOOTAGE_FILES.get(selected_zone)
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        video_path = os.path.join(PROJECT_ROOT, "footage", footage_filename) if footage_filename else None

        stream_cctv_feed(dashboard_placeholders, selected_zone, video_path, data_dict['latest'], alert_system, am, data_dict=data_dict)

        current_detections = st.session_state.get('current_detections', [])
        render_risk_analysis_row(dashboard_placeholders, data_dict, selected_zone, current_detections)
        render_decision_telemetry_row(dashboard_placeholders, data_dict, selected_zone, current_detections)
        render_notifications_panel(dashboard_placeholders['notifications'], data_dict, selected_zone)
        render_alerts_panel(dashboard_placeholders['alerts'], am)

    elif active_tab == 'analytics':
        from dashboard.components import render_analytics_tab
        render_analytics_tab(placeholders, data_dict, engine, alert_system)

    elif active_tab == 'zones':
        from dashboard.components import render_zones_tab
        render_zones_tab(placeholders, data_dict, engine, alert_system)

    elif active_tab == 'settings':
        from dashboard.components import render_settings_tab
        render_settings_tab(placeholders, data_dict, engine, alert_system)

# Run background headless CCTV streaming loop on Analytics and Settings pages
# so telemetry, YOLO inference, and alerts keep updating continuously.
if active_tab in ('analytics', 'settings'):
    bg_zone = st.session_state.get('cctv_zone_selector')
    if not bg_zone:
        from src.config.ui_constants import SENSOR_ZONES
        bg_zone = SENSOR_ZONES[0]

    FOOTAGE_FILES = {
        'Zone_A': 'Battery_4.mp4',
        'Zone_B': 'Battery_5.mp4',
        'Zone_C': 'Battery_6.mp4',
        'Reactor_Area': 'Reactor_Block.mp4',
        'Storage_Area': 'Storage_Block.mp4'
    }
    bg_footage_filename = FOOTAGE_FILES.get(bg_zone)
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    bg_video_path = os.path.join(PROJECT_ROOT, "footage", bg_footage_filename) if bg_footage_filename else None

    bg_placeholders = {
        'cctv_header': st.empty(),
        'cctv_frame': st.empty(),
        'cctv_status': st.empty(),
        'warnings': st.empty(),
        'alerts': placeholders.get('alerts', st.empty()),
        'notifications': placeholders.get('notifications', st.empty()),
        'zone_status': placeholders.get('zone_status', st.empty()),
        'failsafes': placeholders.get('failsafes', st.empty()),
        'db_logs': placeholders.get('db_logs', st.empty()),
        'kpi_cols': None,
    }

    stream_cctv_feed(
        bg_placeholders,
        bg_zone,
        bg_video_path,
        data_dict['latest'],
        alert_system,
        am,
        data_dict=data_dict
    )

# Render floating AI Explainability Console Modal overlay if toggled active
if st.session_state.get('show_explainability_modal', False):
    from dashboard.components import render_explainability_modal
    render_explainability_modal()

# Handle 1-second interval auto-refresh preference
if st.session_state.get('auto_refresh', False):
    st.markdown("""
    <script>
    if (!window.suraksha_refresh_timeout) {
        window.suraksha_refresh_timeout = setTimeout(function() {
            window.suraksha_refresh_timeout = null;
            window.location.reload();
        }, 1000);
    }
    </script>
    """, unsafe_allow_html=True)

# Close wrapper tags
st.markdown("</div>", unsafe_allow_html=True)
