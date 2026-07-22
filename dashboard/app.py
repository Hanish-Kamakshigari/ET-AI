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
from typing import Any, Dict, Optional

# Suppress warnings process-wide
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=DeprecationWarning)

if sys.platform == 'win32':
    # 0) Patch _ProactorBasePipeTransport._call_connection_lost to swallow socket shutdown exceptions.
    # On Windows, when a remote client forcibly closes the connection, socket.shutdown()
    # raises ConnectionResetError (WinError 10054). Because it occurs in the finally block,
    # it prevents socket cleanup/detachment and causes infinite loops and noisy printouts.
    try:
        import socket
        from asyncio.proactor_events import _ProactorBasePipeTransport     
        
        def _patched_call_connection_lost(self: _ProactorBasePipeTransport, exc: Optional[BaseException]) -> None:
            if self._called_connection_lost:
                return
            try:
                self._protocol.connection_lost(exc)
            finally:
                if hasattr(self._sock, 'shutdown') and self._sock.fileno() != -1:
                    try:
                        self._sock.shutdown(socket.SHUT_RDWR)
                    except (ConnectionResetError, ConnectionAbortedError, OSError):
                        pass
                self._sock.close()
                self._sock = None
                server = self._server
                if server is not None:
                    server._detach(self)
                    self._server = None
                self._called_connection_lost = True

        _ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost
    except Exception:
        pass

    # 1) Log filter — catches messages routed through the logging system.
    class _SuppressAsyncioFilter(logging.Filter):
        _SUPPRESS = ("Event loop is closed", "ConnectionResetError", "ConnectionAbortedError")
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(s in msg for s in self._SUPPRESS)

    for _log_name in ("asyncio", "asyncio.proactor_events"):
        _lg = logging.getLogger(_log_name)
        if not any(isinstance(f, _SuppressAsyncioFilter) for f in _lg.filters):
            _lg.addFilter(_SuppressAsyncioFilter())

    # 2) Exception-handler patch — the real source of the WinError 10054 printouts.
    # asyncio calls loop.call_exception_handler() for transport errors, which bypasses
    # the logging system entirely and writes directly to stderr.
    _loop: Optional[asyncio.AbstractEventLoop] = None
    try:
        _loop = asyncio.get_event_loop()
    except RuntimeError:
        pass
    if _loop is not None and not getattr(_loop, '_suraksha_exc_handler_patched', False):
        _original_exc_handler = _loop.call_exception_handler
        _SUPPRESS_EXC = ("ConnectionResetError", "ConnectionAbortedError", "WinError 10054", "WinError 10053")
        def _filtered_exception_handler(context: Dict[str, Any]) -> None:
            msg = context.get("message", "") + str(context.get("exception", ""))
            if any(s in msg for s in _SUPPRESS_EXC):
                return  # swallow harmless Windows transport teardown noise
            _original_exc_handler(context)
        _loop.call_exception_handler = _filtered_exception_handler
        _loop._suraksha_exc_handler_patched = True

import streamlit as st
from datetime import datetime

# Import project directories
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load ui helpers and modules
from src.ui_components import inject_global_css, render_navbar, render_section_header
from src.alert_system import get_alert_system, AlertManager
from src.cctv.inference import reset_ppe_buffer

from src.cctv.frame_processor import FrameProcessor

@st.cache_resource
def get_frame_processor() -> FrameProcessor:
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
from dashboard.layout import create_layout, render_top_alert_banner
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

# Safety Intelligence & Digital Twin panels
import dashboard.intelligence_ui
importlib.reload(dashboard.intelligence_ui)
from dashboard.intelligence_ui import render_intelligence_panels

import dashboard.digital_twin
importlib.reload(dashboard.digital_twin)
from dashboard.digital_twin import render_zone_digital_twin_full

from src.permit_intelligence import init_default_permits, render_permit_intelligence_panel
from src.safety_intelligence import get_intelligence_orchestrator

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

if 'rerun_counter' not in st.session_state:
    st.session_state.rerun_counter = 0
st.session_state.rerun_counter += 1

print(f"[DEBUG_AUTOPLAY] Rerun #{st.session_state.rerun_counter}: sim_play_active={st.session_state.get('sim_play_active')}")

# Load plant database csv
df = load_data()

# Initialize core services
engine = init_engine()
alert_system = init_alerts(engine, df)
frame_processor = get_frame_processor()
print(f"[DIAGNOSTIC] FrameProcessor initialized: use_simulation={frame_processor.detector.use_simulation}, model_loaded={frame_processor.detector.model is not None}")
# Session-scoped AlertManager — persists across reruns within a session
# but does NOT leak across sessions/users like @st.cache_resource would.
if 'alert_manager' not in st.session_state:
    st.session_state.alert_manager = AlertManager()
am = st.session_state.alert_manager

# On initial load (or when autoplay is off): resolve any stale active alerts
# so the UI starts completely clean before the operator starts the simulation.
if not st.session_state.get('sim_play_active', False):
    try:
        from src.alert_system import clear_alert_if_safe
        _all_zones = ["Zone_A", "Zone_B", "Zone_C", "Reactor_Area", "Storage_Area"]
        for _z in _all_zones:
            clear_alert_if_safe(_z)
        for _alert_id in list(am.active_alerts.keys()):
            try:
                am.resolve_alert(_alert_id)
            except Exception:
                pass
        
        # Reset notification channel statuses back to STANDBY
        st.session_state.sms_status = {
            "status": "STANDBY",
            "color": "#64748b",
            "detail": "Awaiting active threat alerts"
        }
        st.session_state.email_status = {
            "status": "STANDBY",
            "color": "#64748b",
            "detail": "Awaiting active threat alerts"
        }
        st.session_state.telegram_status = {
            "status": "STANDBY",
            "color": "#64748b",
            "detail": "Awaiting active threat alerts"
        }
        st.session_state.siren_status = {
            "status": "STANDBY",
            "color": "#64748b",
            "detail": "Awaiting active threat alerts"
        }
    except Exception:
        pass

# Handle URL parameters/Operator Action Acknowledges
handle_url_actions(alert_system, am)

# Inject CSS styles
inject_global_css()

# ════════════════════════════════════════════════════════════════════════════════
# EMERGENCY MODE ORCHESTRATION — Immersive incident experience
# ════════════════════════════════════════════════════════════════════════════════
from dashboard.emergency_mode import (
    orchestrate_emergency_mode,
    render_critical_banner,
    render_cctv_emergency_overlay,
    render_camera_focus_style,
    is_emergency_active,
    get_affected_zone,
)

# Calculate telemetry metrics across all zones
data_dict = calculate_telemetry(df, engine, alert_system)
st.session_state.zone_risks = data_dict.get('zone_risks', {})
st.session_state.latest = data_dict.get('latest', {})

# Orchestrate emergency mode (injects CSS, toggles body class, audio, recovery)
_emergency_zone = st.session_state.get('cctv_zone_selector', 'Zone_A')
_emergency_dets = st.session_state.get('current_detections', [])
orchestrate_emergency_mode(data_dict, _emergency_zone, _emergency_dets)

# Critical incident banner placeholder (rendered after layout is created)
critical_banner_placeholder = st.empty()

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
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

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

# Persist risk level so navbar status pill updates each rerun cycle
st.session_state['last_risk_level'] = data_dict.get('STATUS', {}).get('level', 'LOW')

(
    auto_banner_placeholder,
    sim_banner_placeholder,
    sidebar_placeholder,
    col_center,
    col_right
) = create_layout()

# Render permanent Right Panel (Notification Channels, Live Alerts, Diagnostics)
with col_right:
    st.markdown(render_section_header("⚠️ ACTIVE COMPLIANCE WARNINGS"), unsafe_allow_html=True)
    warnings_placeholder = st.empty()

    st.markdown("<div style='height:3px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("📢 NOTIFICATION CHANNELS"), unsafe_allow_html=True)
    notifications_placeholder = st.empty()

    st.markdown("<div style='height:3px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("🔔 LIVE ALERTS"), unsafe_allow_html=True)
    alerts_placeholder = st.empty()

    st.markdown("<div style='height:3px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("🧩 COMPOUND RISK ENGINE"), unsafe_allow_html=True)
    risk_engine_placeholder = st.empty()

    st.markdown("<div style='height:3px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("📊 LIVE TELEMETRY"), unsafe_allow_html=True)
    telemetry_trends_placeholder = st.empty()

    st.markdown("<div style='height:3px;'></div>", unsafe_allow_html=True)
    st.markdown(render_section_header("🧠 SAFETY INTELLIGENCE"), unsafe_allow_html=True)
    intelligence_placeholder = st.empty()

    placeholders = {
        'alerts': alerts_placeholder,
        'notifications': notifications_placeholder,
        'warnings': warnings_placeholder,
        'top_banner': auto_banner_placeholder,
        'risk_engine': risk_engine_placeholder,
        'telemetry_trends': telemetry_trends_placeholder,
        'intelligence': intelligence_placeholder,
        'critical_banner': critical_banner_placeholder,
    }

    # ── Safety Intelligence Panels (Digital Twin, Copilot, XAI, etc.) ──
    # Initialize default work permits once per session for SIMOPS analysis
    if 'permits_initialized' not in st.session_state:
        try:
            init_default_permits()
            st.session_state['permits_initialized'] = True
        except Exception:
            st.session_state['permits_initialized'] = True

    # Feed the intelligence orchestrator with live telemetry so all agents
    # have fresh data to reason over every rerun cycle.
    try:
        _orch = get_intelligence_orchestrator()
        _sel_zone = st.session_state.get('cctv_zone_selector', 'Zone_A')
        _live_dets = st.session_state.get('current_detections', [])
        _telemetry_raw = data_dict.get('latest')
        _telemetry = dict(_telemetry_raw) if _telemetry_raw is not None else {}
        if _telemetry or _live_dets:
            _orch.ingest_live_frame(_sel_zone, _live_dets, _telemetry, am)
    except Exception:
        pass

    # Render all intelligence panels into the intelligence placeholder slot
    with intelligence_placeholder.container():
        render_intelligence_panels()

# Render the top alert banner above the column layout — scoped to selected zone
render_top_alert_banner(auto_banner_placeholder, am, selected_zone=st.session_state.get('cctv_zone_selector', None))

# Render the critical incident banner (animated, auto-dismiss on resolution)
render_critical_banner(critical_banner_placeholder, data_dict)

render_sidebar(sidebar_placeholder, placeholders, data_dict, engine, am, alert_system)

with col_center:
    kpi_cols: Optional[Dict[str, Any]] = None
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
        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

    if active_tab == 'dashboard':
        from src.config.ui_constants import SENSOR_ZONES, ZONE_LABELS
        selected_zone = st.session_state.get('cctv_zone_selector')
        if not selected_zone:
            selected_zone = SENSOR_ZONES[0]

        def on_zone_change() -> None:
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
        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
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

        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        # Compound Risk Engine & Live Telemetry moved to right sidebar for better column balance
        timeline_placeholder = st.empty()

        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        # Intelligence Timeline (moved from right column to center, always visible)
        intelligence_timeline_placeholder = st.empty()

        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        # Compound Risk Intelligence detailed panel (moved from right to center)
        compound_risk_detail_placeholder = st.empty()

        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        ai_decision_placeholder = st.empty()

        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        multi_agent_placeholder = st.empty()

        st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
        smart_permit_placeholder = st.empty()

        st.markdown("<div style='height: 2px;'></div>", unsafe_allow_html=True)
        col_l3, col_r3 = st.columns([1.0, 1.0])
        zone_response_placeholder = col_l3.empty()
        incident_summary_placeholder = col_r3.empty()



        dashboard_placeholders = {
            'cctv_frame_1': cctv_frame_placeholder_1,
            'cctv_frame_2': cctv_frame_placeholder_2,
            'cctv_frame': None,
            'cctv_status': cctv_status_placeholder,
            'timeline': timeline_placeholder,
            'risk_engine': risk_engine_placeholder,
            'ai_decision': ai_decision_placeholder,
            'telemetry_trends': telemetry_trends_placeholder,
            'multi_agent': multi_agent_placeholder,
            'smart_permit': smart_permit_placeholder,
            'zone_response': zone_response_placeholder,
            'incident_summary': incident_summary_placeholder,
            'warnings': warnings_placeholder,
            'notifications': notifications_placeholder,
            'alerts': alerts_placeholder,
            'intelligence_timeline': intelligence_timeline_placeholder,
            'compound_risk_detail': compound_risk_detail_placeholder,
            'zone_status': placeholders.get('zone_status'),
            'failsafes': placeholders.get('failsafes'),
            'db_logs': placeholders.get('db_logs'),
            'kpi_cols': kpi_cols,
            'critical_banner': critical_banner_placeholder
        }
        dashboard_placeholders.update(placeholders)

        # Initial static draws
        from dashboard.components import (
            render_risk_analysis_row,
            render_decision_telemetry_row,
            render_notifications_panel,
            render_alerts_panel,
            render_incident_summary_html
        )
        current_detections = st.session_state.get('current_detections', [])
        render_risk_analysis_row(dashboard_placeholders, data_dict, selected_zone, current_detections)
        render_decision_telemetry_row(dashboard_placeholders, data_dict, selected_zone, current_detections)
        render_notifications_panel(notifications_placeholder, data_dict, selected_zone)
        render_alerts_panel(alerts_placeholder, am, selected_zone=selected_zone)

        # Center column panels (Intelligence Timeline + Compound Risk Intelligence)
        from dashboard.intelligence_ui import render_center_column_panels
        render_center_column_panels(dashboard_placeholders)

        # Incident counters — read directly from session-scoped AlertManager.
        # No sim_on gate: active alerts should always be reflected in real time.
        open_incidents = len(am.active_alerts)
        closed_incidents = len(am.history)
        today_incidents = open_incidents + closed_incidents
        incident_summary_placeholder.markdown(
            render_incident_summary_html(open_incidents, closed_incidents, today_incidents),
            unsafe_allow_html=True
        )



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

# Close wrapper tags if any were opened (SCADA footer is self-contained)

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
        <span>👤 USER: <b>OPERATOR #01</b></span>
        <span>📡 MQTT: <b style="color: #22c55e;">CONNECTED</b></span>
        <span>🗄️ DB: <b style="color: #22c55e;">SQLITE OK</b></span>
        <span>🧠 MODEL: <b style="color: #60a5fa;">YOLOv8n-PPE</b></span>
        <span>⏱️ SYNC: <b style="color: #22c55e;">ONLINE</b></span>
    </div>
</div>
<style>
/* Bottom padding for the fixed SCADA footer is handled by the canonical
   .main-content rule in src/ui_components.py (padding-bottom: 110px).
   No duplicate override here to avoid conflicting spacing. */
</style>
""", unsafe_allow_html=True)