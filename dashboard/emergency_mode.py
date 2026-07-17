"""
SurakshaAI — Emergency Mode & Immersive Incident Experience
Enhances the dashboard during live critical incidents without changing layout.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import streamlit as st
from src.alert_system import AlertManager


def is_emergency_active(data_dict: Dict[str, Any] = None) -> bool:
    if data_dict:
        risk_state = data_dict.get('risk_state', '')
        status_level = data_dict.get('STATUS', {}).get('level', '')
        compound_score = data_dict.get('compound_risk_score', 0)
        if risk_state in ('HIGH', 'CRITICAL') or status_level in ('HIGH', 'CRITICAL') or compound_score > 0:
            return True
    return st.session_state.get('compound_risk_active', False) or st.session_state.get('sim_stage') == 'active'


def get_emergency_level(data_dict: Dict[str, Any] = None) -> str:
    if data_dict:
        status_level = data_dict.get('STATUS', {}).get('level', '')
        risk_state = data_dict.get('risk_state', '')
        if status_level == 'CRITICAL' or risk_state == 'CRITICAL':
            return 'CRITICAL'
        if status_level == 'HIGH' or risk_state == 'HIGH':
            return 'HIGH'
    if st.session_state.get('sim_stage') == 'active':
        return 'CRITICAL'
    return 'NORMAL'


def get_affected_zone(data_dict: Dict[str, Any] = None) -> str:
    if data_dict:
        zone_risks = data_dict.get('zone_risks', {})
        for zone_id, info in zone_risks.items():
            if info.get('risk_level', '').upper() in ('HIGH', 'CRITICAL'):
                return zone_id
    return st.session_state.get('cctv_zone_selector', 'Zone_A')


EMERGENCY_CSS = """
<style>
body.emergency-mode .stApp { animation: emergencyAmbientGlow 4s ease-in-out infinite !important; }
@keyframes emergencyAmbientGlow {
    0%, 100% { box-shadow: inset 0 0 120px rgba(239,68,68,0.04); }
    50%      { box-shadow: inset 0 0 160px rgba(239,68,68,0.08); }
}
body.emergency-mode::before {
    content: ""; position: fixed; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, rgba(239,68,68,0) 0%, rgba(239,68,68,0.8) 20%, rgba(239,68,68,1) 50%, rgba(239,68,68,0.8) 80%, rgba(239,68,68,0) 100%);
    background-size: 200% 100%; animation: emergencyBorderSweep 3s linear infinite;
    z-index: 999998; pointer-events: none;
}
@keyframes emergencyBorderSweep { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
body.emergency-mode .glass-card-critical, body.emergency-mode .emergency-pulse { animation: emergencyWidgetPulse 2.5s ease-in-out infinite; }
@keyframes emergencyWidgetPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.0), inset 0 0 0 0 rgba(239,68,68,0); }
    50%      { box-shadow: 0 0 14px 1px rgba(239,68,68,0.12), inset 0 0 20px rgba(239,68,68,0.03); }
}
.emergency-warning-indicator { display: inline-flex; align-items: center; gap: 6px; animation: warningBlink 1.5s ease-in-out infinite; }
@keyframes warningBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.critical-incident-banner {
    position: relative; background: linear-gradient(90deg, rgba(127,7,7,0.92) 0%, rgba(180,15,15,0.85) 50%, rgba(127,7,7,0.92) 100%);
    border: 1px solid rgba(239,68,68,0.6); border-radius: 10px; padding: 12px 20px; margin-bottom: 12px;
    font-family: 'Outfit', sans-serif; box-shadow: 0 0 24px rgba(239,68,68,0.25), inset 0 1px 0 rgba(255,255,255,0.06);
    overflow: hidden; animation: bannerSlideIn 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}
.critical-incident-banner.banner-resolving { animation: bannerSlideOut 0.6s cubic-bezier(0.7, 0, 0.84, 0) forwards; }
@keyframes bannerSlideIn { from { opacity: 0; transform: translateY(-20px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes bannerSlideOut { from { opacity: 1; transform: translateY(0); max-height: 200px; } to { opacity: 0; transform: translateY(-20px); max-height: 0; padding: 0; margin: 0; } }
.critical-incident-banner::after {
    content: ""; position: absolute; top: 0; left: -100%; width: 50%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent);
    animation: bannerScan 3s linear infinite;
}
@keyframes bannerScan { 0% { left: -50%; } 100% { left: 150%; } }
.cctv-emergency-overlay {
    position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 10;
    border: 2px solid rgba(239,68,68,0.7); border-radius: 8px;
    animation: cctvBorderPulse 1.5s ease-in-out infinite; box-sizing: border-box;
}
@keyframes cctvBorderPulse {
    0%, 100% { border-color: rgba(239,68,68,0.7); box-shadow: 0 0 12px rgba(239,68,68,0.2); }
    50%      { border-color: rgba(239,68,68,1.0); box-shadow: 0 0 24px rgba(239,68,68,0.4); }
}
.cctv-overlay-topbar { position: absolute; top: 6px; left: 8px; right: 8px; display: flex; justify-content: space-between; align-items: center; font-family: 'Outfit', sans-serif; z-index: 11; }
.cctv-overlay-live { background: rgba(239,68,68,0.85); color: #fff; font-size: 9px; font-weight: 800; padding: 2px 8px; border-radius: 3px; letter-spacing: 1px; text-transform: uppercase; animation: warningBlink 1.5s ease-in-out infinite; }
.cctv-overlay-rec { display: flex; align-items: center; gap: 4px; background: rgba(0,0,0,0.6); color: #ef4444; font-size: 9px; font-weight: 800; padding: 2px 8px; border-radius: 3px; letter-spacing: 1px; }
.cctv-overlay-rec-dot { width: 7px; height: 7px; border-radius: 50%; background: #ef4444; animation: recBlink 1s ease-in-out infinite; }
@keyframes recBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }
.cctv-overlay-info { position: absolute; bottom: 8px; left: 8px; right: 8px; background: rgba(0,0,0,0.7); border: 1px solid rgba(239,68,68,0.3); border-radius: 6px; padding: 6px 10px; font-family: 'Outfit', sans-serif; z-index: 11; animation: overlayFadeIn 0.4s ease; }
@keyframes overlayFadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.cctv-focus-mode { transform: scale(1.18); transform-origin: center center; transition: transform 0.5s cubic-bezier(0.16, 1, 0.3, 1); border: 2px solid rgba(239,68,68,0.8); border-radius: 8px; box-shadow: 0 0 30px rgba(239,68,68,0.3), 0 0 60px rgba(239,68,68,0.1); animation: cctvFocusGlow 2s ease-in-out infinite; z-index: 5; position: relative; }
@keyframes cctvFocusGlow { 0%, 100% { box-shadow: 0 0 30px rgba(239,68,68,0.3), 0 0 60px rgba(239,68,68,0.1); } 50% { box-shadow: 0 0 40px rgba(239,68,68,0.45), 0 0 80px rgba(239,68,68,0.15); } }
.kpi-value-changed { animation: kpiFlash 0.6s ease; }
@keyframes kpiFlash { 0% { transform: scale(1); } 30% { transform: scale(1.08); text-shadow: 0 0 12px currentColor; } 100% { transform: scale(1); } }
.kpi-trend-up { color: #ef4444; font-size: 10px; } .kpi-trend-down { color: #22c55e; font-size: 10px; } .kpi-trend-flat { color: #64748b; font-size: 10px; }
.timeline-entry { animation: timelineSlideIn 0.4s cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes timelineSlideIn { from { opacity: 0; transform: translateX(-12px); } to { opacity: 1; transform: translateX(0); } }
.timeline-resolved { animation: timelineResolve 0.5s ease; opacity: 0.6; }
@keyframes timelineResolve { from { opacity: 1; } to { opacity: 0.6; } }
.ai-decision-update { animation: aiDecisionUpdate 0.5s ease; }
@keyframes aiDecisionUpdate { 0% { transform: scale(1); } 50% { transform: scale(1.02); box-shadow: 0 0 16px rgba(59,130,246,0.2); } 100% { transform: scale(1); } }
.compound-risk-new { animation: compoundRiskEnter 0.5s cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes compoundRiskEnter { from { opacity: 0; transform: translateY(-8px); max-height: 0; } to { opacity: 1; transform: translateY(0); max-height: 200px; } }
.predictive-gauge-fill { transition: width 0.8s cubic-bezier(0.16, 1, 0.3, 1); }
.predictive-countdown { font-family: monospace; font-variant-numeric: tabular-nums; transition: color 0.3s ease; }
.copilot-section { animation: copilotFadeIn 0.4s ease; }
@keyframes copilotFadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.alert-pinned { border: 1px solid rgba(239,68,68,0.4) !important; animation: alertPinPulse 2s ease-in-out infinite; }
@keyframes alertPinPulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); } 50% { box-shadow: 0 0 10px 1px rgba(239,68,68,0.15); } }
.alert-entering { animation: alertEnter 0.4s cubic-bezier(0.16, 1, 0.3, 1); }
@keyframes alertEnter { from { opacity: 0; transform: translateX(-10px); max-height: 0; } to { opacity: 1; transform: translateX(0); max-height: 100px; } }
.alert-fading { animation: alertFade 0.6s ease forwards; }
@keyframes alertFade { from { opacity: 1; } to { opacity: 0.3; filter: grayscale(0.6); } }
.emergency-response-expanded { animation: responseExpand 0.5s cubic-bezier(0.16, 1, 0.3, 1); max-height: 600px; overflow: hidden; }
@keyframes responseExpand { from { max-height: 0; opacity: 0; } to { max-height: 600px; opacity: 1; } }
.emergency-response-collapsed { animation: responseCollapse 0.5s ease forwards; max-height: 0; overflow: hidden; }
@keyframes responseCollapse { from { max-height: 600px; opacity: 1; } to { max-height: 0; opacity: 0; } }
body.emergency-resolving .stApp { animation: emergencyResolve 1.2s ease forwards; }
@keyframes emergencyResolve { from { box-shadow: inset 0 0 160px rgba(239,68,68,0.08); } to { box-shadow: inset 0 0 0 rgba(239,68,68,0); } }
.ambient-intensify { animation: ambientIntensify 2s ease-in-out infinite; }
@keyframes ambientIntensify { 0%, 100% { filter: brightness(1); } 50% { filter: brightness(1.06); } }
.audio-mute-toggle { position: fixed; bottom: 36px; right: 16px; z-index: 999999; background: rgba(17,24,39,0.9); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 6px 10px; font-family: 'Outfit', sans-serif; font-size: 10px; color: #94a3b8; cursor: pointer; transition: all 0.2s ease; }
.audio-mute-toggle:hover { border-color: rgba(0,212,255,0.3); color: #00d4ff; }
</style>
"""


def inject_emergency_css() -> None:
    st.markdown(EMERGENCY_CSS, unsafe_allow_html=True)


def toggle_emergency_mode(active: bool, resolving: bool = False) -> None:
    if active:
        cls = "emergency-mode emergency-resolving" if resolving else "emergency-mode"
        st.markdown(f'<script>document.body.classList.add("{cls}".split(" "));</script>', unsafe_allow_html=True)
    else:
        st.markdown('<script>document.body.classList.remove("emergency-mode","emergency-resolving");</script>', unsafe_allow_html=True)


def render_critical_banner(placeholder: st.delta_generator.DeltaGenerator, data_dict: Dict[str, Any]) -> None:
    if not is_emergency_active(data_dict):
        if st.session_state.get('_banner_was_active', False):
            placeholder.markdown('<div class="critical-incident-banner banner-resolving"><span style="color:#22c55e;font-size:12px;font-weight:700;">✅ INCIDENT RESOLVED — Returning to normal operations</span></div>', unsafe_allow_html=True)
            st.session_state._banner_was_active = False
        else:
            placeholder.empty()
        return
    st.session_state._banner_was_active = True
    level = get_emergency_level(data_dict)
    affected_zone = get_affected_zone(data_dict)
    from src.config.ui_constants import ZONE_LABELS
    zone_label = ZONE_LABELS.get(affected_zone, affected_zone)
    risk_state = data_dict.get('risk_state', 'HIGH')
    compound_score = data_dict.get('compound_risk_score', 0)
    latest = data_dict.get('latest', {})
    gas_val = float(latest.get(f"{affected_zone}_gas_ppm", 0))
    worker_count = int(latest.get(f"{affected_zone}_worker_count", 0))
    incident_parts = []
    if gas_val > 35: incident_parts.append("Gas Leak")
    if worker_count > 0: incident_parts.append("Worker Nearby")
    if not incident_parts: incident_parts.append("Compound Risk Detected")
    incident_desc = " + ".join(incident_parts)
    escalation_secs = max(60, 300 - compound_score * 20)
    escalation_str = f"{escalation_secs // 60:02d}:{escalation_secs % 60:02d}"
    if level == 'CRITICAL': action, icon = "Immediate Evacuation Recommended", "🚨"
    else: action, icon = "Restrict Zone Access — Deploy Response Team", "⚠️"
    html = f"""
    <div class="critical-incident-banner">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;position:relative;z-index:1;">
            <div style="display:flex;align-items:center;gap:12px;min-width:0;flex:1;">
                <span style="font-size:24px;flex-shrink:0;" class="emergency-warning-indicator">{icon}</span>
                <div style="min-width:0;">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                        <span style="font-weight:800;color:#fff;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;">{icon} CRITICAL INDUSTRIAL INCIDENT</span>
                        <span style="background:rgba(239,68,68,0.3);color:#fca5a5;border:1px solid rgba(239,68,68,0.5);border-radius:4px;padding:1px 8px;font-size:9px;font-weight:700;letter-spacing:0.5px;">{level}</span>
                    </div>
                    <div style="color:#fca5a5;font-size:11.5px;margin-top:3px;font-weight:500;">{incident_desc} &nbsp;•&nbsp; {zone_label} &nbsp;•&nbsp; {action}</div>
                </div>
            </div>
            <div style="text-align:right;flex-shrink:0;">
                <div style="color:#94a3b8;font-size:8.5px;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Estimated Escalation</div>
                <div style="color:#ef4444;font-size:18px;font-weight:800;font-family:monospace;font-variant-numeric:tabular-nums;">{escalation_str}</div>
            </div>
        </div>
    </div>"""
    placeholder.markdown(html, unsafe_allow_html=True)


def render_cctv_emergency_overlay(
    placeholder: st.delta_generator.DeltaGenerator,
    data_dict: Dict[str, Any],
    selected_zone: str,
    detections_list: Optional[List[Any]] = None,
    confidence: float = 0.94,
) -> None:
    if not is_emergency_active(data_dict):
        placeholder.empty()
        return
    from src.config.ui_constants import ZONE_LABELS
    zone_label = ZONE_LABELS.get(selected_zone, selected_zone)
    labels = []
    if detections_list:
        for d in detections_list[:6]:
            lbl = getattr(d, 'label', str(d)); conf = getattr(d, 'confidence', 0)
            labels.append(f"{lbl} ({conf*100:.0f}%)")
    if not labels: labels = ["Gas Anomaly", "Worker Detected"]
    labels_str = "  ".join(labels)
    level = get_emergency_level(data_dict)
    html = f"""
    <div class="cctv-emergency-overlay">
        <div class="cctv-overlay-topbar">
            <span class="cctv-overlay-live">🔴 LIVE INCIDENT</span>
            <span class="cctv-overlay-rec"><span class="cctv-overlay-rec-dot"></span> REC</span>
        </div>
        <div class="cctv-overlay-info">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                <span style="color:#ef4444;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.5px;">⚠ Critical Risk — {level}</span>
                <span style="color:#fca5a5;font-size:9px;font-weight:700;">Confidence: {confidence*100:.0f}%</span>
            </div>
            <div style="color:#cbd5e1;font-size:9px;margin-bottom:2px;"><b style="color:#94a3b8;">Zone:</b> {zone_label}</div>
            <div style="color:#cbd5e1;font-size:9px;"><b style="color:#94a3b8;">Detections:</b> {labels_str}</div>
        </div>
    </div>"""
    placeholder.markdown(html, unsafe_allow_html=True)


def render_camera_focus_style(placeholder: st.delta_generator.DeltaGenerator, active: bool) -> None:
    if active:
        placeholder.markdown('<style>.cctv-buffer-anchor{transform:scale(1.18);transform-origin:center center;transition:transform 0.5s cubic-bezier(0.16,1,0.3,1);}</style>', unsafe_allow_html=True)
    else:
        placeholder.markdown('<style>.cctv-buffer-anchor{transform:scale(1);transition:transform 0.5s ease;}</style>', unsafe_allow_html=True)


def render_audio_warning(data_dict: Dict[str, Any]) -> None:
    if 'audio_muted' not in st.session_state: st.session_state.audio_muted = False
    muted = st.session_state.audio_muted
    mute_label = "🔇 Muted" if muted else "🔊 Sound On"
    st.markdown(f'<div class="audio-mute-toggle" onclick="document.getElementById(\'audio-mute-btn\').click();">{mute_label}</div>', unsafe_allow_html=True)
    if st.button("Toggle Audio", key="audio_mute_btn", help="Mute/unmute emergency warning sound"):
        st.session_state.audio_muted = not st.session_state.audio_muted
        st.rerun()
    is_critical = get_emergency_level(data_dict) == 'CRITICAL'
    was_played = st.session_state.get('_emergency_audio_played', False)
    if is_critical and not was_played and not muted:
        st.session_state._emergency_audio_played = True
        st.markdown("""<script>
        (function(){try{var ctx=new(window.AudioContext||window.webkitAudioContext)();var now=ctx.currentTime;
        for(var i=0;i<3;i++){var t=now+i*0.6;var osc1=ctx.createOscillator();var gain1=ctx.createGain();
        osc1.type="sawtooth";osc1.frequency.setValueAtTime(800,t);osc1.frequency.setValueAtTime(600,t+0.25);
        gain1.gain.setValueAtTime(0.0001,t);gain1.gain.exponentialRampToValueAtTime(0.15,t+0.02);
        gain1.gain.exponentialRampToValueAtTime(0.0001,t+0.5);osc1.connect(gain1).connect(ctx.destination);
        osc1.start(t);osc1.stop(t+0.5);}setTimeout(function(){ctx.close();},2200);}catch(e){}})();
        </script>""", unsafe_allow_html=True)
    elif not is_critical and was_played:
        st.session_state._emergency_audio_played = False


def render_live_timeline(events: List[Dict[str, Any]], is_resolved: bool = False) -> str:
    from src.ui_components import clean_html
    if not events:
        return clean_html('<div style="background:rgba(17,24,39,0.7);border:1px solid var(--border2);border-radius:12px;padding:14px 16px;min-height:170px;box-sizing:border-box;font-family:Outfit,sans-serif;display:flex;flex-direction:column;"><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:8px;">LIVE INCIDENT TIMELINE</div><div style="color:#64748b;font-size:10px;text-align:center;padding:20px 0;">No events recorded. Monitoring active.</div></div>')
    events_html = []
    for i, e in enumerate(events):
        icon = e.get("icon", "🟢"); time_str = e.get("time", ""); message = e.get("message", ""); status = e.get("status", "NOMINAL")
        if icon in ('🚨', '🔴'): bg, color, border, status_label = 'rgba(239,68,68,0.15)', '#ef4444', 'rgba(239,68,68,0.3)', 'CRITICAL'
        elif icon in ('⚠️', '🟡'): bg, color, border, status_label = 'rgba(245,158,11,0.15)', '#f59e0b', 'rgba(245,158,11,0.3)', 'WARNING'
        elif icon in ('📱', '📧', '🔊'): bg, color, border, status_label = 'rgba(59,130,246,0.15)', '#3b82f6', 'rgba(59,130,246,0.3)', 'ESCALATED'
        elif icon in ('✅', '🟢'): bg, color, border, status_label = 'rgba(34,197,94,0.12)', '#22c55e', 'rgba(34,197,94,0.3)', 'RESOLVED' if is_resolved else 'NOMINAL'
        else: bg, color, border, status_label = 'rgba(34,197,94,0.12)', '#22c55e', 'rgba(34,197,94,0.3)', status
        entry_cls = "timeline-entry" if i == 0 else ""
        if is_resolved and icon in ('✅', '🟢'): entry_cls += " timeline-resolved"
        events_html.append(f'<div class="{entry_cls}" style="display:grid;grid-template-columns:64px 20px 1fr auto;align-items:center;gap:6px;padding:5px 10px;margin-bottom:3px;background:{bg};border:1px solid {border};border-radius:6px;"><span style="color:#64748b;font-family:monospace;font-size:9px;text-align:left;">{time_str}</span><span style="font-size:11px;text-align:center;">{icon}</span><span style="color:#cbd5e1;font-weight:500;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{message}</span><span style="background:{bg};color:{color};border:1px solid {border};border-radius:4px;padding:1px 6px;font-size:7.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.4px;">{status_label}</span></div>')
    timeline_html = f'<div style="background:rgba(17,24,39,0.7);border:1px solid var(--border2);border-radius:12px;padding:14px 16px;min-height:170px;box-sizing:border-box;box-shadow:var(--shadow-sm);font-family:Outfit,sans-serif;display:flex;flex-direction:column;"><div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:8px;">LIVE INCIDENT TIMELINE</div><div style="max-height:160px;overflow-y:auto;font-size:10px;line-height:1.4;flex-grow:1;">{"".join(events_html)}</div></div>'
    return clean_html(timeline_html)


def render_enhanced_ai_decision(
    data_dict: Dict[str, Any],
    selected_zone: str,
    detections_list: Optional[List[Any]] = None,
) -> str:
    from src.ui_components import clean_html
    from src.config.ui_constants import ZONE_LABELS
    STATUS = data_dict.get('STATUS', {}); level = STATUS.get('level', 'LOW'); risk_color = STATUS.get('color', '#22c55e'); compound_score = data_dict.get('compound_risk_score', 0)
    if level == 'CRITICAL': risk_icon, risk_level, confidence = '🔴', 'CRITICAL', "98%"
    elif level == 'HIGH': risk_icon, risk_level, confidence = '🟠', 'HIGH', "94%"
    elif level == 'MEDIUM': risk_icon, risk_level, confidence = '🟡', 'MEDIUM', "88%"
    else: risk_icon, risk_level, confidence = '🟢', 'LOW', "99%"
    latest = data_dict.get('latest', {}); current_gas = float(latest.get(f"{selected_zone}_gas_ppm", 0.0)); current_temp = float(latest.get(f"{selected_zone}_temperature_c", 0.0)); current_workers = len([d for d in (detections_list or []) if getattr(d, 'label', '') == 'person'])
    is_overpressure = (selected_zone == 'Zone_C' and st.session_state.get('cctv_frame_index', 0) >= 95); h_count = len([d for d in (detections_list or []) if getattr(d, 'label', '') == 'helmet']); missing_helmets = current_workers - h_count
    rule_states = [("Fire Detection", any(getattr(d, 'label', '') == 'fire' for d in (detections_list or []))), ("Smoke Detection", any(getattr(d, 'label', '') == 'smoke' for d in (detections_list or []))), ("Gas Critical", current_gas > 35), ("Gas Elevated", current_gas > 20), ("Temp Critical", current_temp > 95), ("Intrusion", any(getattr(d, 'zone_violation', False) for d in (detections_list or []))), ("Pressure Alert", is_overpressure), ("PPE Rules", missing_helmets > 0), ("Overcrowding", current_workers > 9), ("Triple Threat", st.session_state.get('compound_risk_active', False))]
    matched = [name for name, m in rule_states if m]; matched_html = "".join(f"<div style='color:#ef4444;font-weight:600;font-size:9.5px;'>✓ {name}</div>" for name in matched[:4]) or "<div style='color:#22c55e;font-weight:600;font-size:9.5px;'>✓ All Systems Nominal</div>"
    reasoning = f"AI correlated {len(matched)} active rule(s) across sensor + CCTV channels for {ZONE_LABELS.get(selected_zone, selected_zone)}."
    if level == 'CRITICAL': recommendation = f"Evacuate {ZONE_LABELS.get(selected_zone, 'Battery-4')} Immediately"
    elif level == 'HIGH': recommendation = "Deploy Emergency Response Team. Restrict Zone Access."
    elif level == 'MEDIUM': recommendation = "Verify compliance and telemetry levels."
    else: recommendation = "Continue standard plant surveillance."
    esc_secs = max(60, 300 - compound_score * 20); esc_str = f"{esc_secs // 60:02d}:{esc_secs % 60:02d}"
    is_emergency = level in ('HIGH', 'CRITICAL'); update_cls = "ai-decision-update" if is_emergency else ""; border_glow = f"box-shadow:0 0 16px {risk_color}33;" if is_emergency else ""
    html = f"""<div class="{update_cls}" style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid {risk_color};border-radius:12px;padding:14px 16px;min-height:155px;box-sizing:border-box;font-family:Outfit,sans-serif;display:flex;flex-direction:column;{border_glow}"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:8px;">🤖 AI DECISION ENGINE</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;flex-grow:1;align-content:space-between;"><div style="display:flex;flex-direction:column;gap:6px;justify-content:space-between;"><div><span style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:600;letter-spacing:0.5px;display:block;margin-bottom:2px;">Risk Level</span><div style="font-size:17px;font-weight:800;color:{risk_color};display:flex;align-items:center;gap:4px;">{risk_icon} {risk_level}</div></div><div><span style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:600;letter-spacing:0.5px;display:block;margin-bottom:2px;">Confidence</span><div style="font-size:17px;font-weight:800;color:#3b82f6;">{confidence}</div></div><div><span style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:600;letter-spacing:0.5px;display:block;margin-bottom:2px;">Est. Escalation</span><div style="font-size:15px;font-weight:800;color:{risk_color};font-family:monospace;font-variant-numeric:tabular-nums;">{esc_str}</div></div></div><div style="display:flex;flex-direction:column;gap:8px;border-left:1px solid rgba(255,255,255,0.06);padding-left:14px;justify-content:space-between;"><div style="flex-grow:1;"><span style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;letter-spacing:0.5px;">Matched Rules</span><div style="line-height:1.4;max-height:52px;overflow-y:auto;font-size:11px;">{matched_html}</div></div><div><span style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:600;display:block;margin-bottom:2px;letter-spacing:0.5px;">Reasoning</span><div style="font-size:9.5px;color:#94a3b8;line-height:1.3;font-style:italic;">{reasoning}</div></div><div><span style="font-size:10px;color:#64748b;text-transform:uppercase;font-weight:600;display:block;margin-bottom:3px;letter-spacing:0.5px;">Recommended Action</span><div style="font-size:12px;font-weight:700;color:#fff;line-height:1.3;">{recommendation}</div></div></div></div></div>"""
    return clean_html(html)


def render_enhanced_predictive_analytics(data_dict: Dict[str, Any]) -> str:
    from src.ui_components import clean_html
    STATUS = data_dict.get('STATUS', {}); current_level = STATUS.get('level', 'LOW'); current_color = STATUS.get('color', '#22c55e'); compound_score = data_dict.get('compound_risk_score', 0)
    if current_level == 'CRITICAL': predicted_level, predicted_color, probability = 'CRITICAL', '#ef4444', 0.85
    elif current_level == 'HIGH': predicted_level, predicted_color, probability = 'CRITICAL', '#ef4444', 0.62
    elif current_level == 'MEDIUM': predicted_level, predicted_color, probability = 'HIGH', '#f97316', 0.38
    else: predicted_level, predicted_color, probability = 'LOW', '#22c55e', 0.12
    esc_secs = max(60, 300 - compound_score * 20); esc_str = f"{esc_secs // 60:02d}:{esc_secs % 60:02d}"
    if probability > 0.5: trend_icon, trend_color = "📈 RISING", "#ef4444"
    elif probability > 0.25: trend_icon, trend_color = "➡️ STABLE", "#f59e0b"
    else: trend_icon, trend_color = "📉 LOW", "#22c55e"
    prob_pct = probability * 100; gauge_color = predicted_color
    html = f"""<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid {predicted_color};border-radius:12px;padding:12px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;box-shadow:0 0 12px {predicted_color}22;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:8px;">🔮 PREDICTIVE RISK ANALYTICS</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;"><div style="text-align:center;background:rgba(0,0,0,0.2);border-radius:8px;padding:8px;"><div style="color:#64748b;font-size:8.5px;text-transform:uppercase;font-weight:600;margin-bottom:3px;">Current Risk</div><div style="color:{current_color};font-size:18px;font-weight:800;">{current_level}</div></div><div style="text-align:center;background:rgba(0,0,0,0.2);border-radius:8px;padding:8px;"><div style="color:#64748b;font-size:8.5px;text-transform:uppercase;font-weight:600;margin-bottom:3px;">Predicted Risk</div><div style="color:{predicted_color};font-size:18px;font-weight:800;">{predicted_level}</div></div></div><div style="margin-bottom:8px;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;"><span style="color:#94a3b8;font-size:9px;font-weight:600;text-transform:uppercase;">Accident Probability</span><span style="color:{gauge_color};font-size:16px;font-weight:800;font-family:monospace;">{prob_pct:.0f}%</span></div><div style="width:100%;height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;"><div class="predictive-gauge-fill" style="width:{prob_pct:.0f}%;height:100%;background:linear-gradient(90deg,{gauge_color}88,{gauge_color});border-radius:4px;"></div></div></div><div style="display:flex;justify-content:space-between;align-items:center;"><div><span style="color:#94a3b8;font-size:8.5px;text-transform:uppercase;font-weight:600;">Escalation in</span><div class="predictive-countdown" style="color:{gauge_color};font-size:18px;font-weight:800;">{esc_str}"</div></div></div>
    </div>"""
    return clean_html(html)


def render_enhanced_safety_copilot(
    data_dict: Dict[str, Any],
    selected_zone: str,
    detections_list: Optional[List[Any]] = None,
) -> str:
    from src.ui_components import clean_html
    from src.config.ui_constants import ZONE_LABELS
    STATUS = data_dict.get('STATUS', {}); level = STATUS.get('level', 'LOW'); latest = data_dict.get('latest', {}); zone_label = ZONE_LABELS.get(selected_zone, selected_zone)
    if level not in ('HIGH', 'CRITICAL'):
        return clean_html('<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #8b5cf6;border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;"><div style="color:#8b5cf6;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:4px;">🤖 AI SAFETY COPILOT</div><div style="color:#22c55e;font-size:10px;">✅ All systems nominal — no incident explanation required.</div></div>')
    gas_val = float(latest.get(f"{selected_zone}_gas_ppm", 0)); temp_val = float(latest.get(f"{selected_zone}_temperature_c", 0)); worker_count = int(latest.get(f"{selected_zone}_worker_count", 0))
    causes = []
    if gas_val > 35: causes.append(f"Volatile gas concentration ({gas_val:.1f} ppm) exceeded critical threshold in {zone_label}")
    if temp_val > 95: causes.append(f"Equipment temperature ({temp_val:.1f}°C) breached safe operating limit")
    if worker_count > 0: causes.append(f"{worker_count} worker(s) detected in the hazard zone without adequate clearance")
    if not causes: causes.append(f"Compound risk pattern detected across multiple sensor channels in {zone_label}")
    why_alert = f"The AI safety engine correlated {len(causes)} concurrent hazard signals from CCTV detection, gas telemetry, and thermal sensors. The compound risk score exceeded the escalation threshold, triggering an automatic {level} alert for {zone_label}."
    affected_equip = f"Gas sensors, ventilation systems, and CCTV infrastructure in {zone_label}."
    if temp_val > 95: affected_equip += " Thermal stress on processing equipment detected."
    affected_workers = f"{worker_count} worker(s) currently in {zone_label} within the hazard radius. PPE compliance and evacuation status being monitored via CCTV."
    if level == 'CRITICAL': immediate = f"1. Initiate immediate evacuation of {zone_label}. 2. Activate emergency shutdown. 3. Dispatch response teams."
    else: immediate = f"1. Restrict access to {zone_label}. 2. Deploy ERT for verification. 3. Halt active work permits."
    long_term = "Install additional gas detection sensors, review maintenance schedules, enhance ventilation capacity, and conduct operator safety retraining."
    guidelines = "Follow plant emergency response procedure ERP-001. Maintain minimum 50m exclusion zone. Use SCBA equipment for zone entry. All personnel must report to muster point Alpha."
    causes_html = "".join(f"<div style='color:#cbd5e1;font-size:10px;margin-left:8px;margin-bottom:2px;'>• {c}</div>" for c in causes)
    html = f"""<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #8b5cf6;border-radius:12px;padding:12px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;box-shadow:0 0 12px #8b5cf622;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="color:#8b5cf6;font-size:11px;font-weight:600;letter-spacing:1px;">🤖 AI SAFETY COPILOT — INCIDENT EXPLANATION</span><span style="color:#64748b;font-size:9px;">{datetime.now().strftime('%H:%M:%S')} • {level}</span></div><div class="copilot-section" style="margin-bottom:8px;"><div style="color:#ef4444;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">📌 CAUSE</div>{causes_html}</div><div class="copilot-section" style="margin-bottom:8px;"><div style="color:#3b82f6;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">❓ WHY THIS ALERT WAS GENERATED</div><div style="color:#cbd5e1;font-size:10px;line-height:1.4;">{why_alert}</div></div><div class="copilot-section" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;"><div><div style="color:#f97316;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">⚙️ AFFECTED EQUIPMENT</div><div style="color:#94a3b8;font-size:9.5px;line-height:1.3;">{affected_equip}</div></div><div><div style="color:#f97316;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">👷 AFFECTED WORKERS</div><div style="color:#94a3b8;font-size:9.5px;line-height:1.3;">{affected_workers}</div></div></div><div class="copilot-section" style="margin-bottom:6px;"><div style="color:#ef4444;font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">🚨 IMMEDIATE ACTION</div><div style="color:#cbd5e1;font-size:10px;line-height:1.4;">{immediate}</div></div><details style="margin-top:4px;"><summary style="color:#94a3b8;font-size:9px;cursor:pointer;outline:none;font-weight:600;">Long-term prevention & safety guidelines</summary><div class="copilot-section" style="margin-top:4px;"><div style="color:#22c55e;font-size:9.5px;font-weight:700;text-transform:uppercase;margin-bottom:2px;">LONG TERM PREVENTION</div><div style="color:#94a3b8;font-size:9.5px;line-height:1.3;">{long_term}</div></div><div class="copilot-section" style="margin-top:4px;"><div style="color:#22c55e;font-size:9.5px;font-weight:700;text-transform:uppercase;margin-bottom:2px;">SAFETY GUIDELINES</div><div style="color:#94a3b8;font-size:9.5px;line-height:1.3;">{guidelines}</div></div></details></div>"""
    return clean_html(html)


def render_enhanced_emergency_response(data_dict: Dict[str, Any], selected_zone: str) -> str:
    from src.ui_components import clean_html
    from src.config.ui_constants import ZONE_LABELS
    is_active = is_emergency_active(data_dict); level = get_emergency_level(data_dict); zone_label = ZONE_LABELS.get(selected_zone, selected_zone)
    if not is_active:
        return clean_html('<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #1e3a5f;border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:4px;">🆘 EMERGENCY RESPONSE — STANDBY</div><div style="color:#22c55e;font-size:10px;">✅ No active emergency — response teams on standby</div></div>')
    sev_color = "#ef4444" if level == 'CRITICAL' else "#f97316"; compound_score = data_dict.get('compound_risk_score', 0); eta_secs = max(60, 180 - compound_score * 10); eta_str = f"{eta_secs // 60:02d}:{eta_secs % 60:02d}"
    affected_cameras = f"📹 {zone_label} Camera"; affected_zones = zone_label; evidence_status = "🔄 Collecting — CCTV frames + sensor logs archived"
    html = f"""<div class="emergency-response-expanded" style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid {sev_color};border-radius:12px;padding:12px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;box-shadow:0 0 14px {sev_color}33;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="color:{sev_color};font-size:11px;font-weight:600;letter-spacing:1px;">🆘 EMERGENCY RESPONSE — ACTIVE</span><span style="color:{sev_color};font-size:10px;font-weight:700;">{'🚨 EVACUATION RECOMMENDED' if level == 'CRITICAL' else '⚠️ RESTRICTED ACCESS'}</span></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-size:10px;margin-bottom:8px;"><div><span style="color:#94a3b8;font-weight:600;font-size:9px;display:block;margin-bottom:1px;">Incident Commander</span><span style="color:#fff;font-weight:700;">Shift Supervisor #08</span></div><div><span style="color:#94a3b8;font-weight:600;font-size:9px;display:block;margin-bottom:1px;">Emergency Teams</span><span style="color:#cbd5e1;">Alpha & Beta Teams</span></div><div><span style="color:#94a3b8;font-weight:600;font-size:9px;display:block;margin-bottom:1px;">Affected Cameras</span><span style="color:#cbd5e1;">{affected_cameras}</span></div><div><span style="color:#94a3b8;font-weight:600;font-size:9px;display:block;margin-bottom:1px;">Affected Zones</span><span style="color:#fff;font-weight:700;">{affected_zones}</span></div><div><span style="color:#94a3b8;font-weight:600;font-size:9px;display:block;margin-bottom:1px;">Live ETA</span><span style="color:{sev_color};font-weight:800;font-family:monospace;">{eta_str}</span></div><div><span style="color:#94a3b8;font-weight:600;font-size:9px;display:block;margin-bottom:1px;">Evidence Status</span><span style="color:#3b82f6;font-size:9px;">{evidence_status}</span></div></div><div style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px;margin-bottom:6px;"><div style="color:#22c55e;font-size:9px;font-weight:600;text-transform:uppercase;margin-bottom:4px;">Evacuation Routes</div><div style="color:#22c55e;font-size:10px;margin-left:8px;">→ Primary: North Exit → Muster Point Alpha</div><div style="color:#22c55e;font-size:10px;margin-left:8px;">→ Secondary: East Exit → Muster Point Bravo</div></div><div style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px;"><div style="color:#94a3b8;font-size:9px;font-weight:600;text-transform:uppercase;margin-bottom:4px;">Response Checklist</div><div style="color:#cbd5e1;font-size:10px;margin-left:8px;margin-bottom:2px;">☐ Evacuate personnel from {zone_label}</div><div style="color:#cbd5e1;font-size:10px;margin-left:8px;margin-bottom:2px;">☐ Activate emergency shutdown procedures</div><div style="color:#cbd5e1;font-size:10px;margin-left:8px;margin-bottom:2px;">☐ Dispatch Alpha & Beta response teams</div><div style="color:#cbd5e1;font-size:10px;margin-left:8px;margin-bottom:2px;">☐ Isolate gas supply to affected zone</div><div style="color:#cbd5e1;font-size:10px;margin-left:8px;">☐ Confirm all personnel at muster point</div></div></div>"""
    return clean_html(html)


def render_enhanced_compound_risk(
    data_dict: Dict[str, Any],
    selected_zone: str,
    detections_list: Optional[List[Any]] = None,
) -> str:
    from src.ui_components import clean_html
    from src.config.ui_constants import ZONE_LABELS
    compound_score = data_dict.get('compound_risk_score', 0); risk_state = data_dict.get('risk_state', 'LOW'); risk_color = data_dict.get('risk_color', '#22c55e'); total_rules = data_dict.get('total_rules', 1)
    if compound_score == 0:
        return clean_html('<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #1e3a5f;border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:4px;">🧠 COMPOUND RISK INTELLIGENCE</div><div style="color:#22c55e;font-size:10px;">✅ No compound risks detected — all zones stable</div></div>')
    zone_label = ZONE_LABELS.get(selected_zone, selected_zone); latest = data_dict.get('latest', {}); gas_val = float(latest.get(f"{selected_zone}_gas_ppm", 0)); temp_val = float(latest.get(f"{selected_zone}_temperature_c", 0))
    risk_type = "Gas Leak + Worker Proximity" if gas_val > 35 else "Compound Risk Detected"; confidence = 0.94 if risk_state == 'CRITICAL' else 0.88; escalation_prob = min(0.95, compound_score / max(total_rules, 1) + 0.2)
    sensors_matched = []
    if gas_val > 35: sensors_matched.append(f"Gas={gas_val:.1f}ppm")
    if temp_val > 95: sensors_matched.append(f"Temp={temp_val:.1f}°C")
    if not sensors_matched: sensors_matched.append("Multi-sensor anomaly")
    sensors_str = ", ".join(sensors_matched); cameras_matched = f"📹 {zone_label} Camera"
    recommended = f"Evacuate {zone_label} — deploy response teams" if risk_state == 'CRITICAL' else f"Restrict access to {zone_label}"
    html = f"""<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid {risk_color};border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;box-shadow:0 0 12px {risk_color}22;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:8px;">🧠 COMPOUND RISK INTELLIGENCE — {compound_score} Active Risk(s)</div><div class="compound-risk-new" style="background:rgba(0,0,0,0.2);border-left:3px solid {risk_color};border-radius:6px;padding:8px 10px;margin-bottom:6px;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;"><span style="color:{risk_color};font-size:12px;font-weight:700;">#1 {risk_type}</span><span style="color:#64748b;font-size:9px;">{zone_label} • {datetime.now().strftime('%H:%M:%S')}</span></div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 12px;margin-bottom:4px;"><div><span style="color:#64748b;font-size:8px;text-transform:uppercase;font-weight:600;">Risk Score</span><div style="color:{risk_color};font-size:14px;font-weight:800;">{compound_score}/{total_rules}</div></div><div><span style="color:#64748b;font-size:8px;text-transform:uppercase;font-weight:600;">Confidence</span><div style="color:{risk_color};font-size:14px;font-weight:800;">{confidence*100:.0f}%</div></div><div><span style="color:#64748b;font-size:8px;text-transform:uppercase;font-weight:600;">Escalation Prob</span><div style="color:#f97316;font-size:14px;font-weight:800;">{escalation_prob*100:.0f}%</div></div></div><div style="color:#94a3b8;font-size:9.5px;margin-bottom:2px;"><b style="color:#64748b;">Sensors:</b> {sensors_str}</div><div style="color:#94a3b8;font-size:9.5px;margin-bottom:2px;"><b style="color:#64748b;">Cameras:</b> {cameras_matched}</div><div style="color:{risk_color};font-size:10px;margin-top:4px;font-style:italic;">→ {recommended}</div></div></div>"""
    return clean_html(html)


def render_enhanced_smart_alerts(
    data_dict: Dict[str, Any],
    am: AlertManager,
    selected_zone: Optional[str] = None,
) -> str:
    from src.ui_components import clean_html
    if not st.session_state.get('sim_play_active', False):
        return clean_html('<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #1e3a5f;border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:4px;">🚨 SMART ALERT PRIORITIZATION</div><div style="color:#64748b;font-size:10px;">Simulation inactive — no alerts to prioritize.</div></div>')
    all_alerts = getattr(am, 'active_alerts', {})
    if selected_zone and all_alerts: zone_alerts = {k: v for k, v in all_alerts.items() if getattr(v, 'zone', None) == selected_zone}
    else: zone_alerts = all_alerts
    if not zone_alerts:
        return clean_html('<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #1e3a5f;border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:4px;">🚨 SMART ALERT PRIORITIZATION</div><div style="color:#22c55e;font-size:10px;">✅ No active alerts — all zones nominal</div></div>')
    sorted_alerts = sorted(zone_alerts.values(), key=lambda x: getattr(x, 'severity', getattr(x, 'risk_level', 'LOW')).value if hasattr(getattr(x, 'severity', None), 'value') else 0, reverse=True)
    alert_items = ""
    for i, alert in enumerate(sorted_alerts[:5]):
        sev_name = getattr(alert, 'risk_level', getattr(getattr(alert, 'severity', None), 'name', 'LOW')).upper()
        sev_color = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#eab308", "LOW": "#3b82f6"}.get(sev_name, "#22c55e")
        message = getattr(alert, 'message', ''); zone = getattr(alert, 'zone', ''); is_pinned = i == 0; is_new = i == 0
        pin_badge = "📌 PINNED" if is_pinned else f"#{i+1}"; entry_cls = "alert-entering" if is_new else ""; pin_cls = "alert-pinned" if is_pinned else ""
        alert_items += f'<div class="{entry_cls} {pin_cls}" style="background:rgba(0,0,0,0.2);border-radius:6px;padding:6px 10px;margin-bottom:4px;border-left:2px solid {sev_color};"><div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:{sev_color};font-size:10px;font-weight:700;">{pin_badge} {sev_name} • {zone}</span></div><div style="color:#94a3b8;font-size:9px;margin-top:2px;">{message}</div></div>'
    html = f"""<div style="background:linear-gradient(135deg,#0f1f38,#0a1628);border:1px solid #1e3a5f;border-radius:12px;padding:10px 14px;font-family:Outfit,sans-serif;margin-bottom:6px;"><div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;margin-bottom:6px;">🚨 SMART ALERT PRIORITIZATION — {len(sorted_alerts)} Ranked Alert(s)</div>{alert_items}</div>"""
    return clean_html(html)


def orchestrate_emergency_mode(
    data_dict: Dict[str, Any],
    selected_zone: str,
    detections_list: Optional[List[Any]] = None,
) -> None:
    is_active = is_emergency_active(data_dict); was_active = st.session_state.get('_emergency_was_active', False)
    inject_emergency_css()
    if is_active and not was_active:
        toggle_emergency_mode(active=True); st.session_state._emergency_was_active = True
    elif is_active and was_active:
        toggle_emergency_mode(active=True)
    elif not is_active and was_active:
        toggle_emergency_mode(active=True, resolving=True); st.session_state._emergency_was_active = False
        st.markdown('<script>setTimeout(function(){document.body.classList.remove("emergency-mode","emergency-resolving");},1200);</script>', unsafe_allow_html=True)
    else:
        toggle_emergency_mode(active=False)
    render_audio_warning(data_dict)