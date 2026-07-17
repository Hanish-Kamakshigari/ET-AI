"""
SurakshaAI — AI Explainability State Bus
Central singleton that captures AI reasoning data on every inference cycle.
All explainability panels read from this — no DB round-trips needed for live display.
"""

import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from collections import deque


# ─────────────────────────────────────────────────────────────────────────────
# Detection snapshot
# ─────────────────────────────────────────────────────────────────────────────

class DetectionSnapshot:
    """A single AI detection captured at inference time."""

    LABEL_ICONS: Dict[str, str] = {
        'person':        '👷', 'helmet':       '⛑️',  'no_helmet':    '⚠️',
        'vest':          '🦺', 'no_vest':      '⚠️',  'gas_leak':     '💨',
        'gas_alarm':     '🚨', 'fire':         '🔥',  'smoke':        '💨',
        'welding_fume':  '🌫️', 'sparks':       '✨',  'warning_light':'🔦',
        'chemical_haze': '🌫️', 'overpressure': '💥', 'worker_fall':  '🆘',
        'intrusion':     '🚷',
    }
    HAZARD_LABELS: frozenset[str] = frozenset([
        'gas_leak','gas_alarm','fire','smoke','overpressure','worker_fall',
        'chemical_haze','welding_fume','no_helmet','no_vest','intrusion','warning_light',
    ])

    def __init__(self, label: str, confidence: float, zone: str) -> None:
        self.label = label
        self.confidence = confidence
        self.zone = zone
        self.timestamp = datetime.now().strftime('%H:%M:%S')

    @property
    def icon(self) -> str:
        return self.LABEL_ICONS.get(self.label, '🔍')

    @property
    def display_name(self) -> str:
        return self.label.replace('_', ' ').title()

    @property
    def conf_pct(self) -> str:
        return f"{int(self.confidence * 100)}%"

    def is_hazard(self) -> bool:
        return self.label in self.HAZARD_LABELS


# ─────────────────────────────────────────────────────────────────────────────
# Rule Evaluation Result
# ─────────────────────────────────────────────────────────────────────────────

class RuleEvalResult:
    """Stores the evaluation result of a single safety rule."""

    def __init__(
        self,
        rule_id: str,
        rule_name: str,
        passed: bool,
        conditions: List[Dict[str, Any]],
        severity: str = 'LOW',
        score: float = 0.0,
    ) -> None:
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.passed = passed
        self.conditions = conditions  # List[dict]: label, passed, actual, threshold
        self.severity = severity
        self.score = score
        self.timestamp = datetime.now().strftime('%H:%M:%S')


# ─────────────────────────────────────────────────────────────────────────────
# AI Frame State
# ─────────────────────────────────────────────────────────────────────────────

class AIFrameState:
    """Snapshot of one complete inference cycle."""

    def __init__(self) -> None:
        self.frame_number: int = 0
        self.zone: str = ''
        self.model_name: str = 'YOLOv11'
        self.inference_ms: float = 0.0
        self.fps: float = 0.0
        self.detections: List[DetectionSnapshot] = []
        self.sensor_values: Dict[str, Any] = {}
        self.permit_active: bool = False
        self.permit_zone: str = ''
        self.rule_results: List[RuleEvalResult] = []
        self.matched_rules: List[RuleEvalResult] = []
        self.risk_level: str = 'LOW'
        self.risk_score: int = 0
        self.risk_color: str = '#22c55e'
        self.recommendation: str = 'Continue standard plant surveillance.'
        self.notification_channels: List[str] = []
        self.alert_generated: bool = False
        self.alert_id: Optional[str] = None
        self.timestamp: str = ''
        self.total_rules_evaluated: int = 0
        self.total_alerts_active: int = 0

    @property
    def object_count(self) -> int:
        return len(self.detections)

    @property
    def worker_count(self) -> int:
        return sum(1 for d in self.detections if d.label == 'person')

    @property
    def hazard_count(self) -> int:
        return sum(1 for d in self.detections if d.is_hazard())

    def gas_ppm(self) -> float:
        return float(self.sensor_values.get('gas_ppm', 0.0))

    def temperature_c(self) -> float:
        return float(self.sensor_values.get('temperature', 0.0))

    def pressure_bar(self) -> float:
        return float(self.sensor_values.get('pressure', 0.0))


# ─────────────────────────────────────────────────────────────────────────────
# Detection History Entry
# ─────────────────────────────────────────────────────────────────────────────

class DetectionHistoryEntry:
    EVENT_COLORS: Dict[str, str] = {
        'frame':        '#475569', 'detection':    '#3b82f6',
        'hazard':       '#ef4444', 'sensor':       '#f97316',
        'rule_match':   '#8b5cf6', 'alert':        '#ef4444',
        'notification': '#22c55e',
    }

    def __init__(
        self,
        event_type: str,
        label: str,
        detail: str,
        zone: str,
        confidence: float = 0.0,
    ) -> None:
        self.timestamp = datetime.now().strftime('%H:%M:%S')
        self.event_type = event_type
        self.label = label
        self.confidence = confidence
        self.detail = detail
        self.zone = zone
        self.color = self.EVENT_COLORS.get(event_type, '#64748b')


# ─────────────────────────────────────────────────────────────────────────────
# AI Explainability State Bus — Singleton
# ─────────────────────────────────────────────────────────────────────────────

class AIExplainabilityBus:
    """
    Thread-safe singleton that holds the real-time AI reasoning state.
    Written by the CCTV inference loop on every frame.
    Read by every explainability panel.
    """

    _instance: Optional['AIExplainabilityBus'] = None
    _class_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'AIExplainabilityBus':
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._state_lock = threading.RLock()
                inst.current = AIFrameState()
                inst.history: deque = deque(maxlen=30)
                cls._instance = inst
        return cls._instance

    # ── Write ────────────────────────────────────────────────────────────────

    def update_frame(
        self,
        frame_number: int,
        zone: str,
        detections: List[Any],
        sensor_values: Dict[str, Any],
        latest_telemetry: Dict[str, Any],
        inference_ms: float,
        fps: float,
        model_name: str = 'YOLOv11',
        permit_active: bool = False,
        permit_zone: str = '',
    ) -> None:
        """Called once per inference cycle. Captures the full AI reasoning snapshot."""
        with self._state_lock:
            s = AIFrameState()
            s.frame_number = frame_number
            s.zone = zone
            s.model_name = model_name
            s.inference_ms = inference_ms
            s.fps = fps
            s.timestamp = datetime.now().strftime('%H:%M:%S')
            s.permit_active = permit_active
            s.permit_zone = permit_zone

            s.detections = [
                DetectionSnapshot(
                    label=getattr(d, 'label', str(d)),
                    confidence=float(getattr(d, 'confidence', 0.90)),
                    zone=zone
                )
                for d in detections
            ]

            s.sensor_values = {
                'gas_ppm':     float(latest_telemetry.get(f'{zone}_gas_ppm',        sensor_values.get('gas_ppm', 0.0))),
                'temperature': float(latest_telemetry.get(f'{zone}_temperature_c',  sensor_values.get('temperature', 0.0))),
                'pressure':    float(latest_telemetry.get(f'{zone}_pressure_bar',   sensor_values.get('pressure', 0.0))),
            }

            s.rule_results, s.matched_rules = self._evaluate_rules(
                s.detections, s.sensor_values, permit_active, zone
            )
            s.total_rules_evaluated = len(s.rule_results)

            if s.matched_rules:
                top = max(s.matched_rules, key=lambda r: r.score)
                s.risk_level = top.severity
                s.risk_score = min(top.score * 2, 100)
            else:
                s.risk_level = 'LOW'
                s.risk_score = 0

            s.risk_color = {
                'CRITICAL': '#ef4444', 'HIGH': '#f97316',
                'MEDIUM':   '#eab308', 'LOW':  '#22c55e',
            }.get(s.risk_level, '#22c55e')

            s.alert_generated = bool(s.matched_rules)

            try:
                from src.config.ui_constants import ZONE_LABELS
                zone_label = ZONE_LABELS.get(zone, zone)
            except Exception:
                zone_label = zone

            if s.risk_level == 'CRITICAL':
                s.recommendation = f'Evacuate {zone_label} Immediately. Activate Emergency Shutdown.'
            elif s.risk_level == 'HIGH':
                s.recommendation = 'Deploy Emergency Response Team. Restrict Zone Access.'
            elif s.risk_level == 'MEDIUM':
                s.recommendation = 'Verify PPE compliance and inspect telemetry source.'
            else:
                s.recommendation = 'Continue standard plant surveillance.'

            self.current = s
            self._append_history(s)

    def update_notifications(self, channels: List[str], alert_id: Optional[str] = None) -> None:
        with self._state_lock:
            self.current.notification_channels = channels
            if alert_id:
                self.current.alert_id = alert_id
            for ch in channels:
                self.history.appendleft(DetectionHistoryEntry(
                    event_type='notification', label=f'{ch} dispatched',
                    detail=ch.upper(), zone=self.current.zone,
                ))

    def update_alert_count(self, count: int) -> None:
        with self._state_lock:
            self.current.total_alerts_active = count

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_current(self) -> AIFrameState:
        with self._state_lock:
            return self.current

    def get_history(self) -> List[DetectionHistoryEntry]:
        with self._state_lock:
            return list(self.history)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _evaluate_rules(
        self,
        detections: List[Any],
        sensors: Dict[str, Any],
        permit_active: bool,
        zone: str,
    ) -> Tuple[List[RuleEvalResult], List[RuleEvalResult]]:
        gas = sensors.get('gas_ppm', 0.0)
        temp = sensors.get('temperature', 0.0)
        pressure = sensors.get('pressure', 0.0)
        workers = sum(1 for d in detections if d.label == 'person')
        has_gas   = any(d.label == 'gas_leak'    for d in detections)
        has_fire  = any(d.label == 'fire'         for d in detections)
        has_smoke = any(d.label == 'smoke'        for d in detections)
        no_helmet = any(d.label == 'no_helmet'    for d in detections)
        no_vest   = any(d.label == 'no_vest'      for d in detections)
        overpress = any(d.label == 'overpressure' for d in detections)
        has_fall  = any(d.label == 'worker_fall'  for d in detections)

        specs = [
            {'rule_id':'GAS_HOT_WORK','rule_name':'Explosion Risk','severity':'CRITICAL','score':48,
             'predicate': gas>40 and workers>0 and permit_active,
             'conditions':[
                {'label':'Gas > 40 ppm',   'passed':gas>40,        'actual':f'{gas:.1f} ppm',      'threshold':'40 ppm'},
                {'label':'Worker Present',  'passed':workers>0,     'actual':f'{workers} worker(s)','threshold':'>0'},
                {'label':'Hot Work Permit', 'passed':permit_active, 'actual':'Active' if permit_active else 'None','threshold':'Active'},
                {'label':'Hazard Zone',     'passed':True,          'actual':zone,                 'threshold':'Any'},
             ]},
            {'rule_id':'GAS_WORKER_PRESENT','rule_name':'Gas Hazard & Exposure','severity':'HIGH','score':30,
             'predicate': gas>25 and workers>0,
             'conditions':[
                {'label':'Gas > 25 ppm',  'passed':gas>25,    'actual':f'{gas:.1f} ppm',      'threshold':'25 ppm'},
                {'label':'Worker Present','passed':workers>0,  'actual':f'{workers} worker(s)','threshold':'>0'},
             ]},
            {'rule_id':'GAS_CRITICAL','rule_name':'Critical Gas Level','severity':'CRITICAL','score':40,
             'predicate': gas>35,
             'conditions':[{'label':'Gas > 35 ppm','passed':gas>35,'actual':f'{gas:.1f} ppm','threshold':'35 ppm'}]},
            {'rule_id':'GAS_ELEVATED','rule_name':'Elevated Gas Level','severity':'HIGH','score':22,
             'predicate': gas>20,
             'conditions':[{'label':'Gas > 20 ppm','passed':gas>20,'actual':f'{gas:.1f} ppm','threshold':'20 ppm'}]},
            {'rule_id':'FIRE_SMOKE','rule_name':'Fire / Smoke Hazard','severity':'CRITICAL','score':50,
             'predicate': has_fire or has_smoke,
             'conditions':[
                {'label':'Fire Detected', 'passed':has_fire, 'actual':'Detected' if has_fire else 'Clear','threshold':'Detected'},
                {'label':'Smoke Detected','passed':has_smoke,'actual':'Detected' if has_smoke else 'Clear','threshold':'Detected'},
             ]},
            {'rule_id':'TEMP_CRITICAL','rule_name':'Critical Temperature','severity':'CRITICAL','score':38,
             'predicate': temp>95,
             'conditions':[{'label':'Temp > 95°C','passed':temp>95,'actual':f'{temp:.1f}°C','threshold':'95°C'}]},
            {'rule_id':'OVERPRESSURE','rule_name':'Overpressure Event','severity':'CRITICAL','score':45,
             'predicate': overpress or pressure>80,
             'conditions':[
                {'label':'Overpressure Detected','passed':overpress,   'actual':'YES' if overpress else 'NO','threshold':'Detected'},
                {'label':'Pressure > 80 bar',    'passed':pressure>80, 'actual':f'{pressure:.0f} bar',      'threshold':'80 bar'},
             ]},
            {'rule_id':'PPE_VIOLATION','rule_name':'PPE Non-Compliance','severity':'MEDIUM','score':18,
             'predicate': no_helmet or no_vest,
             'conditions':[
                {'label':'No Helmet','passed':no_helmet,'actual':'YES' if no_helmet else 'NO','threshold':'Detected'},
                {'label':'No Vest',  'passed':no_vest,  'actual':'YES' if no_vest   else 'NO','threshold':'Detected'},
             ]},
            {'rule_id':'WORKER_FALL','rule_name':'Worker Fall Detected','severity':'CRITICAL','score':42,
             'predicate': has_fall,
             'conditions':[{'label':'Fall Detected','passed':has_fall,'actual':'YES' if has_fall else 'NO','threshold':'Detected'}]},
            {'rule_id':'GAS_LEAK_VISUAL','rule_name':'Visual Gas Leak Detection','severity':'CRITICAL','score':44,
             'predicate': has_gas and workers>0,
             'conditions':[
                {'label':'Gas Leak (CCTV)','passed':has_gas,   'actual':'Detected' if has_gas else 'Clear','threshold':'Detected'},
                {'label':'Worker Present', 'passed':workers>0, 'actual':f'{workers}','threshold':'>0'},
             ]},
        ]

        all_results, matched = [], []
        for sp in specs:
            r = RuleEvalResult(sp['rule_id'], sp['rule_name'], bool(sp['predicate']),
                               sp['conditions'], sp['severity'], sp['score'])
            all_results.append(r)
            if r.passed:
                matched.append(r)
        return all_results, matched

    def _append_history(self, s: AIFrameState) -> None:
        self.history.appendleft(DetectionHistoryEntry(
            'frame', f'Frame #{s.frame_number}',
            f'{s.inference_ms:.0f}ms \u2022 {s.model_name}', s.zone
        ))
        seen = set()
        for det in sorted(s.detections, key=lambda d: d.is_hazard(), reverse=True):
            if det.label in seen:
                continue
            seen.add(det.label)
            self.history.appendleft(DetectionHistoryEntry(
                'hazard' if det.is_hazard() else 'detection',
                det.display_name, f'Conf: {det.conf_pct}', det.zone, det.confidence
            ))
        if s.gas_ppm() > 0:
            self.history.appendleft(DetectionHistoryEntry(
                'sensor', 'Gas Sensor', f'{s.gas_ppm():.1f} ppm', s.zone
            ))
        for rule in s.matched_rules:
            self.history.appendleft(DetectionHistoryEntry(
                'rule_match', f'Rule: {rule.rule_id}',
                f'{rule.rule_name} \u2192 {rule.severity}', s.zone
            ))
        if s.alert_generated:
            self.history.appendleft(DetectionHistoryEntry(
                'alert', f'{s.risk_level} Alert Generated',
                f'Score: {s.risk_score}/100', s.zone
            ))


def get_ai_bus() -> AIExplainabilityBus:
    """Returns the singleton AI Explainability State Bus."""
    return AIExplainabilityBus()
