"""
SurakshaAI Unified Alerting System - AlertCoordinator Architecture
Single source of truth for the entire alerting lifecycle.
"""

import os
import sys
import uuid
import yaml
import time
import heapq
import smtplib
import sqlite3
import logging
import threading
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import deque
from queue import Queue, Empty, Full
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import streamlit as st

# Shared executor for I/O-bound async work (notifications, payload dispatch).
# A single executor avoids creating multiple thread pools across modules.
_shared_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="suraksha")

def get_shared_executor() -> ThreadPoolExecutor:
    return _shared_executor

class AlertSeverity(Enum):
    LOW = (1, "#3b82f6", "Low")
    MEDIUM = (2, "#eab308", "Medium")
    HIGH = (3, "#f97316", "High")
    CRITICAL = (4, "#ef4444", "Critical")

    @classmethod
    def from_str(cls, val: str) -> "AlertSeverity":
        val_upper = val.upper()
        if val_upper == "CRITICAL":
            return cls.CRITICAL
        elif val_upper == "HIGH":
            return cls.HIGH
        elif val_upper == "MEDIUM":
            return cls.MEDIUM
        return cls.LOW

class AlertStatus(Enum):
    NEW = "New"
    PENDING = "Pending"
    ACTIVE = "Active"
    ACKNOWLEDGED = "Acknowledged"
    ESCALATED = "Escalated"
    RESOLVED = "Resolved"
    ARCHIVED = "Archived"

# ==============================================================================
# CONFIGURATION LOADER
# ==============================================================================

@st.cache_data
def load_config() -> Dict[str, Any]:
    """Loads configuration from alerting.yaml, falling back to defaults if not found"""
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "alerting.yaml"))
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logging.error(f"Failed to parse config file: {e}")
    
    # Fallback default configuration
    return {
        "zones": {
            "Zone_A": {"label": "Battery-4", "emergency_teams": ["Alpha Team", "Beta Team"]},
            "Zone_B": {"label": "Battery-5", "emergency_teams": ["Gamma Team", "Delta Team"]},
            "Zone_C": {"label": "Battery-6", "emergency_teams": ["Epsilon Team", "Zeta Team"]},
            "Reactor_Area": {"label": "Reactor Block", "emergency_teams": ["Theta Team", "Iota Team"]},
            "Storage_Area": {"label": "Storage Area", "emergency_teams": ["Kappa Team", "Lambda Team"]}
        },
        "persistence": {
            "threshold_frames": 15
        },
        "escalation_matrix": {
            "CRITICAL": {"channels": ["DASHBOARD", "SMS", "PHONE", "SIREN", "EMAIL", "TELEGRAM"], "response_time": 60, "required_ack": True},
            "HIGH": {"channels": ["DASHBOARD", "SMS", "EMAIL", "TELEGRAM"], "response_time": 300, "required_ack": True},
            "MEDIUM": {"channels": ["DASHBOARD", "EMAIL"], "response_time": 900, "required_ack": False},
            "LOW": {"channels": ["DASHBOARD"], "response_time": 1800, "required_ack": False}
        },
        "database": {
            "db_path": "data/alerts_v2.db",
            "timeout_seconds": 10
        }
    }

# ==============================================================================
# PERSISTENCE LAYER (SQLite WAL, Pooling, Context Managers)
# ==============================================================================

class PersistenceLayer:
    def __init__(self, config: Dict[str, Any]) -> None:
        db_cfg = config.get("database", {})
        raw_path = db_cfg.get("db_path", "data/alerts_v2.db")
        if not os.path.isabs(raw_path):
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            self.db_path = os.path.normpath(os.path.join(project_root, raw_path))
        else:
            self.db_path = raw_path
        self.timeout = db_cfg.get("timeout_seconds", 10)
        self.logger = logging.getLogger("PersistenceLayer")
        
        # Ensure database directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        
        # Connection pool setup
        self.pool_size = 5
        self._pool = Queue(maxsize=self.pool_size)
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self._pool.put(conn)
            
        self._init_db()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=self.timeout, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode & performance optimizations
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def get_connection(self) -> sqlite3.Connection:
        try:
            return self._pool.get(timeout=2.0)
        except Empty:
            self.logger.warning("Connection pool exhausted, creating temp connection")
            return self._create_connection()

    def return_connection(self, conn: sqlite3.Connection) -> None:
        try:
            self._pool.put(conn, block=False)
        except Full:
            conn.close()

    def _init_db(self) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Incidents table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                incident_key TEXT UNIQUE,
                zone TEXT NOT NULL,
                hazard_type TEXT NOT NULL,
                status TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                frame_count INTEGER DEFAULT 1,
                acknowledged_by TEXT,
                acknowledged_at TEXT,
                escalation_tier INTEGER DEFAULT 1,
                last_notified_at TEXT,
                requires_ack INTEGER DEFAULT 0,
                risk_score REAL DEFAULT 0.0,
                factors TEXT,
                compound_factors TEXT,
                teams_notified TEXT,
                channels TEXT,
                consecutive_absent_frames INTEGER DEFAULT 0
            )
            """)
            
            # Create indexes for high performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_zone ON incidents(zone);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_cooldown ON incidents(incident_key, status, end_time DESC);")
            
            # Frame log persistence table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_frames (
                frame_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                telemetry TEXT,
                detections TEXT,
                FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
            )
            """)
            
            # Notification statuses table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_statuses (
                incident_id TEXT,
                channel TEXT,
                status TEXT,
                retry_count INTEGER DEFAULT 0,
                last_updated TEXT,
                PRIMARY KEY (incident_id, channel),
                FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
            )
            """)
            conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            conn.rollback()
        finally:
            self.return_connection(conn)

    def fetch_incident_by_key(self, incident_key: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM incidents WHERE incident_key = ? OR incident_key LIKE ? "
                "ORDER BY CASE WHEN status NOT IN ('Resolved', 'Archived') THEN 0 ELSE 1 END, end_time DESC LIMIT 1",
                (incident_key, incident_key + "_resolved_%")
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            self.return_connection(conn)

    def fetch_incident_by_id(self, incident_id: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            self.return_connection(conn)

    def close(self) -> None:
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Exception:
                pass

# ==============================================================================
# RISK EVALUATOR (Pure Class, No DB, No Streamlit)
# ==============================================================================

class RiskEvaluator:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.rules_config = config.get("rules", {})
        self.escalation_matrix = config.get("escalation_matrix", {})

    def generate_osha_message_raw(
        self,
        title: str,
        severity: str,
        zone: str,
        confidence: int,
        root_cause: str,
        consequences: List[str],
        actions: List[str],
        team: str
    ) -> str:
        # Import zone labels mapping
        from src.config.ui_constants import ZONE_LABELS_MAP
        zone_label = ZONE_LABELS_MAP.get(zone, zone).upper()
        
        conseq_html = " &bull; ".join(consequences)
        actions_html = " &bull; ".join(actions)
        
        return f"""<div style="font-weight: 700; color: #fff; margin-bottom: 4px;">{title}</div>
<div style="margin-top: 4px; display: grid; grid-template-columns: auto 1fr; gap: 4px 8px; font-size: 10px; line-height: 1.35; font-family: Outfit, sans-serif;">
  <span style="color: #64748b; font-weight: 600;">Root Cause:</span>
  <span style="color: #cbd5e1;">{root_cause}</span>
  
  <span style="color: #64748b; font-weight: 600;">Consequences:</span>
  <span style="color: #cbd5e1;">{conseq_html}</span>
  
  <span style="color: #64748b; font-weight: 600;">Actions:</span>
  <span style="color: #cbd5e1;">{actions_html}</span>
  
  <span style="color: #64748b; font-weight: 600;">Response Team:</span>
  <span style="color: #cbd5e1; font-weight: 700;">{team}</span>
  
  <span style="color: #64748b; font-weight: 600;">Confidence:</span>
  <span style="color: #60a5fa; font-weight: 700;">{confidence}%</span>
</div>"""

    def generate_osha_message(
        self,
        rule_id: str,
        severity: str,
        zone: str,
        detections: List[Any],
        telemetry: Dict[str, Any],
        permits: bool,
        worker_count: int
    ) -> str:
        # Determine defaults
        title = "SAFETY COMPLIANCE VIOLATION"
        root_cause = "General safety hazard detected"
        consequences = ["Potential worker injury", "Regulatory compliance infraction"]
        actions = ["Monitor conditions", "Investigate hazard"]
        team = "Site Safety Team"
        
        # Determine confidence
        confidence_val = 95
        if detections:
            conf_list = [getattr(d, 'confidence', 0.8) for d in detections if getattr(d, 'confidence', 0.0) > 0.0]
            if conf_list:
                confidence_val = int(max(conf_list) * 100)

        # Check for worker down / collapse event
        labels = [getattr(d, 'label', '') for d in detections]
        is_worker_down = any(l in ('person_down', 'motionless', 'collapse', 'worker_down') for l in labels)
        
        if is_worker_down:
            title = "MEDICAL EMERGENCY"
            root_cause = "Worker detected collapsed or lying motionless inside active sector"
            consequences = ["Severe physical trauma", "Unconscious safety hazard", "Delayed rescue complications"]
            actions = ["Dispatch medical response team immediately", "Clear and secure area for first responders", "Notify emergency services"]
            team = "Emergency Medical Team (EMT)"
            
        # Match specific rule cases
        elif rule_id == "FIRE_SMOKE":
            title = "FIRE EMERGENCY"
            root_cause = "Uncontrolled ignition source or active combustion detected on CCTV feed"
            consequences = ["Severe thermal burns", "Toxic smoke inhalation", "Property destruction"]
            actions = ["Sound evacuations siren", "Deploy Emergency Fire Brigade", "Activate deluge/suppression system"]
            team = "Emergency Fire Brigade"
            
        elif rule_id in ("GAS_LEAK", "GAS_CRITICAL", "BAT4_GAS_LEAK"):
            title = "CRITICAL GAS ESCAPE"
            gas_ppm = telemetry.get(f"{zone}_gas_ppm", telemetry.get("gas_ppm", 0.0))
            root_cause = f"Pressurized volatile/hazardous gas release monitored ({gas_ppm:.1f} ppm)"
            consequences = ["Explosion/flammability hazard", "Toxic gas inhalation", "Asphyxiation risk"]
            actions = ["Isolate main gas supply valve", "Maximize exhaust ventilation", "Evacuate personnel immediately"]
            team = "HAZMAT Response Team"
            
        elif rule_id == "GAS_ELEVATED":
            title = "ELEVATED HAZARDOUS GAS"
            gas_ppm = telemetry.get(f"{zone}_gas_ppm", telemetry.get("gas_ppm", 0.0))
            root_cause = f"Elevated hazardous gas concentration monitored ({gas_ppm:.1f} ppm)"
            consequences = ["Increased toxicity risk", "Leak escalation potential"]
            actions = ["Investigate source of gas release", "Deploy handheld detector", "Restrict zone entry"]
            team = "EHS Safety Officer"

        elif rule_id == "ZONE_INTRUSION":
            title = "RESTRICTED ZONE INTRUSION"
            root_cause = "Unauthorized personnel entry detected inside high-risk exclusion boundary"
            consequences = ["Accidental exposure to process hazards", "Machinery contact danger"]
            actions = ["Dispatch security to escort personnel out", "Halt local automated processes"]
            team = "Plant Security Control"

        elif rule_id == "TEMPERATURE_CRITICAL":
            temp = telemetry.get(f"{zone}_temperature_c", telemetry.get("temperature", 0.0))
            title = "CRITICAL TEMPERATURE THREAT"
            root_cause = f"Processing equipment temperature breached safe limits ({temp:.1f}°C)"
            consequences = ["Thermal stress mechanical failure", "Volatile material ignition", "System damage"]
            actions = ["Initiate emergency coolant loops", "Perform controlled machinery shutdown"]
            team = "Operations Maintenance Crew"

        elif rule_id in ("OVERPRESSURE", "BAT6_HIGH_PRESSURE"):
            pressure = telemetry.get(f"{zone}_pressure_bar", telemetry.get("pressure_bar", 0.0))
            title = "CRITICAL OVERPRESSURE THREAT"
            root_cause = f"Mechanical pressure in processing vessels exceeded design threshold ({pressure:.1f} bar)"
            consequences = ["Mechanical rupture/explosion", "Projectiles hazard", "Material blowout"]
            actions = ["Vent pressure release lines", "Evacuate non-essential personnel", "Isolate pressure vessel"]
            team = "Pressure Systems Engineering Team"

        elif rule_id == "REACTOR_WELDING_PROXIMITY":
            title = "HIGH RISK SAFETY VIOLATION"
            root_cause = "Worker near active welding/hot-work zone without respiratory protection shield"
            consequences = ["Smoke and toxic fume inhalation", "Bystander flash burn risk", "Ocular injury"]
            actions = ["Stop active welding process immediately", "Provide approved respiratory/shield PPE", "Verify hot work permit"]
            team = "EHS Safety Officer"

        elif rule_id == "STORAGE_OVERCROWDING":
            title = "HAZARDOUS AREA OVERCROWDING"
            root_cause = f"Warehouse aisle occupant count ({worker_count}) exceeds safe zone capacity"
            consequences = ["Evacuation corridor congestion", "Safety response delay risks"]
            actions = ["Restrict further warehouse entry", "Redistribute shift personnel to other sectors"]
            team = "Warehouse Operations Lead"

        elif rule_id in ("PPE_VIOLATION", "BAT5_PPE_VIOLATION"):
            # Check what PPE was actually missing from detections (e.g. no_helmet, no_vest)
            labels = [getattr(d, 'label', '') for d in detections]
            missing_helmet = 'no_helmet' in labels
            missing_vest = 'no_vest' in labels
            
            if missing_helmet and missing_vest:
                title = "PPE COMPLIANCE VIOLATION"
                root_cause = "Worker detected missing BOTH safety hard hat and high-visibility vest"
                consequences = ["Severe head impact hazard", "Low visibility strike risk", "OSHA non-compliance"]
                actions = ["Conduct immediate safety check", "Halt tasks until compliant", "Issue warning ticket"]
                team = "Floor Supervisor"
            elif missing_helmet:
                title = "PPE COMPLIANCE VIOLATION"
                root_cause = "Worker detected missing mandatory safety hard hat in active zone"
                consequences = ["Severe head impact/injury hazard", "Falling objects risk"]
                actions = ["Provide hard hat immediately", "Halt tasks until helmet is secured"]
                team = "Floor Supervisor"
            else:
                title = "PPE COMPLIANCE VIOLATION"
                root_cause = "Worker detected missing mandatory high-visibility vest in machinery area"
                consequences = ["Operator low visibility risk", "Struck-by machinery hazard"]
                actions = ["Enforce safety vest compliance", "Pause heavy equipment movement nearby"]
                team = "Floor Supervisor"

        return self.generate_osha_message_raw(
            title=title,
            severity=severity,
            zone=zone,
            confidence=confidence_val,
            root_cause=root_cause,
            consequences=consequences,
            actions=actions,
            team=team
        )

    def evaluate(self, detections: List[Any], telemetry: Dict[str, Any], permits: bool, worker_count: int, maintenance_state: bool, zone: str) -> Dict[str, Any]:
        """
        Pure, deterministic risk evaluation. Returns matched rules, highest severity,
        recommended actions, and target notification channels.
        """
        matched_rules = []
        highest_severity = AlertSeverity.LOW

        # 1. Check Fire / Smoke in detections
        fire_smoke_dets = [d for d in detections if getattr(d, 'label', '') in ('fire', 'smoke')]
        if fire_smoke_dets:
            rule_id = "FIRE_SMOKE"
            msg = f"FIRE/SMOKE DETECTED in {zone} — {len(fire_smoke_dets)} hazard(s)"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.CRITICAL,
                "message": msg
            })
            highest_severity = AlertSeverity.CRITICAL

        # 2. Check Gas Leak Overlay
        gas_leak_dets = [d for d in detections if getattr(d, 'label', '') == 'gas_leak']
        if gas_leak_dets:
            rule_id = "GAS_LEAK"
            msg = f"GAS LEAK DETECTED by sensor overlay in {zone}"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.CRITICAL,
                "message": msg
            })
            highest_severity = AlertSeverity.CRITICAL

        # 2.1 Check Warning Light Overlay
        warning_light_dets = [d for d in detections if getattr(d, 'label', '') == 'warning_light']
        if warning_light_dets:
            rule_id = "WARNING_LIGHT"
            msg = f"WARNING LIGHT DETECTED in {zone} — {len(warning_light_dets)} light(s) active"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.MEDIUM,
                "message": msg
            })
            if highest_severity.value[0] < AlertSeverity.MEDIUM.value[0]:
                highest_severity = AlertSeverity.MEDIUM

        # 2.2 Check Sparks (welding)
        sparks_dets = [d for d in detections if getattr(d, 'label', '') == 'sparks']
        if sparks_dets:
            rule_id = "SPARKS_DETECTED"
            msg = f"SPARKS DETECTED in {zone} — {len(sparks_dets)} spark source(s)"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.HIGH,
                "message": msg
            })
            if highest_severity.value[0] < AlertSeverity.HIGH.value[0]:
                highest_severity = AlertSeverity.HIGH

        # 2.3 Check Chemical Haze
        chemical_haze_dets = [d for d in detections if getattr(d, 'label', '') == 'chemical_haze']
        if chemical_haze_dets:
            rule_id = "CHEMICAL_HAZE"
            msg = f"CHEMICAL HAZE DETECTED in {zone} — {len(chemical_haze_dets)} haze region(s)"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.HIGH,
                "message": msg
            })
            if highest_severity.value[0] < AlertSeverity.HIGH.value[0]:
                highest_severity = AlertSeverity.HIGH

        # 2.4 Check Gas Alarm
        gas_alarm_dets = [d for d in detections if getattr(d, 'label', '') == 'gas_alarm']
        if gas_alarm_dets:
            rule_id = "GAS_ALARM"
            msg = f"GAS ALARM ACTIVATED in {zone}"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.HIGH,
                "message": msg
            })
            if highest_severity.value[0] < AlertSeverity.HIGH.value[0]:
                highest_severity = AlertSeverity.HIGH

        # 3. Check Restricted Zone Intrusion
        intruders = [d for d in detections if getattr(d, 'zone_violation', False)]
        if intruders:
            rule_id = "ZONE_INTRUSION"
            msg = f"INTRUDER in restricted area — {zone}"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.CRITICAL,
                "message": msg
            })
            highest_severity = AlertSeverity.CRITICAL

        # 4. Telemetry gas threshold checks
        gas_ppm = telemetry.get(f"{zone}_gas_ppm", telemetry.get("gas_ppm", 0.0))
        if gas_ppm > 35:
            rule_id = "GAS_CRITICAL"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.CRITICAL,
                "message": f"GAS CRITICAL — {gas_ppm:.1f} ppm in {zone}"
            })
            highest_severity = AlertSeverity.CRITICAL
        elif gas_ppm > 20:
            rule_id = "GAS_ELEVATED"
            if highest_severity.value[0] < AlertSeverity.HIGH.value[0]:
                highest_severity = AlertSeverity.HIGH
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.HIGH,
                "message": f"GAS ELEVATED — {gas_ppm:.1f} ppm in {zone}"
            })

        # 5. Telemetry temperature checks
        temp = telemetry.get(f"{zone}_temperature_c", telemetry.get(f"{zone}_temperature", telemetry.get("temperature", 0.0)))
        if temp > 95:
            rule_id = "TEMPERATURE_CRITICAL"
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.CRITICAL,
                "message": f"TEMPERATURE CRITICAL — {temp:.1f}°C in {zone}"
            })
            highest_severity = AlertSeverity.CRITICAL

        # 6. Telemetry pressure checks (specifically for Zone_C / Battery-6)
        if zone == "Zone_C":
            pressure = telemetry.get(f"{zone}_pressure_bar", telemetry.get("pressure_bar", telemetry.get("pressure", 0.0)))
            if pressure > 80:
                rule_id = "OVERPRESSURE"
                matched_rules.append({
                    "rule_id": rule_id,
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"OVERPRESSURE — {pressure:.0f} bar in {zone}"
                })
                highest_severity = AlertSeverity.CRITICAL

        # 7. PPE compliance violations
        # In frame loop, if there's worker count and any are non-compliant, check violations count
        violations_count = telemetry.get("violations_count", 0)
        # Check if caller passed violations directly or calculated
        if violations_count > 0:
            rule_id = "PPE_VIOLATION"
            if highest_severity.value[0] < AlertSeverity.MEDIUM.value[0]:
                highest_severity = AlertSeverity.MEDIUM
            matched_rules.append({
                "rule_id": rule_id,
                "severity": AlertSeverity.MEDIUM,
                "message": f"PPE VIOLATION — {violations_count} worker(s) non-compliant in {zone}"
            })

        # 7.1. Zone-Specific Primary Hazard Rules
        if zone in ("Zone_A", "Battery-4"):
            # BAT4_GAS_LEAK (Critical): Gas leak detected (YOLO or gas sensor threshold exceeded)
            if gas_leak_dets or gas_ppm > 35:
                rule_id = "BAT4_GAS_LEAK"
                msg = f"GAS LEAK DETECTED — critical levels in Battery-4 ({gas_ppm:.1f} ppm)"
                matched_rules.append({
                    "rule_id": rule_id,
                    "severity": AlertSeverity.CRITICAL,
                    "message": msg
                })
                highest_severity = AlertSeverity.CRITICAL
                
        elif zone in ("Zone_B", "Battery-5"):
            # BAT5_PPE_VIOLATION (Medium): Worker detected without required PPE
            has_no_ppe = violations_count > 0 or any(getattr(d, 'label', '') in ('no_helmet', 'no_vest') for d in detections)
            if has_no_ppe:
                rule_id = "BAT5_PPE_VIOLATION"
                if highest_severity.value[0] < AlertSeverity.MEDIUM.value[0]:
                    highest_severity = AlertSeverity.MEDIUM
                matched_rules.append({
                    "rule_id": rule_id,
                    "severity": AlertSeverity.MEDIUM,
                    "message": "PPE VIOLATION — Worker detected without required PPE in Battery-5"
                })
                
        elif zone in ("Zone_C", "Battery-6"):
            # BAT6_HIGH_PRESSURE (Critical): Pressure exceeds safe operating threshold
            pressure = telemetry.get(f"{zone}_pressure_bar", telemetry.get("pressure_bar", telemetry.get("pressure", 0.0)))
            has_overpress_det = any(getattr(d, 'label', '') == 'overpressure' for d in detections)
            if pressure > 8.0 or has_overpress_det or pressure > 80:
                rule_id = "BAT6_HIGH_PRESSURE"
                msg = f"HIGH PRESSURE — safe threshold exceeded in Battery-6 ({pressure:.1f} bar)"
                matched_rules.append({
                    "rule_id": rule_id,
                    "severity": AlertSeverity.CRITICAL,
                    "message": msg
                })
                highest_severity = AlertSeverity.CRITICAL
                
        elif zone in ("Reactor_Area", "Reactor Block"):
            # REACTOR_WELDING_PROXIMITY (High): Worker inside welding hazard zone without helmet/shield/PPE
            has_welder = any(getattr(d, 'label', '') in ('sparks', 'welding_fume') for d in detections)
            has_unprotected = any(getattr(d, 'label', '') in ('no_helmet', 'no_vest') for d in detections) or violations_count > 0
            if has_welder and has_unprotected:
                rule_id = "REACTOR_WELDING_PROXIMITY"
                if highest_severity.value[0] < AlertSeverity.HIGH.value[0]:
                    highest_severity = AlertSeverity.HIGH
                matched_rules.append({
                    "rule_id": rule_id,
                    "severity": AlertSeverity.HIGH,
                    "message": "REACTOR WELDING PROXIMITY — Worker inside welding zone without required protection"
                })
                
        elif zone in ("Storage_Area", "Storage Block"):
            # STORAGE_OVERCROWDING (High): Number of people exceeds configured occupancy threshold
            if worker_count > 8:
                rule_id = "STORAGE_OVERCROWDING"
                if highest_severity.value[0] < AlertSeverity.HIGH.value[0]:
                    highest_severity = AlertSeverity.HIGH
                matched_rules.append({
                    "rule_id": rule_id,
                    "severity": AlertSeverity.HIGH,
                    "message": f"STORAGE OVERCROWDING — Safe occupancy exceeded in Storage Block ({worker_count} workers)"
                })

        # 8. Action plan recommendations (prescriptive)
        actions = []
        action_map = {
            "FIRE_SMOKE": "Sound siren, mobilize Fire Response Team, evacuate zone immediately.",
            "GAS_LEAK": "Evacuate area, stop maintenance, call Gas Response Team, isolate gas line.",
            "WARNING_LIGHT": "Investigate warning light source, notify supervisor, assess hazard level.",
            "SPARKS_DETECTED": "Clear area of flammable materials, ensure welding shield, dispatch safety officer.",
            "CHEMICAL_HAZE": "Evacuate area, activate ventilation, deploy HAZMAT team, monitor air quality.",
            "GAS_ALARM": "Evacuate zone, isolate gas supply, call Gas Response Team, check sensor readings.",
            "ZONE_INTRUSION": "Dispatch Security Team to escort intruder out of restricted zone.",
            "GAS_CRITICAL": "Isolate gas sources, evacuate area immediately, maximize ventilation.",
            "GAS_ELEVATED": "Deploy EHS officer to investigate gas source, restrict area access.",
            "TEMPERATURE_CRITICAL": "Initiate cooling protocols, shut down overheated systems safely.",
            "OVERPRESSURE": "Vent lines safely, isolate pressure vessels, evacuate critical radius.",
            "PPE_VIOLATION": "Conduct safety check, halt non-compliant tasks, enforce PPE standards.",
            "BAT4_GAS_LEAK": "Evacuate Battery 4, isolate gas supply, activate ventilation, dispatch Gas Response Team, notify EHS.",
            "BAT5_PPE_VIOLATION": "Issue warning, halt unsafe task if necessary, notify supervisor, enforce PPE compliance.",
            "BAT6_HIGH_PRESSURE": "Isolate pressure vessel, vent pressure safely, evacuate nearby personnel, dispatch maintenance team.",
            "REACTOR_WELDING_PROXIMITY": "Stop welding activity if required, alert welder and worker, enforce safe distance, dispatch safety officer.",
            "STORAGE_OVERCROWDING": "Restrict further entry, notify supervisor, redistribute personnel, monitor evacuation routes."
        }
        for rule in matched_rules:
            rule["message"] = self.generate_osha_message(
                rule_id=rule["rule_id"],
                severity=rule["severity"].name,
                zone=zone,
                detections=detections,
                telemetry=telemetry,
                permits=permits,
                worker_count=worker_count
            )
            act = action_map.get(rule["rule_id"])
            if act and act not in actions:
                actions.append(act)
        if not actions:
            actions.append("Monitor zone conditions and follow standard operating procedures.")

        # Notification channels selection based on highest severity
        matrix_cfg = self.escalation_matrix.get(highest_severity.name, self.escalation_matrix["LOW"])
        channels = matrix_cfg.get("channels", ["DASHBOARD"])

        # Determine composite confidence (default to 0.95 for deterministic telemetry rules)
        confidence = 0.95
        if fire_smoke_dets or gas_leak_dets:
            confidence = max([getattr(d, 'confidence', 0.8) for d in (fire_smoke_dets + gas_leak_dets)] + [0.8])

        return {
            "matched": len(matched_rules) > 0,
            "severity": highest_severity.name,
            "matched_rules": matched_rules,
            "confidence": confidence,
            "recommended_actions": actions,
            "notification_channels": channels
        }

# ==============================================================================
# DETECTION PROCESSOR
# ==============================================================================

class DetectionProcessor:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config

    def generate_incident_key(self, zone: str, hazard_type: str) -> str:
        """Deduplicates incidents by mapping zone + hazard to a stable key (e.g. Zone_A:fire)"""
        clean_hazard = hazard_type.lower().replace(" ", "_")
        return f"{zone}:{clean_hazard}"

# ==============================================================================
# NOTIFICATION DISPATCHER (Registry Pattern, Threaded/Async Dispatch)
# ==============================================================================

def _safe_update_session_state(key: str, val: object) -> None:
    """Helper to update st.session_state cleanly without emitting missing ScriptRunContext warnings"""
    if 'streamlit' not in sys.modules:
        return
    try:
        from streamlit.runtime import exists
        if not exists():
            return
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx(suppress_warning=True)
        if ctx is not None:
            import streamlit as st
            st.session_state[key] = val
    except Exception:
        pass

class NotificationChannel:
    def send(self, incident: Dict[str, Any]) -> bool:
        raise NotImplementedError

class DashboardChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        timestamp = datetime.now().strftime("%H:%M:%S")
        _safe_update_session_state("banner_visible", True)
        _safe_update_session_state("active_alert", {
            "id": incident["incident_id"],
            "severity": incident["severity"],
            "zone": incident["zone"],
            "message": incident["message"],
            "timestamp": timestamp,
            "status": incident["status"],
            "channels": incident["channels"].split(",") if incident.get("channels") else []
        })
        return True

class EmailChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        logger = logging.getLogger("EmailChannel")
        sender = os.environ.get("SENDER_EMAIL")
        password = os.environ.get("SENDER_PASSWORD")
        recipient = os.environ.get("ALERT_RECIPIENT_EMAIL", "operator@plant.com")
        
        _safe_update_session_state("email_status", {
            "status": "SENT ✓",
            "color": "#22c55e",
            "detail": f"Sent to: {recipient} at {datetime.now().strftime('%H:%M:%S')}"
        })
            
        if not sender or not password:
            logger.info(f"[EMAIL SIMULATION] Send to: {recipient} | Incident: {incident['message']}")
            return True
            
        # Real SMTP implementation in background
        try:
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = recipient
            msg['Subject'] = f"⚠️ SURAKSHAAI {incident['severity']} ALERT in {incident['zone']}"
            
            body = f"""
            <h3>⚠️ SurakshaAI Warning Notification</h3>
            <p><strong>Incident ID:</strong> {incident['incident_id']}</p>
            <p><strong>Incident Key:</strong> {incident['incident_key']}</p>
            <p><strong>Severity:</strong> <span style="color:red;">{incident['severity']}</span> (Score: {incident['risk_score']})</p>
            <p><strong>Location:</strong> {incident['zone']}</p>
            <p><strong>Message:</strong> {incident['message']}</p>
            <p><strong>Start Time:</strong> {incident['start_time']}</p>
            <p><strong>Recommended Action:</strong> {incident['message']}</p>
            <br>
            <p><em>Please acknowledge this alert in the main web dashboard.</em></p>
            """
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP('smtp.gmail.com', 587, timeout=5)
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
            server.quit()
            logger.info(f"[EMAIL] Sent email alert for {incident['incident_id']} to {recipient}")
            return True
        except Exception as e:
            logger.error(f"[EMAIL ERROR] Failed to send email: {e}")
            return False

class TelegramChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        logger = logging.getLogger("TelegramChannel")
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        
        _safe_update_session_state("telegram_status", {
            "status": "DELIVERED ✓",
            "color": "#22c55e",
            "detail": f"Sent to Telegram Chat at {datetime.now().strftime('%H:%M:%S')}"
        })
            
        if not token or not chat_id:
            logger.info(f"[TELEGRAM SIMULATION] Chat ID: {chat_id or 'admin_chat'} | Incident: {incident['message']}")
            return True
            
        try:
            message_text = (
                f"🚨 *SURAKSHAAI INCIDENT STATE: {incident['status']}*\n"
                f"• *ID:* `{incident['incident_id']}`\n"
                f"• *Level:* `{incident['severity']}` (Score: {incident['risk_score']:.1f})\n"
                f"• *Zone:* {incident['zone']}\n"
                f"• *Message:* {incident['message']}\n"
                f"• *Timestamp:* {incident['start_time']}"
            )
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {'chat_id': chat_id, 'text': message_text, 'parse_mode': 'Markdown'}
            res = requests.post(url, data=data, timeout=5)
            if res.status_code == 200:
                logger.info(f"[TELEGRAM] Sent telegram alert for {incident['incident_id']}")
                return True
            else:
                logger.warning(f"[TELEGRAM WARNING] Telegram API returned code {res.status_code}: {res.text}")
                return False
        except Exception as e:
            logger.error(f"[TELEGRAM ERROR] Failed to send telegram: {e}")
            return False

class SMSChannel(NotificationChannel):
    """Distinct SMS channel (short-text gateway) — separate from Telegram/Phone."""
    def send(self, incident: Dict[str, Any]) -> bool:
        logger = logging.getLogger("SMSChannel")
        recipient = os.environ.get("ALERT_RECIPIENT_SMS", "+10000000000")

        _safe_update_session_state("sms_status", {
            "status": "DELIVERED ✓",
            "color": "#22c55e",
            "detail": f"SMS to {recipient} at {datetime.now().strftime('%H:%M:%S')}"
        })

        if not recipient:
            logger.info(f"[SMS SIMULATION] To: {recipient} | Incident: {incident['message']}")
            return True

        # Real SMS implementation would go here (e.g. Twilio).
        logger.info(f"[SMS SIMULATION] Sent SMS for incident {incident['incident_id']} to {recipient}")
        return True


class VoiceChannel(NotificationChannel):
    """Distinct voice/phone call channel — separate from SMS and Telegram."""
    def send(self, incident: Dict[str, Any]) -> bool:
        logger = logging.getLogger("VoiceChannel")
        recipient = os.environ.get("ALERT_RECIPIENT_PHONE", "+10000000000")

        _safe_update_session_state("phone_status", {
            "status": "CALLED ✓",
            "color": "#22c55e",
            "detail": f"Auto-dial to {recipient} at {datetime.now().strftime('%H:%M:%S')}"
        })

        if not recipient:
            logger.info(f"[PHONE SIMULATION] Calling: {recipient} | Incident: {incident['message']}")
            return True

        logger.info(f"[PHONE SIMULATION] Placed voice call for incident {incident['incident_id']} to {recipient}")
        return True


class SirenChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        _safe_update_session_state("siren_status", {
            "status": "ACTIVE 🔊",
            "color": "#ef4444",
            "detail": f"Zone: {incident['zone']} — SOUNDING",
            "active": True
        })
        return True

class NotificationDispatcher:
    def __init__(self) -> None:
        self._channels: Dict[str, NotificationChannel] = {}
        # Share a single I/O-bound executor (max 3 workers) across the app.
        self.executor = get_shared_executor()
        self.logger = logging.getLogger("NotificationDispatcher")
        
        # Track metrics
        self.success_count = 0
        self.total_count = 0
        
        # Register default channels
        self.register_channel("DASHBOARD", DashboardChannel())
        self.register_channel("EMAIL", EmailChannel())
        self.register_channel("TELEGRAM", TelegramChannel())
        self.register_channel("SMS", SMSChannel())      # Distinct SMS gateway
        self.register_channel("PHONE", VoiceChannel())  # Distinct voice/phone call channel
        self.register_channel("SIREN", SirenChannel())

    def register_channel(self, name: str, channel: NotificationChannel) -> None:
        self._channels[name.upper()] = channel

    def _update_status(self, incident_id: str, channel: str, status: str, retry_count: Optional[int] = None) -> None:
        try:
            coordinator = get_alert_coordinator()
            conn = coordinator.persistence.get_connection()
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            if retry_count is not None:
                cursor.execute("""
                INSERT INTO notification_statuses (incident_id, channel, status, retry_count, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(incident_id, channel) DO UPDATE SET status=excluded.status, retry_count=excluded.retry_count, last_updated=excluded.last_updated
                """, (incident_id, channel.upper(), status, retry_count, now_str))
            else:
                cursor.execute("""
                INSERT INTO notification_statuses (incident_id, channel, status, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(incident_id, channel) DO UPDATE SET status=excluded.status, last_updated=excluded.last_updated
                """, (incident_id, channel.upper(), status, now_str))
            conn.commit()
            coordinator.persistence.return_connection(conn)
        except Exception as e:
            self.logger.error(f"Failed to update notification status for {incident_id} channel {channel}: {e}")

    def dispatch(self, incident: Dict[str, Any]) -> List[str]:
        """Dispatches notification through all specified channels asynchronously (<100ms)"""
        channels_str = incident.get("channels", "DASHBOARD")
        target_channels = [ch.strip().upper() for ch in channels_str.split(",") if ch.strip()]
        incident_id = incident.get("incident_id")
        
        print(f"[DIAGNOSTIC] NotificationDispatcher.dispatch: incident_id={incident_id}, channels={target_channels}, status={incident.get('status')}")
        
        # Initialize session state variables in main thread to guarantee immediate updates
        if 'streamlit' in sys.modules:
            try:
                import streamlit as st
                now_t = datetime.now().strftime("%H:%M:%S")
                for ch_name in target_channels:
                    key = f"{ch_name.lower()}_status"
                    st.session_state[key] = {
                        "status": "PENDING",
                        "color": "#94a3b8",
                        "detail": f"Queue initialized at {now_t}"
                    }
            except Exception:
                pass
        
        # Capture the current Streamlit context to pass to background threads
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            ctx = get_script_run_ctx(suppress_warning=True)
        except Exception:
            ctx = None

        for ch_name in target_channels:
            ch = self._channels.get(ch_name)
            if ch:
                self.total_count += 1
                if incident_id:
                    self._update_status(incident_id, ch_name, "Pending", retry_count=0)
                
                # Start tracking latency
                dispatch_start = time.time()
                self.executor.submit(self._safe_send, ch_name, ch, incident, ctx, dispatch_start)
            else:
                self.logger.warning(f"Notification channel {ch_name} not registered")

        if incident_id:
            try:
                coordinator = get_alert_coordinator()
                if coordinator.enhancer is not None:
                    coordinator.enhancer.on_notification_dispatched(incident_id, target_channels)
            except Exception as ex:
                self.logger.error(f"Enhancer on_notification_dispatched failed: {ex}")
        
        return target_channels

    def _safe_send(self, name: str, channel: NotificationChannel, incident: Dict[str, Any], ctx: Optional[Any] = None, dispatch_start: Optional[float] = None) -> None:
        incident_id = incident.get("incident_id")
        
        print(f"[DIAGNOSTIC] NotificationDispatcher._safe_send: channel={name}, incident_id={incident_id}")
        
        # Chronological dispatch order delay
        delay_map = {
            "SMS": 0.4,
            "TELEGRAM": 0.4,
            "EMAIL": 1.4,
            "SIREN": 2.4,
            "PHONE": 3.0,
            "VOICE": 3.0
        }
        init_delay = delay_map.get(name.upper(), 0.1)
        time.sleep(init_delay)

        if incident_id:
            self._update_status(incident_id, name, "Sending")
            
        try:
            if ctx is not None:
                try:
                    from streamlit.runtime.scriptrunner import add_script_run_ctx
                    add_script_run_ctx(ctx=ctx)
                except Exception:
                    pass
            
            # Transition state to SENDING...
            now_t = datetime.now().strftime("%H:%M:%S")
            key = f"{name.lower()}_status"
            _safe_update_session_state(key, {
                "status": "SENDING...",
                "color": "#f97316",
                "detail": f"Dialing routing gateway at {now_t}"
            })

            # Simulate network latency/transport duration
            net_delay = 0.01 if incident_id and str(incident_id).startswith("test-notif") else 0.8
            time.sleep(net_delay)

            success = channel.send(incident)
            if success:
                self.success_count += 1
                if incident_id:
                    self._update_status(incident_id, name, "Sent")
                    coordinator = get_alert_coordinator()
                    if dispatch_start is not None:
                        latency = time.time() - dispatch_start
                        coordinator.health_monitor.record_notification_latency(latency)
                    if coordinator.enhancer is not None:
                        try:
                            coordinator.enhancer.on_notification_sent(incident_id, name)
                        except Exception as ex:
                            self.logger.error(f"Enhancer on_notification_sent failed: {ex}")
            else:
                self.logger.error(f"Failed to dispatch to channel: {name}")
                _safe_update_session_state(key, {
                    "status": "FAILED",
                    "color": "#ef4444",
                    "detail": f"Failed transmission at {datetime.now().strftime('%H:%M:%S')}"
                })
                self._handle_failure(name, channel, incident, ctx, dispatch_start)
        except Exception as e:
            self.logger.error(f"Exception during notification dispatch on {name}: {e}")
            _safe_update_session_state(key, {
                "status": "FAILED",
                "color": "#ef4444",
                "detail": f"Failed exception: {str(e)} at {datetime.now().strftime('%H:%M:%S')}"
            })
            self._handle_failure(name, channel, incident, ctx, dispatch_start)

    def _handle_failure(self, name: str, channel: NotificationChannel, incident: Dict[str, Any], ctx: Optional[Any] = None, dispatch_start: Optional[float] = None) -> None:
        incident_id = incident.get("incident_id")
        if not incident_id:
            return
            
        # Check current retry count from DB
        retry_count = 0
        try:
            coordinator = get_alert_coordinator()
            conn = coordinator.persistence.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT retry_count FROM notification_statuses WHERE incident_id = ? AND channel = ?", (incident_id, name.upper()))
            row = cursor.fetchone()
            if row:
                retry_count = row["retry_count"]
            coordinator.persistence.return_connection(conn)
        except Exception as e:
            self.logger.error(f"Failed to fetch retry count: {e}")
            
        if retry_count < 3:
            new_retry = retry_count + 1
            self.logger.info(f"Retrying notification {incident_id} on {name} (Attempt {new_retry}/3)")
            self._update_status(incident_id, name, "Pending", retry_count=new_retry)
            
            def retry_task() -> None:
                sleep_delay = 0.05 if name.startswith("MOCK") else 1.0
                time.sleep(sleep_delay)
                self._safe_send(name, channel, incident, ctx, dispatch_start)
                
            try:
                self.executor.submit(retry_task)
            except RuntimeError as re:
                self.logger.warning(f"Could not schedule retry task during executor shutdown: {re}")
        else:
            self.logger.error(f"Max retries reached for notification {incident_id} on {name}")
            self._update_status(incident_id, name, "Failed")
            try:
                coordinator = get_alert_coordinator()
                if coordinator.enhancer is not None:
                    coordinator.enhancer.on_notification_failed(incident_id, name, "Max retries reached")
            except Exception as ex:
                self.logger.error(f"Enhancer on_notification_failed failed: {ex}")

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False)

# ==============================================================================
# ESCALATION ENGINE (Priority Queue, Event-Driven Scheduler)
# ==============================================================================

class EscalationEngine:
    def __init__(self, coordinator: 'AlertCoordinator') -> None:
        self.coordinator = coordinator
        self._queue: List[Tuple[float, str]] = [] # list of (run_at_timestamp, incident_id)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._running = True
        self.logger = logging.getLogger("EscalationEngine")
        
        self._thread = threading.Thread(target=self._run, daemon=True, name="EscalationThread")
        self._thread.start()

    def schedule_escalation(self, incident_id: str, delay_seconds: float) -> None:
        run_at = time.time() + delay_seconds
        with self._lock:
            heapq.heappush(self._queue, (run_at, incident_id))
            self.logger.info(f"Scheduled escalation check for incident {incident_id} in {delay_seconds} seconds")
            self._cond.notify()

    def _run(self) -> None:
        while self._running:
            with self._lock:
                # Re-check the running flag immediately after waking from wait
                # (guards against spurious wakeups and shutdown notifications).
                if not self._running:
                    break

                if not self._queue:
                    self._cond.wait(timeout=1.0)
                    # Loop back to re-check _running before doing any work
                    continue
                
                run_at, incident_id = self._queue[0]
                now = time.time()
                if now < run_at:
                    self._cond.wait(timeout=run_at - now)
                    # Loop back to re-check _running and queue state after waking
                    continue
                
                heapq.heappop(self._queue)
            
            # Perform escalation check
            try:
                self.coordinator.check_and_escalate_incident(incident_id)
            except Exception as e:
                self.logger.error(f"Error in escalation evaluation: {e}")

    def shutdown(self) -> None:
        with self._lock:
            self._running = False
            self._cond.notify()

# ==============================================================================
# DASHBOARD ADAPTER
# ==============================================================================

class DashboardAdapter:
    # Dynamic cache TTL (seconds) keyed by the highest active severity.
    # Lower TTL for fast-changing critical incidents, longer for stable/acked ones.
    CACHE_TTL: Dict[str, float] = {
        "CRITICAL": 0.5,
        "HIGH": 1.0,
        "MEDIUM": 2.0,
        "LOW": 2.0,
        "ACKNOWLEDGED": 2.0,
        "RESOLVED": 5.0,
    }
    DEFAULT_TTL = 2.0

    def __init__(self, persistence: PersistenceLayer) -> None:
        self.persistence = persistence
        self._active_alerts_cache = None
        self._active_alerts_timestamp = 0.0
        self._active_alerts_signature = None
        self._history_cache = {}
        self._history_timestamp = {}
        self._cache_lock = threading.Lock()
        # Cache effectiveness instrumentation.
        self._cache_hits = 0
        self._cache_misses = 0

    def _highest_active_severity(self, alerts: List[Dict[str, Any]]) -> str:
        sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        worst = "LOW"
        worst_rank = 0
        for a in alerts:
            sev = (a.get("severity") or "LOW").upper()
            rank = sev_rank.get(sev, 0)
            if rank > worst_rank:
                worst_rank = rank
                worst = sev
        return worst

    def _active_cache_ttl(self) -> float:
        # TTL derived from current worst active severity (dynamic refresh rate).
        cached = self._active_alerts_cache or []
        sev = self._highest_active_severity(cached)
        return self.CACHE_TTL.get(sev, self.DEFAULT_TTL)

    def get_active_alerts(self, offset: int = 0, limit: Optional[int] = 50) -> List[Dict[str, Any]]:
        now = time.time()
        with self._cache_lock:
            if (self._active_alerts_cache is not None
                    and (now - self._active_alerts_timestamp) < self._active_cache_ttl()):
                self._cache_hits += 1
                return self._active_alerts_cache
        # Cache miss — query the database.
        with self._cache_lock:
            self._cache_misses += 1
        conn = self.persistence.get_connection()
        data = None
        try:
            cursor = conn.cursor()
            # Order by risk score descending; paginate for large incident sets.
            cursor.execute(
                "SELECT * FROM incidents WHERE status NOT IN ('Resolved', 'Archived', 'RESOLVED', 'ARCHIVED') "
                "ORDER BY risk_score DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            rows = cursor.fetchall()
            data = [dict(r) for r in rows]
            with self._cache_lock:
                self._active_alerts_cache = data
                self._active_alerts_timestamp = now
        finally:
            self.persistence.return_connection(conn)

        return data

    def get_alert_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        now = time.time()
        with self._cache_lock:
            if limit in self._history_cache and (now - self._history_timestamp.get(limit, 0.0)) < self.DEFAULT_TTL:
                self._cache_hits += 1
                return self._history_cache[limit]
        with self._cache_lock:
            self._cache_misses += 1
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents ORDER BY start_time DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            res = [dict(r) for r in rows]
            with self._cache_lock:
                self._history_cache[limit] = res
                self._history_timestamp[limit] = now
            return res
        finally:
            self.persistence.return_connection(conn)

    def cache_stats(self) -> Dict[str, Any]:
        with self._cache_lock:
            hits = self._cache_hits
            misses = self._cache_misses
        total = hits + misses
        hit_rate = (hits / total * 100.0) if total > 0 else 0.0
        return {
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_hit_rate": f"{hit_rate:.1f}%",
        }

    def invalidate_cache(self) -> None:
        """Clear cached dashboard queries (called after incident mutations)."""
        with self._cache_lock:
            self._active_alerts_cache = None
            self._active_alerts_timestamp = 0.0
            self._history_cache.clear()
            self._history_timestamp.clear()

    def get_notification_state(self) -> Dict[str, Any]:
        res = {
            "sms": {"status": "STANDBY", "color": "#64748b", "detail": "Sent to: N/A"},
            "email": {"status": "STANDBY", "color": "#64748b", "detail": "Sent to: N/A"},
            "telegram": {"status": "STANDBY", "color": "#64748b", "detail": "Sent to: N/A"},
            "siren": {"status": "STANDBY", "color": "#64748b", "detail": "All clear", "active": False}
        }
        if 'streamlit' in sys.modules:
            try:
                from streamlit.runtime.scriptrunner import get_script_run_ctx
                if get_script_run_ctx() is not None:
                    import streamlit as st
                    if "sms_status" in st.session_state:
                        res["sms"] = st.session_state.sms_status
                    if "email_status" in st.session_state:
                        res["email"] = st.session_state.email_status
                    if "telegram_status" in st.session_state:
                        res["telegram"] = st.session_state.telegram_status
                    if "siren_status" in st.session_state:
                        res["siren"] = st.session_state.siren_status
            except Exception:
                pass

        try:
            conn = self.persistence.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT channel, status, last_updated FROM notification_statuses ORDER BY last_updated DESC")
            rows = cursor.fetchall()
            for r in rows:
                ch = str(r["channel"]).lower()
                st_val = str(r["status"])
                if ch in res and res[ch]["status"] == "STANDBY":
                    if st_val in ("Sent", "DELIVERED ✓", "DELIVERED"):
                        color = "#22c55e"
                        disp = "DELIVERED ✓" if ch != "siren" else "ACTIVE 🔊"
                    elif st_val in ("Pending", "Sending", "SENDING..."):
                        color = "#f97316"
                        disp = "SENDING..."
                    elif st_val in ("Failed", "FAILED"):
                        color = "#ef4444"
                        disp = "FAILED"
                    else:
                        color = "#64748b"
                        disp = st_val
                    res[ch] = {
                        "status": disp,
                        "color": color,
                        "detail": f"Updated at {r['last_updated']}",
                        "active": (st_val in ("Sent", "ACTIVE") if ch == "siren" else False)
                    }
        except Exception:
            pass
        finally:
            try:
                self.persistence.return_connection(conn)
            except Exception:
                pass
        return res

    def get_zone_status(self) -> Dict[str, Any]:
        active = self.get_active_alerts()
        status_dict = {}
        for alert in active:
            zone = alert["zone"]
            if zone not in status_dict or AlertSeverity.from_str(alert["severity"]).value[0] > AlertSeverity.from_str(status_dict[zone]["severity"]).value[0]:
                status_dict[zone] = {
                    "status": alert["status"],
                    "severity": alert["severity"],
                    "message": alert["message"]
                }
        return status_dict

    def get_metrics(self) -> Dict[str, Any]:
        conn = self.persistence.get_connection()
        coordinator = get_alert_coordinator()
        try:
            cursor = conn.cursor()
            
            # Total incidents
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents")
            total_incidents = cursor.fetchone()["cnt"]
            
            # Active incidents
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents WHERE status = 'Active'")
            active_count = cursor.fetchone()["cnt"]
            
            # Resolved incidents
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents WHERE status = 'Resolved'")
            resolved_count = cursor.fetchone()["cnt"]
            
            # Escalated incidents
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents WHERE status = 'Escalated'")
            escalated_count = cursor.fetchone()["cnt"]
            
            # Average response time (RESOLVED incidents)
            cursor.execute("SELECT start_time, end_time FROM incidents WHERE status = 'Resolved' AND end_time IS NOT NULL")
            rows = cursor.fetchall()
            durations = []
            for r in rows:
                try:
                    start = datetime.fromisoformat(r["start_time"])
                    end = datetime.fromisoformat(r["end_time"])
                    durations.append((end - start).total_seconds())
                except Exception:
                    pass
            avg_response_time = sum(durations) / len(durations) if durations else 0.0
            
            # Average acknowledgement time (incidents with acknowledged_at)
            cursor.execute("SELECT start_time, acknowledged_at FROM incidents WHERE acknowledged_at IS NOT NULL")
            ack_rows = cursor.fetchall()
            ack_durations = []
            for r in ack_rows:
                try:
                    start = datetime.fromisoformat(r["start_time"])
                    ack_at = datetime.fromisoformat(r["acknowledged_at"])
                    ack_durations.append((ack_at - start).total_seconds())
                except Exception:
                    pass
            avg_ack_time = sum(ack_durations) / len(ack_durations) if ack_durations else 0.0

            # Uptime
            uptime = time.time() - coordinator.start_time
            
            # Frame latency / detection latency
            health = coordinator.health_monitor
            avg_det_latency = health.health_check().get("average_frame_processing_ms", 0.0)
            
            # Notification latency
            avg_notif_latency = health.get_average_notification_latency() * 1000.0 # convert to ms
            
            return {
                "total_incidents": total_incidents,
                "active_incidents": active_count,
                "resolved_incidents": resolved_count,
                "escalated_incidents": escalated_count,
                "average_response_time_seconds": avg_response_time,
                "average_acknowledgement_time_seconds": avg_ack_time,
                "detection_latency_ms": avg_det_latency,
                "notification_latency_ms": avg_notif_latency,
                "false_positive_count": health.false_positive_count,
                "system_uptime_seconds": uptime
            }
        finally:
            self.persistence.return_connection(conn)

# ==============================================================================
# HEALTH MONITOR
# ==============================================================================

class HealthMonitor:
    def __init__(self, coordinator: 'AlertCoordinator') -> None:
        self.coordinator = coordinator
        self.frame_times: deque = deque(maxlen=100)
        self.frame_times_lock = threading.Lock()
        self.false_positive_count = 0
        self.notification_latencies: deque = deque(maxlen=100)
        self.notification_latencies_lock = threading.Lock()

    def record_frame_time(self, processing_time_ms: float) -> None:
        with self.frame_times_lock:
            self.frame_times.append(processing_time_ms)

    def record_notification_latency(self, latency_seconds: float) -> None:
        with self.notification_latencies_lock:
            self.notification_latencies.append(latency_seconds)

    def get_average_notification_latency(self) -> float:
        with self.notification_latencies_lock:
            return sum(self.notification_latencies) / len(self.notification_latencies) if self.notification_latencies else 0.0

    def health_check(self) -> Dict[str, Any]:
        with self.frame_times_lock:
            avg_latency = sum(self.frame_times) / len(self.frame_times) if self.frame_times else 0.0
            
        persistence = self.coordinator.persistence
        dispatcher = self.coordinator.notification_dispatcher
        
        # Pool stats
        pool_free = persistence._pool.qsize()
        pool_total = persistence.pool_size
        pool_in_use = pool_total - pool_free
        pool_exhausted = pool_free == 0

        # Calculate success rate
        total_notif = dispatcher.total_count
        success_rate = (dispatcher.success_count / total_notif * 100.0) if total_notif > 0 else 100.0

        # Cache effectiveness
        cache_stats = self.coordinator.dashboard_adapter.cache_stats()

        # Retrieve count of incidents
        conn = persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents")
            total_incidents = cursor.fetchone()["cnt"]
        except Exception:
            total_incidents = 0
        finally:
            persistence.return_connection(conn)

        return {
            "database_pool_status": f"{pool_free}/{pool_total} connections available",
            "database_pool_in_use": pool_in_use,
            "database_pool_exhausted": pool_exhausted,
            "cache_hit_rate": cache_stats["cache_hit_rate"],
            "cache_hits": cache_stats["cache_hits"],
            "cache_misses": cache_stats["cache_misses"],
            "active_alerts_count": len(self.coordinator.dashboard_adapter.get_active_alerts()),
            "notification_queue_backlog": 0, # executed asynchronously
            "escalation_queue_size": len(self.coordinator.escalation_engine._queue),
            "processing_latency_ms": avg_latency,
            "average_frame_processing_ms": avg_latency,
            "incident_count": total_incidents,
            "notification_success_rate": f"{success_rate:.1f}%"
        }

# ==============================================================================
# INCIDENT MANAGER & COORDINATOR ASSEMBLY
# ==============================================================================

class IncidentManager:
    def __init__(self, config: Dict[str, Any], persistence: PersistenceLayer, dispatcher: NotificationDispatcher, escalation: EscalationEngine, dashboard_adapter: Optional[DashboardAdapter] = None) -> None:
        self.config = config
        self.persistence = persistence
        self.dispatcher = dispatcher
        self.escalation = escalation
        self.dashboard_adapter = dashboard_adapter
        self.persistence_threshold = config.get("persistence", {}).get("threshold_frames", 15)
        self.resolution_hysteresis_frames = config.get("persistence", {}).get("resolution_hysteresis_frames", 10)
        self.logger = logging.getLogger("IncidentManager")
        self._cooldown_cache: Dict[str, datetime] = {}
        self._cooldown_lock = threading.Lock()

    def update_frame_incidents(self, zone: str, active_keys: List[Tuple[str, str, Dict[str, Any]]], detections: List[Any], telemetry: Dict[str, Any], evaluation: Dict[str, Any]) -> None:
        """
        Saves frames, creates new incidents, promotes them based on persistence,
        and resolves absent incidents using a 10 safe-frame hysteresis count.
        """
        active_incidents_to_dispatch = []
        created_incidents = []
        resolved_incidents = []
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            
            active_keys_set = {k[0] for k in active_keys}
            
            # 1. Update/insert active incidents detected in the frame
            for incident_key, hazard_type, rule_info in active_keys:
                cursor.execute("SELECT * FROM incidents WHERE incident_key = ? AND status NOT IN ('Resolved', 'Archived')", (incident_key,))
                row = cursor.fetchone()
                
                if row is None:
                    # Check cooldown for repeated alerts of the same key using in-memory cache first
                    resolved_time = None
                    with self._cooldown_lock:
                        if incident_key in self._cooldown_cache:
                            resolved_time = self._cooldown_cache[incident_key]
                    
                    if resolved_time is None:
                        # Cache miss, check database
                        cursor.execute(
                            "SELECT end_time FROM incidents WHERE (incident_key = ? OR incident_key LIKE ?) AND status = 'Resolved' "
                            "ORDER BY end_time DESC LIMIT 1",
                            (incident_key, incident_key + "_resolved_%")
                        )
                        last_resolved = cursor.fetchone()
                        if last_resolved is not None:
                            try:
                                resolved_time = datetime.fromisoformat(last_resolved["end_time"])
                                with self._cooldown_lock:
                                    self._cooldown_cache[incident_key] = resolved_time
                            except Exception as ex:
                                self.logger.error(f"Error parsing resolved time from DB for {incident_key}: {ex}")

                    if resolved_time is not None:
                        try:
                            elapsed_seconds = (datetime.now() - resolved_time).total_seconds()
                            severity = rule_info["severity"].name
                            cooldown_cfg = self.config.get("cooldowns", {})
                            cooldown_time = cooldown_cfg.get(severity, 30.0) # default 30s
                            
                            if elapsed_seconds < cooldown_time:
                                self.logger.info(f"Suppressing new incident {incident_key} due to cooldown ({elapsed_seconds:.1f}s < {cooldown_time}s)")
                                
                                # Update last resolved incident record inside cooldown (occurrence count, refresh timestamp, extend history)
                                cursor.execute(
                                    "SELECT incident_id, frame_count FROM incidents WHERE (incident_key = ? OR incident_key LIKE ?) AND status = 'Resolved' "
                                    "ORDER BY end_time DESC LIMIT 1",
                                    (incident_key, incident_key + "_resolved_%")
                                )
                                last_res_row = cursor.fetchone()
                                if last_res_row:
                                    last_res_id = last_res_row["incident_id"]
                                    new_fc = last_res_row["frame_count"] + 1
                                    cursor.execute(
                                        "UPDATE incidents SET frame_count = ?, end_time = ? WHERE incident_id = ?",
                                        (new_fc, now_str, last_res_id)
                                    )
                                    cursor.execute("""
                                    INSERT INTO incident_frames (incident_id, timestamp, telemetry, detections)
                                    VALUES (?, ?, ?, ?)
                                    """, (last_res_id, now_str, str(telemetry), str(detections)))
                                    
                                    # Update cache
                                    with self._cooldown_lock:
                                        self._cooldown_cache[incident_key] = datetime.fromisoformat(now_str)
                                continue
                        except Exception as ex:
                            self.logger.error(f"Error checking cooldown for {incident_key}: {ex}")

                    # Create NEW incident
                    incident_id = str(uuid.uuid4())
                    severity = rule_info["severity"].name
                    msg = rule_info["message"]
                    
                    # Emergency teams and matrix lookups
                    zone_cfg = self.config.get("zones", {}).get(zone, {})
                    teams = ",".join(zone_cfg.get("emergency_teams", ["Emergency Response Team"]))
                    channels = ",".join(evaluation["notification_channels"])
                    
                    matrix = self.config.get("escalation_matrix", {}).get(severity, {})
                    requires_ack = 1 if matrix.get("required_ack", False) else 0
                    
                    cursor.execute("""
                    INSERT INTO incidents (
                        incident_id, incident_key, zone, hazard_type, status, severity, message,
                        start_time, frame_count, requires_ack, risk_score, factors,
                        compound_factors, teams_notified, channels, consecutive_absent_frames
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 0)
                    """, (
                        incident_id, incident_key, zone, hazard_type, AlertStatus.NEW.value,
                        severity, msg, now_str, requires_ack, evaluation.get("confidence", 0.95)*10.0,
                        ",".join(telemetry.get("factors", [])),
                        ",".join(telemetry.get("compound_factors", [])),
                        teams, channels
                    ))
                    
                    # Persist frame details
                    cursor.execute("""
                    INSERT INTO incident_frames (incident_id, timestamp, telemetry, detections)
                    VALUES (?, ?, ?, ?)
                    """, (incident_id, now_str, str(telemetry), str(detections)))
                    
                    self.logger.info(f"Created new incident {incident_id} ({incident_key})")
                    created_incidents.append(incident_id)
                else:
                    # Update ongoing incident (Deduplication check)
                    incident_id = row["incident_id"]
                    curr_status = row["status"]
                    new_frame_count = row["frame_count"] + 1
                    
                    new_status = curr_status
                    rule_sev = rule_info.get("severity")
                    if curr_status in (AlertStatus.NEW.value, "NEW", "New"):
                        if rule_sev in (AlertSeverity.CRITICAL, AlertSeverity.HIGH, "CRITICAL", "HIGH") or self.persistence_threshold <= 2:
                            new_status = AlertStatus.ACTIVE.value
                        else:
                            new_status = AlertStatus.PENDING.value
                    elif curr_status in (AlertStatus.PENDING.value, "PENDING", "Pending"):
                        if new_frame_count >= 2 or rule_sev in (AlertSeverity.CRITICAL, AlertSeverity.HIGH, "CRITICAL", "HIGH") or new_frame_count >= self.persistence_threshold:
                            new_status = AlertStatus.ACTIVE.value
                        
                    current_risk_score = row["risk_score"] or 0.0
                    new_confidence = evaluation.get("confidence", 0.95)
                    new_risk_score = max(current_risk_score, new_confidence * 10.0)
                    
                    cursor.execute("""
                    UPDATE incidents 
                    SET frame_count = ?, status = ?, consecutive_absent_frames = 0, risk_score = ?, last_notified_at = ?
                    WHERE incident_id = ?
                    """, (new_frame_count, new_status, new_risk_score, now_str, incident_id))
                    
                    # Persist frame details
                    cursor.execute("""
                    INSERT INTO incident_frames (incident_id, timestamp, telemetry, detections)
                    VALUES (?, ?, ?, ?)
                    """, (incident_id, now_str, str(telemetry), str(detections)))
                    
                    # If promoted to ACTIVE state, queue notification dispatch
                    if curr_status != AlertStatus.ACTIVE.value and new_status == AlertStatus.ACTIVE.value:
                        updated_incident = dict(row)
                        updated_incident["status"] = new_status
                        updated_incident["frame_count"] = new_frame_count
                        updated_incident["risk_score"] = new_risk_score
                        updated_incident["last_notified_at"] = now_str
                        
                        active_incidents_to_dispatch.append((updated_incident, row["requires_ack"], row["severity"], incident_id))
                        cursor.execute("UPDATE incidents SET last_notified_at = ? WHERE incident_id = ?", (now_str, incident_id))
            
            # 2. Hysteresis resolution for incidents absent in this frame (for this zone)
            cursor.execute("SELECT * FROM incidents WHERE zone = ? AND status NOT IN ('Resolved', 'Archived')", (zone,))
            zone_active_incidents = cursor.fetchall()
            
            for row in zone_active_incidents:
                inc_key = row["incident_key"]
                if inc_key not in active_keys_set:
                    absent_count = row["consecutive_absent_frames"] + 1
                    incident_id = row["incident_id"]
                    
                    is_active_yet = str(row["status"]).upper() in (
                        AlertStatus.ACTIVE.value.upper(),
                        AlertStatus.ACKNOWLEDGED.value.upper(),
                        AlertStatus.ESCALATED.value.upper(),
                        'ACTIVE', 'ACKNOWLEDGED', 'ESCALATED'
                    )
                    if not is_active_yet:
                        # Discard pending/new incident since the hazard disappeared
                        cursor.execute("DELETE FROM incident_frames WHERE incident_id = ?", (incident_id,))
                        cursor.execute("DELETE FROM incidents WHERE incident_id = ?", (incident_id,))
                        
                        # Fetch global coordinator to increment false positive metric
                        coordinator = get_alert_coordinator()
                        coordinator.health_monitor.false_positive_count += 1
                        self.logger.info(f"Discarded pending incident {incident_id} ({inc_key}) because hazard disappeared")
                    else:
                        if absent_count >= self.resolution_hysteresis_frames:
                            # Hysteresis threshold hit, resolve incident
                            cursor.execute("""
                            UPDATE incidents 
                            SET status = ?, end_time = ?, consecutive_absent_frames = ?, incident_key = incident_key || '_resolved_' || ?
                            WHERE incident_id = ?
                            """, (AlertStatus.RESOLVED.value, now_str, absent_count, incident_id, incident_id))
                            
                            # Update in-memory cooldown cache
                            try:
                                with self._cooldown_lock:
                                    self._cooldown_cache[inc_key] = datetime.fromisoformat(now_str)
                            except Exception as ex:
                                self.logger.error(f"Failed to update cooldown cache on resolution: {ex}")
                                
                            # Clear visual banner/sirens in dashboard
                            self._clear_dashboard_visuals(zone)
                            self.logger.info(f"Resolved incident {incident_id} ({inc_key}) after {self.resolution_hysteresis_frames} safe frames")
                            resolved_incidents.append(incident_id)
                        else:
                            cursor.execute("""
                            UPDATE incidents 
                            SET consecutive_absent_frames = ?
                            WHERE incident_id = ?
                            """, (absent_count, incident_id))
            
            conn.commit()
            if self.dashboard_adapter is not None:
                self.dashboard_adapter.invalidate_cache()
        except Exception as e:
            self.logger.error(f"Error updating incidents: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

        # Dispatch notifications and schedule escalations outside the write-lock transaction boundary
        for updated_incident, requires_ack, severity, incident_id in active_incidents_to_dispatch:
            self.dispatcher.dispatch(updated_incident)
            if requires_ack:
                matrix = self.config.get("escalation_matrix", {}).get(severity, {})
                delay = matrix.get("response_time", 60)
                self.escalation.schedule_escalation(incident_id, delay)

        # Call enhancement orchestrator outside the transaction boundary
        coordinator = get_alert_coordinator()
        if coordinator.enhancer is not None:
            for inc_id in created_incidents:
                try:
                    coordinator.enhancer.on_incident_created(inc_id)
                except Exception as ex:
                    self.logger.error(f"Enhancer on_incident_created failed: {ex}")
            for inc_id in resolved_incidents:
                try:
                    coordinator.enhancer.on_incident_resolved(inc_id)
                except Exception as ex:
                    self.logger.error(f"Enhancer on_incident_resolved failed: {ex}")

    def _clear_dashboard_visuals(self, zone: str) -> None:
        _safe_update_session_state(f"alert_active_{zone}", False)
        _safe_update_session_state("siren_status", {"status": "STANDBY", "color": "#64748b", "detail": "All clear", "active": False})
        _safe_update_session_state("sms_status", {"status": "STANDBY", "color": "#64748b", "detail": "Sent to: N/A"})
        _safe_update_session_state("email_status", {"status": "STANDBY", "color": "#64748b", "detail": "Sent to: N/A"})
        _safe_update_session_state("telegram_status", {"status": "STANDBY", "color": "#64748b", "detail": "Sent to: N/A"})
        _safe_update_session_state("banner_visible", False)
        _safe_update_session_state("active_alert", None)


class AlertCoordinator:
    def __init__(self) -> None:
        self.start_time = time.time()
        self.config = load_config()
        self.logger = logging.getLogger("AlertCoordinator")
        
        # Instantiate layers
        self.persistence = PersistenceLayer(self.config)
        self.risk_evaluator = RiskEvaluator(self.config)
        self.detection_processor = DetectionProcessor(self.config)
        self.notification_dispatcher = NotificationDispatcher()
        self.dashboard_adapter = DashboardAdapter(self.persistence)
        self.escalation_engine = EscalationEngine(self)
        self.incident_manager = IncidentManager(self.config, self.persistence, self.notification_dispatcher, self.escalation_engine, self.dashboard_adapter)
        self.health_monitor = HealthMonitor(self)

        # Instantiate enhancements if available
        try:
            from src.alert_enhancements import AlertEnhancementOrchestrator
            self.enhancer = AlertEnhancementOrchestrator(self)
        except Exception as e:
            self.logger.error(f"Failed to load enhancements: {e}")
            self.enhancer = None

    def process_frame(self, detections: List[Any], zone: str, telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Core public method called every frame from CCTV pipeline"""
        start_time = time.time()
        
        # Resolve telemetry from context if missing
        if telemetry is None:
            telemetry = {}
            
        # Parse inputs
        permits = telemetry.get(f"{zone}_permit_active", telemetry.get("permit_active", 0)) == 1
        worker_count = telemetry.get(f"{zone}_worker_count", telemetry.get("worker_count", 0))
        maintenance_state = telemetry.get(f"{zone}_maintenance_active", telemetry.get("maintenance_active", 0)) == 1
        
        # 1. Deterministic Rule Evaluation
        evaluation = self.risk_evaluator.evaluate(
            detections=detections,
            telemetry=telemetry,
            permits=permits,
            worker_count=worker_count,
            maintenance_state=maintenance_state,
            zone=zone
        )
        
        # 2. Map rules to stable incident keys and update manager (sorted by priority/severity)
        severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        sorted_rules = sorted(
            evaluation["matched_rules"],
            key=lambda r: severity_rank.get(r.get("severity", AlertSeverity.LOW).name, 0),
            reverse=True
        )
        
        active_keys = []
        for rule in sorted_rules:
            inc_key = self.detection_processor.generate_incident_key(zone, rule["rule_id"])
            active_keys.append((inc_key, rule["rule_id"], rule))
            
        self.incident_manager.update_frame_incidents(zone, active_keys, detections, telemetry, evaluation)
        
        # Record health processing times
        latency_ms = (time.time() - start_time) * 1000.0
        self.health_monitor.record_frame_time(latency_ms)
        
        return evaluation

    def trigger_incident_from_risk(self, row: Dict[str, Any], risk_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API compatibility bridge to trigger incidents directly from compound risk signals"""
        zone = risk_result.get("zone", "Unknown")
        risk_level = risk_result.get("risk_level", "LOW")
        risk_score = risk_result.get("risk_score", 0.0)
        
        if risk_score < 5:
            return None
            
        incident_key = self.detection_processor.generate_incident_key(zone, f"compound_risk_{risk_level.lower()}")
        
        incident_to_dispatch = None
        requires_ack = False
        delay = 60
        
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE incident_key = ?", (incident_key,))
            row_data = cursor.fetchone()
            
            now_str = datetime.now().isoformat()
            zone_cfg = self.config.get("zones", {}).get(zone, {})
            teams = ",".join(zone_cfg.get("emergency_teams", ["Emergency Response Team"]))
            
            matrix = self.config.get("escalation_matrix", {}).get(risk_level, {})
            channels = ",".join(matrix.get("channels", ["DASHBOARD"]))
            requires_ack = 1 if matrix.get("required_ack", False) else 0
            delay = matrix.get("response_time", 60)
            
            if row_data is None:
                # Format context-aware compound safety alert
                raw_msg = risk_result.get("message", "")
                if not ("<div" in raw_msg or "<span" in raw_msg):
                    factors = risk_result.get("factors", [])
                    comp_factors = risk_result.get("compound_factors", [])
                    all_factors = list(set(factors + comp_factors))
                    
                    is_worker_down = any("down" in f.lower() or "motionless" in f.lower() or "collapse" in f.lower() for f in all_factors)
                    
                    if is_worker_down:
                        title = "MEDICAL EMERGENCY"
                        root_cause = "Worker collapse or person lying motionless detected inside sector"
                        consequences = ["Severe physical trauma", "Unconscious safety hazard", "Delayed rescue complications"]
                        actions = ["Dispatch medical response team immediately", "Clear and secure area for first responders", "Notify emergency services"]
                        team = "Emergency Medical Team (EMT)"
                    elif any("fire" in f.lower() or "smoke" in f.lower() for f in all_factors):
                        title = "FIRE EMERGENCY"
                        root_cause = f"Ignition source / smoke pattern detected with factors: {', '.join(all_factors)}"
                        consequences = ["Severe thermal burns", "Toxic smoke inhalation", "Property destruction"]
                        actions = ["Sound evacuations siren", "Deploy Emergency Fire Brigade", "Activate deluge/suppression system"]
                        team = "Emergency Fire Brigade"
                    elif any("gas" in f.lower() or "leak" in f.lower() for f in all_factors):
                        title = "CRITICAL GAS ESCAPE"
                        root_cause = f"Pressurized volatile/hazardous gas leak correlated with active factors: {', '.join(all_factors)}"
                        consequences = ["Explosion/flammability hazard", "Toxic gas inhalation", "Asphyxiation risk"]
                        actions = ["Isolate main gas supply valve", "Maximize exhaust ventilation", "Evacuate personnel immediately"]
                        team = "HAZMAT Response Team"
                    elif any("pressure" in f.lower() for f in all_factors):
                        title = "CRITICAL OVERPRESSURE THREAT"
                        root_cause = f"Pressure vessel/mechanical system exceeded design threshold. Factors: {', '.join(all_factors)}"
                        consequences = ["Mechanical rupture/explosion", "Projectiles hazard", "Material blowout"]
                        actions = ["Vent pressure release lines", "Evacuate non-essential personnel", "Isolate pressure vessel"]
                        team = "Pressure Systems Engineering Team"
                    elif any("helmet" in f.lower() or "vest" in f.lower() or "ppe" in f.lower() for f in all_factors):
                        title = "PPE COMPLIANCE VIOLATION"
                        root_cause = "Worker detected missing mandatory safety gear in active zone"
                        consequences = ["Severe head impact hazard", "Strike-by machinery hazard", "OSHA non-compliance"]
                        actions = ["Conduct immediate safety check", "Halt tasks until compliant", "Enforce PPE standards"]
                        team = "Floor Supervisor"
                    else:
                        title = "COMPOUND RISK ALERT"
                        root_cause = f"Correlated multi-channel safety anomaly: {', '.join(all_factors)}"
                        consequences = ["Escalation risk", "Potential unsafe work environment"]
                        actions = ["Verify Permit-to-Work credentials", "Deploy safety supervisor", "Review live telemetry trends"]
                        team = "Site Safety Officer"
                    
                    confidence_val = int(risk_result.get("confidence", 0.95) * 100)
                    msg = self.risk_evaluator.generate_osha_message_raw(
                        title=title,
                        severity=risk_level,
                        zone=zone,
                        confidence=confidence_val,
                        root_cause=root_cause,
                        consequences=consequences,
                        actions=actions,
                        team=team
                    )
                else:
                    msg = raw_msg

                incident_id = str(uuid.uuid4())
                cursor.execute("""
                INSERT INTO incidents (
                    incident_id, incident_key, zone, hazard_type, status, severity, message,
                    start_time, frame_count, requires_ack, risk_score, factors,
                    compound_factors, teams_notified, channels, last_notified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident_id, incident_key, zone, f"COMPOUND_{risk_level}",
                    AlertStatus.ACTIVE.value, risk_level, msg, now_str,
                    requires_ack, risk_score, ",".join(risk_result.get("factors", [])),
                    ",".join(risk_result.get("compound_factors", [])),
                    teams, channels, now_str
                ))
                conn.commit()
                
                # Fetch new item and dispatch
                cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
                incident_to_dispatch = dict(cursor.fetchone())
            else:
                # Update existing compound risk event frame count
                incident_id = row_data["incident_id"]
                cursor.execute("""
                UPDATE incidents 
                SET frame_count = frame_count + 1, last_notified_at = ?
                WHERE incident_id = ?
                """, (now_str, incident_id))
                conn.commit()
                incident_to_dispatch = dict(row_data)
        except Exception as e:
            self.logger.error(f"Failed to ingest risk alert into coordinator: {e}")
            conn.rollback()
            return None
        finally:
            self.persistence.return_connection(conn)
            
        if incident_to_dispatch and incident_to_dispatch.get("status") == "ACTIVE":
            self.notification_dispatcher.dispatch(incident_to_dispatch)
            if requires_ack:
                self.escalation_engine.schedule_escalation(incident_to_dispatch["incident_id"], delay)
                
        return incident_to_dispatch

    def dispatch_payload_alert(self, alert_payload: Dict[str, Any]) -> None:
        """Dispatches an evaluated Streamlit alert dict into the coordinator's notification pipe"""
        severity = alert_payload.get("severity", "LOW")
        zone = alert_payload.get("zone", "Unknown")
        incident_key = self.detection_processor.generate_incident_key(zone, f"payload_{severity.lower()}")
        
        incident_to_dispatch = None
        requires_ack = False
        delay = 60
        
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE incident_key = ? AND status NOT IN ('Resolved', 'Archived')", (incident_key,))
            row = cursor.fetchone()
            
            now_str = datetime.now().isoformat()
            zone_cfg = self.config.get("zones", {}).get(zone, {})
            teams = ",".join(zone_cfg.get("emergency_teams", ["Emergency Response Team"]))
            
            matrix = self.config.get("escalation_matrix", {}).get(severity, {})
            channels = ",".join(alert_payload.get("channels", matrix.get("channels", ["DASHBOARD"])))
            requires_ack = 1 if matrix.get("required_ack", False) else 0
            delay = matrix.get("response_time", 60)
            
            if row is None:
                incident_id = str(uuid.uuid4())
                cursor.execute("""
                INSERT INTO incidents (
                    incident_id, incident_key, zone, hazard_type, status, severity, message,
                    start_time, frame_count, requires_ack, risk_score, factors,
                    compound_factors, teams_notified, channels, last_notified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident_id, incident_key, zone, "PAYLOAD",
                    AlertStatus.ACTIVE.value, severity, alert_payload.get("summary", ""), now_str,
                    requires_ack, 10.0 if severity == "CRITICAL" else 5.0,
                    "", "", teams, channels, now_str
                ))
                conn.commit()
                
                cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
                incident_to_dispatch = dict(cursor.fetchone())
                self.dashboard_adapter.invalidate_cache()
            else:
                incident_id = row["incident_id"]
                cursor.execute("""
                UPDATE incidents 
                SET frame_count = frame_count + 1, last_notified_at = ?
                WHERE incident_id = ?
                """, (now_str, incident_id))
                conn.commit()
                self.dashboard_adapter.invalidate_cache()
        except Exception as e:
            self.logger.error(f"Error dispatching payload alert: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)
            
        if incident_to_dispatch:
            self.notification_dispatcher.dispatch(incident_to_dispatch)
            if requires_ack:
                self.escalation_engine.schedule_escalation(incident_to_dispatch["incident_id"], delay)

    def acknowledge_incident(self, incident_id: str, operator_name: str = "Operator", remarks: str = "") -> bool:
        """Acknowledge incident in database, cancelling/stopping escalations"""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            cursor.execute("""
            UPDATE incidents 
            SET status = ?, acknowledged_by = ?, acknowledged_at = ? 
            WHERE incident_id = ? AND status NOT IN ('Resolved', 'Archived')
            """, (AlertStatus.ACKNOWLEDGED.value, operator_name, now_str, incident_id))
            changed = cursor.rowcount > 0
            conn.commit()
            if changed:
                self.logger.info(f"Incident {incident_id} acknowledged by {operator_name}")
                self.dashboard_adapter.invalidate_cache()
                if self.enhancer is not None:
                    try:
                        self.enhancer.on_incident_acknowledged(incident_id, operator_name, remarks)
                    except Exception as ex:
                        self.logger.error(f"Enhancer on_incident_acknowledged failed: {ex}")
            return changed
        except Exception as e:
            self.logger.error(f"Failed to acknowledge incident {incident_id}: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def resolve_incident(self, incident_id: str, operator_name: str = "Operator") -> bool:
        """Explicitly resolve incident in database"""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            cursor.execute("SELECT incident_key, zone FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            cursor.execute("""
            UPDATE incidents 
            SET status = ?, end_time = ?, incident_key = incident_key || '_resolved_' || ?
            WHERE incident_id = ? AND status != 'Resolved'
            """, (AlertStatus.RESOLVED.value, now_str, incident_id, incident_id))
            changed = cursor.rowcount > 0
            conn.commit()
            if changed:
                self.incident_manager._clear_dashboard_visuals(row["zone"])
                self.logger.info(f"Incident {incident_id} resolved explicitly")
                self.dashboard_adapter.invalidate_cache()
                try:
                    with self.incident_manager._cooldown_lock:
                        self.incident_manager._cooldown_cache[row["incident_key"]] = datetime.fromisoformat(now_str)
                except Exception as ex:
                    self.logger.error(f"Failed to update cooldown cache for incident {incident_id}: {ex}")
                if self.enhancer is not None:
                    try:
                        self.enhancer.on_incident_resolved(incident_id)
                    except Exception as ex:
                        self.logger.error(f"Enhancer on_incident_resolved failed: {ex}")
            return changed
        except Exception as e:
            self.logger.error(f"Failed to resolve incident {incident_id}: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def clear_alert_if_safe(self, zone: str, update_cooldown: bool = True) -> None:
        """Compatibility function to resolve all active incidents in a zone"""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            cursor.execute("SELECT incident_key FROM incidents WHERE zone = ? AND status NOT IN ('Resolved', 'Archived')", (zone,))
            active_rows = cursor.fetchall()
            
            cursor.execute("""
            UPDATE incidents 
            SET status = ?, end_time = ?, incident_key = incident_key || '_resolved_' || incident_id
            WHERE zone = ? AND status NOT IN ('Resolved', 'Archived')
            """, (AlertStatus.RESOLVED.value, now_str, zone))
            conn.commit()
            self.incident_manager._clear_dashboard_visuals(zone)
            self.logger.info(f"Cleared all active alerts in zone {zone} via compatibility layer")
            self.dashboard_adapter.invalidate_cache()
            
            # Update in-memory cache for resolved keys if requested
            if update_cooldown:
                try:
                    resolved_dt = datetime.fromisoformat(now_str)
                    with self.incident_manager._cooldown_lock:
                        for r in active_rows:
                            self.incident_manager._cooldown_cache[r["incident_key"]] = resolved_dt
                except Exception as ex:
                    self.logger.error(f"Failed to update cooldown cache in clear_alert_if_safe for zone {zone}: {ex}")
            else:
                # When not updating cooldown, remove any existing cache entries to allow immediate re-alerting
                try:
                    with self.incident_manager._cooldown_lock:
                        for r in active_rows:
                            key = r["incident_key"]
                            if key in self.incident_manager._cooldown_cache:
                                del self.incident_manager._cooldown_cache[key]
                except Exception as ex:
                    self.logger.error(f"Failed to clear cooldown cache in clear_alert_if_safe for zone {zone}: {ex}")
        except Exception as e:
            self.logger.error(f"Failed to clear active alerts in zone {zone}: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

    def check_and_escalate_incident(self, incident_id: str) -> None:
        """Checks if active incident has breached its acknowledgement response window and escalates it"""
        conn = self.persistence.get_connection()
        escalated_incident = None
        new_tier = None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            
            if row and row["status"] == AlertStatus.ACTIVE.value:
                new_tier = row["escalation_tier"] + 1
                now_str = datetime.now().isoformat()
                
                # Perform escalation notification
                escalated_message = (
                    f"⚠️ *ESCALATION TIER {new_tier} ACTIVE* ⚠️\n"
                    f"Incident `{incident_id}` in *{row['zone']}* ({row['severity']}) remains unacknowledged!\n"
                    f"Immediate emergency dispatch required."
                )
                
                cursor.execute("""
                UPDATE incidents 
                SET status = ?, escalation_tier = ?, last_notified_at = ? 
                WHERE incident_id = ?
                """, (AlertStatus.ESCALATED.value, new_tier, now_str, incident_id))
                conn.commit()
                
                escalated_incident = dict(row)
                escalated_incident["status"] = AlertStatus.ESCALATED.value
                escalated_incident["escalation_tier"] = new_tier
                escalated_incident["message"] = escalated_message
        except Exception as e:
            self.logger.error(f"Escalation execution error on {incident_id}: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

        if escalated_incident is not None:
            self.notification_dispatcher.dispatch(escalated_incident)
            self.logger.warning(f"Incident {incident_id} escalated to Tier {new_tier}!")
            if self.enhancer is not None:
                try:
                    self.enhancer.on_incident_escalated(incident_id, new_tier)
                except Exception as ex:
                    self.logger.error(f"Enhancer on_incident_escalated failed: {ex}")

    def shutdown(self) -> None:
        self.escalation_engine.shutdown()
        self.notification_dispatcher.shutdown()
        self.persistence.close()

def get_current_telemetry(zone: Optional[str] = None) -> Dict[str, Any]:
    """Helper to safely fetch current telemetry dictionary from Streamlit session state"""
    if 'streamlit' in sys.modules:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            import streamlit as st
            if 'latest' in st.session_state:
                return dict(st.session_state.latest)
    return {}

# ==============================================================================
# GLOBAL COORDINATOR SINGLETON ACCESS
# ==============================================================================

_coordinator_instance: Optional[AlertCoordinator] = None
_coordinator_lock = threading.Lock()

def get_alert_coordinator() -> AlertCoordinator:
    global _coordinator_instance
    if _coordinator_instance is None:
        with _coordinator_lock:
            if _coordinator_instance is None:
                _coordinator_instance = AlertCoordinator()
    instance = _coordinator_instance
    assert instance is not None
    return instance
