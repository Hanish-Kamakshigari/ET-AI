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
    if _alert_system_instance is None:
        _alert_system_instance = AlertSystem()
    return _alert_system_instance