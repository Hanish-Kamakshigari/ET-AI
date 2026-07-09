"""
Compliance Engine - Regulatory Compliance & Reporting
"""
# Refactoring Safeguard: Preserves 100% of the original business logic and algorithms.


import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os

class ComplianceEngine:
    """
    Generates regulatory compliance reports
    Supports OISD, Factory Act, DGMS standards
    """
    
    def __init__(self, plant_name: str = "Suraksha Plant", plant_id: str = "SP-001"):
        self.plant_name = plant_name
        self.plant_id = plant_id
        self.standards = self._load_standards()
    
    def _load_standards(self) -> Dict:
        """Load regulatory standards"""
        return {
            'OISD_150': {
                'name': 'Safety in Oil and Gas Operations',
                'gas_limit': 50,
                'temp_limit': 100,
                'pressure_limit': 7.0
            },
            'Factory_Act_1948': {
                'name': 'Worker Safety Standards',
                'max_workers': 10,
                'working_hours': 8,
                'safety_equipment_required': True
            },
            'DGMS_Regulations': {
                'name': 'Mining Safety Standards',
                'gas_limit': 40,
                'ventilation_required': True,
                'emergency_plan_required': True
            }
        }
    
    def check_compliance(self, df: pd.DataFrame) -> Dict:
        """
        Check compliance against all standards
        
        Args:
            df: Plant data DataFrame
        
        Returns:
            Compliance status dictionary
        """
        compliance_status = {}
        
        for standard_id, standard in self.standards.items():
            compliance_status[standard_id] = self._check_standard(df, standard)
        
        return compliance_status
    
    def _check_standard(self, df: pd.DataFrame, standard: Dict) -> Dict:
        """Check compliance for a single standard"""
        violations = []
        
        # Check gas limits
        if 'gas_limit' in standard:
            gas_cols = [col for col in df.columns if 'gas_ppm' in col]
            for col in gas_cols:
                exceeded = df[df[col] > standard['gas_limit']]
                if not exceeded.empty:
                    violations.append({
                        'type': 'GAS_LIMIT_EXCEEDED',
                        'column': col,
                        'count': len(exceeded),
                        'max_value': exceeded[col].max(),
                        'limit': standard['gas_limit']
                    })
        
        # Check temperature limits
        if 'temp_limit' in standard:
            temp_cols = [col for col in df.columns if 'temperature_c' in col]
            for col in temp_cols:
                exceeded = df[df[col] > standard['temp_limit']]
                if not exceeded.empty:
                    violations.append({
                        'type': 'TEMP_LIMIT_EXCEEDED',
                        'column': col,
                        'count': len(exceeded),
                        'max_value': exceeded[col].max(),
                        'limit': standard['temp_limit']
                    })
        
        # Check worker limits
        if 'max_workers' in standard:
            worker_cols = [col for col in df.columns if 'worker_count' in col]
            for col in worker_cols:
                exceeded = df[df[col] > standard['max_workers']]
                if not exceeded.empty:
                    violations.append({
                        'type': 'WORKER_LIMIT_EXCEEDED',
                        'column': col,
                        'count': len(exceeded),
                        'max_value': exceeded[col].max(),
                        'limit': standard['max_workers']
                    })
        
        return {
            'status': 'COMPLIANT' if not violations else 'VIOLATION',
            'violations': violations,
            'violation_count': len(violations)
        }
    
    def generate_compliance_report(self, df: pd.DataFrame, 
                                   start_date: datetime = None,
                                   end_date: datetime = None) -> Dict:
        """
        Generate a complete compliance report
        
        Args:
            df: Plant data
            start_date: Report start date
            end_date: Report end date
        
        Returns:
            Complete report dictionary
        """
        if start_date and end_date:
            mask = (df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)
            df = df.loc[mask]
        
        compliance_status = self.check_compliance(df)
        
        # Calculate metrics
        alert_rows = df[df['max_risk_score'] > 0]
        
        report = {
            'plant_name': self.plant_name,
            'plant_id': self.plant_id,
            'report_date': datetime.now().isoformat(),
            'period': {
                'start': start_date.isoformat() if start_date else 'N/A',
                'end': end_date.isoformat() if end_date else 'N/A'
            },
            'metrics': {
                'total_records': len(df),
                'total_alerts': len(alert_rows),
                'critical_alerts': len(df[df['max_risk_level'] == 'CRITICAL']),
                'high_alerts': len(df[df['max_risk_level'] == 'HIGH']),
                'medium_alerts': len(df[df['max_risk_level'] == 'MEDIUM']),
                'alert_rate': (len(alert_rows) / len(df) * 100) if len(df) > 0 else 0
            },
            'compliance': compliance_status,
            'overall_status': self._get_overall_status(compliance_status)
        }
        
        return report
    
    def _get_overall_status(self, compliance_status: Dict) -> str:
        """Get overall compliance status"""
        for standard in compliance_status.values():
            if standard['status'] == 'VIOLATION':
                return 'VIOLATION'
        return 'COMPLIANT'
    
    def export_report_to_pdf(self, report: Dict) -> bytes:
        """Export report as PDF (placeholder)"""
        # In real implementation, use reportlab or similar
        return json.dumps(report, indent=2).encode('utf-8')
    
    def get_compliance_score(self, df: pd.DataFrame) -> float:
        """Calculate overall compliance score (0-100)"""
        report = self.generate_compliance_report(df)
        
        if report['overall_status'] == 'COMPLIANT':
            return 100.0
        
        # Calculate score based on violations
        total_violations = 0
        for standard in report['compliance'].values():
            total_violations += standard['violation_count']
        
        # Simple scoring: 100 - (violations * 5), minimum 0
        score = max(0, 100 - (total_violations * 5))
        return score