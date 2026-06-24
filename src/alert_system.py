"""
PHASE 4: Alert & Notification System
Multi-channel alerting with escalation matrix
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd

class AlertSystem:
    """
    Multi-channel alert system with escalation paths.
    Different risk levels trigger different notification channels.
    """
    
    def __init__(self):
        self.alerts = []
        self.logger = logging.getLogger(__name__)
        
        # Escalation matrix
        self.escalation_matrix = {
            'CRITICAL': {
                'channels': ['SMS', 'PHONE', 'SIREN', 'EMAIL'],
                'response_time': 1,
                'required_ack': True
            },
            'HIGH': {
                'channels': ['SMS', 'EMAIL'],
                'response_time': 5,
                'required_ack': True
            },
            'MEDIUM': {
                'channels': ['EMAIL', 'DASHBOARD'],
                'response_time': 15,
                'required_ack': False
            },
            'LOW': {
                'channels': ['DASHBOARD'],
                'response_time': 30,
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
    
    def trigger_alert(self, row: pd.Series, risk_result: Dict) -> Optional[Dict]:
        """Trigger an alert based on risk assessment"""
        risk_level = risk_result['risk_level']
        risk_score = risk_result['risk_score']
        
        if risk_score < 5:  # Only alert for MEDIUM and above
            return None
        
        zone = risk_result['zone']
        teams = self.emergency_teams.get(zone, ['Emergency Response Team'])
        
        alert = {
            'alert_id': f"ALT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'timestamp': row['timestamp'].isoformat(),
            'zone': zone,
            'risk_level': risk_level,
            'risk_score': risk_score,
            'factors': risk_result['factors'],
            'compound_factors': risk_result['compound_factors'],
            'message': risk_result['message'],
            'teams_notified': teams,
            'channels': self.escalation_matrix[risk_level]['channels'],
            'response_time_required': self.escalation_matrix[risk_level]['response_time'],
            'requires_ack': self.escalation_matrix[risk_level]['required_ack'],
            'status': 'triggered',
            'acknowledged': False,
            'resolved': False
        }
        
        self.alerts.append(alert)
        self._send_notifications(alert)
        
        return alert
    
    def _send_notifications(self, alert: Dict):
        """Simulate sending notifications through multiple channels"""
        print("\n" + "=" * 60)
        print(f"ALERT TRIGGERED: {alert['alert_id']}")
        print(f"Level: {alert['risk_level']} | Score: {alert['risk_score']}/20")
        print(f"Zone: {alert['zone']}")
        print(f"Channels: {', '.join(alert['channels'])}")
        print(f"Teams: {', '.join(alert['teams_notified'])}")
        print("-" * 60)
        print(alert['message'])
        print("=" * 60 + "\n")
        
        self.logger.info(f"Alert {alert['alert_id']}: {alert['message'][:100]}")
        
        if alert['risk_level'] == 'CRITICAL':
            self.logger.warning(f"CRITICAL ALERT: {alert['message'][:100]}")
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert"""
        for alert in self.alerts:
            if alert['alert_id'] == alert_id:
                alert['acknowledged'] = True
                alert['status'] = 'acknowledged'
                print(f"Alert {alert_id} acknowledged")
                return True
        return False
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert"""
        for alert in self.alerts:
            if alert['alert_id'] == alert_id:
                alert['resolved'] = True
                alert['status'] = 'resolved'
                print(f"Alert {alert_id} resolved")
                return True
        return False
    
    def get_active_alerts(self) -> List[Dict]:
        """Get all unresolved alerts"""
        return [a for a in self.alerts if not a['resolved']]
    
    def get_recent_alerts(self, n: int = 10) -> List[Dict]:
        """Get n most recent alerts"""
        return self.alerts[-n:] if self.alerts else []


if __name__ == "__main__":
    print("Testing Alert System...")
    print("=" * 50)
    
    from risk_engine import CompoundRiskEngine
    
    # Load data
    df = pd.read_csv('data/plant_data.csv', parse_dates=['timestamp'])
    
    # Initialize
    engine = CompoundRiskEngine()
    alert_system = AlertSystem()
    
    # Trigger alerts for recent data
    for idx in range(len(df) - 100, len(df), 10):
        row = df.iloc[idx]
        alerts = engine.analyze_timestamp(row)
        for alert in alerts:
            alert_system.trigger_alert(row, {
                'zone': alert.zone,
                'risk_level': alert.risk_level,
                'risk_score': alert.risk_score,
                'factors': alert.factors,
                'compound_factors': alert.compound_factors,
                'message': alert.message
            })
    
    print(f"\nTotal alerts triggered: {len(alert_system.alerts)}")
    print(f"Active alerts: {len(alert_system.get_active_alerts())}")