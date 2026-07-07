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
import importlib
import dashboard.layout
importlib.reload(dashboard.layout)
from dashboard.layout import create_layout
import dashboard.components
importlib.reload(dashboard.components)
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

def flush_alert_queue():
    """Flushes background alert stream queue into the session state queue list"""
    if getattr(st.session_state, "live_queue", None) is not None:
        try:
            while not st.session_state.live_queue.empty():
                inc = st.session_state.live_queue.get_nowait()
                # Deduplicate or update elements in session alert queue
                exists = False
                for i, item in enumerate(st.session_state.alert_queue):
                    if item["incident_id"] == inc["incident_id"]:
                        st.session_state.alert_queue[i] = inc
                        exists = True
                        break
                if not exists:
                    st.session_state.alert_queue.append(inc)
        except Exception:
            pass

# Load plant database csv
df = load_data()

# Initialize core services
engine = init_engine()
alert_system = init_alerts(engine, df)
frame_processor = get_frame_processor()
am = AlertManager()

# Set live stream queue references
st.session_state.live_queue = alert_system.live_stream.queue
flush_alert_queue()

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

# Create layout and retrieve placeholders & selectbox choice
(
    auto_banner_placeholder,
    sim_banner_placeholder,
    kpi_cols,
    placeholders,
    selected_zone
) = create_layout(active_tab)

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

# Conditionally render page body contents depending on selected navbar tab
if active_tab == 'dashboard':
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

elif active_tab == 'analytics':
    from dashboard.components import render_analytics_tab
    render_analytics_tab(placeholders, data_dict, engine, alert_system)

elif active_tab == 'zones':
    from dashboard.components import render_zones_tab
    render_zones_tab(placeholders, data_dict, engine, alert_system)

elif active_tab == 'settings':
    from dashboard.components import render_settings_tab
    render_settings_tab(placeholders, data_dict, engine, alert_system)

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
