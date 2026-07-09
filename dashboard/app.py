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
import dashboard.video
importlib.reload(dashboard.video)
from dashboard.video import stream_cctv_feed_fragment

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

# Calculate telemetry metrics across all zones
data_dict = calculate_telemetry(df, engine, alert_system)

# Persist risk level so navbar status pill updates each rerun cycle
st.session_state['last_risk_level'] = data_dict.get('STATUS', {}).get('level', 'LOW')

(
    auto_banner_placeholder,
    sim_banner_placeholder,
    sidebar_placeholder,
    col_center,
    col_right
) = create_layout()

# Render permanent Right Panel (Notification Channels & Live Alerts & Diagnostics)
with col_right:
    st.markdown(render_section_header("⚠️ ACTIVE COMPLIANCE WARNINGS"), unsafe_allow_html=True)
    warnings_placeholder = st.empty()

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("📢 NOTIFICATION CHANNELS"), unsafe_allow_html=True)
    notifications_placeholder = st.empty()

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("🔔 LIVE ALERTS"), unsafe_allow_html=True)
    alerts_placeholder = st.empty()

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("🔌 SYSTEM DIAGNOSTICS & TELEMETRY"), unsafe_allow_html=True)

    # Initialize placeholders dict for sidebar panels & right panel components
    placeholders = {
        'alerts': alerts_placeholder,
        'notifications': notifications_placeholder,
        'warnings': warnings_placeholder
    }
    from dashboard.components import render_right_panel_diagnostics
    render_right_panel_diagnostics(placeholders, data_dict, am, init_mode=True)

render_sidebar(sidebar_placeholder, placeholders, data_dict, engine, am, alert_system)

with col_center:
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
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    else:
        kpi_cols = None

    if active_tab == 'dashboard':
        from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS
        selected_zone = st.session_state.get('cctv_zone_selector')
        if not selected_zone:
            selected_zone = SENSOR_ZONES[0]

        def on_zone_change():
            st.session_state.cctv_frame_index = 0
            from src.cctv.inference import reset_ppe_buffer
            reset_ppe_buffer()

        zone_sel = st.selectbox(
            "Select CCTV Camera Feed:",
            options=SENSOR_ZONES,
            format_func=lambda z: f"📹 {ZONE_LABELS.get(z, z)} Camera Feed",
            key="cctv_zone_selector",
            on_change=on_zone_change
        )
        selected_zone = zone_sel

        selected_zone_name = ZONE_LABELS.get(selected_zone, selected_zone).upper()
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class='cctv-header'>
            <span style='color:#e2e8f0; font-weight:bold; font-family:"Outfit",sans-serif; font-size:12px; letter-spacing:0.5px;'>📷 LIVE CCTV FEED — {selected_zone_name}</span>
            <span class='live-badge'>● LIVE</span>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            st.markdown("<div class='cctv-buffer-anchor'></div>", unsafe_allow_html=True)
            cctv_frame_placeholder_1 = st.empty()
            cctv_frame_placeholder_2 = st.empty()
            
        cctv_status_placeholder = st.empty()

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        col_l1, col_r1 = st.columns([1.2, 0.8])
        timeline_placeholder = col_l1.empty()
        risk_engine_placeholder = col_r1.empty()

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        col_l2, col_r2 = st.columns([1.0, 1.0])
        ai_decision_placeholder = col_l2.empty()
        telemetry_trends_placeholder = col_r2.empty()

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        col_l3, col_r3 = st.columns([1.0, 1.0])
        zone_response_placeholder = col_l3.empty()
        incident_summary_placeholder = col_r3.empty()

        # Operational Overview SCADA status row (6 columns)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        col_scada1, col_scada2, col_scada3, col_scada4, col_scada5, col_scada6 = st.columns(6)
        scada_placeholders = {
            'plant_health': col_scada1.empty(),
            'sensor_status': col_scada2.empty(),
            'network_status': col_scada3.empty(),
            'database_status': col_scada4.empty(),
            'ai_model_status': col_scada5.empty(),
            'sync_time': col_scada6.empty()
        }

        dashboard_placeholders = {
            'cctv_frame_1': cctv_frame_placeholder_1,
            'cctv_frame_2': cctv_frame_placeholder_2,
            'cctv_frame': None,
            'cctv_status': cctv_status_placeholder,
            'timeline': timeline_placeholder,
            'risk_engine': risk_engine_placeholder,
            'ai_decision': ai_decision_placeholder,
            'telemetry_trends': telemetry_trends_placeholder,
            'zone_response': zone_response_placeholder,
            'incident_summary': incident_summary_placeholder,
            'warnings': warnings_placeholder,
            'notifications': notifications_placeholder,
            'alerts': alerts_placeholder,
            'zone_status': placeholders.get('zone_status'),
            'failsafes': placeholders.get('failsafes'),
            'db_logs': placeholders.get('db_logs'),
            'kpi_cols': kpi_cols
        }
        dashboard_placeholders.update(placeholders)

        # Initial static draws
        from dashboard.components import (
            render_risk_analysis_row,
            render_decision_telemetry_row,
            render_notifications_panel,
            render_alerts_panel,
            render_incident_summary_html,
            render_operational_overview
        )
        current_detections = st.session_state.get('current_detections', [])
        render_risk_analysis_row(dashboard_placeholders, data_dict, selected_zone, current_detections)
        render_decision_telemetry_row(dashboard_placeholders, data_dict, selected_zone, current_detections)
        render_notifications_panel(notifications_placeholder, data_dict, selected_zone)
        render_alerts_panel(alerts_placeholder, am)

        open_incidents = len(am.active_alerts)
        closed_incidents = len(am.history)
        today_incidents = open_incidents + closed_incidents
        incident_summary_placeholder.markdown(
            render_incident_summary_html(open_incidents, closed_incidents, today_incidents),
            unsafe_allow_html=True
        )
        
        # Render bottom SCADA operational overview row
        render_operational_overview(scada_placeholders, data_dict)

        from dashboard.video import stream_cctv_feed_fragment
        stream_cctv_feed_fragment(
            placeholders=dashboard_placeholders,
            data_dict=data_dict,
            selected_zone=selected_zone,
            engine=engine,
            am=am,
            alert_system=alert_system
        )

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

        from dashboard.video import stream_cctv_feed_headless
        stream_cctv_feed_headless(
            placeholders,
            bg_zone,
            bg_video_path,
            data_dict,
            alert_system,
            am
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

# Append SCADA Status Footer
from datetime import datetime
current_time_str = datetime.now().strftime("%H:%M:%S")
st.markdown(f"""
<div style="
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 28px;
    background: #060c14;
    border-top: 1px solid #1e3a5f;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 16px;
    font-family: monospace;
    font-size: 10px;
    color: #94a3b8;
    z-index: 999999;
">
    <div>🛡️ SURAKSHAAI CONSOLE — v3.0.4</div>
    <div style="display: flex; gap: 16px;">
        <span>👤 USER: <b>OPERATOR #08</b></span>
        <span>📡 MQTT: <b style="color: #22c55e;">CONNECTED</b></span>
        <span>🗄️ DB: <b style="color: #22c55e;">SQLITE OK</b></span>
        <span>🧠 MODEL: <b style="color: #60a5fa;">YOLOv8n-PPE</b></span>
        <span>⏱️ SYNC: <b style="color: #f59e0b;">{current_time_str}</b></span>
    </div>
</div>
<style>
/* Add extra bottom padding to main layout content wrapper to prevent overlap with fixed footer */
.main-content {{
    padding-bottom: 140px !important;
}}
</style>
""", unsafe_allow_html=True)
