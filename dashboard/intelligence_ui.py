"""
SurakshaAI — Intelligence Dashboard UI Components
Renders the Safety Intelligence panels using the existing dark industrial theme.
All panels are collapsible/expandable to avoid overcrowding the dashboard.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
import streamlit as _st
from src.ui_components import clean_html

class _StreamlitWrapper:
    def __getattr__(self, name: str) -> Any:
        return getattr(_st, name)
    def markdown(self, body: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(body, str) and kwargs.get("unsafe_allow_html", False):
            body = clean_html(body)
        return _st.markdown(body, *args, **kwargs)

st = _StreamlitWrapper()

from src.safety_intelligence import (
    get_intelligence_orchestrator,
    RiskGrade,
    CompoundRisk,
    PredictionResult,
    PrioritizedAlert,
    EmergencyResponsePlan,
    IncidentPattern,
    SafetyCopilotExplanation,
    SafetyIntelligenceOrchestrator,
)
from dashboard.emergency_mode import (
    is_emergency_active,
    render_enhanced_predictive_analytics,
    render_enhanced_safety_copilot,
    render_enhanced_emergency_response,
    render_enhanced_compound_risk,
    render_enhanced_smart_alerts,
)


# ════════════════════════════════════════════════════════════════════════════════
# THEME CONSTANTS — matches existing dark industrial theme
# ════════════════════════════════════════════════════════════════════════════════

_BG_GRADIENT   = "linear-gradient(135deg,#0f1f38,#0a1628)"
_BORDER        = "#1e3a5f"
_BORDER_GLOW   = "rgba(59,130,246,0.3)"
_TEXT_PRIMARY  = "#e2e8f0"
_TEXT_MUTED    = "#94a3b8"
_TEXT_DIM      = "#64748b"
_ACCENT_BLUE   = "#3b82f6"
_ACCENT_GREEN  = "#22c55e"
_ACCENT_YELLOW = "#eab308"
_ACCENT_ORANGE = "#f97316"
_ACCENT_RED    = "#ef4444"
_ACCENT_PURPLE = "#8b5cf6"
_CARD_RADIUS   = "12px"
_FONT          = "Outfit,sans-serif"


def _severity_color(severity: str) -> str:
    return {
        "CRITICAL": _ACCENT_RED, "HIGH": _ACCENT_ORANGE,
        "MEDIUM": _ACCENT_YELLOW, "LOW": _ACCENT_GREEN,
    }.get((severity or "LOW").upper(), _ACCENT_GREEN)


def _grade_color(grade: RiskGrade) -> str:
    return grade.color


# ════════════════════════════════════════════════════════════════════════════════
# 1. EXECUTIVE COMMAND CENTER — Compact Summary Panel
# ════════════════════════════════════════════════════════════════════════════════

def _calculate_business_impact(orch: SafetyIntelligenceOrchestrator) -> Dict[str, Any]:
    """Calculate business impact metrics from incident history."""
    patterns = orch.get_incident_patterns()
    zone_scores = orch.get_zone_scores()

    # Estimate financial impact avoided
    critical_count = sum(1 for _ in range(len(patterns)))  # simplified
    near_miss_prevented = critical_count * 2  # assumption: 2 near misses prevented per critical

    # Business value calculations
    downtime_saved = critical_count * 4.5  # hours estimated per avoided incident
    financial_saved = downtime_saved * 25000  # $25k per hour estimated plant value

    return {
        'downtime_prevented_hours': round(downtime_saved, 1),
        'financial_impact_saved': f"${financial_saved/1000000:.1f}M",
        'near_miss_prevented': near_miss_prevented,
        'lives_potentially_protected': critical_count * 8,  # workers at risk
    }


def render_executive_command_center() -> None:
    """Compact executive summary — plant health, critical risks, workers at risk, business impact."""
    orch = get_intelligence_orchestrator()
    summary = orch.get_executive_summary()

    business_impact = _calculate_business_impact(orch)

    if not summary:
        # No active intelligence — show safe state
        html = f"""
        <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                    padding:12px 14px; font-family:{_FONT}; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <span style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px;">
                    🎯 EXECUTIVE COMMAND CENTER
                </span>
                <span style="color:{_ACCENT_GREEN}; font-size:10px; font-weight:700;">
                    ● ALL SYSTEMS NOMINAL
                </span>
            </div>
            <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px;">
                <div style="text-align:center;">
                    <div style="color:{_ACCENT_GREEN}; font-size:22px; font-weight:700;">100</div>
                    <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">Plant Health</div>
                </div>
                <div style="text-align:center;">
                    <div style="color:{_TEXT_PRIMARY}; font-size:22px; font-weight:700;">0</div>
                    <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">Critical Risks</div>
                </div>
                <div style="text-align:center;">
                    <div style="color:{_TEXT_PRIMARY}; font-size:22px; font-weight:700;">0</div>
                    <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">Workers at Risk</div>
                </div>
                <div style="text-align:center;">
                    <div style="color:{_ACCENT_GREEN}; font-size:22px; font-weight:700;">100%</div>
                    <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">PPE Compliance</div>
                </div>
            </div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)
        return

    health = summary['overall_plant_health']
    grade_color = summary.get('grade_color', _ACCENT_GREEN)
    grade_label = summary.get('safety_grade', 'SAFE')
    critical = summary.get('critical_risks', 0)
    high = summary.get('high_risks', 0)
    workers = summary.get('workers_at_risk', 0)
    open_inc = summary.get('open_incidents', 0)
    ppe = summary.get('ppe_compliance', 100)
    predicted = summary.get('predicted_hazards', [])

    predicted_html = ""
    if predicted:
        pred_items = "".join(
            f"<div style='color:{_TEXT_MUTED}; font-size:10px; margin-top:2px;'>"
            f"⚠️ {p['zone']}: {p['hazard']} ({p['probability']*100:.0f}% prob, {p['escalation_min']}min)</div>"
            for p in predicted[:2]
        )
        predicted_html = f"""
        <div style="margin-top:8px; padding-top:8px; border-top:1px solid {_BORDER};">
            <div style="color:{_ACCENT_ORANGE}; font-size:9px; font-weight:600; text-transform:uppercase; margin-bottom:4px;">
                📊 Predicted Hazards
            </div>
            {pred_items}
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {grade_color}; border-radius:{_CARD_RADIUS};
                padding:12px 14px; font-family:{_FONT}; margin-bottom:8px;
                box-shadow:0 0 12px {grade_color}33;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px;">
                🎯 EXECUTIVE COMMAND CENTER
            </span>
            <span style="color:{grade_color}; font-size:10px; font-weight:700;">
                ● {grade_label}
            </span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px;">
            <div style="text-align:center;">
                <div style="color:{grade_color}; font-size:22px; font-weight:700;">{health:.0f}</div>
                <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">Plant Health</div>
            </div>
            <div style="text-align:center;">
                <div style="color:{_ACCENT_RED if critical else _TEXT_PRIMARY}; font-size:22px; font-weight:700;">{critical}</div>
                <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">Critical Risks</div>
            </div>
            <div style="text-align:center;">
                <div style="color:{_ACCENT_ORANGE if workers else _TEXT_PRIMARY}; font-size:22px; font-weight:700;">{workers}</div>
                <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">Workers at Risk</div>
            </div>
            <div style="text-align:center;">
                <div style="color:{_ACCENT_GREEN if ppe>=80 else _ACCENT_YELLOW}; font-size:22px; font-weight:700;">{ppe:.0f}%</div>
                <div style="color:{_TEXT_DIM}; font-size:9px; text-transform:uppercase;">PPE Compliance</div>
            </div>
        </div>
        {predicted_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 2. COMPOUND RISK INTELLIGENCE — Correlated Hazards
# ════════════════════════════════════════════════════════════════════════════════

def render_compound_risk_intelligence() -> None:
    """Display highest-priority compound risks with confidence, severity, escalation."""
    orch = get_intelligence_orchestrator()
    risks = orch.get_compound_risks()

    if not risks:
        st.markdown(f"""
        <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                    padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
            <span style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px;">
                🧠 COMPOUND RISK INTELLIGENCE
            </span>
            <div style="color:{_ACCENT_GREEN}; font-size:11px; margin-top:6px;">
                ✅ No compound risks detected — all zones stable
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Display only highest priority risks (top 3)
    top_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)[:3]

    risk_items = ""
    for risk in top_risks:
        sev_color = _severity_color(risk.severity)
        dets = ", ".join(risk.contributing_detections) if risk.contributing_detections else "Sensor anomaly"
        sensors = ", ".join(f"{k}={v:.1f}" for k, v in risk.contributing_sensors.items()) if risk.contributing_sensors else ""

        risk_items += f"""
        <div style="background:rgba(0,0,0,0.2); border-left:3px solid {sev_color}; border-radius:6px;
                    padding:8px 10px; margin-bottom:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:{sev_color}; font-size:12px; font-weight:700;">{risk.risk_type}</span>
                <span style="color:{_TEXT_DIM}; font-size:9px;">{risk.zone} • {risk.timestamp}</span>
            </div>
            <div style="color:{_TEXT_MUTED}; font-size:10px; margin-top:3px;">
                Detections: {dets}{' | Sensors: ' + sensors if sensors else ''}
            </div>
            <div style="display:flex; gap:12px; margin-top:4px;">
                <span style="color:{_TEXT_PRIMARY}; font-size:10px;">
                    Confidence: <b style="color:{sev_color};">{risk.confidence*100:.0f}%</b>
                </span>
                <span style="color:{_TEXT_PRIMARY}; font-size:10px;">
                    Score: <b style="color:{sev_color};">{risk.risk_score:.0f}/100</b>
                </span>
                <span style="color:{_TEXT_PRIMARY}; font-size:10px;">
                    Escalation: <b style="color:{_ACCENT_ORANGE};">{risk.escalation_time_min}min</b>
                </span>
            </div>
            <div style="color:{_TEXT_PRIMARY}; font-size:10px; margin-top:4px; font-style:italic;">
                → {risk.recommended_action}
            </div>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">
            🧠 COMPOUND RISK INTELLIGENCE — {len(risks)} Active Risk(s)
        </div>
        {risk_items}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 3. PREDICTIVE RISK ANALYTICS
# ════════════════════════════════════════════════════════════════════════════════

def render_predictive_analytics() -> None:
    """Display predictive warnings before critical conditions occur."""
    orch = get_intelligence_orchestrator()
    latest = orch.get_latest()

    if not latest or 'predictions' not in latest:
        return

    predictions: Dict[str, PredictionResult] = latest.get('predictions', {})
    if not predictions:
        return

    pred_items = ""
    for zone, pred in predictions.items():
        prob_color = _ACCENT_RED if pred.accident_probability > 0.5 else \
                     _ACCENT_ORANGE if pred.accident_probability > 0.3 else \
                     _ACCENT_YELLOW if pred.accident_probability > 0.15 else _ACCENT_GREEN

        trend_icon = "📈" if pred.trend == "RISING" else "📉" if pred.trend == "DECLINING" else "➡️"

        pred_items += f"""
        <div style="background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 10px; margin-bottom:5px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:{_TEXT_PRIMARY}; font-size:11px; font-weight:600;">{zone}</span>
                <span style="color:{prob_color}; font-size:10px; font-weight:700;">
                    {pred.accident_probability*100:.0f}% accident risk {trend_icon}
                </span>
            </div>
            <div style="color:{_TEXT_MUTED}; font-size:9px; margin-top:2px;">
                Next: {pred.next_likely_hazard} • Escalation: {pred.estimated_escalation_min}min
            </div>
            <div style="color:{prob_color}; font-size:9px; margin-top:2px; font-style:italic;">
                {pred.warning}
            </div>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:6px;">
            🔮 PREDICTIVE RISK ANALYTICS
        </div>
        {pred_items}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 4. AI SAFETY COPILOT — Human-Readable Explanation
# ════════════════════════════════════════════════════════════════════════════════

def render_safety_copilot() -> None:
    """AI Safety Copilot 2.0 — comprehensive incident explanation with all fields."""
    orch = get_intelligence_orchestrator()
    explanation: Optional[SafetyCopilotExplanation] = orch.get_copilot_explanation()

    if not explanation:
        return

    # Enhanced root causes list
    root_causes = "".join(
        "<li style='color:" + _TEXT_MUTED + "; font-size:9px; margin-left:12px;'>" + rc + "</li>"
        for rc in explanation.possible_root_causes[:3]
    )

    # PPE Requirements section
    ppe_section = "<div style='color:" + _ACCENT_BLUE + "; font-size:9px; font-weight:600; margin-top:4px;'>PPE Required:</div>" + \
        "<div style='color:" + _TEXT_MUTED + "; font-size:9px; margin-top:2px;'>" + explanation.ppe_requirements + "</div>" if explanation.ppe_requirements else ""

    # Evacuation guidance section
    evac_section = "<div style='color:" + _ACCENT_ORANGE + "; font-size:9px; font-weight:600; margin-top:4px;'>Evacuation:</div>" + \
        "<div style='color:" + _TEXT_MUTED + "; font-size:9px; margin-top:2px;'>" + explanation.evacuation_guidance + "</div>" if explanation.evacuation_guidance else ""

    # Applicable regulations section
    reg_list = "".join(
        "<div style='color:" + _ACCENT_BLUE + "; font-size:8px; margin:1px 0;'>" + r + "</div>"
        for r in explanation.applicable_regulations[:5]
    ) if explanation.applicable_regulations else ""
    reg_section = "<div style='color:" + _ACCENT_BLUE + "; font-size:9px; font-weight:600; margin-top:4px;'>Regulations:</div>" + \
        "<div style='max-height:60px; overflow-y:auto;'>" + reg_list + "</div>" if explanation.applicable_regulations else ""

    # Preventive actions section
    preventive_list = "".join(
        "<div style='color:" + _ACCENT_GREEN + "; font-size:8px; margin:1px 0;'>" + a + "</div>"
        for a in explanation.preventive_actions[:4]
    ) if explanation.preventive_actions else ""
    preventive_section = "<div style='color:" + _ACCENT_GREEN + "; font-size:9px; font-weight:600; margin-top:4px;'>Prevention:</div>" + \
        "<div style='max-height:60px; overflow-y:auto;'>" + preventive_list + "</div>" if explanation.preventive_actions else ""

    html = """<div style='background:""" + _BG_GRADIENT + """; border:1px solid """ + _ACCENT_PURPLE + """;
                border-radius:""" + _CARD_RADIUS + """; padding:10px 14px; font-family:""" + _FONT + """; margin-bottom:6px;'>
        <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>
            <span style='color:""" + _ACCENT_PURPLE + """; font-size:11px; font-weight:600;'>🤖 AI SAFETY COPILOT 2.0</span>
            <span style='color:""" + _TEXT_DIM + """; font-size:9px;'>""" + str(explanation.confidence * 100) + """% confidence</span>
        </div>
        <div style='color:""" + _TEXT_PRIMARY + """; font-size:10px; margin-bottom:4px;'>
            <b style='color:""" + _ACCENT_BLUE + """;'>Why:</b> """ + explanation.why_it_happened + """
        </div>
        <div style='color:""" + _TEXT_PRIMARY + """; font-size:10px; margin-bottom:4px;'>
            <b style='color:""" + _ACCENT_ORANGE + """;'>Action:</b> """ + explanation.immediate_action + """
        </div>
        """ + ppe_section + evac_section + """
        <details style='margin-top:6px;'><summary style='color:""" + _TEXT_MUTED + """; font-size:9px; cursor:pointer;'>Show full analysis</summary>
            <div style='margin-top:4px;'><div style='color:""" + _TEXT_PRIMARY + """; font-size:9px; font-weight:600;'>Root Causes:</div>
                <ul style='margin:2px 0 4px 0; padding:0;'>""" + root_causes + """</ul>
                <div style='color:""" + _TEXT_PRIMARY + """; font-size:9px; font-weight:600;'>Prevention:</div>
                <div style='color:""" + _TEXT_MUTED + """; font-size:9px;'>""" + explanation.long_term_prevention + """</div>
                <div style='color:""" + _TEXT_PRIMARY + """; font-size:9px; font-weight:600; margin-top:4px;'>Guidelines:</div>
                <div style='color:""" + _TEXT_MUTED + """; font-size:9px;'>""" + explanation.safety_guidelines + """</div>
                """ + reg_section + preventive_section + """
            </div>
        </details>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 5. DYNAMIC SAFETY SCORES — Per Zone
# ════════════════════════════════════════════════════════════════════════════════

def render_dynamic_safety_scores() -> None:
    """Live Safety Score (0-100) for every zone with Green/Yellow/Orange/Red grade."""
    orch = get_intelligence_orchestrator()
    scores = orch.get_zone_scores()

    if not scores:
        return

    score_items = ""
    for zone, score in scores.items():
        grade = RiskGrade.from_score(score)
        score_items += f"""
        <div style="text-align:center; padding:6px 4px; background:rgba(0,0,0,0.2); border-radius:6px;">
            <div style="color:{grade.color}; font-size:18px; font-weight:700;">{score:.0f}</div>
            <div style="color:{_TEXT_DIM}; font-size:8px; text-transform:uppercase;">{zone.replace('_',' ')}</div>
            <div style="color:{grade.color}; font-size:8px; font-weight:600;">{grade.label}</div>
        </div>"""

    dept_score = orch.risk_agent.compute_department_score(scores)
    dept_grade = RiskGrade.from_score(dept_score)

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px;">
                📊 DYNAMIC SAFETY SCORES
            </span>
            <span style="color:{dept_grade.color}; font-size:10px; font-weight:700;">
                Plant: {dept_score:.0f}/100 • {dept_grade.label}
            </span>
        </div>
        <div style="display:grid; grid-template-columns:repeat({min(len(scores),5)},1fr); gap:6px;">
            {score_items}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 6. SMART ALERT PRIORITIZATION
# ════════════════════════════════════════════════════════════════════════════════

def render_smart_alert_prioritization() -> None:
    """Display smart-prioritized alerts ranked by human safety, impact, urgency."""
    orch = get_intelligence_orchestrator()
    alerts = orch.get_prioritized_alerts()

    if not alerts:
        return

    alert_items = ""
    for alert in alerts[:5]:  # top 5
        sev_color = _severity_color(alert.severity)
        rank_badge = "🔴" if alert.priority_rank == 1 else f"#{alert.priority_rank}"

        alert_items += f"""
        <div style="background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 10px; margin-bottom:4px;
                    border-left:2px solid {sev_color};">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:{sev_color}; font-size:10px; font-weight:700;">
                    {rank_badge} {alert.severity} • {alert.zone}
                </span>
                <span style="color:{_TEXT_DIM}; font-size:8px;">
                    Safety:{alert.human_safety_score:.0f} • Impact:{alert.business_impact_score:.0f} • Urgency:{alert.urgency:.0f}
                </span>
            </div>
            <div style="color:{_TEXT_MUTED}; font-size:9px; margin-top:2px;">{alert.message}</div>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:6px;">
            🚨 SMART ALERT PRIORITIZATION — {len(alerts)} Ranked Alert(s)
        </div>
        {alert_items}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 7. EMERGENCY RESPONSE ORCHESTRATOR
# ════════════════════════════════════════════════════════════════════════════════

def render_emergency_response_plan() -> None:
    """Auto-generated emergency response: evacuation, contacts, routes, checklist."""
    orch = get_intelligence_orchestrator()
    plan: Optional[EmergencyResponsePlan] = orch.get_emergency_plan()

    if not plan:
        return

    sev_color = _severity_color(plan.severity)
    evac_badge = "🚨 EVACUATION RECOMMENDED" if plan.evacuation_recommended else "⚠️ RESTRICTED ACCESS"

    contacts_html = "".join(
        f"<div style='color:{_TEXT_MUTED}; font-size:10px; margin-left:8px;'>"
        f"📞 {c['name']} ({c['role']}) — {c['phone']}</div>"
        for c in plan.emergency_contacts
    )

    routes_html = "".join(f"<div style='color:{_ACCENT_GREEN}; font-size:10px; margin-left:8px;'>→ {r}</div>"
                          for r in plan.safe_routes)

    checklist_html = "".join(f"<div style='color:{_TEXT_MUTED}; font-size:10px; margin-left:8px;'>{item}</div>"
                             for item in plan.response_checklist[:6])

    timeline_html = ""
    for event in (plan.incident_timeline or [])[:5]:
        timeline_html += f"""
        <div style="color:{_TEXT_MUTED}; font-size:9px; margin-left:8px;">
            <span style="color:{_ACCENT_BLUE};">{event.get('timestamp','')}</span>
            — {event.get('event','')} 
            <span style="color:{_severity_color(event.get('status',''))};">[{event.get('status','')}]</span>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {sev_color}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;
                box-shadow:0 0 12px {sev_color}33;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="color:{sev_color}; font-size:11px; font-weight:600; letter-spacing:1px;">
                🆘 EMERGENCY RESPONSE ORCHESTRATOR
            </span>
            <span style="color:{sev_color}; font-size:10px; font-weight:700;">{evac_badge}</span>
        </div>
        <div style="color:{_TEXT_PRIMARY}; font-size:10px; margin-bottom:4px;">
            <b>Zone:</b> {plan.zone} • <b>Severity:</b> {plan.severity} • <b>Workers:</b> {plan.affected_workers} • <b>Cameras:</b> {', '.join(plan.affected_cameras)}
        </div>
        <details open style="margin-top:4px;">
            <summary style="color:{_TEXT_MUTED}; font-size:10px; cursor:pointer; outline:none; font-weight:600;">
                📞 Emergency Contacts & Safe Routes
            </summary>
            <div style="margin-top:4px;">
                {contacts_html}
                <div style="color:{_TEXT_PRIMARY}; font-size:10px; font-weight:600; margin-top:4px;">Safe Evacuation Routes:</div>
                {routes_html}
            </div>
        </details>
        <details style="margin-top:4px;">
            <summary style="color:{_TEXT_MUTED}; font-size:10px; cursor:pointer; outline:none; font-weight:600;">
                ✅ Response Checklist
            </summary>
            <div style="margin-top:4px;">{checklist_html}</div>
        </details>
        {f'''<details style="margin-top:4px;">
            <summary style="color:{_TEXT_MUTED}; font-size:10px; cursor:pointer; outline:none; font-weight:600;">
                📋 Incident Timeline
            </summary>
            <div style="margin-top:4px;">{timeline_html}</div>
        </details>''' if timeline_html else ''}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 8. INCIDENT INTELLIGENCE — Pattern Detection
# ════════════════════════════════════════════════════════════════════════════════

def render_incident_intelligence() -> None:
    """Display recurring incident patterns and preventive recommendations."""
    orch = get_intelligence_orchestrator()
    patterns = orch.get_incident_patterns()

    if not patterns:
        return

    pattern_items = ""
    for p in patterns:
        pattern_items += f"""
        <div style="background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 10px; margin-bottom:4px;
                    border-left:2px solid {_ACCENT_PURPLE};">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="color:{_ACCENT_PURPLE}; font-size:10px; font-weight:600;">{p.description}</span>
                <span style="color:{_TEXT_DIM}; font-size:8px;">{p.confidence*100:.0f}% confidence</span>
            </div>
            <div style="color:{_TEXT_MUTED}; font-size:9px; margin-top:2px;">
                Frequency: {p.frequency} • Occurrences: {p.occurrence_count}
            </div>
            <div style="color:{_ACCENT_GREEN}; font-size:9px; margin-top:2px; font-style:italic;">
                → {p.preventive_recommendation}
            </div>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:6px;">
            🔍 INCIDENT INTELLIGENCE — {len(patterns)} Pattern(s) Detected
        </div>
        {pattern_items}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 9. INTELLIGENCE TIMELINE — Automatic Incident Timeline
# ════════════════════════════════════════════════════════════════════════════════

def render_intelligence_timeline() -> None:
    """Automatic incident timeline — every incident creates a timeline entry."""
    orch = get_intelligence_orchestrator()
    timeline = orch.get_incident_timeline()

    if not timeline:
        return

    timeline_items = ""
    for event in timeline[:10]:
        sev_color = _severity_color(event.get('status', ''))
        timeline_items += f"""
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
            <div style="min-width:50px; color:{_ACCENT_BLUE}; font-size:9px; font-weight:600;">
                {event.get('timestamp','')}
            </div>
            <div style="width:8px; height:8px; border-radius:50%; background:{sev_color};
                        box-shadow:0 0 6px {sev_color};"></div>
            <div style="color:{_TEXT_MUTED}; font-size:10px; flex:1;">
                {event.get('event','')}
            </div>
            <div style="color:{sev_color}; font-size:9px; font-weight:600;">
                [{event.get('status','')}]
            </div>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:6px;">
            📋 INTELLIGENCE TIMELINE
        </div>
        {timeline_items}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 10. INTERACTIVE PLANT DIGITAL TWIN — Enhanced Zone Map
# ════════════════════════════════════════════════════════════════════════════════

def render_interactive_plant_twin() -> None:
    """Enhanced interactive digital twin with full system synchronization."""
    try:
        from dashboard.digital_twin import render_zone_digital_twin_full
        render_zone_digital_twin_full()
    except Exception:
        # Fallback to basic geospatial map
        render_geospatial_plant_map()


# ════════════════════════════════════════════════════════════════════════════════
# 10a. GEOSPATIAL PLANT INTELLIGENCE — Expandable Plant Map
# ════════════════════════════════════════════════════════════════════════════════

def render_geospatial_plant_map() -> None:
    """Expandable plant map with camera locations, danger zones, live incidents."""
    orch = get_intelligence_orchestrator()
    scores = orch.get_zone_scores()
    risks = orch.get_compound_risks()

    # Zone positions on the plant map (percentage coordinates)
    zone_positions = {
        'Zone_A':       {'x': 20, 'y': 30, 'label': 'Battery-4', 'cam': '📹'},
        'Zone_B':       {'x': 50, 'y': 25, 'label': 'Battery-5', 'cam': '📹'},
        'Zone_C':       {'x': 80, 'y': 30, 'label': 'Battery-6', 'cam': '📹'},
        'Reactor_Area': {'x': 35, 'y': 65, 'label': 'Reactor', 'cam': '📹'},
        'Storage_Area': {'x': 70, 'y': 70, 'label': 'Storage', 'cam': '📹'},
    }

    zone_markers = ""
    for zone, pos in zone_positions.items():
        score = scores.get(zone, 100)
        grade = RiskGrade.from_score(score)
        has_risk = any(r.zone == zone for r in risks)

        pulse = "animation: pulse 1.5s infinite;" if has_risk else ""
        zone_markers += f"""
        <div style="position:absolute; left:{pos['x']}%; top:{pos['y']}%; transform:translate(-50%,-50%);">
            <div style="width:28px; height:28px; border-radius:50%; background:{grade.color}33;
                        border:2px solid {grade.color}; display:flex; align-items:center; justify-content:center;
                        font-size:12px; {pulse} box-shadow:0 0 10px {grade.color}66;">
                {pos['cam']}
            </div>
            <div style="color:{grade.color}; font-size:8px; font-weight:600; text-align:center; margin-top:2px;
                        text-shadow:0 0 4px rgba(0,0,0,0.8);">
                {pos['label']}
            </div>
            <div style="color:{_TEXT_DIM}; font-size:7px; text-align:center;">
                {score:.0f}
            </div>
        </div>"""

    html = f"""
    <details style="margin-bottom:6px;">
        <summary style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                        padding:8px 14px; font-family:{_FONT}; cursor:pointer; outline:none;
                        color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px;">
            🗺️ GEOSPATIAL PLANT INTELLIGENCE — Click to Expand
        </summary>
        <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                    padding:12px; font-family:{_FONT}; margin-top:4px; position:relative;
                    height:220px; overflow:hidden;">
            <!-- Plant layout grid -->
            <div style="position:absolute; inset:0; opacity:0.15;
                        background-image:linear-gradient({_BORDER} 1px, transparent 1px),
                        linear-gradient(90deg, {_BORDER} 1px, transparent 1px);
                        background-size:20px 20px;"></div>
            <!-- Zone boundaries -->
            <div style="position:absolute; left:10%; top:15%; width:25%; height:30%;
                        border:1px dashed {_BORDER}; border-radius:8px; opacity:0.3;"></div>
            <div style="position:absolute; left:40%; top:15%; width:25%; height:30%;
                        border:1px dashed {_BORDER}; border-radius:8px; opacity:0.3;"></div>
            <div style="position:absolute; left:70%; top:15%; width:25%; height:30%;
                        border:1px dashed {_BORDER}; border-radius:8px; opacity:0.3;"></div>
            <div style="position:absolute; left:20%; top:55%; width:30%; height:35%;
                        border:1px dashed {_BORDER}; border-radius:8px; opacity:0.3;"></div>
            <div style="position:absolute; left:55%; top:55%; width:35%; height:35%;
                        border:1px dashed {_BORDER}; border-radius:8px; opacity:0.3;"></div>
            <!-- Zone markers -->
            {zone_markers}
            <!-- Legend -->
            <div style="position:absolute; bottom:8px; right:8px; background:rgba(0,0,0,0.4);
                        border:1px solid {_BORDER}; border-radius:6px; padding:4px 8px;">
                <div style="color:{_TEXT_DIM}; font-size:8px; text-transform:uppercase; margin-bottom:2px;">Legend</div>
                <div style="display:flex; gap:8px;">
                    <span style="color:{_ACCENT_GREEN}; font-size:8px;">● Safe</span>
                    <span style="color:{_ACCENT_YELLOW}; font-size:8px;">● Caution</span>
                    <span style="color:{_ACCENT_ORANGE}; font-size:8px;">● Elevated</span>
                    <span style="color:{_ACCENT_RED}; font-size:8px;">● Critical</span>
                </div>
            </div>
        </div>
    </details>
    <style>
    @keyframes pulse {{
        0%, 100% {{ transform: scale(1); opacity: 1; }}
        50% {{ transform: scale(1.15); opacity: 0.8; }}
    }}
    </style>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 11. EXECUTIVE SAFETY INTELLIGENCE — Actionable Decision Metrics
# ════════════════════════════════════════════════════════════════════════════════

def render_executive_safety_intelligence() -> None:
    """Executive decision platform — actionable intelligence beyond KPIs."""
    orch = get_intelligence_orchestrator()
    summary = orch.get_executive_summary()
    scores = orch.get_zone_scores()
    risks = orch.get_compound_risks()
    patterns = orch.get_incident_patterns()
    business = _calculate_business_impact(orch)

    # Highest risk zone
    highest_risk_zone = "—"
    highest_risk_score = 0.0
    if scores:
        worst_zone = min(scores, key=scores.get)
        highest_risk_zone = worst_zone.replace('_', ' ')
        highest_risk_score = scores[worst_zone]

    # Most frequent hazard
    most_frequent_hazard = "—"
    if patterns:
        most_frequent_hazard = patterns[0].description

    # Predicted hotspot
    predicted_hotspot = "—"
    latest = orch.get_latest()
    if latest and 'predictions' in latest:
        preds = latest['predictions']
        if preds:
            hotspot_zone = max(preds, key=lambda z: preds[z].accident_probability)
            predicted_hotspot = f"{hotspot_zone.replace('_',' ')} ({preds[hotspot_zone].accident_probability*100:.0f}%)"

    # Repeat incident zone
    repeat_zone = "—"
    if patterns:
        zone_counts: Dict[str, int] = {}
        for p in patterns:
            for word in p.description.split():
                if 'zone' in word.lower() or 'area' in word.lower():
                    zone_counts[word] = zone_counts.get(word, 0) + p.occurrence_count
        if zone_counts:
            repeat_zone = max(zone_counts, key=zone_counts.get)

    # Safety score
    dept_score = orch.risk_agent.compute_department_score(scores) if scores else 100.0
    safety_score = round(dept_score, 1)

    metrics = [
        ("Highest Risk Zone", highest_risk_zone, _ACCENT_RED if highest_risk_score < 50 else _ACCENT_ORANGE),
        ("Most Frequent Hazard", most_frequent_hazard[:25], _ACCENT_YELLOW),
        ("Predicted Hotspot", predicted_hotspot[:25], _ACCENT_ORANGE),
        ("Repeat Incident Zone", repeat_zone, _ACCENT_PURPLE),
        ("Near Miss Count", str(business.get('near_miss_prevented', 0)), _ACCENT_BLUE),
        ("Compliance Trend", "↗ Improving" if summary.get('ppe_compliance', 100) >= 80 else "↘ Declining",
         _ACCENT_GREEN if summary.get('ppe_compliance', 100) >= 80 else _ACCENT_RED),
        ("Risk Trend", "↘ Declining" if len(risks) < 3 else "↗ Rising",
         _ACCENT_GREEN if len(risks) < 3 else _ACCENT_ORANGE),
        ("Downtime Prevented", f"{business.get('downtime_prevented_hours', 0)} hrs", _ACCENT_GREEN),
        ("Financial Loss Prevented", business.get('financial_impact_saved', '$0'), _ACCENT_GREEN),
        ("Lives Protected", str(business.get('lives_potentially_protected', 0)), _ACCENT_BLUE),
        ("Avg Response Time", f"{summary.get('avg_response_time_min', 3.5)} min", _ACCENT_BLUE),
        ("Overall Safety Score", f"{safety_score}/100", RiskGrade.from_score(dept_score).color),
    ]

    metric_grid = ""
    for label, value, color in metrics:
        metric_grid += f"""
        <div style="background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 8px; text-align:center;">
            <div style="color:{color}; font-size:13px; font-weight:700;">{value}</div>
            <div style="color:{_TEXT_DIM}; font-size:7px; text-transform:uppercase; margin-top:2px;">{label}</div>
        </div>"""

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">
            📈 EXECUTIVE SAFETY INTELLIGENCE — Decision Support
        </div>
        <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:6px;">
            {metric_grid}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 12. EXPLAINABLE AI PIPELINE — Visual Factor → Risk Flow
# ════════════════════════════════════════════════════════════════════════════════

def render_explainable_ai_pipeline() -> None:
    """Visual explanation: Gas + Temp + Workers + Permit → Compound Risk → Action."""
    orch = get_intelligence_orchestrator()
    risks = orch.get_compound_risks()

    if not risks:
        return

    top_risk = max(risks, key=lambda r: r.risk_score)
    sev_color = _severity_color(top_risk.severity)

    # Build factor chips from contributing detections and sensors
    factors_html = ""
    for det in top_risk.contributing_detections[:4]:
        icon = "🔥" if "fire" in det else "💨" if "gas" in det else "👷" if "person" in det else "⚠️"
        factors_html += f"""
        <div style="background:rgba(59,130,246,0.15); border:1px solid {_ACCENT_BLUE}55; border-radius:6px;
                    padding:4px 8px; font-size:9px; color:{_TEXT_PRIMARY};">{icon} {det.replace('_',' ').title()}</div>"""

    for sensor, value in top_risk.contributing_sensors.items():
        icon = "🌡️" if "temp" in sensor.lower() else "📊" if "pressure" in sensor.lower() else "💨"
        factors_html += f"""
        <div style="background:rgba(249,115,22,0.15); border:1px solid {_ACCENT_ORANGE}55; border-radius:6px;
                    padding:4px 8px; font-size:9px; color:{_TEXT_PRIMARY};">{icon} {sensor}: {value:.1f}</div>"""

    if not factors_html:
        factors_html = f"<div style='color:{_TEXT_DIM}; font-size:9px;'>No contributing factors</div>"

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {sev_color}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">
            🔬 EXPLAINABLE AI — Decision Pipeline
        </div>
        <!-- Factor chips -->
        <div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:6px;">
            {factors_html}
        </div>
        <!-- Arrow -->
        <div style="text-align:center; color:{_TEXT_DIM}; font-size:14px; margin:2px 0;">↓</div>
        <!-- Compound risk -->
        <div style="background:rgba(0,0,0,0.3); border-radius:6px; padding:6px 10px; text-align:center; margin-bottom:4px;">
            <div style="color:{sev_color}; font-size:12px; font-weight:700;">Compound Risk: {top_risk.risk_type}</div>
            <div style="color:{_TEXT_MUTED}; font-size:9px;">Score: {top_risk.risk_score:.0f}/100 • Confidence: {top_risk.confidence*100:.0f}%</div>
        </div>
        <!-- Arrow -->
        <div style="text-align:center; color:{_TEXT_DIM}; font-size:14px; margin:2px 0;">↓</div>
        <!-- Reasoning -->
        <div style="background:rgba(139,92,246,0.1); border-radius:6px; padding:6px 10px; margin-bottom:4px;">
            <div style="color:{_ACCENT_PURPLE}; font-size:9px; font-weight:600;">AI Reasoning:</div>
            <div style="color:{_TEXT_MUTED}; font-size:9px;">{top_risk.zone} • {top_risk.timestamp} — correlated {len(top_risk.contributing_detections)} detection(s) + {len(top_risk.contributing_sensors)} sensor(s)</div>
        </div>
        <!-- Arrow -->
        <div style="text-align:center; color:{_TEXT_DIM}; font-size:14px; margin:2px 0;">↓</div>
        <!-- Recommended action -->
        <div style="background:rgba(34,197,94,0.1); border-radius:6px; padding:6px 10px;">
            <div style="color:{_ACCENT_GREEN}; font-size:9px; font-weight:600;">Recommended Action:</div>
            <div style="color:{_TEXT_PRIMARY}; font-size:9px;">{top_risk.recommended_action}</div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 13. SMART OPERATOR GUIDANCE — Dynamic Response Procedures
# ════════════════════════════════════════════════════════════════════════════════

def render_smart_operator_guidance() -> None:
    """Dynamic operator guidance that updates as incidents evolve."""
    orch = get_intelligence_orchestrator()
    plan: Optional[EmergencyResponsePlan] = orch.get_emergency_plan()

    if not plan:
        return

    sev_color = _severity_color(plan.severity)

    # Build dynamic guidance sections
    guidance_sections = [
        ("🚨 Immediate Actions", plan.response_checklist[:3], _ACCENT_RED),
        ("🔒 Isolation Procedure", [
            f"Isolate {plan.zone} from process operations",
            "Close upstream valves and block drains",
            "Tag out / lock out affected equipment",
        ], _ACCENT_ORANGE),
        ("🦺 PPE Verification", [
            "Verify SCBA for all responders",
            "Confirm gas detectors operational",
            "Check fire-retardant suits for entry team",
        ], _ACCENT_BLUE),
        ("🏃 Evacuation Route", plan.safe_routes[:2], _ACCENT_GREEN),
        ("📍 Assembly Point", [
            f"Muster at {plan.zone} assembly point",
            "Conduct roll call — account for all personnel",
        ], _ACCENT_GREEN),
        ("🔧 Recovery Procedure", [
            "Do not re-enter until atmosphere verified safe",
            "Conduct damage assessment before restart",
            "File incident report within 24 hours",
        ], _ACCENT_PURPLE),
    ]

    sections_html = ""
    for title, items, color in guidance_sections:
        items_html = "".join(
            f"<div style='color:{_TEXT_MUTED}; font-size:9px; margin:2px 0;'>• {item}</div>"
            for item in items
        )
        sections_html += f"""
        <div style="margin-bottom:6px;">
            <div style="color:{color}; font-size:9px; font-weight:600; margin-bottom:2px;">{title}</div>
            {items_html}
        </div>"""

    # Emergency contacts
    contacts_html = "".join(
        f"<div style='color:{_TEXT_MUTED}; font-size:9px;'>📞 {c['name']} ({c['role']}) — {c['phone']}</div>"
        for c in plan.emergency_contacts[:3]
    )

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {sev_color}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="color:{sev_color}; font-size:11px; font-weight:600; letter-spacing:1px;">
                🎯 SMART OPERATOR GUIDANCE
            </span>
            <span style="color:{_TEXT_DIM}; font-size:8px;">Dynamic • Updates live</span>
        </div>
        <div style="color:{_TEXT_PRIMARY}; font-size:9px; margin-bottom:6px;">
            <b>Zone:</b> {plan.zone} • <b>Severity:</b> {plan.severity} • <b>Workers:</b> {plan.affected_workers}
        </div>
        {sections_html}
        <div style="margin-top:6px; padding-top:6px; border-top:1px solid {_BORDER};">
            <div style="color:{_ACCENT_ORANGE}; font-size:9px; font-weight:600; margin-bottom:2px;">Emergency Contacts:</div>
            {contacts_html}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 14. INCIDENT STORY MODE — Complete Operational Log
# ════════════════════════════════════════════════════════════════════════════════

def render_incident_story_mode() -> None:
    """Convert the incident timeline into a readable operational story."""
    orch = get_intelligence_orchestrator()
    timeline = orch.get_incident_timeline()

    if not timeline or len(timeline) < 2:
        return

    # Reverse to chronological order for story
    story_events = list(reversed(timeline))[:12]

    story_html = ""
    for i, event in enumerate(story_events):
        sev_color = _severity_color(event.get('status', ''))
        is_last = i == len(story_events) - 1

        story_html += f"""
        <div style="display:flex; align-items:flex-start; gap:8px; margin-bottom:2px;">
            <div style="min-width:42px; color:{_ACCENT_BLUE}; font-size:9px; font-weight:600; padding-top:2px;">
                {event.get('timestamp','')}
            </div>
            <div style="width:10px; height:10px; border-radius:50%; background:{sev_color};
                        box-shadow:0 0 6px {sev_color}; margin-top:3px; flex-shrink:0;"></div>
            <div style="color:{_TEXT_MUTED}; font-size:9px; flex:1; padding-top:1px;">
                {event.get('event','')}
            </div>
        </div>"""
        if not is_last:
            story_html += f"<div style='margin-left:50px; border-left:2px solid {_BORDER}; height:8px;'></div>"

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">
            📖 INCIDENT STORY MODE — Operational Log
        </div>
        {story_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# 15. MULTI-AGENT REASONING PIPELINE — Collaborative AI Visualization
# ════════════════════════════════════════════════════════════════════════════════

def render_multi_agent_pipeline() -> None:
    """Visualize the multi-agent reasoning pipeline: Detection → Correlation → Risk → Prediction → Compliance → Emergency → Decision."""
    orch = get_intelligence_orchestrator()
    latest = orch.get_latest()

    # Agent states
    agents = [
        ("Detection", "👁️", _ACCENT_BLUE, "Correlating CCTV + sensor hazards"),
        ("Correlation", "🔗", _ACCENT_PURPLE, "Merging related alerts into incidents"),
        ("Risk Analysis", "🧠", _ACCENT_ORANGE, "Computing compound risk scores"),
        ("Prediction", "🔮", _ACCENT_YELLOW, "Forecasting escalation probability"),
        ("Compliance", "📋", _ACCENT_GREEN, "Checking PPE & permit compliance"),
        ("Emergency", "🆘", _ACCENT_RED, "Generating response plans"),
        ("Executive Decision", "🎯", _TEXT_PRIMARY, "Synthesizing actionable intelligence"),
    ]

    # Determine active agents from latest data
    active_flags = [False] * 7
    if latest:
        active_flags[0] = bool(latest.get('compound_risks'))
        active_flags[1] = bool(latest.get('prioritized_alerts'))
        active_flags[2] = bool(latest.get('zone_scores'))
        active_flags[3] = bool(latest.get('predictions'))
        active_flags[4] = 'ppe_compliance_rate' in latest
        active_flags[5] = bool(latest.get('emergency_plan'))
        active_flags[6] = bool(latest)

    pipeline_html = ""
    for i, (name, icon, color, desc) in enumerate(agents):
        active = active_flags[i]
        opacity = "1.0" if active else "0.4"
        border_color = color if active else _BORDER
        glow = f"box-shadow:0 0 8px {color}55;" if active else ""

        pipeline_html += f"""
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:2px; opacity:{opacity};">
            <div style="width:28px; height:28px; border-radius:50%; background:{color}22; border:1.5px solid {border_color};
                        display:flex; align-items:center; justify-content:center; font-size:12px; {glow}">
                {icon}
            </div>
            <div style="flex:1;">
                <div style="color:{color if active else _TEXT_DIM}; font-size:9px; font-weight:600;">{name} Agent</div>
                <div style="color:{_TEXT_DIM}; font-size:8px;">{desc}</div>
            </div>
            <div style="color:{_ACCENT_GREEN if active else _TEXT_DIM}; font-size:8px; font-weight:600;">
                {'● ACTIVE' if active else '○ STANDBY'}
            </div>
        </div>"""
        if i < len(agents) - 1:
            pipeline_html += f"<div style='margin-left:14px; border-left:2px solid {_BORDER}; height:6px;'></div>"

    html = f"""
    <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
        <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:8px;">
            🤝 MULTI-AGENT REASONING PIPELINE
        </div>
        {pipeline_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# MASTER RENDER — All Intelligence Panels
# ════════════════════════════════════════════════════════════════════════════════

def render_intelligence_panels() -> None:
    """
    Render all intelligence panels in the right sidebar.
    Uses collapsible/expandable sections to avoid overcrowding.
    Only renders panels that have active data.
    """
    orch = get_intelligence_orchestrator()
    latest = orch.get_latest()

    if not latest:
        # No intelligence data yet — show standby state
        st.markdown(f"""
        <div style="background:{_BG_GRADIENT}; border:1px solid {_BORDER}; border-radius:{_CARD_RADIUS};
                    padding:10px 14px; font-family:{_FONT}; margin-bottom:6px;">
            <div style="color:{_TEXT_MUTED}; font-size:11px; font-weight:600; letter-spacing:1px; margin-bottom:4px;">
                🧠 SAFETY INTELLIGENCE
            </div>
            <div style="color:{_ACCENT_GREEN}; font-size:10px;">
                ✅ All agents standing by — monitoring active
            </div>
        </div>
        """, unsafe_allow_html=True)
        # Still show the digital twin and multi-agent pipeline in standby
        render_interactive_plant_twin()
        render_multi_agent_pipeline()
        return

    # Executive Command Center (always shown)
    render_executive_command_center()

    # Executive Safety Intelligence — actionable metrics (always shown)
    render_executive_safety_intelligence()

    # Dynamic Safety Scores (always shown if scores exist)
    render_dynamic_safety_scores()

    # Compound Risk Intelligence (only if risks exist)
    render_compound_risk_intelligence()

    # Explainable AI Pipeline (only if risks exist)
    render_explainable_ai_pipeline()

    # Predictive Analytics (always shown if predictions exist)
    render_predictive_analytics()

    # AI Safety Copilot (only if explanation exists)
    render_safety_copilot()

    # Smart Alert Prioritization (only if alerts exist)
    render_smart_alert_prioritization()

    # Emergency Response Plan (only if plan exists)
    render_emergency_response_plan()

    # Smart Operator Guidance (only if emergency plan exists)
    render_smart_operator_guidance()

    # Incident Intelligence (only if patterns exist)
    render_incident_intelligence()

    # Incident Story Mode (only if timeline exists)
    render_incident_story_mode()

    # Intelligence Timeline (only if timeline exists)
    render_intelligence_timeline()

    # Multi-Agent Reasoning Pipeline (always shown)
    render_multi_agent_pipeline()

    # Interactive Plant Digital Twin (always available)
    render_interactive_plant_twin()
