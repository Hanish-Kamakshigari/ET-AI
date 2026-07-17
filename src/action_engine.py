"""
Action Engine - Prescriptive Actions for Safety Teams
Tells users WHAT to do, not just WHAT's wrong
"""
# Refactoring Safeguard: Preserves 100% of the original business logic and algorithms.


import json
from typing import Dict, List, Optional
from datetime import datetime
import os

class ActionEngine:
    """
    Generates specific, actionable recommendations
    """
    
    def __init__(self, knowledge_base_path: str = 'data/actions.json') -> None:
        self.knowledge_base_path = knowledge_base_path
        self.action_kb = self._load_knowledge_base()
    
    def _load_knowledge_base(self) -> Dict:
        """Load the action knowledge base"""
        default_actions = {
            "MAINTENANCE_GAS_LEAK": {
                "immediate": [
                    "Stop all maintenance activities in the zone",
                    "Sound evacuation alarm",
                    "Mobilize emergency response team",
                    "Shut down gas supply if possible"
                ],
                "follow_up": [
                    "Investigate gas source",
                    "Test gas monitoring equipment",
                    "Review maintenance procedures",
                    "Complete incident report"
                ],
                "personnel": [
                    "Safety Officer",
                    "Maintenance Lead",
                    "Emergency Response Team",
                    "Plant Manager"
                ],
                "time_to_respond": 1,
                "severity": "CRITICAL"
            },
            "TRIPLE_THREAT": {
                "immediate": [
                    "IMMEDIATE ZONE WIDE EVACUATION",
                    "Shut down all equipment in the zone",
                    "Activate emergency protocols",
                    "Call emergency services"
                ],
                "follow_up": [
                    "Full incident investigation",
                    "Root cause analysis",
                    "Report to regulatory authorities",
                    "Implement corrective actions"
                ],
                "personnel": [
                    "Safety Officer",
                    "Plant Manager",
                    "Emergency Response Team",
                    "Maintenance Lead",
                    "Operations Manager"
                ],
                "time_to_respond": 1,
                "severity": "CRITICAL"
            },
            "PERMIT_GAS_COMBINATION": {
                "immediate": [
                    "Revoke all permits in the zone",
                    "Investigate gas source",
                    "Increase ventilation"
                ],
                "follow_up": [
                    "Review permit procedures",
                    "Inspect gas monitoring systems",
                    "Update safety protocols"
                ],
                "personnel": [
                    "Safety Officer",
                    "Permit Coordinator",
                    "Operations Manager"
                ],
                "time_to_respond": 5,
                "severity": "HIGH"
            },
            "OVERHEATING_WITH_GAS": {
                "immediate": [
                    "Cool reactor/equipment",
                    "Shut down process if needed",
                    "Monitor gas levels closely"
                ],
                "follow_up": [
                    "Investigate temperature spike",
                    "Review cooling systems",
                    "Update operating procedures"
                ],
                "personnel": [
                    "Process Engineer",
                    "Maintenance Team",
                    "Safety Officer"
                ],
                "time_to_respond": 5,
                "severity": "HIGH"
            },
            "WORKER_OVER_CROWDING": {
                "immediate": [
                    "Reduce workers in zone",
                    "Increase ventilation",
                    "Implement crowd control"
                ],
                "follow_up": [
                    "Review staffing requirements",
                    "Update zone capacity limits",
                    "Improve communication"
                ],
                "personnel": [
                    "Shift Supervisor",
                    "Safety Officer",
                    "Operations Manager"
                ],
                "time_to_respond": 15,
                "severity": "MEDIUM"
            },
            "SHIFT_CHANGE_RISK": {
                "immediate": [
                    "Delay shift change if possible",
                    "Conduct thorough handover",
                    "Review gas levels before handover"
                ],
                "follow_up": [
                    "Review shift change procedures",
                    "Improve communication protocols",
                    "Update training materials"
                ],
                "personnel": [
                    "Shift Supervisor",
                    "Safety Officer",
                    "Operations Manager"
                ],
                "time_to_respond": 15,
                "severity": "MEDIUM"
            }
        }
        
        try:
            if os.path.exists(self.knowledge_base_path):
                with open(self.knowledge_base_path, 'r') as f:
                    return json.load(f)
            else:
                # Create default file
                os.makedirs(os.path.dirname(self.knowledge_base_path), exist_ok=True)
                with open(self.knowledge_base_path, 'w') as f:
                    json.dump(default_actions, f, indent=2)
                return default_actions
        except Exception as e:
            print(f"⚠️ Error loading knowledge base: {e}")
            return default_actions
    
    def get_action_plan(self, alert: object, plant_state: Optional[Dict] = None) -> Dict:
        """
        Generate a complete action plan for an alert
        
        Args:
            alert: RiskAlert object
            plant_state: Current plant state (optional)
        
        Returns:
            Action plan dictionary
        """
        action_plan = {
            'timestamp': datetime.now().isoformat(),
            'alert_id': getattr(alert, 'alert_id', f"ALT-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
            'zone': getattr(alert, 'zone', 'Unknown'),
            'priority': self._get_priority(getattr(alert, 'risk_level', 'LOW')),
            'immediate_actions': [],
            'follow_up_actions': [],
            'required_personnel': [],
            'estimated_response_time': 0,
            'status': 'PENDING'
        }
        
        # Get actions for each compound factor
        compound_factors = getattr(alert, 'compound_factors', [])
        if not compound_factors:
            # If no compound factors, check risk level
            risk_level = getattr(alert, 'risk_level', 'LOW')
            if risk_level == 'CRITICAL':
                compound_factors = ['TRIPLE_THREAT']
            elif risk_level == 'HIGH':
                compound_factors = ['MAINTENANCE_GAS_LEAK']
            elif risk_level == 'MEDIUM':
                compound_factors = ['WORKER_OVER_CROWDING']
        
        for factor in compound_factors:
            if factor in self.action_kb:
                kb_actions = self.action_kb[factor]
                action_plan['immediate_actions'].extend(kb_actions.get('immediate', []))
                action_plan['follow_up_actions'].extend(kb_actions.get('follow_up', []))
                action_plan['required_personnel'].extend(kb_actions.get('personnel', []))
                action_plan['estimated_response_time'] = max(
                    action_plan['estimated_response_time'],
                    kb_actions.get('time_to_respond', 0)
                )
        
        # Deduplicate
        action_plan['immediate_actions'] = list(dict.fromkeys(action_plan['immediate_actions']))
        action_plan['follow_up_actions'] = list(dict.fromkeys(action_plan['follow_up_actions']))
        action_plan['required_personnel'] = list(dict.fromkeys(action_plan['required_personnel']))
        
        return action_plan
    
    def _get_priority(self, risk_level: str) -> int:
        """Map risk level to priority number"""
        priorities = {
            'CRITICAL': 1,
            'HIGH': 2,
            'MEDIUM': 3,
            'LOW': 4
        }
        return priorities.get(risk_level, 4)
    
    def export_action_plan_pdf(self, action_plan: Dict) -> bytes:
        """Export action plan as PDF (optional)"""
        # This would use reportlab or similar
        # For hackathon, just return JSON
        return json.dumps(action_plan, indent=2).encode('utf-8')