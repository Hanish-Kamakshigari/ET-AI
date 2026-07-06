# -*- coding: utf-8 -*-
"""
SurakshaAI Industrial Safety Dashboard
Main Streamlit Application Entrypoint
"""

# 1. Patch Windows Event Loop policies to avoid Streamlit process-shutdown exceptions
import asyncio
import sys
import os

if sys.platform == 'win32':
    try:
        from asyncio import WindowsProactorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
    except ImportError:
        pass
    
    try:
        import asyncio.proactor_events
        orig_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost
        
        def patched_connection_lost(self, exc=None):
            try:
                orig_connection_lost(self, exc)
            except (ConnectionResetError, ConnectionAbortedError):
                pass
            except OSError as e:
                if e.errno in (10054, 10038, 9, 10053):
                    pass
                else:
                    raise
        asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = patched_connection_lost
    except Exception:
        pass
    
    import select
    if hasattr(select, 'select'):
        _orig_select = select.select
        def patched_select(*args, **kwargs):
            try:
                return _orig_select(*args, **kwargs)
            except (OSError, ValueError) as e:
                return [], [], []
        select.select = patched_select

import streamlit as st
from datetime import datetime

# Import project directories
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load ui helpers and modules
from src.ui_components import inject_global_css, render_navbar
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
from dashboard.layout import create_layout
from dashboard.components import (
    render_kpi_grid,
    render_zone_status_panel,
    render_failsafes_panel,
    render_db_logs_panel,
    render_scada_panel,
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

# Render fixed top navbar (risk level filled in after data loads below)
# We render it here with a placeholder level; it re-renders each cycle
_navbar_risk = st.session_state.get('last_risk_level', 'LOW')
render_navbar(risk_level=_navbar_risk, active_tab='dashboard')

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

# Create layout and retrieve placeholders & selectbox choice
(
    auto_banner_placeholder,
    sim_banner_placeholder,
    kpi_cols,
    placeholders,
    selected_zone
) = create_layout()

# Reset CCTV frame loop when selected camera feed changes
if 'prev_selected_zone' not in st.session_state:
    st.session_state.prev_selected_zone = selected_zone
    
if st.session_state.prev_selected_zone != selected_zone:
    st.session_state.cctv_frame_index = 0
    st.session_state.prev_selected_zone = selected_zone
    reset_ppe_buffer()

# Calculate telemetry metrics across all zones
data_dict = calculate_telemetry(df, engine, alert_system)

# Persist risk level so navbar status pill updates each rerun cycle
st.session_state['last_risk_level'] = data_dict.get('STATUS', {}).get('level', 'LOW')

# Render Sidebar Console
render_sidebar(data_dict, engine, am, alert_system)

# ════════════════════════════════════════════════════════════════════════════════
# 3. RENDER DASHBOARD KPI & GRIDS
# ════════════════════════════════════════════════════════════════════════════════

# Top KPI Metric Cards
render_kpi_grid(kpi_cols, data_dict)

# Left Panels
render_zone_status_panel(placeholders['zone_status'], data_dict)
render_failsafes_panel(placeholders['failsafes'], data_dict)
render_db_logs_panel(placeholders['db_logs'], data_dict)
render_scada_panel(placeholders['scada'])

# Right Notification and Alert panels
render_notifications_panel(placeholders['notifications'], data_dict, selected_zone)
render_alerts_panel(placeholders['alerts'], am)

# ════════════════════════════════════════════════════════════════════════════════
# 4. CCTV VIDEO FEED FRAGMENT & TELEMETRY CHARTS
# ════════════════════════════════════════════════════════════════════════════════

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

placeholders['kpi_cols'] = kpi_cols

# CCTV Video Streaming inside non-blocking st.fragment callback
stream_cctv_feed(placeholders, selected_zone, video_path, data_dict['latest'], alert_system, am, data_dict=data_dict)

# Retrieve current detection list to update charts
current_detections = st.session_state.get('current_detections', [])

# Render Live Timeline & Rule matched list
render_risk_analysis_row(placeholders, data_dict, selected_zone, current_detections)

# Render AI Decision recommendations and live gauges
render_decision_telemetry_row(placeholders, data_dict, selected_zone, current_detections)

# Close wrapper tags
st.markdown("</div>", unsafe_allow_html=True)
