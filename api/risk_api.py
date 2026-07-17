"""
REST API for SurakshaAI - Enterprise Integration
Allows external systems to integrate with SurakshaAI
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime
import pandas as pd
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.risk_engine import CompoundRiskEngine
from src.alert_system import AlertSystem
from src.action_engine import ActionEngine
from src.compliance_engine import ComplianceEngine

# ============================================
# FastAPI App
# ============================================
app = FastAPI(
    title="SurakshaAI API",
    description="Enterprise Integration API for Industrial Safety",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ============================================
# Data Models
# ============================================
class SensorData(BaseModel):
    timestamp: datetime
    zone: str
    gas_ppm: float
    temperature_c: float
    pressure_bar: float
    worker_count: int
    maintenance_active: bool
    permit_active: bool

class BulkSensorData(BaseModel):
    plant_id: str
    data: List[SensorData]

class AlertResponse(BaseModel):
    alert_id: str
    timestamp: datetime
    zone: str
    risk_level: str
    risk_score: int
    compound_factors: List[str]
    message: str
    recommended_action: str

class ActionPlanResponse(BaseModel):
    alert_id: str
    zone: str
    priority: int
    immediate_actions: List[str]
    follow_up_actions: List[str]
    required_personnel: List[str]
    estimated_response_time: int

class ComplianceReportResponse(BaseModel):
    plant_name: str
    report_date: str
    metrics: Dict
    compliance: Dict
    overall_status: str

# ============================================
# Initialize Engines
# ============================================
risk_engine = CompoundRiskEngine()
alert_system = AlertSystem()
action_engine = ActionEngine()
compliance_engine = ComplianceEngine()

# ============================================
# Endpoints
# ============================================
@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "SurakshaAI",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": [
            "/docs - API Documentation",
            "/api/v1/ingest - Ingest sensor data",
            "/api/v1/alerts - Get alerts",
            "/api/v1/alerts/{id}/acknowledge - Acknowledge alert",
            "/api/v1/actions/{alert_id} - Get action plan",
            "/api/v1/compliance/report - Generate compliance report",
            "/api/v1/health - Health check"
        ]
    }

@app.post("/api/v1/ingest")
async def ingest_sensor_data(data: BulkSensorData, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Ingest sensor data from plant systems
    
    This is how real plants would send data to SurakshaAI.
    Supports background processing for large datasets.
    """
    try:
        # Convert to DataFrame
        df = pd.DataFrame([d.dict() for d in data.data])
        
        # Process in background
        background_tasks.add_task(process_ingested_data, df, data.plant_id)
        
        return {
            "status": "accepted",
            "plant_id": data.plant_id,
            "rows_processed": len(df),
            "message": "Data accepted for processing"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_ingested_data(df: pd.DataFrame, plant_id: str) -> None:
    """Background processing for ingested data"""
    try:
        # Analyze with risk engine
        df_analyzed = risk_engine.analyze_dataframe(df)
        
        # Generate alerts
        for idx, row in df_analyzed.iterrows():
            if row['max_risk_score'] > 0:
                # Create alert
                alert = {
                    'timestamp': row['timestamp'],
                    'zone': row.get('zone', 'Unknown'),
                    'risk_level': row['max_risk_level'],
                    'risk_score': row['max_risk_score'],
                    'factors': row.get('risk_factors', '').split(',') if row.get('risk_factors') else [],
                    'compound_factors': row.get('compound_factors', '').split(',') if row.get('compound_factors') else [],
                    'message': f"Risk score is elevated in {row.get('zone', 'Unknown')} at {row['max_risk_score']:.1f}"
                }
                
                # Store alert via database trigger
                alert_system.trigger_alert(row, alert)
                
        print(f"✅ Processed {len(df)} records for plant {plant_id}")
    except Exception as e:
        print(f"❌ Error processing data: {e}")

@app.get("/api/v1/alerts", response_model=List[AlertResponse])
async def get_alerts(limit: int = 10, severity: Optional[str] = None) -> List[AlertResponse]:
    """
    Get recent alerts
    
    Args:
        limit: Number of alerts to return
        severity: Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)
    """
    alerts = alert_system.get_recent_alerts(limit)
    
    if severity:
        alerts = [a for a in alerts if a.get('risk_level') == severity]
    
    return [
        AlertResponse(
            alert_id=f"ALT-{a.get('timestamp', datetime.now()).strftime('%Y%m%d%H%M%S')}",
            timestamp=a.get('timestamp', datetime.now()),
            zone=a.get('zone', 'Unknown'),
            risk_level=a.get('risk_level', 'LOW'),
            risk_score=a.get('risk_score', 0),
            compound_factors=a.get('compound_factors', []),
            message=a.get('message', 'No message'),
            recommended_action=get_recommended_action(a)
        )
        for a in alerts[:limit]
    ]

@app.post("/api/v1/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> Dict[str, Any]:
    """Acknowledge an alert - integrates with EHS workflows"""
    success = alert_system.acknowledge_alert(alert_id)
    if success:
        return {"status": "acknowledged", "alert_id": alert_id}
    raise HTTPException(status_code=404, detail="Alert not found")

@app.get("/api/v1/actions/{alert_id}", response_model=ActionPlanResponse)
async def get_action_plan(alert_id: str) -> ActionPlanResponse:
    """Get action plan for an alert"""
    # Find alert
    alert = None
    for a in alert_system.get_recent_alerts(100):
        if a['alert_id'] == alert_id:
            alert = a
            break
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Create alert object for action engine
    class AlertObject:
        def __init__(self, data: Dict[str, Any]) -> None:
            self.zone = data.get('zone', 'Unknown')
            self.risk_level = data.get('risk_level', 'LOW')
            self.compound_factors = data.get('compound_factors', [])
    
    action_plan = action_engine.get_action_plan(AlertObject(alert))
    
    return ActionPlanResponse(
        alert_id=alert_id,
        zone=action_plan['zone'],
        priority=action_plan['priority'],
        immediate_actions=action_plan['immediate_actions'],
        follow_up_actions=action_plan['follow_up_actions'],
        required_personnel=action_plan['required_personnel'],
        estimated_response_time=action_plan['estimated_response_time']
    )

@app.get("/api/v1/compliance/report", response_model=ComplianceReportResponse)
async def get_compliance_report(start_date: Optional[str] = None, end_date: Optional[str] = None) -> ComplianceReportResponse:
    """Generate compliance report"""
    # Load data
    df = pd.read_csv('data/plant_data.csv', parse_dates=['timestamp'])
    
    # Parse dates if provided
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    
    report = compliance_engine.generate_compliance_report(df, start, end)
    
    return ComplianceReportResponse(
        plant_name=report['plant_name'],
        report_date=report['report_date'],
        metrics=report['metrics'],
        compliance=report['compliance'],
        overall_status=report['overall_status']
    )

@app.get("/api/v1/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

def get_recommended_action(alert: Dict) -> str:
    """Get recommended action for an alert"""
    recommendations = {
        'MAINTENANCE_GAS_LEAK': 'Evacuate area, stop maintenance, call emergency team',
        'TRIPLE_THREAT': 'IMMEDIATE EVACUATION - All personnel leave zone',
        'PERMIT_GAS_COMBINATION': 'Revoke permit, investigate gas source',
        'OVERHEATING_WITH_GAS': 'Cool reactor, shut down process if needed',
        'WORKER_OVER_CROWDING': 'Reduce workers in zone, increase ventilation'
    }
    
    compound_factors = alert.get('compound_factors', [])
    for factor in compound_factors:
        if factor in recommendations:
            return recommendations[factor]
    
    return 'Investigate conditions and follow standard protocols'

# ============================================
# Run the API
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)