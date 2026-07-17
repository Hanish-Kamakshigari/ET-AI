"""
Quick manual verification script for the Alerting & Post-Alerting System.

Run:  python verify_alerting.py

This script demonstrates the full alerting lifecycle end-to-end:
1. Creates an AlertCoordinator with a temporary database
2. Triggers a critical gas leak incident
3. Shows the incident in the database
4. Acknowledges the incident (with audit trail)
5. Resolves the incident
6. Displays the full incident timeline
7. Shows system metrics
8. Displays rule version information
"""

import os
import sys
import json
import tempfile
from datetime import datetime

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.alert_coordinator import (
    get_alert_coordinator, PersistenceLayer, RiskEvaluator,
    NotificationDispatcher, IncidentManager,
)
from src.alert_enhancements import (
    get_enhancement_orchestrator, RuleVersionRegistry,
    EnhancedPersistence, SystemMetricsProvider,
)


class MockDetection:
    """Minimal mock detection object matching the interface expected by RiskEvaluator."""
    def __init__(self, label: str, confidence: float = 0.9, zone_violation: bool = False) -> None:
        self.label = label
        self.confidence = confidence
        self.zone_violation = zone_violation


def main() -> None:
    print("=" * 80)
    print("  SurakshaAI - Alerting System Manual Verification")
    print("=" * 80)

    # ------------------------------------------------------------------
    # 1. Set up a temporary database
    # ------------------------------------------------------------------
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)  # Let SQLite create fresh

    print(f"\n[1] Temporary database: {db_path}")

    # ------------------------------------------------------------------
    # 2. Get AlertCoordinator singleton and rebind to temp DB
    # ------------------------------------------------------------------
    print("\n[2] Initializing AlertCoordinator...")
    coordinator = get_alert_coordinator()
    coordinator.config["database"]["db_path"] = db_path
    coordinator.is_primary = True
    coordinator.persistence = PersistenceLayer(coordinator.config)
    coordinator.risk_evaluator = RiskEvaluator(coordinator.config)
    coordinator.notification_dispatcher = NotificationDispatcher()
    coordinator.incident_manager = IncidentManager(
        coordinator.config,
        coordinator.persistence,
        coordinator.notification_dispatcher,
        coordinator.escalation_engine,
    )
    print(f"    Coordinator initialized with {len(coordinator.config['zones'])} zones")

    # ------------------------------------------------------------------
    # 3. Get the enhancement orchestrator
    # ------------------------------------------------------------------
    print("\n[3] Connecting Post-Alerting Enhancement Orchestrator...")
    orchestrator = get_enhancement_orchestrator()
    orchestrator.coordinator = coordinator
    orchestrator.persistence = EnhancedPersistence(coordinator.persistence)
    orchestrator.rule_registry = RuleVersionRegistry(coordinator.config)
    orchestrator.metrics_provider = SystemMetricsProvider(coordinator.persistence)
    print("    Enhancement orchestrator connected (audit trail, timeline, snapshots, metrics)")

    # ------------------------------------------------------------------
    # 4. Trigger a CRITICAL gas leak incident
    # ------------------------------------------------------------------
    print("\n[4] Triggering CRITICAL gas leak in Zone_A (Battery-4)...")
    print("    Simulating: gas_ppm=72 (critical range 55-100), temperature=90C, pressure=5.0 bar")
    print("    Persistence threshold: 15 frames - feeding 20 frames to trigger...")

    dets = [MockDetection("gas_leak")]
    zone = "Zone_A"
    telemetry = {"gas_ppm": 72, "temperature_c": 90, "pressure_bar": 5.0, "worker_count": 3}

    incident_id = None
    for frame in range(20):
        result = coordinator.process_frame(dets, zone, telemetry)
        if result and result.get("matched") and result.get("incident_id"):
            incident_id = result["incident_id"]

    if incident_id:
        print(f"    Incident CREATED: {incident_id}")
        inc = coordinator.persistence.fetch_incident_by_id(incident_id)
        if inc:
            print(f"      Severity: {inc.get('severity', 'N/A')}")
            print(f"      Message:  {inc.get('message', 'N/A')}")
            print(f"      Channels: {inc.get('channels', 'N/A')}")
        orchestrator.on_incident_created(incident_id, frame_number=20)
        print("    Audit trail + timeline event recorded (DETECTION)")
    else:
        print("    No alert triggered from process_frame - checking DB for any incidents...")
        conn = coordinator.persistence.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT incident_id, severity, status, message FROM incidents ORDER BY start_time DESC LIMIT 5")
        rows = cursor.fetchall()
        print(f"    Found {len(rows)} incidents in DB:")
        for r in rows:
            print(f"      {dict(r)}")
        coordinator.persistence.return_connection(conn)
        if rows:
            incident_id = rows[0]["incident_id"]
            print(f"    Using latest incident: {incident_id}")
        else:
            print("    No incidents found. Exiting.")
            return

    # ------------------------------------------------------------------
    # 5. Simulate notification dispatch
    # ------------------------------------------------------------------
    print("\n[5] Dispatching notifications (DASHBOARD, SMS, EMAIL, SIREN)...")
    channels = ["DASHBOARD", "SMS", "EMAIL", "SIREN"]
    orchestrator.on_notification_dispatched(incident_id, channels)
    for ch in channels:
        orchestrator.on_notification_sent(incident_id, ch)
    print(f"    {len(channels)} notifications dispatched and sent")
    print("    Timeline events recorded (NOTIFICATION_DISPATCHED + NOTIFICATION_SENT)")

    # ------------------------------------------------------------------
    # 6. Acknowledge the incident
    # ------------------------------------------------------------------
    print("\n[6] Acknowledging incident...")
    ack_by = "Shift Supervisor - Ravi Kumar"
    ack_remarks = "Investigating gas leak in Battery-4. Evacuating personnel."
    orchestrator.on_incident_acknowledged(incident_id, ack_by, ack_remarks)
    print(f"    Acknowledged by: {ack_by}")
    print(f"    Remarks: {ack_remarks}")
    print("    Response duration computed and stored")
    print("    Audit trail event recorded (ACKNOWLEDGED)")

    # ------------------------------------------------------------------
    # 7. Escalate the incident
    # ------------------------------------------------------------------
    print("\n[7] Escalating to Tier 2 (no acknowledgment within SLA)...")
    orchestrator.on_incident_escalated(incident_id, 2)
    print("    Escalation tier: 2")
    print("    Timeline event recorded (ESCALATED)")

    # ------------------------------------------------------------------
    # 8. Resolve the incident
    # ------------------------------------------------------------------
    print("\n[8] Resolving incident (gas leak contained)...")
    orchestrator.on_incident_resolved(incident_id)
    print("    Incident status: Resolved")
    print("    Audit trail event recorded (RESOLVED)")

    # ------------------------------------------------------------------
    # 9. Display the full incident timeline
    # ------------------------------------------------------------------
    print("\n[9] Full Incident Timeline:")
    print("-" * 80)
    timeline = orchestrator.get_incident_timeline(incident_id)
    for event in timeline:
        ts = event['event_timestamp'][:19].replace('T', ' ')
        etype = event['event_type']
        actor = event.get('actor', '')
        remarks = event.get('remarks', '')
        detail = f" [{actor}]" if actor else ""
        detail += f" - {remarks}" if remarks else ""
        print(f"  {ts}  {etype:<25s}{detail}")
    print("-" * 80)
    print(f"  Total timeline events: {len(timeline)}")

    # ------------------------------------------------------------------
    # 10. Display audit trail
    # ------------------------------------------------------------------
    print("\n[10] Audit Trail:")
    print("-" * 80)
    trail = orchestrator.get_audit_trail(incident_id)
    for event in trail:
        ts = event['event_timestamp'][:19].replace('T', ' ')
        etype = event['event_type']
        actor = event.get('actor', '')
        remarks = event.get('remarks', '')
        print(f"  {ts}  {etype:<25s}  by={actor:<25s}  remarks={remarks}")
    print("-" * 80)
    print(f"  Total audit events: {len(trail)}")

    # ------------------------------------------------------------------
    # 11. Display system metrics
    # ------------------------------------------------------------------
    print("\n[11] System Metrics Dashboard:")
    print("-" * 80)
    metrics = orchestrator.get_system_metrics()
    print(f"  Active incidents:           {metrics['active_incidents']}")
    print(f"  Total incidents (all time): {metrics['total_incidents_all_time']}")
    print(f"  Avg response time:          {metrics['average_response_time_seconds']:.1f}s")
    print(f"  Avg resolution time:        {metrics['average_resolution_time_seconds']:.1f}s")
    print(f"  Notification success rate:  {metrics['notification_success_rate']:.1f}%")
    print(f"  False positive rate:         {metrics['false_positive_rate']:.1f}%")
    print(f"  Incidents by severity:       {metrics['incidents_by_severity']}")
    print(f"  Incidents by zone:           {metrics['incidents_by_zone']}")
    print("-" * 80)

    # ------------------------------------------------------------------
    # 12. Display rule version info
    # ------------------------------------------------------------------
    print("\n[12] Rule Versioning:")
    print("-" * 80)
    active_version = orchestrator.get_active_rule_version()
    if active_version:
        print(f"  Active rule version:  {active_version['version_hash']}")
        print(f"  Activated at:          {active_version['activated_at'][:19].replace('T', ' ')}")
        snapshot_raw = active_version.get('rules_snapshot', '{}')
        snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
        print(f"  Rules snapshot keys:   {list(snapshot.keys()) if snapshot else 'N/A'}")
    else:
        print("  No active rule version found.")
    history = orchestrator.get_rule_version_history()
    print(f"  Total versions in DB: {len(history)}")
    print("-" * 80)

    # ------------------------------------------------------------------
    # 13. Verify incident is stamped with rule version
    # ------------------------------------------------------------------
    print("\n[13] Incident Rule Version Stamp:")
    print("-" * 80)
    conn = coordinator.persistence.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT incident_id, rule_version, response_duration_seconds, acknowledged_by FROM incidents WHERE incident_id = ?", (incident_id,))
    row = cursor.fetchone()
    if row:
        print(f"  Incident ID:              {row['incident_id']}")
        print(f"  Rule version stamp:       {row['rule_version']}")
        print(f"  Response duration (sec):  {row['response_duration_seconds']}")
        print(f"  Acknowledged by:          {row['acknowledged_by']}")
    else:
        print("  Incident not found in DB.")
    print("-" * 80)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    coordinator.persistence.return_connection(conn)
    print(f"\nVerification complete! Temporary DB: {db_path}")
    print(f"   Inspect it with: sqlite3 {db_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()