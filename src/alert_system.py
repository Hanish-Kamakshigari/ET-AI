"""
PHASE 4: Alert & Notification System
Multi-channel alerting with escalation matrix and SQLite persistence
"""

import logging
import sqlite3
import os
import smtplib
import threading
import time
import requests
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

class AlertStatus(Enum):
    TRIGGERED = "Triggered"    # Just detected
    ACTIVE = "Active"          # Validated and ongoing
    ACKNOWLEDGED = "Acknowledged" # Operator knows about it
    RESOLVED = "Resolved"      # Danger is gone

class AlertSeverity(Enum):
    LOW = (1, "#3b82f6", "Low")
    MEDIUM = (2, "#eab308", "Medium")
    HIGH = (3, "#f97316", "High")
    CRITICAL = (4, "#ef4444", "Critical")

@dataclass
class SafetyAlert:
    alert_id: str
    severity: AlertSeverity
    message: str
    zone: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime = None
    status: AlertStatus = AlertStatus.TRIGGERED
    acknowledged_by: str = None
    frame_counter: int = 1

    @property
    def duration(self):
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

class AlertManager:
    def __init__(self):
        self.active_alerts = {}  # {alert_id: SafetyAlert}
        self.history = []         # List of resolved alerts for auditing
        self.persistence_threshold = 15 # Frames required to trigger alert

    def map_severity(self, label):
        mapping = {
            "no_helmet": AlertSeverity.MEDIUM,
            "no_vest": AlertSeverity.MEDIUM,
            "gas_leak": AlertSeverity.HIGH,
            "overheating": AlertSeverity.CRITICAL,
            "fire": AlertSeverity.CRITICAL,
            "smoke": AlertSeverity.CRITICAL,
            "zone_violation": AlertSeverity.CRITICAL,
            "overpressure": AlertSeverity.HIGH,
        }
        return mapping.get(label, None)

    def get_message(self, label):
        msg_map = {
            "no_helmet": "Worker detected without helmet",
            "no_vest": "Worker detected without hi-vis vest",
            "gas_leak": "Gas leak detected by sensor overlay",
            "overheating": "Critical equipment overheating detected",
            "fire": "Fire hazard detected in active area",
            "smoke": "Smoke detected in active area",
            "zone_violation": "Unauthorized worker in restricted zone",
            "overpressure": "OVERPRESSURE WARNING — Gauge in red zone",
        }
        return msg_map.get(label, f"Safety violation: {label} detected")

    def update(self, current_detections, zone):
        """
        The main loop called every frame.
        """
        # 1. Handle New/Ongoing Detections
        detected_ids = []
        for det in current_detections:
            is_violation = getattr(det, 'zone_violation', False)
            label = "zone_violation" if is_violation else det.label
            
            severity = self.map_severity(label)
            if severity is None:
                continue
                
            alert_id = f"{zone}_{label}"
            detected_ids.append(alert_id)

            if alert_id not in self.active_alerts:
                # New potential alert - Start tracking
                self.active_alerts[alert_id] = SafetyAlert(
                    alert_id=alert_id,
                    severity=severity,
                    message=self.get_message(label),
                    zone=zone,
                    status=AlertStatus.TRIGGERED,
                    frame_counter=1
                )
            else:
                # Ongoing alert - increment frame counter
                alert = self.active_alerts[alert_id]
                if alert.status == AlertStatus.TRIGGERED:
                    alert.frame_counter += 1
                    if alert.frame_counter >= self.persistence_threshold:
                        alert.status = AlertStatus.ACTIVE

        # 2. Clean up Resolved Alerts
        for aid in list(self.active_alerts.keys()):
            alert = self.active_alerts[aid]
            # Only resolve alerts for the active zone
            if alert.zone == zone and aid not in detected_ids:
                if alert.status == AlertStatus.TRIGGERED:
                    # Flicker / transient detection that didn't persist - discard silently
                    self.active_alerts.pop(aid)
                else:
                    # Active/Acknowledged alert is now resolved
                    alert = self.active_alerts.pop(aid)
                    alert.status = AlertStatus.RESOLVED
                    alert.end_time = datetime.now()
                    self.history.append(alert)

        # 3. Check for escalation/automatic promotion
        for alert in self.active_alerts.values():
            if alert.status in (AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED):
                dur = alert.duration
                if alert.severity == AlertSeverity.LOW and dur > 60:
                    alert.severity = AlertSeverity.MEDIUM
                    alert.message = alert.message + " (Escalated to Medium)"
                elif alert.severity == AlertSeverity.MEDIUM and dur > 120:
                    alert.severity = AlertSeverity.HIGH
                    alert.message = alert.message + " (Escalated to High)"
                elif alert.severity == AlertSeverity.HIGH and dur > 180:
                    alert.severity = AlertSeverity.CRITICAL
                    alert.message = alert.message + " (CRITICAL ESCALATION)"

    def acknowledge(self, alert_id, user_name):
        if alert_id in self.active_alerts:
            self.active_alerts[alert_id].status = AlertStatus.ACKNOWLEDGED
            self.active_alerts[alert_id].acknowledged_by = user_name

def render_improved_alerts(placeholder, alert_manager):
    import streamlit as st
    if not alert_manager.active_alerts:
        nominal_html = (
            '<div style="background: rgba(34, 197, 94, 0.04); backdrop-filter: blur(12px); border: 1px solid rgba(34, 197, 94, 0.2); border-radius: 12px; padding: 12px 14px; text-align: center; font-family: \'Outfit\', sans-serif;">'
            '<div style="font-size: 20px; margin-bottom: 4px;">🟢</div>'
            '<div style="color: #22c55e; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">All Zones Nominal</div>'
            '<div style="color: #94a3b8; font-size: 11px; margin-top: 3px; line-height: 1.4;">All monitored zones are operating normally.</div>'
            '</div>'
        )
        placeholder.markdown(nominal_html, unsafe_allow_html=True)
        return

    # Sort by severity (Critical first)
    sorted_alerts = sorted(
        alert_manager.active_alerts.values(),
        key=lambda x: x.severity.value[0],
        reverse=True
    )

    cards_html = []
    
    # Show up to 3 alerts
    visible_alerts = sorted_alerts[:3]
    extra_count = len(sorted_alerts) - 3
    
    # We map zone keys to clean readable labels
    ZONE_LABELS_MAP = {
        'Zone_A': 'Battery-4',
        'Zone_B': 'Battery-5',
        'Zone_C': 'Battery-6',
        'Reactor_Area': 'Reactor Block',
        'Storage_Area': 'Storage Area',
        'Control_Room': 'Control Room'
    }

    for alert in visible_alerts:
        color = alert.severity.value[1]
        severity_label = alert.severity.value[2]
        
        sev_icons = {
            "Low": "ℹ️",
            "Medium": "🟡",
            "High": "🟠",
            "Critical": "🚨"
        }
        sev_icon = sev_icons.get(severity_label, "⚠️")

        # Format duration (e.g., "00:12s")
        dur = int(alert.duration)
        time_str = f"{dur // 60:02d}:{dur % 60:02d}s"

        # Status badge style
        if alert.status in (AlertStatus.ACTIVE, AlertStatus.TRIGGERED):
            status_bg = 'rgba(239, 68, 68, 0.15)'
            status_color = '#ef4444'
            status_border = 'rgba(239, 68, 68, 0.3)'
        elif alert.status == AlertStatus.ACKNOWLEDGED:
            status_bg = 'rgba(245, 158, 11, 0.15)'
            status_color = '#f59e0b'
            status_border = 'rgba(245, 158, 11, 0.3)'
        else:
            status_bg = 'rgba(34, 197, 94, 0.15)'
            status_color = '#22c55e'
            status_border = 'rgba(34, 197, 94, 0.3)'

        # Acknowledge button or badge
        if alert.status == AlertStatus.ACKNOWLEDGED:
            ack_btn = f"""<span style="background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 800; text-transform: uppercase;">✔ ACKNOWLEDGED</span>"""
        else:
            ack_btn = f"""<a href="?ack_alert={alert.alert_id}" target="_self" style="text-decoration: none;"><span style="background: {color}; color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 800; cursor: pointer; text-transform: uppercase;">ACKNOWLEDGE</span></a>"""

        zone_lbl = ZONE_LABELS_MAP.get(alert.zone, alert.zone)

        card_html = (
            f'<div style="background: rgba(17, 24, 39, 0.6); backdrop-filter: blur(12px); border: 1px solid {color}44; border-radius: 12px; padding: 10px 12px; margin-bottom: 8px; font-family: \'Outfit\', sans-serif;">'
            f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">'
            f'<span style="display: flex; align-items: center; gap: 4px; font-weight: 800; color: {color}; font-size: 10px; letter-spacing: 0.5px; text-transform: uppercase;">'
            f'{sev_icon} {severity_label}'
            f'</span>'
            f'<span style="background: {status_bg}; color: {status_color}; border: 1px solid {status_border}; border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">'
            f'{alert.status.value}'
            f'</span>'
            f'</div>'
            f'<div style="color: #fff; font-size: 12px; font-weight: 700; margin-bottom: 2px;">{alert.message}</div>'
            f'<div style="display: flex; justify-content: space-between; align-items: center; color: #64748b; font-size: 10px; margin-top: 6px;">'
            f'<span>Zone: <b style="color: #cbd5e1;">{zone_lbl}</b> | Duration: <b style="color: #cbd5e1;">{time_str}</b></span>'
            f'{ack_btn}'
            f'</div>'
            f'</div>'
        )
        cards_html.append(card_html)

    if extra_count > 0:
        extra_card = (
            f'<div style="background: rgba(255, 255, 255, 0.02); border: 1px dashed rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 8px; text-align: center; color: #94a3b8; font-size: 11px; font-family: \'Outfit\', sans-serif; margin-bottom: 8px;">'
            f'+ {extra_count} More Alerts'
            f'</div>'
        )
        cards_html.append(extra_card)

    placeholder.markdown("\n".join(cards_html), unsafe_allow_html=True)

    placeholder.markdown("\n".join(cards_html), unsafe_allow_html=True)

class AlertSystem:
    """
    Multi-channel alert system with escalation paths and local SQLite persistence.
    Different risk levels trigger different notification channels.
    Includes a background worker thread that monitors unacknowledged alerts and escalates them.
    """
    
    def __init__(self, db_path: str = "data/alerts.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        
        # Initialize SQLite DB
        self._init_db()
        
        # Escalation matrix: maps risk levels to target channels, timeout for ack (seconds), and required_ack
        self.escalation_matrix = {
            'CRITICAL': {
                'channels': ['DASHBOARD', 'SMS', 'PHONE', 'SIREN', 'EMAIL'],
                'response_time': 60, # 1 minute response time
                'required_ack': True
            },
            'HIGH': {
                'channels': ['DASHBOARD', 'SMS', 'EMAIL'],
                'response_time': 300, # 5 minutes response time
                'required_ack': True
            },
            'MEDIUM': {
                'channels': ['DASHBOARD', 'EMAIL'],
                'response_time': 900, # 15 minutes
                'required_ack': False
            },
            'LOW': {
                'channels': ['DASHBOARD'],
                'response_time': 1800, # 30 minutes
                'required_ack': False
            }
        }
        
        # Emergency response teams by zone
        self.emergency_teams = {
            'Zone_A': ['Alpha Team', 'Beta Team'],
            'Zone_B': ['Gamma Team', 'Delta Team'],
            'Zone_C': ['Epsilon Team', 'Zeta Team'],
            'Reactor_Area': ['Theta Team', 'Iota Team'],
            'Storage_Area': ['Kappa Team', 'Lambda Team']
        }
        
        # Start background escalation thread
        self.running = True
        self.worker_thread = threading.Thread(target=self._escalation_worker, daemon=True)
        self.worker_thread.start()

    def _init_db(self):
        """Initialise SQLite database tables for alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_alerts (
            alert_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            zone TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            risk_score REAL NOT NULL,
            factors TEXT NOT NULL,
            compound_factors TEXT NOT NULL,
            message TEXT NOT NULL,
            teams_notified TEXT NOT NULL,
            channels TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE', -- ACTIVE, ACKNOWLEDGED, RESOLVED
            escalation_tier INTEGER DEFAULT 1,
            last_notified_at TEXT,
            requires_ack INTEGER DEFAULT 0
        )
        """)
        conn.commit()
        conn.close()

    def trigger_alert(self, row: pd.Series, risk_result: Dict) -> Optional[Dict]:
        """Trigger an alert, save to DB, and send notifications"""
        risk_level = risk_result.get('risk_level', 'LOW')
        risk_score = risk_result.get('risk_score', 0)
        
        if risk_score < 5:  # Only alert for MEDIUM and above
            return None
        
        zone = risk_result.get('zone', 'Unknown')
        teams = self.emergency_teams.get(zone, ['Emergency Response Team'])
        matrix = self.escalation_matrix.get(risk_level, self.escalation_matrix['LOW'])
        
        if hasattr(row, 'timestamp') and hasattr(row['timestamp'], 'strftime'):
            # Convert pandas Timestamp or python datetime to string format
            alert_id = f"ALT-{row['timestamp'].strftime('%Y%m%d%H%M%S')}"
        else:
            alert_id = f"ALT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
        timestamp_str = row['timestamp'].isoformat() if hasattr(row, 'timestamp') and hasattr(row['timestamp'], 'isoformat') else datetime.now().isoformat()
        
        factors_str = ",".join(risk_result.get('factors', []))
        compound_str = ",".join(risk_result.get('compound_factors', []))
        teams_str = ",".join(teams)
        channels_str = ",".join(matrix['channels'])
        requires_ack_val = 1 if matrix['required_ack'] else 0
        now_str = datetime.now().isoformat()
        
        alert = {
            'alert_id': alert_id,
            'timestamp': timestamp_str,
            'zone': zone,
            'risk_level': risk_level,
            'risk_score': risk_score,
            'factors': risk_result.get('factors', []),
            'compound_factors': risk_result.get('compound_factors', []),
            'message': risk_result.get('message', ''),
            'teams_notified': teams,
            'channels': matrix['channels'],
            'response_time_required': matrix['response_time'],
            'requires_ack': bool(requires_ack_val),
            'status': 'ACTIVE',
            'escalation_tier': 1,
            'acknowledged': False,
            'resolved': False
        }
        
        # Save to DB
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO system_alerts 
        (alert_id, timestamp, zone, risk_level, risk_score, factors, compound_factors, message, teams_notified, channels, status, escalation_tier, last_notified_at, requires_ack)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 1, ?, ?)
        """, (
            alert_id, timestamp_str, zone, risk_level, risk_score, 
            factors_str, compound_str, alert['message'], teams_str, 
            channels_str, now_str, requires_ack_val
        ))
        conn.commit()
        conn.close()
        
        # Send notifications
        self._send_notifications(alert)
        
        return alert

    def _send_notifications(self, alert: Dict):
        """Dispatches notifications through multiple configured channels"""
        print(f"\n==========================================")
        print(f"NOTIFICATION DISPATCHED: {alert['alert_id']}")
        print(f"Level: {alert['risk_level']} | Zone: {alert['zone']}")
        print(f"Message: {alert['message']}")
        print(f"Channels: {alert['channels']}")
        print(f"==========================================\n")
        
        # 1. Email Channel
        if 'EMAIL' in alert['channels']:
            self._dispatch_email_notification(alert)
            
        # 2. Telegram Bot Channel
        if 'SMS' in alert['channels'] or 'TELEGRAM' in alert['channels']:
            self._dispatch_telegram_notification(alert)

    def _dispatch_email_notification(self, alert: Dict):
        """Sends email alert via SMTP with local credentials or log simulation fallback"""
        sender = os.environ.get("SENDER_EMAIL")
        password = os.environ.get("SENDER_PASSWORD")
        recipient = os.environ.get("ALERT_RECIPIENT_EMAIL")
        
        if not sender or not password or not recipient:
            self.logger.info(f"[EMAIL SIMULATION] Send to: {recipient or 'operator@plant.com'} | Alert: {alert['message']}")
            return
            
        try:
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = recipient
            msg['Subject'] = f"⚠️ SURAKSHAAI {alert['risk_level']} ALERT in {alert['zone']}"
            
            body = f"""
            <h3>⚠️ SurakshaAI Warning Notification</h3>
            <p><strong>Alert ID:</strong> {alert['alert_id']}</p>
            <p><strong>Risk Level:</strong> <span style="color:red;">{alert['risk_level']}</span> (Score: {alert['risk_score']}/20)</p>
            <p><strong>Location:</strong> {alert['zone']}</p>
            <p><strong>Message:</strong> {alert['message']}</p>
            <p><strong>Timestamp:</strong> {alert['timestamp']}</p>
            <p><strong>Actions Required:</strong> Immediate compliance check and shift manager authorization.</p>
            <br>
            <p><em>Please acknowledge this alert in the main web dashboard dashboard.</em></p>
            """
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
            server.quit()
            self.logger.info(f"[EMAIL] Sent email alert for {alert['alert_id']} to {recipient}")
        except Exception as e:
            self.logger.error(f"[EMAIL ERROR] Failed to send email: {e}")

    def _dispatch_telegram_notification(self, alert: Dict):
        """Sends Telegram Bot alerts or log simulation fallback"""
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        
        if not token or not chat_id:
            self.logger.info(f"[TELEGRAM SIMULATION] Chat ID: {chat_id or 'admin_chat'} | Alert: {alert['message']}")
            return
            
        try:
            message_text = (
                f"🚨 *SURAKSHAAI ALERT*\n"
                f"• *ID:* `{alert['alert_id']}`\n"
                f"• *Level:* `{alert['risk_level']}` (Score: {alert['risk_score']:.1f}/20)\n"
                f"• *Zone:* {alert['zone']}\n"
                f"• *Message:* {alert['message']}\n"
                f"• *Timestamp:* {alert['timestamp']}"
            )
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {'chat_id': chat_id, 'text': message_text, 'parse_mode': 'Markdown'}
            res = requests.post(url, data=data, timeout=5)
            if res.status_code == 200:
                self.logger.info(f"[TELEGRAM] Sent telegram alert for {alert['alert_id']}")
            else:
                self.logger.warning(f"[TELEGRAM WARNING] Telegram API returned code {res.status_code}: {res.text}")
        except Exception as e:
            self.logger.error(f"[TELEGRAM ERROR] Failed to send telegram: {e}")

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert and update the DB"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE system_alerts SET status = 'ACKNOWLEDGED' WHERE alert_id = ?", (alert_id,))
        rows_changed = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_changed > 0:
            self.logger.info(f"Alert {alert_id} acknowledged in DB")
            return True
        return False

    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert and update the DB"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE system_alerts SET status = 'RESOLVED' WHERE alert_id = ?", (alert_id,))
        rows_changed = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_changed > 0:
            self.logger.info(f"Alert {alert_id} resolved in DB")
            return True
        return False

    def get_active_alerts(self) -> List[Dict]:
        """Get all unresolved alerts (status 'ACTIVE' or 'ACKNOWLEDGED')"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM system_alerts WHERE status != 'RESOLVED'")
        rows = cursor.fetchall()
        conn.close()
        
        alerts = []
        for r in rows:
            alerts.append(self._row_to_dict(r))
        return alerts

    def get_recent_alerts(self, n: int = 10) -> List[Dict]:
        """Get n most recent alerts from DB"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM system_alerts ORDER BY timestamp DESC LIMIT ?", (n,))
        rows = cursor.fetchall()
        conn.close()
        
        alerts = []
        for r in rows:
            alerts.append(self._row_to_dict(r))
        return alerts

    @property
    def alerts(self) -> List[Dict]:
        """Retrieve recent alerts for backward compatibility with list-based access"""
        return self.get_recent_alerts(100)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Helper to convert database row to standard Alert dictionary"""
        return {
            'alert_id': row['alert_id'],
            'timestamp': row['timestamp'],
            'zone': row['zone'],
            'risk_level': row['risk_level'],
            'risk_score': row['risk_score'],
            'factors': row['factors'].split(",") if row['factors'] else [],
            'compound_factors': row['compound_factors'].split(",") if row['compound_factors'] else [],
            'message': row['message'],
            'teams_notified': row['teams_notified'].split(",") if row['teams_notified'] else [],
            'channels': row['channels'].split(",") if row['channels'] else [],
            'status': row['status'],
            'escalation_tier': row['escalation_tier'],
            'last_notified_at': row['last_notified_at'],
            'requires_ack': bool(row['requires_ack']),
            'acknowledged': row['status'] == 'ACKNOWLEDGED',
            'resolved': row['status'] == 'RESOLVED'
        }

    def _escalation_worker(self):
        """Worker loop running in a background thread checking for unacknowledged alerts and escalating them"""
        while self.running:
            try:
                self._check_and_escalate_alerts()
            except Exception as e:
                self.logger.error(f"[ESCALATION ERROR] Exception in background worker: {e}")
            time.sleep(15) # Check every 15 seconds

    def _check_and_escalate_alerts(self):
        """Query unacknowledged active alerts that have breached their response time window and elevate them"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        # Find active (unacknowledged) alerts requiring acknowledgement
        cursor.execute("SELECT * FROM system_alerts WHERE status = 'ACTIVE' AND requires_ack = 1")
        active_alerts = cursor.fetchall()
        
        now = datetime.now()
        for row in active_alerts:
            alert = self._row_to_dict(row)
            last_notified = datetime.fromisoformat(alert['last_notified_at'])
            matrix_info = self.escalation_matrix.get(alert['risk_level'], self.escalation_matrix['LOW'])
            
            # Check if elapsed time exceeds response time limit
            elapsed = (now - last_notified).total_seconds()
            if elapsed >= matrix_info['response_time']:
                new_tier = alert['escalation_tier'] + 1
                
                # Perform escalation notification
                escalated_message = (
                    f"⚠️ *ESCALATION TIER {new_tier} ACTIVE* ⚠️\n"
                    f"Alert `{alert['alert_id']}` in *{alert['zone']}* ({alert['risk_level']}) remains unacknowledged after {matrix_info['response_time']}s.\n"
                    f"Immediate emergency dispatch required."
                )
                
                self.logger.warning(f"[ESCALATION] Alert {alert['alert_id']} escalated to Tier {new_tier}!")
                
                # Dispatch escalated alerts to Telegram & Email immediately
                self._dispatch_telegram_notification({**alert, 'message': escalated_message})
                
                # Update DB record
                cursor.execute("""
                UPDATE system_alerts 
                SET escalation_tier = ?, last_notified_at = ? 
                WHERE alert_id = ?
                """, (new_tier, now.isoformat(), alert['alert_id']))
                
        conn.commit()
        conn.close()

    def shutdown(self):
        """Gracefully stop background loop"""
        self.running = False

# Singleton instance
_alert_system_instance = None
def get_alert_system():
    global _alert_system_instance
    instance = _alert_system_instance
    if instance is None:
        instance = AlertSystem()
        _alert_system_instance = instance
    return instance

def evaluate_alert_conditions(
    detections: list,
    violations: int,
    zone: str,
    telemetry: dict
) -> dict:
    """
    Evaluates all detection outputs and returns alert payload.
    Works with the actual Detection dataclass from src/cctv/object_detector.py.
    Detection.label can be: 'person', 'helmet', 'vest', 'fire', 'smoke',
                             'gas_leak', 'no_helmet', 'no_vest'
    Detection.zone_violation (bool) flags restricted-area intrusions.
    Returns dict with: should_alert, severity, summary, messages, channels, zone, timestamp
    """
    alerts = []
    severity = "LOW"

    # 1. Fire / smoke detections -> CRITICAL
    fire_dets = [d for d in detections
                 if hasattr(d, 'label') and d.label in ('fire', 'smoke')]
    if fire_dets:
        alerts.append(f"🔴 FIRE/SMOKE DETECTED in {zone} — {len(fire_dets)} hazard(s)")
        severity = "CRITICAL"

    # 2. Gas leak overlay detection -> CRITICAL
    gas_leak_dets = [d for d in detections
                     if hasattr(d, 'label') and d.label == 'gas_leak']
    if gas_leak_dets:
        alerts.append(f"🔴 GAS LEAK DETECTED by sensor overlay in {zone}")
        severity = "CRITICAL"

    # 3. Zone intrusion (zone_violation flag set in inference.py) -> CRITICAL
    intruders = [d for d in detections if getattr(d, 'zone_violation', False)]
    if intruders:
        alerts.append(f"🔴 INTRUDER in restricted area — {zone}")
        severity = "CRITICAL"

    # 4. Telemetry threshold checks
    # telemetry is a pandas Series; .get(key, default) works correctly
    gas_ppm = telemetry.get(f"{zone}_gas_ppm", telemetry.get("gas_ppm", 0))
    temp    = telemetry.get(f"{zone}_temperature_c",
                            telemetry.get(f"{zone}_temperature",
                            telemetry.get("temperature", 0)))

    if gas_ppm > 35:
        alerts.append(f"🔴 GAS CRITICAL — {gas_ppm:.1f} ppm in {zone}")
        severity = "CRITICAL"
    elif gas_ppm > 20:
        alerts.append(f"🟠 GAS ELEVATED — {gas_ppm:.1f} ppm in {zone}")
        if severity not in ("CRITICAL",):
            severity = "HIGH"

    if temp > 95:
        alerts.append(f"🔴 TEMPERATURE CRITICAL — {temp:.1f}°C in {zone}")
        if severity not in ("CRITICAL",):
            severity = "CRITICAL"

    if zone == "Zone_C":
        pressure = telemetry.get(f"{zone}_pressure_bar",
                                 telemetry.get("pressure", 0))
        if pressure > 80:
            alerts.append(f"🔴 OVERPRESSURE — {pressure:.0f} bar in {zone}")
            severity = "CRITICAL"

    # 5. PPE violations:
    # inference.py adds Detection(label="helmet") / Detection(label="vest") for compliant workers
    # and Detection(label="no_helmet") / Detection(label="no_vest") labels are NOT generated;
    # instead viol_count counts workers without helmet/vest.
    # Use violations parameter directly (already computed by inference.py).
    if violations > 0 and severity not in ("CRITICAL", "HIGH"):
        alerts.append(f"🟠 PPE VIOLATION — {violations} worker(s) non-compliant in {zone}")
        if severity not in ("CRITICAL", "HIGH"):
            severity = "MEDIUM"

    should_alert = len(alerts) > 0
    channels: list = []
    if severity == "CRITICAL":
        channels = ["sms", "email", "siren"]
    elif severity == "HIGH":
        channels = ["sms", "email"]
    elif severity == "MEDIUM":
        channels = ["email"]

    return {
        "should_alert": should_alert,
        "severity": severity,
        "messages": alerts,
        "summary": " | ".join(alerts),
        "zone": zone,
        "channels": channels,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }

def dispatch_alerts(alert_payload: dict):
    """
    Dispatches alert to all required channels based on severity.
    For hackathon: simulates SMS/Email, activates siren state in session.
    Deduplicates by (zone, severity) within the same incident — will NOT
    insert a duplicate if the most-recent log entry already matches.
    Caps alert_log at 100 entries.
    """
    import streamlit as st
    from datetime import datetime

    severity  = alert_payload["severity"]
    summary   = alert_payload["summary"]
    zone      = alert_payload["zone"]
    timestamp = alert_payload["timestamp"]
    channels  = alert_payload["channels"]

    # Log to persistent alert log in session state
    if "alert_log" not in st.session_state:
        st.session_state.alert_log = []

    # Deduplicate: skip if the newest entry is from the same zone+severity
    if not (st.session_state.alert_log
            and st.session_state.alert_log[0].get("zone") == zone
            and st.session_state.alert_log[0].get("severity") == severity):
        alert_entry = {
            "id":        f"ALT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "severity":  severity,
            "zone":      zone,
            "message":   summary,
            "timestamp": timestamp,
            "status":    "TRIGGERED",
            "channels":  channels
        }
        st.session_state.alert_log.insert(0, alert_entry)  # newest first
        # Cap at 100 entries
        if len(st.session_state.alert_log) > 100:
            st.session_state.alert_log = st.session_state.alert_log[:100]

    # Simulate SMS dispatch
    if "sms" in channels:
        st.session_state.sms_status = {
            "status": "DELIVERED ✓",
            "color": "#22c55e",
            "detail": f"Sent to: +123****890 at {timestamp}"
        }

    # Simulate Email dispatch
    if "email" in channels:
        st.session_state.email_status = {
            "status": "SENT ✓",
            "color": "#22c55e",
            "detail": f"Sent to: safety@***.com at {timestamp}"
        }

    # Activate siren
    if "siren" in channels:
        st.session_state.siren_status = {
            "status": "ACTIVE 🔊",
            "color": "#ef4444",
            "detail": f"Zone: {zone} — SOUNDING",
            "active": True
        }

    # Set global banner state
    st.session_state.active_alert   = alert_payload
    st.session_state.banner_visible = True

def clear_alert_if_safe(zone: str):
    """Call this when violations_count == 0 and no fire/intruder detected."""
    import streamlit as st
    
    st.session_state[f"alert_active_{zone}"] = False
    st.session_state.siren_status = {
        "status": "STANDBY",
        "color": "#6b7280", 
        "detail": "All clear",
        "active": False
    }
    st.session_state.sms_status = {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"}
    st.session_state.email_status = {"status": "STANDBY", "color": "#6b7280", "detail": "Sent to: N/A"}
    st.session_state.banner_visible = False
    st.session_state.active_alert = None