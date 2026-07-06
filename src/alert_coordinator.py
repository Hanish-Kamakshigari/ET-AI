"""
SurakshaAI Unified Alerting System - AlertCoordinator Architecture
Single source of truth for the entire alerting lifecycle.
"""

import os
import sys
import uuid
import yaml
import time
import sqlite3
import logging
import threading
from queue import Queue, Empty, Full
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# ENUMS & DATACLASSES
# ==============================================================================

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
    def __init__(self, config: Dict[str, Any]):
        db_cfg = config.get("database", {})
        self.db_path = db_cfg.get("db_path", "data/alerts_v2.db")
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

    def return_connection(self, conn: sqlite3.Connection):
        try:
            self._pool.put(conn, block=False)
        except Full:
            conn.close()

    def _init_db(self):
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
            cursor.execute("SELECT * FROM incidents WHERE incident_key = ?", (incident_key,))
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

    def close(self):
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
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.rules_config = config.get("rules", {})
        self.escalation_matrix = config.get("escalation_matrix", {})

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
            pressure = telemetry.get(f"{zone}_pressure_bar", telemetry.get("pressure", 0.0))
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

        # 8. Action plan recommendations (prescriptive)
        actions = []
        action_map = {
            "FIRE_SMOKE": "Sound siren, mobilize Fire Response Team, evacuate zone immediately.",
            "GAS_LEAK": "Evacuate area, stop maintenance, call Gas Response Team, isolate gas line.",
            "ZONE_INTRUSION": "Dispatch Security Team to escort intruder out of restricted zone.",
            "GAS_CRITICAL": "Isolate gas sources, evacuate area immediately, maximize ventilation.",
            "GAS_ELEVATED": "Deploy EHS officer to investigate gas source, restrict area access.",
            "TEMPERATURE_CRITICAL": "Initiate cooling protocols, shut down overheated systems safely.",
            "OVERPRESSURE": "Vent lines safely, isolate pressure vessels, evacuate critical radius.",
            "PPE_VIOLATION": "Conduct safety check, halt non-compliant tasks, enforce PPE standards."
        }
        for rule in matched_rules:
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
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def generate_incident_key(self, zone: str, hazard_type: str) -> str:
        """Deduplicates incidents by mapping zone + hazard to a stable key (e.g. Zone_A:fire)"""
        clean_hazard = hazard_type.lower().replace(" ", "_")
        return f"{zone}:{clean_hazard}"

# ==============================================================================
# NOTIFICATION DISPATCHER (Registry Pattern, Threaded/Async Dispatch)
# ==============================================================================

class NotificationChannel:
    def send(self, incident: Dict[str, Any]) -> bool:
        raise NotImplementedError

class DashboardChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        import sys
        if 'streamlit' in sys.modules:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                # Write notification statuses into session state to sync with dashboard
                timestamp = datetime.fromisoformat(incident["start_time"]).strftime("%H:%M:%S")
                st.session_state.active_alert = {
                    "severity": incident["severity"],
                    "summary": incident["message"],
                    "zone": incident["zone"],
                    "timestamp": timestamp,
                    "channels": incident["channels"].split(",") if incident["channels"] else []
                }
                st.session_state.banner_visible = True
                
                # Keep global alert log in sync
                if "alert_log" not in st.session_state:
                    st.session_state.alert_log = []
                
                # Check if this alert is already the latest to prevent duplicate log entries
                log = st.session_state.alert_log
                if not log or log[0].get("id") != incident["incident_id"]:
                    log.insert(0, {
                        "id": incident["incident_id"],
                        "severity": incident["severity"],
                        "zone": incident["zone"],
                        "message": incident["message"],
                        "timestamp": timestamp,
                        "status": incident["status"],
                        "channels": incident["channels"].split(",") if incident["channels"] else []
                    })
                    st.session_state.alert_log = log[:100] # Cap at 100
        return True

class EmailChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        logger = logging.getLogger("EmailChannel")
        sender = os.environ.get("SENDER_EMAIL")
        password = os.environ.get("SENDER_PASSWORD")
        recipient = os.environ.get("ALERT_RECIPIENT_EMAIL", "operator@plant.com")
        
        # Simulate Streamlit status if active
        import sys
        if 'streamlit' in sys.modules:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                st.session_state.email_status = {
                    "status": "SENT ✓",
                    "color": "#22c55e",
                    "detail": f"Sent to: {recipient} at {datetime.now().strftime('%H:%M:%S')}"
                }
            
        if not sender or not password:
            logger.info(f"[EMAIL SIMULATION] Send to: {recipient} | Incident: {incident['message']}")
            return True
            
        # Real SMTP implementation in background
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import smtplib
            
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
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
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
        
        # Simulate Streamlit status if active
        import sys
        if 'streamlit' in sys.modules:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                st.session_state.sms_status = {
                    "status": "DELIVERED ✓",
                    "color": "#22c55e",
                    "detail": f"Sent to Telegram Chat at {datetime.now().strftime('%H:%M:%S')}"
                }
            
        if not token or not chat_id:
            logger.info(f"[TELEGRAM SIMULATION] Chat ID: {chat_id or 'admin_chat'} | Incident: {incident['message']}")
            return True
            
        try:
            import requests
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

class SirenChannel(NotificationChannel):
    def send(self, incident: Dict[str, Any]) -> bool:
        import sys
        if 'streamlit' in sys.modules:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                st.session_state.siren_status = {
                    "status": "ACTIVE 🔊",
                    "color": "#ef4444",
                    "detail": f"Zone: {incident['zone']} — SOUNDING",
                    "active": True
                }
        return True

class NotificationDispatcher:
    def __init__(self):
        self._channels: Dict[str, NotificationChannel] = {}
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.logger = logging.getLogger("NotificationDispatcher")
        
        # Track metrics
        self.success_count = 0
        self.total_count = 0
        
        # Register default channels
        self.register_channel("DASHBOARD", DashboardChannel())
        self.register_channel("EMAIL", EmailChannel())
        self.register_channel("TELEGRAM", TelegramChannel())
        self.register_channel("SMS", TelegramChannel()) # SMS fallback to Telegram bot in simulation
        self.register_channel("PHONE", TelegramChannel()) # Phone fallback to Telegram bot
        self.register_channel("SIREN", SirenChannel())

    def register_channel(self, name: str, channel: NotificationChannel):
        self._channels[name.upper()] = channel

    def dispatch(self, incident: Dict[str, Any]) -> List[str]:
        """Dispatches notification through all specified channels asynchronously (<100ms)"""
        channels_str = incident.get("channels", "DASHBOARD")
        target_channels = [ch.strip().upper() for ch in channels_str.split(",") if ch.strip()]
        
        # Capture the current Streamlit context to pass to background threads
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()

        futures = []
        for ch_name in target_channels:
            ch = self._channels.get(ch_name)
            if ch:
                self.total_count += 1
                futures.append(self.executor.submit(self._safe_send, ch_name, ch, incident, ctx))
            else:
                self.logger.warning(f"Notification channel {ch_name} not registered")
        
        return target_channels

    def _safe_send(self, name: str, channel: NotificationChannel, incident: Dict[str, Any], ctx=None):
        try:
            if ctx is not None:
                from streamlit.runtime.scriptrunner import add_script_run_ctx
                add_script_run_ctx(ctx=ctx)
            success = channel.send(incident)
            if success:
                self.success_count += 1
            else:
                self.logger.error(f"Failed to dispatch to channel: {name}")
        except Exception as e:
            self.logger.error(f"Exception during notification dispatch on {name}: {e}")

    def shutdown(self):
        self.executor.shutdown(wait=False)

# ==============================================================================
# ESCALATION ENGINE (Priority Queue, Event-Driven Scheduler)
# ==============================================================================

class EscalationEngine:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._queue: List[Tuple[float, str]] = [] # list of (run_at_timestamp, incident_id)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._running = True
        self.logger = logging.getLogger("EscalationEngine")
        
        self._thread = threading.Thread(target=self._run, daemon=True, name="EscalationThread")
        self._thread.start()

    def schedule_escalation(self, incident_id: str, delay_seconds: float):
        run_at = time.time() + delay_seconds
        import heapq
        with self._lock:
            heapq.heappush(self._queue, (run_at, incident_id))
            self.logger.info(f"Scheduled escalation check for incident {incident_id} in {delay_seconds} seconds")
            self._cond.notify()

    def _run(self):
        import heapq
        while self._running:
            with self._lock:
                if not self._queue:
                    self._cond.wait(timeout=1.0)
                    continue
                
                run_at, incident_id = self._queue[0]
                now = time.time()
                if now < run_at:
                    self._cond.wait(timeout=run_at - now)
                    continue
                
                heapq.heappop(self._queue)
                
            # Perform escalation check
            try:
                self.coordinator.check_and_escalate_incident(incident_id)
            except Exception as e:
                self.logger.error(f"Error in escalation evaluation: {e}")

    def shutdown(self):
        with self._lock:
            self._running = False
            self._cond.notify()

# ==============================================================================
# DASHBOARD ADAPTER
# ==============================================================================

class DashboardAdapter:
    def __init__(self, persistence: PersistenceLayer):
        self.persistence = persistence

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE status NOT IN ('RESOLVED', 'ARCHIVED')")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            self.persistence.return_connection(conn)

    def get_alert_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents ORDER BY start_time DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            self.persistence.return_connection(conn)

    def get_notification_state(self) -> Dict[str, Any]:
        import sys
        if 'streamlit' in sys.modules:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                return {
                    "sms": st.session_state.get("sms_status", {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"}),
                    "email": st.session_state.get("email_status", {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"}),
                    "siren": st.session_state.get("siren_status", {"status": "STANDBY", "color": "#6b7280", "detail": "All clear", "active": False})
                }
        return {
            "sms": {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"},
            "email": {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"},
            "siren": {"status": "STANDBY", "color": "#6b7280", "detail": "All clear", "active": False}
        }

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
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents WHERE status NOT IN ('RESOLVED', 'ARCHIVED')")
            active_count = cursor.fetchone()["cnt"]
            
            cursor.execute("SELECT COUNT(*) as cnt FROM incidents WHERE status = 'RESOLVED'")
            resolved_count = cursor.fetchone()["cnt"]
            
            cursor.execute("SELECT SUM(frame_count) as total_frames FROM incidents")
            total_frames = cursor.fetchone()["total_frames"] or 0
            
            return {
                "active_incidents": active_count,
                "resolved_incidents": resolved_count,
                "total_frames_processed": total_frames
            }
        finally:
            self.persistence.return_connection(conn)

# ==============================================================================
# HEALTH MONITOR
# ==============================================================================

class HealthMonitor:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.frame_times = []
        self.frame_times_lock = threading.Lock()

    def record_frame_time(self, processing_time_ms: float):
        with self.frame_times_lock:
            self.frame_times.append(processing_time_ms)
            if len(self.frame_times) > 100:
                self.frame_times.pop(0)

    def health_check(self) -> Dict[str, Any]:
        with self.frame_times_lock:
            avg_latency = sum(self.frame_times) / len(self.frame_times) if self.frame_times else 0.0
            
        persistence = self.coordinator.persistence
        dispatcher = self.coordinator.notification_dispatcher
        
        # Pool stats
        pool_free = persistence._pool.qsize()
        
        # Calculate success rate
        total_notif = dispatcher.total_count
        success_rate = (dispatcher.success_count / total_notif * 100.0) if total_notif > 0 else 100.0
        
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
            "database_pool_status": f"{pool_free}/{persistence.pool_size} connections available",
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
    def __init__(self, config: Dict[str, Any], persistence: PersistenceLayer, dispatcher: NotificationDispatcher, escalation: EscalationEngine):
        self.config = config
        self.persistence = persistence
        self.dispatcher = dispatcher
        self.escalation = escalation
        self.persistence_threshold = config.get("persistence", {}).get("threshold_frames", 15)
        self.logger = logging.getLogger("IncidentManager")

    def update_frame_incidents(self, zone: str, active_keys: List[Tuple[str, str, Dict[str, Any]]], detections: List[Any], telemetry: Dict[str, Any], evaluation: Dict[str, Any]):
        """
        Saves frames, creates new incidents, promotes them based on persistence,
        and resolves absent incidents using a 10 safe-frame hysteresis count.
        """
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            
            active_keys_set = {k[0] for k in active_keys}
            
            # 1. Update/insert active incidents detected in the frame
            for incident_key, hazard_type, rule_info in active_keys:
                cursor.execute("SELECT * FROM incidents WHERE incident_key = ?", (incident_key,))
                row = cursor.fetchone()
                
                if row is None:
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
                else:
                    # Update ongoing incident
                    incident_id = row["incident_id"]
                    curr_status = row["status"]
                    new_frame_count = row["frame_count"] + 1
                    
                    new_status = curr_status
                    if curr_status == AlertStatus.NEW.value:
                        new_status = AlertStatus.PENDING.value
                    elif curr_status == AlertStatus.PENDING.value and new_frame_count >= self.persistence_threshold:
                        new_status = AlertStatus.ACTIVE.value
                        
                    cursor.execute("""
                    UPDATE incidents 
                    SET frame_count = ?, status = ?, consecutive_absent_frames = 0
                    WHERE incident_id = ?
                    """, (new_frame_count, new_status, incident_id))
                    
                    # Persist frame details
                    cursor.execute("""
                    INSERT INTO incident_frames (incident_id, timestamp, telemetry, detections)
                    VALUES (?, ?, ?, ?)
                    """, (incident_id, now_str, str(telemetry), str(detections)))
                    
                    # If promoted to ACTIVE state, trigger initial notification and escalation timer
                    if curr_status != AlertStatus.ACTIVE.value and new_status == AlertStatus.ACTIVE.value:
                        updated_incident = dict(row)
                        updated_incident["status"] = new_status
                        updated_incident["frame_count"] = new_frame_count
                        
                        # Dispatch notifications
                        self.dispatcher.dispatch(updated_incident)
                        
                        # Schedule escalation if required
                        if row["requires_ack"]:
                            matrix = self.config.get("escalation_matrix", {}).get(row["severity"], {})
                            delay = matrix.get("response_time", 60)
                            self.escalation.schedule_escalation(incident_id, delay)
                            
                        cursor.execute("UPDATE incidents SET last_notified_at = ? WHERE incident_id = ?", (now_str, incident_id))
            
            # 2. Hysteresis resolution for incidents absent in this frame (for this zone)
            cursor.execute("SELECT * FROM incidents WHERE zone = ? AND status NOT IN ('RESOLVED', 'ARCHIVED')", (zone,))
            zone_active_incidents = cursor.fetchall()
            
            for row in zone_active_incidents:
                inc_key = row["incident_key"]
                if inc_key not in active_keys_set:
                    absent_count = row["consecutive_absent_frames"] + 1
                    incident_id = row["incident_id"]
                    
                    if absent_count >= 10:
                        # Hysteresis threshold hit, resolve incident
                        cursor.execute("""
                        UPDATE incidents 
                        SET status = ?, end_time = ?, consecutive_absent_frames = ?
                        WHERE incident_id = ?
                        """, (AlertStatus.RESOLVED.value, now_str, absent_count, incident_id))
                        
                        # Clear visual banner/sirens in dashboard
                        self._clear_dashboard_visuals(zone)
                        self.logger.info(f"Resolved incident {incident_id} ({inc_key}) after 10 safe frames")
                    else:
                        cursor.execute("""
                        UPDATE incidents 
                        SET consecutive_absent_frames = ?
                        WHERE incident_id = ?
                        """, (absent_count, incident_id))
                        
            conn.commit()
        except Exception as e:
            self.logger.error(f"Error updating incidents: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

    def _clear_dashboard_visuals(self, zone: str):
        import sys
        if 'streamlit' in sys.modules:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx() is not None:
                import streamlit as st
                st.session_state[f"alert_active_{zone}"] = False
                # If all zones are clear, reset the visual warnings
                active_zones = [k for k, v in st.session_state.items() if k.startswith("alert_active_") and v]
                if not active_zones:
                    st.session_state.siren_status = {"status": "STANDBY", "color": "#6b7280", "detail": "All clear", "active": False}
                    st.session_state.sms_status = {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"}
                    st.session_state.email_status = {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"}
                    st.session_state.banner_visible = False
                    st.session_state.active_alert = None


class AlertCoordinator:
    def __init__(self):
        self.config = load_config()
        self.logger = logging.getLogger("AlertCoordinator")
        
        # Instantiate layers
        self.persistence = PersistenceLayer(self.config)
        self.risk_evaluator = RiskEvaluator(self.config)
        self.detection_processor = DetectionProcessor(self.config)
        self.notification_dispatcher = NotificationDispatcher()
        self.escalation_engine = EscalationEngine(self)
        self.incident_manager = IncidentManager(self.config, self.persistence, self.notification_dispatcher, self.escalation_engine)
        self.dashboard_adapter = DashboardAdapter(self.persistence)
        self.health_monitor = HealthMonitor(self)

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
        
        # 2. Map rules to stable incident keys and update manager
        active_keys = []
        for rule in evaluation["matched_rules"]:
            inc_key = self.detection_processor.generate_incident_key(zone, rule["rule_id"])
            active_keys.append((inc_key, rule["rule_id"], rule))
            
        self.incident_manager.update_frame_incidents(zone, active_keys, detections, telemetry, evaluation)
        
        # Record health processing times
        latency_ms = (time.time() - start_time) * 1000.0
        self.health_monitor.record_frame_time(latency_ms)
        
        return evaluation

    def trigger_incident_from_risk(self, row: Any, risk_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API compatibility bridge to trigger incidents directly from compound risk signals"""
        zone = risk_result.get("zone", "Unknown")
        risk_level = risk_result.get("risk_level", "LOW")
        risk_score = risk_result.get("risk_score", 0.0)
        
        if risk_score < 5:
            return None
            
        incident_key = self.detection_processor.generate_incident_key(zone, f"compound_risk_{risk_level.lower()}")
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
            
            if row_data is None:
                incident_id = str(uuid.uuid4())
                cursor.execute("""
                INSERT INTO incidents (
                    incident_id, incident_key, zone, hazard_type, status, severity, message,
                    start_time, frame_count, requires_ack, risk_score, factors,
                    compound_factors, teams_notified, channels, last_notified_at
                ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident_id, incident_key, zone, f"COMPOUND_{risk_level}",
                    risk_level, risk_result.get("message", ""), now_str,
                    requires_ack, risk_score, ",".join(risk_result.get("factors", [])),
                    ",".join(risk_result.get("compound_factors", [])),
                    teams, channels, now_str
                ))
                conn.commit()
                
                # Fetch new item and dispatch
                cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
                incident = dict(cursor.fetchone())
                self.notification_dispatcher.dispatch(incident)
                
                # Schedule escalation
                if requires_ack:
                    self.escalation_engine.schedule_escalation(incident_id, matrix.get("response_time", 60))
                    
                return incident
            else:
                # Update existing compound risk event frame count
                incident_id = row_data["incident_id"]
                cursor.execute("""
                UPDATE incidents 
                SET frame_count = frame_count + 1, last_notified_at = ?
                WHERE incident_id = ?
                """, (now_str, incident_id))
                conn.commit()
                return dict(row_data)
        except Exception as e:
            self.logger.error(f"Failed to ingest risk alert into coordinator: {e}")
            conn.rollback()
            return None
        finally:
            self.persistence.return_connection(conn)

    def dispatch_payload_alert(self, alert_payload: dict):
        """Dispatches an evaluated Streamlit alert dict into the coordinator's notification pipe"""
        severity = alert_payload.get("severity", "LOW")
        zone = alert_payload.get("zone", "Unknown")
        incident_key = self.detection_processor.generate_incident_key(zone, f"payload_{severity.lower()}")
        
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE incident_key = ?", (incident_key,))
            row = cursor.fetchone()
            
            now_str = datetime.now().isoformat()
            zone_cfg = self.config.get("zones", {}).get(zone, {})
            teams = ",".join(zone_cfg.get("emergency_teams", ["Emergency Response Team"]))
            
            matrix = self.config.get("escalation_matrix", {}).get(severity, {})
            channels = ",".join(alert_payload.get("channels", matrix.get("channels", ["DASHBOARD"])))
            requires_ack = 1 if matrix.get("required_ack", False) else 0
            
            if row is None:
                incident_id = str(uuid.uuid4())
                cursor.execute("""
                INSERT INTO incidents (
                    incident_id, incident_key, zone, hazard_type, status, severity, message,
                    start_time, frame_count, requires_ack, risk_score, factors,
                    compound_factors, teams_notified, channels, last_notified_at
                ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident_id, incident_key, zone, "PAYLOAD",
                    severity, alert_payload.get("summary", ""), now_str,
                    requires_ack, 10.0 if severity == "CRITICAL" else 5.0,
                    "", "", teams, channels, now_str
                ))
                conn.commit()
                
                cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
                incident = dict(cursor.fetchone())
                self.notification_dispatcher.dispatch(incident)
                
                if requires_ack:
                    self.escalation_engine.schedule_escalation(incident_id, matrix.get("response_time", 60))
            else:
                incident_id = row["incident_id"]
                cursor.execute("""
                UPDATE incidents 
                SET frame_count = frame_count + 1, last_notified_at = ?
                WHERE incident_id = ?
                """, (now_str, incident_id))
                conn.commit()
        except Exception as e:
            self.logger.error(f"Error dispatching payload alert: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

    def acknowledge_incident(self, incident_id: str, operator_name: str = "Operator") -> bool:
        """Acknowledge incident in database, cancelling/stopping escalations"""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            cursor.execute("""
            UPDATE incidents 
            SET status = ?, acknowledged_by = ?, acknowledged_at = ? 
            WHERE incident_id = ? AND status NOT IN ('RESOLVED', 'ARCHIVED')
            """, (AlertStatus.ACKNOWLEDGED.value, operator_name, now_str, incident_id))
            changed = cursor.rowcount > 0
            conn.commit()
            if changed:
                self.logger.info(f"Incident {incident_id} acknowledged by {operator_name}")
            return changed
        except Exception as e:
            self.logger.error(f"Failed to acknowledge incident {incident_id}: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def resolve_incident(self, incident_id: str) -> bool:
        """Explicitly resolve incident in database"""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            cursor.execute("SELECT zone FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            cursor.execute("""
            UPDATE incidents 
            SET status = ?, end_time = ? 
            WHERE incident_id = ? AND status != 'RESOLVED'
            """, (AlertStatus.RESOLVED.value, now_str, incident_id))
            changed = cursor.rowcount > 0
            conn.commit()
            if changed:
                self.incident_manager._clear_dashboard_visuals(row["zone"])
                self.logger.info(f"Incident {incident_id} resolved explicitly")
            return changed
        except Exception as e:
            self.logger.error(f"Failed to resolve incident {incident_id}: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def clear_alert_if_safe(self, zone: str):
        """Compatibility function to resolve all active incidents in a zone"""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            now_str = datetime.now().isoformat()
            cursor.execute("""
            UPDATE incidents 
            SET status = ?, end_time = ? 
            WHERE zone = ? AND status NOT IN ('RESOLVED', 'ARCHIVED')
            """, (AlertStatus.RESOLVED.value, now_str, zone))
            conn.commit()
            self.incident_manager._clear_dashboard_visuals(zone)
            self.logger.info(f"Cleared all active alerts in zone {zone} via compatibility layer")
        except Exception as e:
            self.logger.error(f"Failed to clear active alerts in zone {zone}: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

    def check_and_escalate_incident(self, incident_id: str):
        """Checks if active incident has breached its acknowledgement response window and escalates it"""
        conn = self.persistence.get_connection()
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
                
                self.notification_dispatcher.dispatch(escalated_incident)
                self.logger.warning(f"Incident {incident_id} escalated to Tier {new_tier}!")
        except Exception as e:
            self.logger.error(f"Escalation execution error on {incident_id}: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

    def shutdown(self):
        self.escalation_engine.shutdown()
        self.notification_dispatcher.shutdown()
        self.persistence.close()

def get_current_telemetry(zone: Optional[str] = None) -> Dict[str, Any]:
    """Helper to safely fetch current telemetry dictionary from Streamlit session state"""
    import sys
    if 'streamlit' in sys.modules:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            import streamlit as st
            if 'latest' in st.session_state:
                return st.session_state.latest
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
