"""
PHASE 2: Compound Risk Engine
Detects dangerous combinations of factors that no single sensor would catch
"""
# Refactoring Safeguard: Preserves 100% of the original business logic and algorithms.


import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
import logging

@dataclass
class RiskAlert:
    """Structure for a risk alert"""
    timestamp: pd.Timestamp
    zone: str
    risk_score: float
    risk_level: str
    factors: List[str]
    compound_factors: List[str]
    message: str
    sensor_data: Dict[str, float]

class CompoundRiskEngine:
    """
    Advanced risk detection engine with realistic industrial thresholds.
    Alerts are rare (< 3-5%) - false alarms kill trust.
    """
    
    def __init__(self) -> None:
        # REALISTIC THRESHOLDS - Based on actual industrial standards
        self.thresholds = {
            'gas_ppm': {
                'normal': (0, 20),      # 0-20 ppm: Normal operations
                'elevated': (20, 35),   # 20-35 ppm: Monitor closely
                'high': (35, 55),       # 35-55 ppm: Investigate immediately
                'critical': (55, 100)   # 55+ ppm: DANGER! Evacuate!
            },
            'temperature_c': {
                'normal': (60, 88),
                'elevated': (88, 95),
                'high': (95, 105),
                'critical': (105, 120)
            },
            'pressure_bar': {
                'normal': (3.5, 5.8),
                'elevated': (5.8, 6.5),
                'high': (6.5, 7.2),
                'critical': (7.2, 8.0)
            },
            'worker_count': {
                'normal': (0, 5),
                'elevated': (5, 8),
                'high': (8, 10),
                'critical': (10, 12)
            }
        }
        
        # COMPOUND RISK RULES - This is your secret sauce!
        self.compound_rules = [
            {
                'id': 'MAINTENANCE_GAS_LEAK',
                'weight': 8,
                'condition': lambda row, zone: (
                    row.get(f'{zone}_maintenance_active', 0) == 1 and
                    row.get(f'{zone}_gas_ppm', 0) > 35
                ),
                'message': 'CRITICAL: Maintenance in high gas area (>35ppm)!',
                'severity': 'CRITICAL'
            },
            {
                'id': 'PERMIT_GAS_COMBINATION',
                'weight': 6,
                'condition': lambda row, zone: (
                    row.get(f'{zone}_permit_active', 0) == 1 and
                    row.get(f'{zone}_gas_ppm', 0) > 40
                ),
                'message': 'HIGH: Active permit in dangerous gas conditions (>40ppm).',
                'severity': 'HIGH'
            },
            {
                'id': 'SHIFT_CHANGE_RISK',
                'weight': 4,
                'condition': lambda row, zone: (
                    row.get('shift_change', 0) == 1 and
                    row.get(f'{zone}_gas_ppm', 0) > 30
                ),
                'message': 'MEDIUM: Shift change during elevated gas levels (>30ppm).',
                'severity': 'MEDIUM'
            },
            {
                'id': 'OVERHEATING_WITH_GAS',
                'weight': 5,
                'condition': lambda row, zone: (
                    row.get(f'{zone}_temperature_c', 0) > 98 and
                    row.get(f'{zone}_gas_ppm', 0) > 25
                ),
                'message': 'HIGH: High temperature (>98C) combined with gas presence.',
                'severity': 'HIGH'
            },
            {
                'id': 'WORKER_OVER_CROWDING',
                'weight': 3,
                'condition': lambda row, zone: (
                    row.get(f'{zone}_worker_count', 0) > 9 and
                    row.get(f'{zone}_gas_ppm', 0) > 25
                ),
                'message': 'MEDIUM: Worker over-crowding in gas-prone area.',
                'severity': 'MEDIUM'
            },
            {
                'id': 'TRIPLE_THREAT',
                'weight': 10,
                'condition': lambda row, zone: (
                    row.get(f'{zone}_maintenance_active', 0) == 1 and
                    row.get(f'{zone}_gas_ppm', 0) > 35 and
                    row.get(f'{zone}_temperature_c', 0) > 95 and
                    row.get(f'{zone}_worker_count', 0) > 5
                ),
                'message': 'CRITICAL: Multiple risk factors! Immediate evacuation required!',
                'severity': 'CRITICAL'
            }
        ]
        
        self.logger = logging.getLogger(__name__)
        self.alert_history = []
    
    def get_sensor_risk(self, value: float, sensor_type: str) -> Tuple[int, str]:
        """Get risk contribution from a single sensor reading"""
        if sensor_type not in self.thresholds:
            return 0, 'NORMAL'
        
        thresholds = self.thresholds[sensor_type]
        
        if value >= thresholds['critical'][0]:
            return 4, 'CRITICAL'
        elif value >= thresholds['high'][0]:
            return 2, 'HIGH'
        elif value >= thresholds['elevated'][0]:
            return 1, 'ELEVATED'
        else:
            return 0, 'NORMAL'
    
    def analyze_zone(self, row: pd.Series, zone: str) -> Dict[str, Any]:
        """Analyze risk for a single zone in a single timestamp"""
        # Get all columns for this zone
        zone_cols = {col: row[col] for col in row.index if zone in col}
        
        # Base risk from individual sensors
        base_score = 0
        sensor_levels = {}
        factors = []
        
        for sensor in self.thresholds.keys():
            col_name = f'{zone}_{sensor}'
            if col_name in row:
                value = row[col_name]
                score, level = self.get_sensor_risk(value, sensor)
                base_score += score
                if score > 0:
                    factors.append(f'{sensor.upper()}_{level}')
                    sensor_levels[sensor] = {'value': value, 'level': level}
        
        # Check compound risk rules
        compound_factors = []
        for rule in self.compound_rules:
            if rule['condition'](row, zone):
                base_score += rule['weight']
                compound_factors.append(rule['id'])
                factors.append(rule['id'])
        
        # Cap score at 20
        final_score = min(base_score, 20)
        
        # Determine overall risk level
        if final_score >= 12:
            risk_level = 'CRITICAL'
        elif final_score >= 8:
            risk_level = 'HIGH'
        elif final_score >= 5:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'
        
        # Generate detailed message
        message = self._generate_message(row, zone, risk_level, final_score, compound_factors)
        
        return {
            'zone': zone,
            'risk_score': final_score,
            'risk_level': risk_level,
            'factors': factors,
            'compound_factors': compound_factors,
            'sensor_data': zone_cols,
            'sensor_levels': sensor_levels,
            'message': message
        }
    
    def _generate_message(self, row: pd.Series, zone: str, 
                         level: str, risk_score: float, compound_factors: List[str]) -> str:
        """Generate human-readable alert message"""
        gas = row.get(f'{zone}_gas_ppm', 0)
        temp = row.get(f'{zone}_temperature_c', 0)
        pressure = row.get(f'{zone}_pressure_bar', 0)
        workers = row.get(f'{zone}_worker_count', 0)
        maintenance = row.get(f'{zone}_maintenance_active', 0)
        permit = row.get(f'{zone}_permit_active', 0)
        
        msg = f"[{level}] ALERT in {zone}\n"
        msg += f"Risk Score: {risk_score}/20\n"
        msg += f"Gas: {gas:.1f} ppm | Temp: {temp:.1f}C | Pressure: {pressure:.1f} bar\n"
        msg += f"Workers: {workers:.0f} | Maintenance: {'Active' if maintenance else 'Inactive'}\n"
        msg += f"Permit: {'Active' if permit else 'Inactive'}\n"
        
        if compound_factors:
            msg += "\nCOMPOUND RISK DETECTED:\n"
            for factor in compound_factors:
                if factor == 'MAINTENANCE_GAS_LEAK':
                    msg += "   Maintenance in high gas area!\n"

                elif factor == 'TRIPLE_THREAT':
                    msg += "   ALL risk factors present!\n"
                    msg += "   Immediate action required!\n"
                else:
                    msg += f"   {factor.replace('_', ' ')}\n"
        
        return msg
    
    def analyze_timestamp(self, row: pd.Series) -> List[RiskAlert]:
        """Analyze a single timestamp across all zones"""
        alerts = []
        
        # Find all zones from columns
        zones = set()
        for col in row.index:
            if '_gas_ppm' in col:
                zones.add(col.replace('_gas_ppm', ''))
        
        for zone in zones:
            result = self.analyze_zone(row, zone)
            
            # Only alert for MEDIUM and above
            if result['risk_score'] >= 5:
                alert = RiskAlert(
                    timestamp=row['timestamp'],
                    zone=zone,
                    risk_score=result['risk_score'],
                    risk_level=result['risk_level'],
                    factors=result['factors'],
                    compound_factors=result['compound_factors'],
                    message=result['message'],
                    sensor_data=result['sensor_data']
                )
                alerts.append(alert)
                self.alert_history.append(alert)
        
        return alerts
    
    def analyze_dataframe(self, df: pd.DataFrame, check_frequency: int = 5) -> pd.DataFrame:
        """Analyze entire dataset"""
        print(f"Analyzing {len(df)} rows of data...")
        
        # Add risk columns
        df['max_risk_score'] = 0
        df['max_risk_level'] = 'LOW'
        df['risk_factors'] = ''
        df['compound_factors'] = ''
        df['alert_message'] = ''
        
        alerts_found = 0
        
        for idx, row in df.iterrows():
            if idx % check_frequency == 0:
                alerts = self.analyze_timestamp(row)
                
                if alerts:
                    max_alert = max(alerts, key=lambda x: x.risk_score)
                    df.at[idx, 'max_risk_score'] = max_alert.risk_score
                    df.at[idx, 'max_risk_level'] = max_alert.risk_level
                    df.at[idx, 'risk_factors'] = ','.join(max_alert.factors)
                    df.at[idx, 'compound_factors'] = ','.join(max_alert.compound_factors)
                    df.at[idx, 'alert_message'] = max_alert.message[:200]
                    alerts_found += 1
            
            if idx % 1000 == 0 and idx > 0:
                print(f"   Processed {idx}/{len(df)} rows... Found {alerts_found} alerts")
        
        print(f"Analysis complete! Found {alerts_found} alerts")
        print(f"Alert rate: {(alerts_found / (len(df) // check_frequency)) * 100:.2f}%")
        
        return df
    
    def export_alert_summary(self, df: pd.DataFrame) -> Dict:
        """Generate summary statistics"""
        total_checked = len(df)
        alert_rows = df[df['max_risk_score'] > 0]
        
        return {
            'total_data_points': total_checked,
            'total_alerts': len(alert_rows),
            'alert_rate': (len(alert_rows) / total_checked) * 100,
            'critical': len(df[df['max_risk_level'] == 'CRITICAL']),
            'high': len(df[df['max_risk_level'] == 'HIGH']),
            'medium': len(df[df['max_risk_level'] == 'MEDIUM']),
            'peak_risk_score': df['max_risk_score'].max(),
            'compound_events': len(df[df['compound_factors'].str.len() > 0])
        }


if __name__ == "__main__":
    print("Testing Compound Risk Engine...")
    print("=" * 50)
    
    # Load data
    df = pd.read_csv('data/plant_data.csv', parse_dates=['timestamp'])
    print(f"Loaded {len(df)} rows of data")
    
    # Initialize engine
    engine = CompoundRiskEngine()
    
    # Analyze dataset
    df_analyzed = engine.analyze_dataframe(df)
    
    # Show summary
    summary = engine.export_alert_summary(df_analyzed)
    print("\nAlert Summary:")
    for key, value in summary.items():
        print(f"   {key}: {value}")