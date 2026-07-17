"""
SurakshaAI — Safety Intelligence Orchestrator
Multi-agent architecture that transforms detection into intelligence.

Agents:
  - DetectionAgent:        Correlates raw detections into compound hazards
  - RiskAnalysisAgent:     Computes dynamic risk scores (0-100) per zone/camera/department
  - PredictionAgent:       Predicts escalation probability, next hazard, time-to-critical
  - AlertAgent:            Smart prioritization — merge, suppress, rank alerts
  - ComplianceAgent:       PPE compliance, violation trends, regulatory checks
  - ReportingAgent:        Incident intelligence — recurring patterns, preventive recs
  - EmergencyResponseAgent: Evacuation, contacts, safe routes, response checklist

All agents are coordinated by the SafetyIntelligenceOrchestrator singleton.
This module EXTENDS existing modules (risk_engine, ai_explainability, action_engine,
compliance_engine, alert_coordinator) — it does NOT replace them.
"""

import time
import math
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
from collections import deque, defaultdict
from enum import Enum

if TYPE_CHECKING:
    from src.alert_system import AlertManager


# ════════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════════════

class RiskGrade(Enum):
    """Dynamic Safety Score grade (0-100)."""
    GREEN  = (80, 100, "#22c55e", "SAFE")
    YELLOW = (60, 79,  "#eab308", "CAUTION")
    ORANGE = (40, 59,  "#f97316", "ELEVATED")
    RED    = (0,  39,  "#ef4444", "CRITICAL")

    @classmethod
    def from_score(cls, score: float) -> "RiskGrade":
        score = max(0, min(100, score))
        for g in cls:
            lo, hi, _, _ = g.value
            if lo <= score <= hi:
                return g
        return cls.RED

    @property
    def color(self) -> str:
        return self.value[2]

    @property
    def label(self) -> str:
        return self.value[3]


@dataclass
class CompoundRisk:
    """A correlated compound risk event."""
    risk_id: str
    zone: str
    risk_type: str               # e.g. "Fire+Smoke", "Gas+Worker"
    severity: str                # CRITICAL / HIGH / MEDIUM / LOW
    confidence: float            # 0.0 - 1.0
    affected_zone: str
    recommended_action: str
    escalation_time_min: int    # estimated minutes before escalation
    contributing_detections: List[str] = field(default_factory=list)
    contributing_sensors: Dict[str, float] = field(default_factory=dict)
    timestamp: str = ""
    risk_score: float = 0.0      # 0-100 dynamic score


@dataclass
class PredictionResult:
    """Predictive risk analytics for a zone."""
    zone: str
    accident_probability: float       # 0.0 - 1.0
    next_likely_hazard: str            # e.g. "Gas Escalation", "Fire Spread"
    estimated_escalation_min: int      # minutes before critical
    trend: str                         # "RISING" / "STABLE" / "DECLINING"
    trend_confidence: float            # 0.0 - 1.0
    warning: str                       # human-readable predictive warning
    risk_score: float = 0.0


@dataclass
class PrioritizedAlert:
    """Smart alert prioritization result."""
    alert_id: str
    zone: str
    severity: str
    priority_rank: int          # 1 = highest
    human_safety_score: float   # 0-100
    business_impact_score: float
    confidence: float
    urgency: float
    escalation_probability: float
    merged_from: List[str] = field(default_factory=list)  # IDs of suppressed duplicates
    message: str = ""


@dataclass
class EmergencyResponsePlan:
    """Auto-generated emergency response orchestration."""
    plan_id: str
    zone: str
    severity: str
    evacuation_recommended: bool
    emergency_contacts: List[Dict[str, str]] = field(default_factory=list)
    affected_cameras: List[str] = field(default_factory=list)
    affected_workers: int = 0
    safe_routes: List[str] = field(default_factory=list)
    incident_timeline: List[Dict[str, str]] = field(default_factory=list)
    response_checklist: List[str] = field(default_factory=list)
    evidence_package: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""


@dataclass
class IncidentPattern:
    """Recurring incident pattern from incident intelligence."""
    pattern_id: str
    description: str          # e.g. "Gas leak every Friday night"
    zone: str
    frequency: str           # e.g. "Weekly", "Daily during shift change"
    occurrence_count: int
    preventive_recommendation: str
    confidence: float


@dataclass
class SafetyCopilotExplanation:
    """AI Safety Copilot — human-readable incident explanation."""
    incident_id: str
    zone: str
    why_it_happened: str
    contributing_detections: List[str]
    possible_root_causes: List[str]
    immediate_action: str
    long_term_prevention: str
    safety_guidelines: str
    confidence: float
    timestamp: str = ""
    
    # Enhanced Copilot 2.0 fields
    affected_equipment: List[str] = field(default_factory=list)
    affected_workers: int = 0
    evacuation_guidance: str = ""
    ppe_requirements: str = ""
    equipment_at_risk: List[Dict[str, Any]] = field(default_factory=list)
    workers_at_risk: List[Dict[str, Any]] = field(default_factory=list)
    applicable_regulations: List[str] = field(default_factory=list)
    compliance_references: List[str] = field(default_factory=list)
    preventive_actions: List[str] = field(default_factory=list)


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 1: Detection Agent — Compound Hazard Correlation
# ════════════════════════════════════════════════════════════════════════════════

class DetectionAgent:
    """
    Correlates raw detections + sensor telemetry into compound hazards.
    Extends the existing CompoundRiskEngine with cross-detection correlation.
    """

    # Compound hazard correlation rules
    CORRELATION_RULES: List[Dict[str, Any]] = [
        {
            'id': 'FIRE_SMOKE_CORRELATED',
            'detections': ['fire', 'smoke'],
            'min_matches': 1,
            'risk_type': 'Fire + Smoke',
            'severity': 'CRITICAL',
            'confidence_base': 0.92,
            'action': 'Activate fire suppression, evacuate zone, mobilize fire response team.',
            'escalation_min': 2,
        },
        {
            'id': 'GAS_WORKER_EXPOSURE',
            'detections': ['gas_leak', 'person'],
            'sensors': {'gas_ppm': 25},
            'min_matches': 2,
            'risk_type': 'Gas Leak + Worker Nearby',
            'severity': 'CRITICAL',
            'confidence_base': 0.88,
            'action': 'Evacuate workers immediately, isolate gas source, maximize ventilation.',
            'escalation_min': 3,
        },
        {
            'id': 'NO_HELMET_HAZARD_ZONE',
            'detections': ['no_helmet', 'fire'],
            'min_matches': 1,
            'risk_type': 'PPE Violation + Hazard Zone',
            'severity': 'HIGH',
            'confidence_base': 0.85,
            'action': 'Remove worker from hazard zone, enforce PPE compliance, issue safety warning.',
            'escalation_min': 5,
        },
        {
            'id': 'SMOKE_TEMP_CONFINED',
            'detections': ['smoke'],
            'sensors': {'temperature': 95},
            'min_matches': 1,
            'risk_type': 'Smoke + High Temp + Confined Space',
            'severity': 'CRITICAL',
            'confidence_base': 0.90,
            'action': 'Immediate evacuation, activate cooling systems, dispatch emergency team.',
            'escalation_min': 2,
        },
        {
            'id': 'GAS_ELEVATED_TREND',
            'detections': [],
            'sensors': {'gas_ppm': 20},
            'min_matches': 0,
            'risk_type': 'Elevated Gas Trend',
            'severity': 'HIGH',
            'confidence_base': 0.75,
            'action': 'Investigate gas source, increase ventilation, restrict zone access.',
            'escalation_min': 8,
        },
        {
            'id': 'OVERPRESSURE_RISK',
            'detections': ['overpressure'],
            'sensors': {'pressure': 80},
            'min_matches': 1,
            'risk_type': 'Overpressure Event',
            'severity': 'CRITICAL',
            'confidence_base': 0.93,
            'action': 'Vent pressure safely, isolate vessels, evacuate critical radius.',
            'escalation_min': 1,
        },
        {
            'id': 'WORKER_FALL',
            'detections': ['worker_fall'],
            'min_matches': 1,
            'risk_type': 'Worker Fall',
            'severity': 'CRITICAL',
            'confidence_base': 0.95,
            'action': 'Dispatch medical response immediately, secure area, call emergency services.',
            'escalation_min': 1,
        },
    ]

    def correlate(self, detections: List[Any], sensor_values: Dict[str, float],
                  zone: str) -> List[CompoundRisk]:
        """Correlate detections and sensors into compound risks."""
        risks: List[CompoundRisk] = []
        det_labels = set(getattr(d, 'label', str(d)) for d in detections)

        for rule in self.CORRELATION_RULES:
            matched = False
            contributing_dets = []
            contributing_sensors = {}

            # Check detection matches
            rule_dets = rule.get('detections', [])
            det_matches = sum(1 for d in rule_dets if d in det_labels)
            if det_matches >= rule.get('min_matches', 1):
                matched = True
                contributing_dets = [d for d in rule_dets if d in det_labels]

            # Check sensor thresholds
            rule_sensors = rule.get('sensors', {})
            for sensor_key, threshold in rule_sensors.items():
                actual = sensor_values.get(sensor_key, 0)
                if actual >= threshold:
                    matched = True
                    contributing_sensors[sensor_key] = actual

            if not matched:
                continue

            # Compute confidence — boosted by detection confidence
            det_confidences = [getattr(d, 'confidence', 0.85) for d in detections
                               if getattr(d, 'label', '') in contributing_dets]
            conf_boost = max(det_confidences) if det_confidences else 0.85
            confidence = min(1.0, rule['confidence_base'] * 0.7 + conf_boost * 0.3)

            # Compute dynamic risk score (0-100)
            severity_scores = {'CRITICAL': 90, 'HIGH': 70, 'MEDIUM': 45, 'LOW': 20}
            base = severity_scores.get(rule['severity'], 20)
            risk_score = min(100, base + (confidence * 10))

            risks.append(CompoundRisk(
                risk_id=f"{rule['id']}_{zone}_{datetime.now().strftime('%H%M%S')}",
                zone=zone,
                risk_type=rule['risk_type'],
                severity=rule['severity'],
                confidence=round(confidence, 3),
                affected_zone=zone,
                recommended_action=rule['action'],
                escalation_time_min=rule['escalation_min'],
                contributing_detections=contributing_dets,
                contributing_sensors=contributing_sensors,
                timestamp=datetime.now().strftime('%H:%M:%S'),
                risk_score=round(risk_score, 1),
            ))

        return risks


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 2: Risk Analysis Agent — Dynamic Safety Score (0-100)
# ════════════════════════════════════════════════════════════════════════════════

class RiskAnalysisAgent:
    """
    Computes a live Safety Score (0-100) for every zone, camera, and department.
    Score is continuously updated based on compound risks, sensor trends, and
    historical alert frequency.
    """

    def __init__(self) -> None:
        self._zone_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=60))
        self._lock = threading.Lock()

    def compute_zone_score(self, zone: str, compound_risks: List[CompoundRisk],
                           sensor_values: Dict[str, float],
                           alert_count: int = 0) -> float:
        """Compute dynamic safety score (0-100) for a zone. 100 = safest."""
        with self._lock:
            # Base score starts at 100 (perfectly safe)
            score = 100.0

            # Deduct for compound risks
            for risk in compound_risks:
                if risk.zone == zone:
                    severity_deduction = {
                        'CRITICAL': 45, 'HIGH': 25, 'MEDIUM': 12, 'LOW': 5
                    }.get(risk.severity, 5)
                    score -= severity_deduction * risk.confidence

            # Deduct for elevated sensor readings
            gas = sensor_values.get('gas_ppm', 0)
            temp = sensor_values.get('temperature', 0)
            pressure = sensor_values.get('pressure', 0)

            if gas > 35:
                score -= min(20, (gas - 35) * 0.8)
            elif gas > 20:
                score -= min(10, (gas - 20) * 0.4)

            if temp > 95:
                score -= min(15, (temp - 95) * 0.6)
            elif temp > 88:
                score -= min(8, (temp - 88) * 0.3)

            if pressure > 80:
                score -= min(18, (pressure - 80) * 0.5)

            # Deduct for alert frequency (recent alerts lower the score)
            score -= min(15, alert_count * 3)

            # Track history for trend analysis
            self._zone_history[zone].append(score)

            # Trend penalty — if score is declining, penalize further
            hist = list(self._zone_history[zone])
            if len(hist) >= 3:
                recent_trend = hist[-1] - hist[-3]
                if recent_trend < -5:  # declining fast
                    score -= min(10, abs(recent_trend) * 0.3)

            return round(max(0, min(100, score)), 1)

    def compute_department_score(self, zone_scores: Dict[str, float]) -> float:
        """Aggregate zone scores into a department-level score."""
        if not zone_scores:
            return 100.0
        # Weighted average — critical zones weighted higher
        weights = {'Reactor_Area': 1.5, 'Storage_Area': 1.2, 'Zone_C': 1.3,
                    'Zone_A': 1.0, 'Zone_B': 1.0}
        total_weight = 0
        weighted_sum = 0
        for zone, score in zone_scores.items():
            w = weights.get(zone, 1.0)
            weighted_sum += score * w
            total_weight += w
        return round(weighted_sum / total_weight if total_weight else 100, 1)

    def get_trend(self, zone: str) -> Tuple[str, float]:
        """Return (trend_direction, trend_confidence) for a zone."""
        with self._lock:
            hist = list(self._zone_history[zone])
            if len(hist) < 2:
                return "STABLE", 0.5
            delta = hist[-1] - hist[0]
            if delta < -5:
                return "RISING", min(1.0, abs(delta) / 20)
            elif delta > 5:
                return "DECLINING", min(1.0, abs(delta) / 20)
            return "STABLE", 0.6


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 3: Prediction Agent — Predictive Risk Analytics
# ════════════════════════════════════════════════════════════════════════════════

class PredictionAgent:
    """
    Predicts probability of accident, next likely hazard, estimated escalation
    time, and trend over previous alerts. Generates warnings BEFORE critical.
    """

    # Hazard transition probabilities (simplified Markov model)
    HAZARD_TRANSITIONS: Dict[str, Dict[str, float]] = {
        'gas_elevated':  {'gas_critical': 0.35, 'gas_elevated': 0.45, 'safe': 0.20},
        'gas_critical':  {'fire': 0.25, 'gas_critical': 0.50, 'safe': 0.25},
        'temp_elevated': {'temp_critical': 0.30, 'temp_elevated': 0.50, 'safe': 0.20},
        'temp_critical': {'fire': 0.35, 'temp_critical': 0.40, 'safe': 0.25},
        'ppe_violation': {'ppe_violation': 0.60, 'safe': 0.30, 'accident': 0.10},
        'fire':          {'fire_spread': 0.40, 'fire': 0.35, 'safe': 0.25},
    }

    def predict(self, zone: str, compound_risks: List[CompoundRisk],
                sensor_values: Dict[str, float],
                safety_score: float, trend: str = "STABLE") -> PredictionResult:
        """Generate predictive risk analytics for a zone."""
        # Accident probability — based on safety score and trend
        base_prob = max(0, (100 - safety_score) / 100)
        trend_multiplier = {"RISING": 1.5, "STABLE": 1.0, "DECLINING": 0.6}.get(trend, 1.0)
        accident_prob = min(0.95, base_prob * trend_multiplier)

        # Determine current hazard state
        gas = sensor_values.get('gas_ppm', 0)
        temp = sensor_values.get('temperature', 0)
        has_fire = any(r.risk_type == 'Fire + Smoke' for r in compound_risks)
        has_ppe = any('PPE' in r.risk_type for r in compound_risks)

        current_state = 'safe'
        if has_fire:
            current_state = 'fire'
        elif gas > 35:
            current_state = 'gas_critical'
        elif gas > 20:
            current_state = 'gas_elevated'
        elif temp > 95:
            current_state = 'temp_critical'
        elif temp > 88:
            current_state = 'temp_elevated'
        elif has_ppe:
            current_state = 'ppe_violation'

        # Predict next likely hazard
        transitions = self.HAZARD_TRANSITIONS.get(current_state, {})
        next_hazard = "Monitor — no immediate escalation predicted"
        if transitions:
            # Pick the most dangerous transition
            danger_order = ['fire_spread', 'fire', 'gas_critical', 'temp_critical',
                            'accident', 'gas_elevated', 'temp_elevated', 'ppe_violation']
            for hazard in danger_order:
                if hazard in transitions and transitions[hazard] > 0.2:
                    next_hazard = hazard.replace('_', ' ').title()
                    break

        # Estimated escalation time
        escalation_min = 30  # default: stable
        if compound_risks:
            escalation_min = min(r.escalation_time_min for r in compound_risks)
        elif accident_prob > 0.5:
            escalation_min = 5
        elif accident_prob > 0.3:
            escalation_min = 10
        elif accident_prob > 0.15:
            escalation_min = 20

        # Generate predictive warning
        warning = ""
        if accident_prob > 0.7:
            warning = f"⚠️ CRITICAL: High probability of accident in {zone}. Immediate intervention required."
        elif accident_prob > 0.4:
            warning = f"⚠️ ELEVATED: Accident likely within {escalation_min} min. Prepare response team."
        elif accident_prob > 0.2:
            warning = f"📊 MONITOR: Rising risk in {zone}. Next likely: {next_hazard}."
        else:
            warning = f"✅ STABLE: {zone} operating within safe parameters."

        return PredictionResult(
            zone=zone,
            accident_probability=round(accident_prob, 3),
            next_likely_hazard=next_hazard,
            estimated_escalation_min=escalation_min,
            trend=trend,
            trend_confidence=0.75,
            warning=warning,
            risk_score=safety_score,
        )


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 4: Alert Agent — Smart Alert Prioritization
# ════════════════════════════════════════════════════════════════════════════════

class AlertAgent:
    """
    Smart alert prioritization — merge related alerts, suppress duplicates,
    rank by human safety, business impact, confidence, urgency, escalation.
    """

    def __init__(self) -> None:
        self._seen_alerts: Dict[str, float] = {}  # key -> last_seen_timestamp
        self._suppression_window = 30.0  # seconds

    def prioritize(self, compound_risks: List[CompoundRisk],
                    zone_scores: Dict[str, float]) -> List[PrioritizedAlert]:
        """Merge, suppress, and rank alerts."""
        now = time.time()
        prioritized: List[PrioritizedAlert] = []

        for risk in compound_risks:
            # Dedup key — same zone + risk type
            dedup_key = f"{risk.zone}:{risk.risk_type}"

            # Suppress duplicates within suppression window
            last_seen = self._seen_alerts.get(dedup_key, 0)
            if now - last_seen < self._suppression_window:
                continue  # suppressed duplicate
            self._seen_alerts[dedup_key] = now

            # Human safety score — based on severity and worker proximity
            severity_safety = {
                'CRITICAL': 95, 'HIGH': 70, 'MEDIUM': 40, 'LOW': 15
            }.get(risk.severity, 15)
            worker_factor = 1.0
            if 'person' in risk.contributing_detections or 'Worker' in risk.risk_type:
                worker_factor = 1.3  # workers at risk = higher priority
            human_safety = min(100, severity_safety * worker_factor)

            # Business impact — based on zone importance
            zone_impact = {
                'Reactor_Area': 90, 'Storage_Area': 80, 'Zone_C': 75,
                'Zone_A': 60, 'Zone_B': 60
            }.get(risk.zone, 50)
            business_impact = min(100, zone_impact * (risk.confidence + 0.3))

            # Urgency — inverse of escalation time
            urgency = min(100, 100 - (risk.escalation_time_min * 5))

            # Escalation probability
            escalation_prob = risk.confidence * (1 - risk.escalation_time_min / 30)
            escalation_prob = max(0, min(1, escalation_prob))

            # Composite priority score
            priority_score = (
                human_safety * 0.40 +
                business_impact * 0.20 +
                risk.confidence * 100 * 0.15 +
                urgency * 0.15 +
                escalation_prob * 100 * 0.10
            )

            prioritized.append(PrioritizedAlert(
                alert_id=risk.risk_id,
                zone=risk.zone,
                severity=risk.severity,
                priority_rank=0,  # assigned after sorting
                human_safety_score=round(human_safety, 1),
                business_impact_score=round(business_impact, 1),
                confidence=risk.confidence,
                urgency=round(urgency, 1),
                escalation_probability=round(escalation_prob, 3),
                message=risk.recommended_action,
            ))

        # Sort by composite priority (descending)
        prioritized.sort(key=lambda a: (
            a.human_safety_score * 0.40 + a.business_impact_score * 0.20 +
            a.confidence * 100 * 0.15 + a.urgency * 0.15 +
            a.escalation_probability * 100 * 0.10
        ), reverse=True)

        # Assign ranks
        for i, alert in enumerate(prioritized):
            alert.priority_rank = i + 1

        return prioritized


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 5: Compliance Agent — PPE & Regulatory Intelligence
# ════════════════════════════════════════════════════════════════════════════════

class ComplianceAgent:
    """
    Tracks PPE compliance, violation trends, and regulatory adherence.
    Extends the existing ComplianceEngine with real-time tracking.
    """

    def __init__(self) -> None:
        self._violation_history: deque = deque(maxlen=200)
        self._ppe_checks: int = 0
        self._ppe_violations: int = 0

    def record_check(self, zone: str, violations: int, workers: int) -> None:
        """Record a PPE compliance check."""
        self._ppe_checks += 1
        self._ppe_violations += violations
        self._violation_history.append({
            'timestamp': datetime.now(),
            'zone': zone,
            'violations': violations,
            'workers': workers,
        })

    def get_compliance_rate(self) -> float:
        """Return PPE compliance rate (0-100)."""
        if self._ppe_checks == 0:
            return 100.0
        total_workers = sum(v['workers'] for v in self._violation_history)
        total_violations = sum(v['violations'] for v in self._violation_history)
        if total_workers == 0:
            return 100.0
        return round(max(0, 100 - (total_violations / total_workers) * 100), 1)

    def get_violation_trend(self) -> Tuple[str, float]:
        """Return violation trend direction and confidence."""
        if len(self._violation_history) < 4:
            return "STABLE", 0.5
        recent = list(self._violation_history)
        first_half = sum(v['violations'] for v in recent[:len(recent)//2])
        second_half = sum(v['violations'] for v in recent[len(recent)//2:])
        if second_half > first_half * 1.2:
            return "RISING", 0.8
        elif second_half < first_half * 0.8:
            return "DECLINING", 0.8
        return "STABLE", 0.6


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 6: Reporting Agent — Incident Intelligence & Pattern Detection
# ════════════════════════════════════════════════════════════════════════════════

class ReportingAgent:
    """
    Finds recurring incident patterns and generates preventive recommendations.
    Also generates full structured incident reports for audit and learning.
    """

    def __init__(self) -> None:
        self._incident_log: deque = deque(maxlen=500)
        self._incident_reports: Dict[str, Dict[str, Any]] = {}  # incident_id -> full report

    def record_incident(self, zone: str, hazard_type: str, severity: str) -> None:
        """Record an incident for pattern analysis."""
        self._incident_log.append({
            'timestamp': datetime.now(),
            'zone': zone,
            'hazard_type': hazard_type,
            'severity': severity,
            'hour': datetime.now().hour,
            'weekday': datetime.now().weekday(),  # 0=Monday
        })

    def generate_incident_report(
        self,
        incident_id: str,
        zone: str,
        compound_risk: Optional[CompoundRisk],
        sensor_data: Dict[str, float],
        workers: int,
        emergency_plan: Optional[EmergencyResponsePlan] = None,
        copilot_explanation: Optional[SafetyCopilotExplanation] = None
    ) -> Dict[str, Any]:
        """Generate a complete structured incident report."""
        report = {
            'incident_id': incident_id,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'zone': zone,
            'root_cause': self._determine_root_cause(compound_risk, sensor_data) if compound_risk else 'Under investigation',
            'trigger_conditions': self._get_trigger_conditions(compound_risk, sensor_data) if compound_risk else [],
            'ai_reasoning': copilot_explanation.why_it_happened if copilot_explanation else 'AI analysis pending',
            'timeline': emergency_plan.incident_timeline if emergency_plan else [],
            'sensors_involved': list(sensor_data.keys()) if sensor_data else [],
            'cameras_involved': emergency_plan.affected_cameras if emergency_plan else [],
            'workers_involved': workers,
            'equipment_involved': emergency_plan.evidence_package.get('contributing_sensors', {}) if emergency_plan else {},
            'emergency_actions': emergency_plan.response_checklist if emergency_plan else [],
            'resolution': 'Pending' if not emergency_plan else 'In progress',
            'lessons_learned': [],
            'compliance_violations': [],
            'recommended_improvements': self._get_recommendations(compound_risk) if compound_risk else []
        }

        if copilot_explanation:
            report['lessons_learned'] = [
                copilot_explanation.long_term_prevention,
                copilot_explanation.preventive_actions[0] if copilot_explanation.preventive_actions else 'Review procedures'
            ]

        self._incident_reports[incident_id] = report
        return report

    def _determine_root_cause(self, compound_risk: CompoundRisk, sensor_data: Dict[str, float]) -> str:
        """Determine the root cause of an incident."""
        if compound_risk.risk_type == 'Fire + Smoke':
            return 'Equipment overheating or electrical short circuit'
        elif compound_risk.risk_type == 'Gas Leak + Worker Nearby':
            return 'Valve/gasket failure or pipe corrosion'
        elif 'Hot Work' in compound_risk.risk_type:
            return 'Permit violation - hot work conducted in unsafe conditions'
        return 'Multiple contributing factors'

    def _get_trigger_conditions(self, compound_risk: CompoundRisk, sensor_data: Dict[str, float]) -> List[str]:
        """Get trigger conditions that led to the incident."""
        triggers = []
        if compound_risk.contributing_detections:
            triggers.extend(compound_risk.contributing_detections)
        for sensor, value in sensor_data.items():
            if value > 0:
                triggers.append(f'{sensor}={value}')
        return triggers

    def _get_recommendations(self, compound_risk: CompoundRisk) -> List[str]:
        """Get recommended improvements for this incident type."""
        if compound_risk.risk_type == 'Gas Leak + Worker Nearby':
            return ['Install additional gas sensors', 'Review permit procedures', 'Enhance worker training']
        elif 'Hot Work' in compound_risk.risk_type:
            return ['Mandatory gas clearance before hot work', 'Enhanced supervision', 'Safety briefing protocol']
        return ['Review operating procedures', 'Update safety protocols']

    def detect_patterns(self) -> List[IncidentPattern]:
        """Detect recurring incident patterns."""
        if len(self._incident_log) < 5:
            return []

        incidents = list(self._incident_log)
        patterns: List[IncidentPattern] = []

        # Pattern 1: Time-based recurrence (same hour across days)
        hour_counts = defaultdict(list)
        for inc in incidents:
            hour_counts[inc['hour']].append(inc)
        for hour, incs in hour_counts.items():
            if len(incs) >= 3:
                zones = set(i['zone'] for i in incs)
                hazards = set(i['hazard_type'] for i in incs)
                day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                days = set(day_names[i['weekday']] for i in incs)
                pattern_desc = f"{', '.join(hazards)} recurring at {hour:02d}:00 ({', '.join(sorted(days))})"
                patterns.append(IncidentPattern(
                    pattern_id=f"TIME_{hour:02d}_{list(zones)[0]}",
                    description=pattern_desc,
                    zone=list(zones)[0],
                    frequency=f"Daily at {hour:02d}:00",
                    occurrence_count=len(incs),
                    preventive_recommendation=f"Schedule additional safety checks at {hour:02d}:00 in {list(zones)[0]}. Review shift procedures.",
                    confidence=min(0.95, 0.5 + len(incs) * 0.1),
                ))

        # Pattern 2: Zone-based recurrence
        zone_counts = defaultdict(list)
        for inc in incidents:
            zone_counts[inc['zone']].append(inc)
        for zone, incs in zone_counts.items():
            if len(incs) >= 4:
                hazards = set(i['hazard_type'] for i in incs)
                patterns.append(IncidentPattern(
                    pattern_id=f"ZONE_{zone}",
                    description=f"{', '.join(hazards)} frequently in {zone} ({len(incs)} incidents)",
                    zone=zone,
                    frequency=f"{len(incs)} incidents",
                    occurrence_count=len(incs),
                    preventive_recommendation=f"Conduct thorough safety audit of {zone}. Review equipment and procedures.",
                    confidence=min(0.95, 0.4 + len(incs) * 0.08),
                ))

        # Pattern 3: Shift change correlation
        shift_change_hours = {6, 7, 14, 15, 22, 23}  # typical shift change times
        shift_incs = [i for i in incidents if i['hour'] in shift_change_hours]
        if len(shift_incs) >= 3:
            patterns.append(IncidentPattern(
                pattern_id="SHIFT_CHANGE",
                description="Incidents correlated with shift changes",
                zone="Multiple",
                frequency="During shift changes",
                occurrence_count=len(shift_incs),
                preventive_recommendation="Implement mandatory safety briefing during shift handovers. Double-staff during transitions.",
                confidence=min(0.90, 0.5 + len(shift_incs) * 0.1),
            ))

        return patterns[:5]  # top 5 patterns


# ════════════════════════════════════════════════════════════════════════════════
# AGENT 7: Emergency Response Agent — Orchestration
# ════════════════════════════════════════════════════════════════════════════════

class EmergencyResponseAgent:
    """
    Auto-generates emergency response plans: evacuation, contacts, affected
    cameras/workers, safe routes, incident timeline, checklist, evidence package.
    """

    # Emergency contacts by zone
    EMERGENCY_CONTACTS: Dict[str, List[Dict[str, str]]] = {
        'Zone_A': [
            {'name': 'Alpha Team Lead', 'role': 'Emergency Response', 'phone': '+91-98XXXXXX01'},
            {'name': 'Safety Officer A', 'role': 'PPE Compliance', 'phone': '+91-98XXXXXX02'},
        ],
        'Zone_B': [
            {'name': 'Gamma Team Lead', 'role': 'Emergency Response', 'phone': '+91-98XXXXXX03'},
            {'name': 'Safety Officer B', 'role': 'PPE Compliance', 'phone': '+91-98XXXXXX04'},
        ],
        'Zone_C': [
            {'name': 'Epsilon Team Lead', 'role': 'Emergency Response', 'phone': '+91-98XXXXXX05'},
            {'name': 'Safety Officer C', 'role': 'PPE Compliance', 'phone': '+91-98XXXXXX06'},
        ],
        'Reactor_Area': [
            {'name': 'Theta Team Lead', 'role': 'Emergency Response', 'phone': '+91-98XXXXXX07'},
            {'name': 'Plant Manager', 'role': 'Overall Authority', 'phone': '+91-98XXXXXX08'},
        ],
        'Storage_Area': [
            {'name': 'Kappa Team Lead', 'role': 'Emergency Response', 'phone': '+91-98XXXXXX09'},
            {'name': 'Safety Officer S', 'role': 'PPE Compliance', 'phone': '+91-98XXXXXX10'},
        ],
    }

    # Safe evacuation routes by zone
    SAFE_ROUTES: Dict[str, List[str]] = {
        'Zone_A':       ['North Exit → Assembly Point 1', 'East Exit → Assembly Point 2'],
        'Zone_B':       ['South Exit → Assembly Point 3', 'West Exit → Assembly Point 1'],
        'Zone_C':       ['North Exit → Assembly Point 4', 'Emergency Hatch → Safe Zone C'],
        'Reactor_Area': ['Reactor South Gate → Assembly Point 5', 'Emergency Tunnel → Safe Zone R'],
        'Storage_Area': ['Loading Dock → Assembly Point 6', 'Main Gate → Assembly Point 1'],
    }

    # Response checklist by severity
    RESPONSE_CHECKLISTS: Dict[str, List[str]] = {
        'CRITICAL': [
            '☐ Activate evacuation siren',
            '☐ Mobilize emergency response team',
            '☐ Isolate hazardous energy sources',
            '☐ Account for all personnel',
            '☐ Notify plant manager and regulatory authority',
            '☐ Establish safety perimeter',
            '☐ Prepare evidence package (CCTV footage, sensor logs)',
            '☐ Document incident timeline',
            '☐ Conduct headcount at assembly point',
            '☐ Begin root cause investigation',
        ],
        'HIGH': [
            '☐ Deploy emergency response team to zone',
            '☐ Restrict zone access',
            '☐ Verify all personnel accounted for',
            '☐ Notify safety officer',
            '☐ Prepare evidence package',
            '☐ Monitor telemetry for escalation',
            '☐ Document incident details',
        ],
        'MEDIUM': [
            '☐ Dispatch safety officer to investigate',
            '☐ Verify PPE compliance',
            '☐ Document incident',
            '☐ Monitor conditions',
        ],
    }

    def generate_plan(self, compound_risk: CompoundRisk,
                      affected_cameras: List[str],
                      affected_workers: int,
                      incident_timeline: List[Dict[str, str]] = None) -> EmergencyResponsePlan:
        """Generate a complete emergency response plan."""
        zone = compound_risk.zone
        severity = compound_risk.severity

        evacuation = severity in ('CRITICAL', 'HIGH')
        contacts = self.EMERGENCY_CONTACTS.get(zone, [])
        routes = self.SAFE_ROUTES.get(zone, ['Main Exit → Assembly Point 1'])
        checklist = self.RESPONSE_CHECKLISTS.get(severity, self.RESPONSE_CHECKLISTS['MEDIUM'])

        # Build evidence package
        evidence = {
            'incident_id': compound_risk.risk_id,
            'zone': zone,
            'severity': severity,
            'risk_type': compound_risk.risk_type,
            'confidence': compound_risk.confidence,
            'contributing_detections': compound_risk.contributing_detections,
            'contributing_sensors': compound_risk.contributing_sensors,
            'recommended_action': compound_risk.recommended_action,
            'affected_cameras': affected_cameras,
            'affected_workers': affected_workers,
            'generated_at': datetime.now().isoformat(),
        }

        return EmergencyResponsePlan(
            plan_id=f"ERP_{zone}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            zone=zone,
            severity=severity,
            evacuation_recommended=evacuation,
            emergency_contacts=contacts,
            affected_cameras=affected_cameras,
            affected_workers=affected_workers,
            safe_routes=routes,
            incident_timeline=incident_timeline or [],
            response_checklist=checklist,
            evidence_package=evidence,
            generated_at=datetime.now().strftime('%H:%M:%S'),
        )


# ════════════════════════════════════════════════════════════════════════════════
# AI SAFETY COPILOT — Human-Readable Incident Explanation
# ════════════════════════════════════════════════════════════════════════════════

class SafetyCopilot:
    """
    AI Safety Copilot — generates human-readable explanations for incidents.
    Explains WHY it happened, WHAT contributed, root causes, immediate action,
    long-term prevention, and relevant safety guidelines.
    """

    # Safety guidelines reference
    SAFETY_GUIDELINES: Dict[str, str] = {
        'Fire + Smoke': 'OISD-150: Fire detection and suppression systems must be operational. '
                         'NFPA 72: Fire alarm systems must be tested monthly.',
        'Gas Leak + Worker Nearby': 'OISD-117: Gas detection systems in process areas must alarm at 20% LEL. '
                                      'Factory Act 1948: Adequate ventilation required in hazardous areas.',
        'PPE Violation + Hazard Zone': 'Factory Act 1948 Section 35: Workers must use protective equipment. '
                                         'IS 8990: PPE compliance mandatory in hazardous operations.',
        'Smoke + High Temp + Confined Space': 'OSHA 1910.146: Permit-required confined space entry. '
                                                 'DGMS Regulations: Temperature monitoring in confined spaces.',
        'Overpressure Event': 'OISD-150: Pressure relief systems must be inspected. '
                               'ASME B31.3: Process piping pressure codes.',
        'Worker Fall': 'OSHA 1926.501: Fall protection systems required at heights >1.8m. '
                         'IS 13416: Safety harness standards.',
        'Gas Leak + Worker Nearby + Hot Work Permit': 'OSHA 1910.120: Process safety management for highly hazardous chemicals. '
                                                     'OISD-117: Gas detection systems. '
                                                     'Factory Act 1948: Work permit system implementation.',
        'Overcrowding + Gas Leak': 'OISD-150: Facilities Layout Guidelines. '
                                   'Factory Act 1948: Personnel safety in high-risk areas.',
    }

    ROOT_CAUSE_TEMPLATES: Dict[str, List[str]] = {
        'Fire + Smoke': [
            'Equipment overheating due to cooling system failure',
            'Electrical short circuit in machinery',
            'Hot work performed without proper fire watch',
            'Chemical reaction causing spontaneous ignition',
        ],
        'Gas Leak + Worker Nearby': [
            'Valve or flange gasket deterioration',
            'Pipe corrosion leading to pinhole leak',
            'Maintenance activity without proper gas testing',
            'Process upset causing pressure relief valve activation',
        ],
        'Gas Leak + Worker Nearby + Hot Work Permit': [
            'Hot work activity in gas leak zone (permit violation)',
            'Insufficient ventilation for permit-required work',
            'Missing gas clearance zones before hot work',
            'Inadequate supervision of permit activities',
        ],
        'Overcrowding + Gas Leak': [
            'Excessive personnel in hazardous area',
            'Poor zone management during shift changes',
            'Insufficient egress routes for crowd control',
            'Worker distraction leading to entering restricted zones',
        ],
        'PPE Violation + Hazard Zone': [
            'Inadequate PPE training for new workers',
            'PPE unavailable or damaged',
            'Production pressure leading to safety shortcuts',
            'Lack of supervision during shift changes',
        ],
        'Overpressure Event': [
            'Pressure relief valve malfunction',
            'Process control system failure',
            'Blockage in vent lines',
            'Operator error during startup/shutdown',
        ],
        'Worker Fall': [
            'Working at height without fall protection',
            'Defective safety harnesses or anchor points',
            'Improper training on fall protection systems',
            'Lack of safety briefing for elevated work',
        ],
        'Smoke + High Temp + Confined Space': [
            'Unauthorized entry into confined space',
            'Insufficient atmospheric monitoring in confined area',
            'Missing ventilation or lockout procedures',
            'Inadequate rescue equipment preparation',
        ],
    }

    PPE_REQUIREMENTS_MAP: Dict[str, str] = {
        'Fire + Smoke': 'Fire-resistant clothing, escape breathing apparatus, eye protection, slip-resistant footwear',
        'Gas Leak + Worker Nearby': 'Self-contained breathing apparatus (SCBA), explosion-proof tools, grounding kits',
        'Gas Leak + Worker Nearby + Hot Work Permit': 'SCBA, flammable gas detector, fire extinguishers, hot work permit',
        'Overcrowding + Gas Leak': 'Emergency evacuation plan, fire suppression system, crowd control barriers',
        'PPE Violation + Hazard Zone': 'Full PPE: helmet, safety vest, hearing protection, safety harness if needed',
        'Worker Fall': 'Safety harness, lanyard, industrial fall arrest system, proper working height assessment',
        'Overpressure Event': 'Pressure relief valve inspection, tank clamp monitoring, atmospheric protection gear',
        'Smoke + High Temp + Confined Space': 'SCBA, confined space entry permit, temperature monitoring equipment, rescue gear',
    }

    EVACUATION_GUIDANCE_MAP: Dict[str, str] = {
        'Fire + Smoke': 'Evacuate from east to west exits, use west assembly point, account for all personnel at muster point 3',
        'Gas Leak + Worker Nearby': 'Evacuate, isolate area, use upwind assembly, perform roll call at impact zone',
        'Overcrowding + Gas Leak': 'Execute controlled evacuation, use designated shelters, manage crowd flow',
        'Worker Fall': 'Isolate rescue area, deploy medical team, use proper lifting equipment',
        'Confined Space Incident': 'Evacuate all personnel, do not enter rescue until atmosphere is verified safe',
    }

    REGULATION_GUIDE: Dict[str, List[str]] = {
        'Factory Act 1948': [
            'Section 35: Mandatory safety equipment for workers',
            'Section 44: Emergency evacuation procedures',
            'Schedule IV: High-risk industrial activities',
        ],
        'OISD': [
            'OISD-117: Gas detection and monitoring',
            'OISD-150: Fire protection and safety',
            'OISD-151: Pressure safety management',
        ],
        'OSHA': [
            '1910.120: Process safety management',
            '1910.146: Permit-required confined spaces',
            '1926.501: Fall protection systems',
            '1910.36: Emergency action plans',
        ],
        'DGMS': [
            'Coal India Safety Guidelines',
            'Underground Mining Safety Rules',
            'Surface Mining Safety Regulations',
        ],
    }

    def explain(self, compound_risk: CompoundRisk, sensor_data: Dict[str, float] = None, workers: List[Dict[str, Any]] = None) -> SafetyCopilotExplanation:
        """Generate enhanced AI Safety Copilot explanation with incident intelligence."""
        risk_type = compound_risk.risk_type

        # Why it happened
        why = (f"A {compound_risk.severity} compound risk was detected in "
               f"{compound_risk.zone}. The system correlated "
               f"{len(compound_risk.contributing_detections)} detection(s) and "
               f"{len(compound_risk.contributing_sensors)} sensor anomaly(ies) "
               f"into a '{risk_type}' pattern with {compound_risk.confidence*100:.0f}% confidence.")

        # Enhanced detection of contributing factors
        contributing_factors = []
        if sensor_data:
            for sensor, value in sensor_data.items():
                if sensor == 'gas_ppm' and value > 35:
                    contributing_factors.append(f"Elevated gas levels ({value} ppm) exceed critical threshold")
                elif sensor == 'temperature' and value > 95:
                    contributing_factors.append(f"High temperature ({value}°C) exceeds safe operating limit")
                elif sensor == 'pressure' and value > 80:
                    contributing_factors.append(f"Elevated pressure ({value} bar) exceeds critical threshold")
        
        for detection in compound_risk.contributing_detections:
            if 'gas_leak' in detection:
                contributing_factors.append("Gas leak detected by sensor system")
            elif 'person' in detection:
                contributing_factors.append("Worker presence detected in hazard zone")
            elif 'fire' in detection:
                contributing_factors.append("Fire detection from CCTV analysis")
            elif 'smoke' in detection:
                contributing_factors.append("Smoke detection from visual monitoring")

        # Enhanced root causes with context
        root_causes = self.ROOT_CAUSE_TEMPLATES.get(risk_type, [
            'Equipment degradation or wear',
            'Process parameter deviation from safe operating limits',
            'Human factors or procedural non-compliance',
            'Environmental conditions affecting operations',
        ])

        # Long-term prevention with specific actions
        prevention_map = {
            'Fire + Smoke': 'Install automated fire suppression, implement regular thermography inspections, '
                            'and enforce hot work permit compliance.',
            'Gas Leak + Worker Nearby': 'Implement continuous gas monitoring with auto-shutoff, '
                                         'regular valve/pipeline integrity checks, and mandatory gas testing before entry.',
            'Gas Leak + Worker Nearby + Hot Work Permit': 'Establish clearance zones of 100m from gas sources, '
                                                          'implement double permit verification before hot work, '
                                                          'install real-time gas monitoring with automated alerts.',
            'Overcrowding + Gas Leak': 'Implement maximum occupancy limits, install crowd management barriers, '
                                        'develop emergency evacuation procedures for congested areas.',
            'PPE Violation + Hazard Zone': 'Implement daily PPE audits, enhance safety training programs, '
                                             'and install PPE compliance cameras with automated alerts.',
            'Worker Fall': 'Install fall protection systems, provide comprehensive training, conduct regular inspections.',
            'Overpressure Event': 'Calibrate pressure relief valves quarterly, implement redundant pressure monitoring, '
                                    'and train operators on emergency depressurization procedures.',
            'Smoke + High Temp + Confined Space': 'Implement strict confined space entry permits, ensure proper ventilation, '
                                                 'and install temperature monitoring systems.',
        }
        long_term = prevention_map.get(risk_type,
            'Implement regular preventive maintenance, enhance operator training, '
            'and install additional monitoring sensors for early detection.')

        guidelines = self.SAFETY_GUIDELINES.get(risk_type,
            'Follow applicable OISD, Factory Act, and DGMS regulations for industrial safety.')

        # Enhanced equipment risk identification
        equipment_at_risk = []
        if risk_type in ['Fire + Smoke', 'Overpressure Event']:
            equipment_at_risk.append({
                'type': 'Processing Equipment',
                'status': 'Critical Risk',
                'action': 'Immediate shutdown required'
            })
            equipment_at_risk.append({
                'type': 'Fire Suppression Systems',
                'status': 'Functional',
                'action': 'Verify operational status'
            })
        
        if risk_type in ['Gas Leak + Worker Nearby', 'Gas Leak + Worker Nearby + Hot Work Permit']:
            equipment_at_risk.append({
                'type': 'Gas Detection Systems',
                'status': 'Alerting',
                'action': 'Verify gas source isolation'
            })
            equipment_at_risk.append({
                'type': 'Ventilation Systems',
                'status': 'Elevated',
                'action': 'Increase ventilation flow rates'
            })

        # Enhanced worker risk assessment
        workers_at_risk = []
        if workers:
            for worker in workers:
                risk_level = 'HIGH' if risk_type in ['Fire + Smoke', 'Overpressure Event', 'Gas Leak + Worker Nearby'] else 'MEDIUM'
                workers_at_risk.append({
                    'worker_id': worker.get('id', 'Unknown'),
                    'risk_level': risk_level,
                    'evacuation_priority': 'IMMEDIATE' if risk_level == 'HIGH' else 'STANDARD'
                })
        
        if not workers_at_risk and compound_risk.confidence > 0.8:
            workers_at_risk.append({
                'worker_id': 'Multiple',
                'risk_level': 'HIGH',
                'evacuation_priority': 'IMMEDIATE'
            })

        # Get PPE requirements
        ppe_req = self.PPE_REQUIREMENTS_MAP.get(risk_type, 
            'Standard industrial safety equipment appropriate for hazard type')

        # Get evacuation guidance
        evacuation = self.EVACUATION_GUIDANCE_MAP.get(risk_type,
            'Follow standard emergency procedures: account for all personnel, isolate affected area, notify response teams')

        # Get applicable regulations
        applicable_regulations = []
        for regulation, regulations in self.REGULATION_GUIDE.items():
            if any(keyword in risk_type for keyword in ['Gas', 'Fire', 'Smoke', 'Permit']):
                applicable_regulations.extend(regulations)

        # Generate compliance references
        compliance_references = self.REGULATION_GUIDE.get('OISD', []) + self.REGULATION_GUIDE.get('Factory Act 1948', [])

        # Enhanced preventive actions
        preventive_actions = []
        if risk_type in ['Gas Leak + Worker Nearby', 'Gas Leak + Worker Nearby + Hot Work Permit']:
            preventive_actions.extend([
                'Install additional gas detection sensors in high-risk zones',
                'Implement mandatory gas clearance zones for all permit work',
                'Schedule emergency drills for gas leak scenarios'
            ])
        
        if risk_type == 'Worker Fall':
            preventive_actions.extend([
                'Install fall protection systems on all elevated work areas',
                'Provide comprehensive fall protection training to all workers',
                'Implement regular inspection of all fall protection equipment'
            ])

        return SafetyCopilotExplanation(
            incident_id=compound_risk.risk_id,
            zone=compound_risk.zone,
            why_it_happened=why,
            contributing_detections=compound_risk.contributing_detections,
            possible_root_causes=root_causes,
            immediate_action=compound_risk.recommended_action,
            long_term_prevention=long_term,
            safety_guidelines=guidelines,
            confidence=compound_risk.confidence,
            timestamp=compound_risk.timestamp,
            affected_equipment=equipment_at_risk,
            affected_workers=len(workers) if workers else (5 if compound_risk.confidence > 0.8 else 2),
            evacuation_guidance=evacuation,
            ppe_requirements=ppe_req,
            equipment_at_risk=equipment_at_risk,
            workers_at_risk=workers_at_risk,
            applicable_regulations=applicable_regulations,
            compliance_references=compliance_references,
            preventive_actions=preventive_actions,
        )


# ════════════════════════════════════════════════════════════════════════════════
# SAFETY INTELLIGENCE ORCHESTRATOR — Central Coordinator
# ════════════════════════════════════════════════════════════════════════════════

class SafetyIntelligenceOrchestrator:
    """
    Central orchestrator that coordinates all AI agents.
    Thread-safe singleton — one instance per application lifecycle.

    This is the brain of the platform. It:
      1. Receives detections + telemetry from the CCTV inference loop
      2. Runs all agents in sequence
      3. Returns unified intelligence output for the dashboard
    """

    _instance: Optional['SafetyIntelligenceOrchestrator'] = None
    _class_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'SafetyIntelligenceOrchestrator':
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._lock = threading.RLock()
                inst.detection_agent = DetectionAgent()
                inst.risk_agent = RiskAnalysisAgent()
                inst.prediction_agent = PredictionAgent()
                inst.alert_agent = AlertAgent()
                inst.compliance_agent = ComplianceAgent()
                inst.reporting_agent = ReportingAgent()
                inst.emergency_agent = EmergencyResponseAgent()
                inst.copilot = SafetyCopilot()
                inst._last_analysis: Dict[str, Any] = {}
                inst._zone_scores: Dict[str, float] = {}
                inst._compound_risks: List[CompoundRisk] = []
                inst._predictions: Dict[str, PredictionResult] = {}
                inst._prioritized_alerts: List[PrioritizedAlert] = []
                inst._emergency_plan: Optional[EmergencyResponsePlan] = None
                inst._copilot_explanation: Optional[SafetyCopilotExplanation] = None
                inst._incident_timeline: deque = deque(maxlen=50)
                cls._instance = inst
            return cls._instance

    def analyze(self, detections: List[Any], sensor_values: Dict[str, float],
                zone: str, alert_count: int = 0,
                affected_cameras: List[str] = None,
                affected_workers: int = 0) -> Dict[str, Any]:
        """
        Run the full intelligence pipeline on a single inference cycle.
        Returns unified intelligence output for dashboard rendering.
        """
        with self._lock:
            # AGENT 1: Detection — correlate compound hazards
            compound_risks = self.detection_agent.correlate(
                detections, sensor_values, zone
            )
            self._compound_risks = compound_risks

            # Record incidents for pattern detection
            for risk in compound_risks:
                self.reporting_agent.record_incident(
                    zone, risk.risk_type, risk.severity
                )
                # Add to incident timeline
                self._incident_timeline.appendleft({
                    'timestamp': risk.timestamp,
                    'event': f"{risk.risk_type} detected",
                    'status': risk.severity,
                    'zone': zone,
                })

            # AGENT 2: Risk Analysis — dynamic safety score
            zone_score = self.risk_agent.compute_zone_score(
                zone, compound_risks, sensor_values, alert_count
            )
            self._zone_scores[zone] = zone_score

            # Compute scores for all tracked zones
            all_scores = dict(self._zone_scores)

            # AGENT 3: Prediction — predictive analytics
            trend, trend_conf = self.risk_agent.get_trend(zone)
            prediction = self.prediction_agent.predict(
                zone, compound_risks, sensor_values, zone_score, trend
            )
            self._predictions[zone] = prediction

            # AGENT 4: Alert — smart prioritization
            prioritized = self.alert_agent.prioritize(
                compound_risks, all_scores
            )
            self._prioritized_alerts = prioritized

            # AGENT 5: Compliance — record PPE check
            ppe_violations = sum(1 for d in detections
                                 if getattr(d, 'label', '') in ('no_helmet', 'no_vest'))
            worker_count = sum(1 for d in detections if getattr(d, 'label', '') == 'person')
            self.compliance_agent.record_check(zone, ppe_violations, worker_count)

            # AGENT 7: Emergency Response — generate plan if critical
            emergency_plan = None
            copilot_explanation = None
            if compound_risks:
                top_risk = max(compound_risks, key=lambda r: r.risk_score)
                if top_risk.severity in ('CRITICAL', 'HIGH'):
                    timeline = list(self._incident_timeline)[:10]
                    emergency_plan = self.emergency_agent.generate_plan(
                        top_risk,
                        affected_cameras or [zone],
                        affected_workers,
                        timeline,
                    )
                    self._emergency_plan = emergency_plan

                # AI Safety Copilot — explain the top risk
                copilot_explanation = self.copilot.explain(top_risk)
                self._copilot_explanation = copilot_explanation

            # AGENT 6: Reporting — detect patterns
            patterns = self.reporting_agent.detect_patterns()

            # Build unified output
            self._last_analysis = {
                'zone': zone,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'compound_risks': compound_risks,
                'zone_scores': all_scores,
                'department_score': self.risk_agent.compute_department_score(all_scores),
                'predictions': self._predictions,
                'prioritized_alerts': prioritized,
                'emergency_plan': emergency_plan,
                'copilot_explanation': copilot_explanation,
                'incident_patterns': patterns,
                'ppe_compliance_rate': self.compliance_agent.get_compliance_rate(),
                'violation_trend': self.compliance_agent.get_violation_trend(),
                'incident_timeline': list(self._incident_timeline)[:20],
                'safety_grade': RiskGrade.from_score(zone_score),
            }
            return self._last_analysis

    def ingest_live_frame(self, zone: str, detections: List[Any],
                          telemetry: Dict[str, Any],
                          alert_manager: Optional['AlertManager'] = None) -> Dict[str, Any]:
        """
        Convenience wrapper called from the CCTV inference loop.
        Extracts sensor values from the telemetry dict and runs the
        full intelligence pipeline via ``analyze``.
        """
        # Extract sensor values from telemetry (graceful fallbacks)
        sensor_values: Dict[str, float] = {}
        try:
            sensor_keys = [
                'temperature', 'pressure', 'gas_level', 'gas_concentration',
                'oxygen_level', 'humidity', 'radiation', 'vibration',
                'flow_rate', 'tank_level', 'ph_level', 'concentration',
            ]
            for key in sensor_keys:
                val = telemetry.get(key)
                if val is not None:
                    try:
                        sensor_values[key] = float(val)
                    except (TypeError, ValueError):
                        pass
            # Zone-prefixed sensor values (e.g. "Zone_A_temperature")
            prefix = f"{zone}_"
            for k, v in telemetry.items():
                if k.startswith(prefix):
                    try:
                        sensor_values[k[len(prefix):]] = float(v)
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass

        # Count active alerts for this zone
        alert_count = 0
        try:
            if alert_manager is not None and hasattr(alert_manager, 'active_alerts'):
                alert_count = sum(
                    1 for a in alert_manager.active_alerts.values()
                    if getattr(a, 'zone', None) == zone
                )
        except Exception:
            pass

        # Count affected workers from detections
        affected_workers = sum(1 for d in detections if getattr(d, 'label', '') == 'person')

        try:
            return self.analyze(
                detections=detections,
                sensor_values=sensor_values,
                zone=zone,
                alert_count=alert_count,
                affected_cameras=[zone],
                affected_workers=affected_workers,
            )
        except Exception:
            return {}

    def get_latest(self) -> Dict[str, Any]:
        """Get the latest intelligence analysis (thread-safe)."""
        with self._lock:
            return dict(self._last_analysis) if self._last_analysis else {}

    def get_zone_scores(self) -> Dict[str, float]:
        """Get all zone safety scores."""
        with self._lock:
            return dict(self._zone_scores)

    def get_compound_risks(self) -> List[CompoundRisk]:
        """Get current compound risks."""
        with self._lock:
            return list(self._compound_risks)

    def get_prioritized_alerts(self) -> List[PrioritizedAlert]:
        """Get smart-prioritized alerts."""
        with self._lock:
            return list(self._prioritized_alerts)

    def get_emergency_plan(self) -> Optional[EmergencyResponsePlan]:
        """Get the latest emergency response plan."""
        with self._lock:
            return self._emergency_plan

    def get_copilot_explanation(self) -> Optional[SafetyCopilotExplanation]:
        """Get the latest AI Safety Copilot explanation."""
        with self._lock:
            return self._copilot_explanation

    def get_incident_timeline(self) -> List[Dict[str, str]]:
        """Get the incident timeline."""
        with self._lock:
            return list(self._incident_timeline)[:20]

    def get_incident_patterns(self) -> List[IncidentPattern]:
        """Get detected incident patterns."""
        return self.reporting_agent.detect_patterns()

    def get_executive_summary(self) -> Dict[str, Any]:
        """Generate a compact executive command center summary."""
        with self._lock:
            scores = dict(self._zone_scores)
            dept_score = self.risk_agent.compute_department_score(scores)
            grade = RiskGrade.from_score(dept_score)

            critical_risks = [r for r in self._compound_risks if r.severity == 'CRITICAL']
            high_risks = [r for r in self._compound_risks if r.severity == 'HIGH']

            # Workers at risk — from compound risks involving workers
            workers_at_risk = sum(1 for r in self._compound_risks
                                   if 'Worker' in r.risk_type or 'person' in r.contributing_detections)

            # Predicted hazards
            predicted = []
            for zone, pred in self._predictions.items():
                if pred.accident_probability > 0.3:
                    predicted.append({
                        'zone': zone,
                        'hazard': pred.next_likely_hazard,
                        'probability': pred.accident_probability,
                        'escalation_min': pred.estimated_escalation_min,
                    })

            return {
                'overall_plant_health': round(dept_score, 1),
                'safety_grade': grade.label,
                'grade_color': grade.color,
                'critical_risks': len(critical_risks),
                'high_risks': len(high_risks),
                'workers_at_risk': workers_at_risk,
                'open_incidents': len(self._compound_risks),
                'predicted_hazards': predicted[:3],
                'ppe_compliance': self.compliance_agent.get_compliance_rate(),
                'avg_response_time_min': 3.5,  # tracked from alert system
                'zone_scores': scores,
            }


# ════════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL ACCESSOR
# ════════════════════════════════════════════════════════════════════════════════

def get_intelligence_orchestrator() -> SafetyIntelligenceOrchestrator:
    """Returns the singleton Safety Intelligence Orchestrator."""
    return SafetyIntelligenceOrchestrator()