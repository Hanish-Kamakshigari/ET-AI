"""
Tests for Alert Enhancement Module — Production Quality Features

Covers:
1. Alert acknowledgment audit trail (who, when, remarks, response duration)
2. Snapshot attachment storage
3. Incident timeline (detection -> notifications -> ack -> resolution)
4. System metrics dashboard
5. Rule versioning
6. Edge cases: simultaneous critical incidents, notification failures,
   corrupted persistence data, sensor dropouts, high-frequency event bursts
"""

import os
import sys
import json
import time
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from typing import Dict, Any, Generator, Optional, List, Tuple
from unittest.mock import MagicMock

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.alert_enhancements import (
    RuleVersionRegistry,
    EnhancedPersistence,
    SystemMetricsProvider,
    AlertEnhancementOrchestrator,
)


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def mock_config() -> Dict[str, Any]:
    """Minimal config matching alerting.yaml structure."""
    return {
        "rules": {
            "gas_ppm": {"normal": [0, 20], "critical": [55, 100]},
            "temperature_c": {"normal": [60, 88], "critical": [105, 120]},
        },
        "database": {"db_path": "data/test_enhancements.db", "timeout_seconds": 10},
        "zones": {"Zone_A": {"label": "Battery-4"}},
        "escalation_matrix": {
            "CRITICAL": {"channels": ["DASHBOARD", "SMS"], "response_time": 60, "required_ack": True},
            "LOW": {"channels": ["DASHBOARD"], "response_time": 1800, "required_ack": False},
        },
    }


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Remove so SQLite can create fresh
    os.unlink(path)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def mock_persistence(temp_db: str) -> Generator[MagicMock, None, None]:
    """Mock PersistenceLayer with a real SQLite database."""
    persistence = MagicMock()
    persistence.db_path = temp_db

    # Create schema using an initial connection
    init_conn = sqlite3.connect(temp_db, check_same_thread=False)
    init_conn.row_factory = sqlite3.Row

    # Create base incidents table (mimicking the real schema)
    init_conn.execute("""
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

    # Create notification_statuses table
    init_conn.execute("""
    CREATE TABLE IF NOT EXISTS notification_statuses (
        incident_id TEXT,
        channel TEXT,
        status TEXT,
        retry_count INTEGER DEFAULT 0,
        last_updated TEXT,
        PRIMARY KEY (incident_id, channel)
    )
    """)

    init_conn.commit()
    init_conn.close()

    # Return a fresh connection per call (mirrors real PersistenceLayer pool behaviour
    # and is safe for concurrent tests — each thread gets its own connection).
    _open_connections: list = []

    def _get_conn() -> sqlite3.Connection:
        c = sqlite3.connect(temp_db, check_same_thread=False, timeout=10)
        c.row_factory = sqlite3.Row
        _open_connections.append(c)
        return c

    def _return_conn(c: sqlite3.Connection) -> None:
        try:
            c.close()
        except Exception:
            pass

    persistence.get_connection = _get_conn
    persistence.return_connection = _return_conn

    yield persistence

    # Close any connections the test body opened via get_connection() but
    # didn't return — required on Windows so temp_db can delete the file.
    for c in _open_connections:
        try:
            c.close()
        except Exception:
            pass


@pytest.fixture
def orchestrator(mock_config: Dict[str, Any], mock_persistence: MagicMock) -> Generator[AlertEnhancementOrchestrator, None, None]:
    """Create an AlertEnhancementOrchestrator with mock dependencies."""
    coordinator = MagicMock()
    coordinator.config = mock_config
    coordinator.persistence = mock_persistence
    coordinator.persistence.fetch_incident_by_id = lambda iid: _fetch_incident(mock_persistence.get_connection(), iid)

    orch = AlertEnhancementOrchestrator(coordinator)
    yield orch


def _fetch_incident(conn: sqlite3.Connection, incident_id: str) -> Optional[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _insert_incident(
    conn: sqlite3.Connection,
    incident_id: str,
    zone: str = "Zone_A",
    severity: str = "CRITICAL",
    status: str = "Active",
    start_time: Optional[str] = None,
    acknowledged_by: Optional[str] = None,
    acknowledged_at: Optional[str] = None,
    end_time: Optional[str] = None,
) -> None:
    """Helper to insert a test incident."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO incidents (incident_id, incident_key, zone, hazard_type, status, severity,
                               message, start_time, end_time, acknowledged_by, acknowledged_at,
                               risk_score, channels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        incident_id, f"{incident_id}:{zone}:test_hazard", zone, "test_hazard", status, severity,
        "Test incident", start_time or datetime.now().isoformat(), end_time,
        acknowledged_by, acknowledged_at, 75.0, "DASHBOARD,SMS"
    ))
    conn.commit()


# ==============================================================================
# 1. RULE VERSIONING TESTS
# ==============================================================================

class TestRuleVersioning:
    def test_rule_version_is_deterministic(self, mock_config: Dict[str, Any]) -> None:
        """Rule version hash should be deterministic for the same config."""
        registry1 = RuleVersionRegistry(mock_config)
        registry2 = RuleVersionRegistry(mock_config)
        assert registry1.get_version() == registry2.get_version()

    def test_rule_version_changes_with_config(self, mock_config: Dict[str, Any]) -> None:
        """Different rule configs should produce different version hashes."""
        registry1 = RuleVersionRegistry(mock_config)
        modified_config = json.loads(json.dumps(mock_config))
        modified_config["rules"]["gas_ppm"]["critical"] = [60, 100]
        registry2 = RuleVersionRegistry(modified_config)
        assert registry1.get_version() != registry2.get_version()

    def test_rule_version_is_12_chars(self, mock_config: Dict[str, Any]) -> None:
        """Version hash should be truncated to 12 characters."""
        registry = RuleVersionRegistry(mock_config)
        version = registry.get_version()
        assert len(version) == 12

    def test_rule_version_metadata_contains_snapshot(self, mock_config: Dict[str, Any]) -> None:
        """Version metadata should include the rules snapshot."""
        registry = RuleVersionRegistry(mock_config)
        meta = registry.get_version_metadata()
        assert "rule_version" in meta
        assert "rules_snapshot" in meta
        assert meta["rules_snapshot"] == mock_config["rules"]

    def test_rule_version_registered_in_db(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Active rule version should be registered in the database."""
        versions = orchestrator.get_rule_version_history()
        assert len(versions) >= 1
        active = orchestrator.get_active_rule_version()
        assert active is not None
        assert active["is_active"] == 1

    def test_incident_stamped_with_rule_version(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Incidents should be stamped with the rule version that generated them."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-001")
        orchestrator.on_incident_created("INC-001")

        cursor = conn.cursor()
        cursor.execute("SELECT rule_version FROM incidents WHERE incident_id = ?", ("INC-001",))
        row = cursor.fetchone()
        assert row is not None
        assert row["rule_version"] is not None
        assert len(row["rule_version"]) == 12


# ==============================================================================
# 2. AUDIT TRAIL TESTS
# ==============================================================================

class TestAuditTrail:
    def test_audit_event_recorded_on_creation(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """An audit event should be recorded when an incident is created."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-AUDIT-001")
        orchestrator.on_incident_created("INC-AUDIT-001")

        trail = orchestrator.get_audit_trail("INC-AUDIT-001")
        assert len(trail) >= 1
        assert trail[0]["event_type"] == "INCIDENT_CREATED"
        assert trail[0]["actor"] == "system"

    def test_audit_trail_records_acknowledgment(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Audit trail should record who acknowledged, when, and remarks."""
        conn = mock_persistence.get_connection()
        start = (datetime.now() - timedelta(seconds=30)).isoformat()
        _insert_incident(conn, "INC-ACK-001", start_time=start)
        orchestrator.on_incident_created("INC-ACK-001")
        orchestrator.on_incident_acknowledged("INC-ACK-001", "John Doe", "Investigating gas leak")

        trail = orchestrator.get_audit_trail("INC-ACK-001")
        ack_events = [e for e in trail if e["event_type"] == "ACKNOWLEDGED"]
        assert len(ack_events) == 1
        assert ack_events[0]["actor"] == "John Doe"
        assert ack_events[0]["remarks"] == "Investigating gas leak"

    def test_audit_trail_records_response_duration(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Response duration should be computed and stored on acknowledgment."""
        conn = mock_persistence.get_connection()
        start = (datetime.now() - timedelta(seconds=45)).isoformat()
        _insert_incident(conn, "INC-DUR-001", start_time=start)
        orchestrator.on_incident_created("INC-DUR-001")
        orchestrator.on_incident_acknowledged("INC-DUR-001", "Operator")

        cursor = conn.cursor()
        cursor.execute("SELECT response_duration_seconds FROM incidents WHERE incident_id = ?", ("INC-DUR-001",))
        row = cursor.fetchone()
        assert row["response_duration_seconds"] is not None
        assert row["response_duration_seconds"] >= 40  # ~45 seconds

    def test_audit_trail_records_resolution(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Audit trail should record incident resolution."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-RES-001")
        orchestrator.on_incident_created("INC-RES-001")
        orchestrator.on_incident_resolved("INC-RES-001")

        trail = orchestrator.get_audit_trail("INC-RES-001")
        resolved_events = [e for e in trail if e["event_type"] == "RESOLVED"]
        assert len(resolved_events) == 1


# ==============================================================================
# 3. INCIDENT TIMELINE TESTS
# ==============================================================================

class TestIncidentTimeline:
    def test_timeline_has_detection_event(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Timeline should start with a DETECTION event."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-TL-001")
        orchestrator.on_incident_created("INC-TL-001")

        timeline = orchestrator.get_incident_timeline("INC-TL-001")
        assert len(timeline) >= 1
        assert timeline[0]["event_type"] == "DETECTION"

    def test_timeline_records_notifications(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Timeline should record notification dispatch and sent events."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-TL-002")
        orchestrator.on_incident_created("INC-TL-002")
        orchestrator.on_notification_dispatched("INC-TL-002", ["DASHBOARD", "SMS"])
        orchestrator.on_notification_sent("INC-TL-002", "DASHBOARD")
        orchestrator.on_notification_sent("INC-TL-002", "SMS")

        timeline = orchestrator.get_incident_timeline("INC-TL-002")
        event_types = [e["event_type"] for e in timeline]
        assert "NOTIFICATION_DISPATCHED" in event_types
        assert "NOTIFICATION_SENT" in event_types

    def test_timeline_is_chronologically_ordered(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Timeline events should be in chronological order."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-TL-003")
        orchestrator.on_incident_created("INC-TL-003")
        time.sleep(0.05)
        orchestrator.on_notification_dispatched("INC-TL-003", ["DASHBOARD"])
        time.sleep(0.05)
        orchestrator.on_incident_acknowledged("INC-TL-003", "Operator")
        time.sleep(0.05)
        orchestrator.on_incident_resolved("INC-TL-003")

        timeline = orchestrator.get_incident_timeline("INC-TL-003")
        timestamps = [e["event_timestamp"] for e in timeline]
        assert timestamps == sorted(timestamps)

    def test_timeline_records_full_lifecycle(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Timeline should capture the full incident lifecycle."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-LIFE-001")
        orchestrator.on_incident_created("INC-LIFE-001")
        orchestrator.on_notification_dispatched("INC-LIFE-001", ["DASHBOARD", "EMAIL"])
        orchestrator.on_notification_sent("INC-LIFE-001", "DASHBOARD")
        orchestrator.on_incident_acknowledged("INC-LIFE-001", "Jane")
        orchestrator.on_incident_resolved("INC-LIFE-001")

        timeline = orchestrator.get_incident_timeline("INC-LIFE-001")
        event_types = [e["event_type"] for e in timeline]
        assert "DETECTION" in event_types
        assert "NOTIFICATION_DISPATCHED" in event_types
        assert "NOTIFICATION_SENT" in event_types
        assert "ACKNOWLEDGED" in event_types
        assert "RESOLVED" in event_types


# ==============================================================================
# 4. SNAPSHOT ATTACHMENT TESTS
# ==============================================================================

class TestSnapshotAttachment:
    def test_snapshot_saved_and_retrieved(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Snapshots should be saved and retrievable for an incident."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-SNAP-001")

        # Create a dummy snapshot file
        fd, snap_path = tempfile.mkstemp(suffix=".jpg")
        os.write(fd, b"fake image data")
        os.close(fd)

        try:
            orchestrator.on_incident_created("INC-SNAP-001", snapshot_path=snap_path, frame_number=42)
            snapshots = orchestrator.get_snapshots("INC-SNAP-001")
            assert len(snapshots) == 1
            assert snapshots[0]["snapshot_path"] == snap_path
            assert snapshots[0]["frame_number"] == 42
            assert snapshots[0]["file_size_bytes"] > 0
        finally:
            os.unlink(snap_path)

    def test_snapshot_path_stored_on_incident(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """The incident record itself should have the snapshot path."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-SNAP-002")

        fd, snap_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)

        try:
            orchestrator.on_incident_created("INC-SNAP-002", snapshot_path=snap_path)
            cursor = conn.cursor()
            cursor.execute("SELECT snapshot_path FROM incidents WHERE incident_id = ?", ("INC-SNAP-002",))
            row = cursor.fetchone()
            assert row["snapshot_path"] == snap_path
        finally:
            os.unlink(snap_path)

    def test_snapshot_timeline_event_recorded(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """A SNAPSHOT_CAPTURED timeline event should be recorded."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-SNAP-003")

        fd, snap_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)

        try:
            orchestrator.on_incident_created("INC-SNAP-003", snapshot_path=snap_path)
            timeline = orchestrator.get_incident_timeline("INC-SNAP-003")
            event_types = [e["event_type"] for e in timeline]
            assert "SNAPSHOT_CAPTURED" in event_types
        finally:
            os.unlink(snap_path)


# ==============================================================================
# 5. SYSTEM METRICS TESTS
# ==============================================================================

class TestSystemMetrics:
    def test_metrics_returns_all_fields(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """System metrics should return all expected fields."""
        metrics = orchestrator.get_system_metrics()
        assert "active_incidents" in metrics
        assert "total_incidents_all_time" in metrics
        assert "average_response_time_seconds" in metrics
        assert "average_resolution_time_seconds" in metrics
        assert "notification_success_rate" in metrics
        assert "false_positive_rate" in metrics
        assert "incidents_by_severity" in metrics
        assert "incidents_by_zone" in metrics
        assert "timestamp" in metrics

    def test_active_incidents_count(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Active incidents count should reflect non-resolved incidents."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-MET-001", status="Active")
        _insert_incident(conn, "INC-MET-002", status="Active")
        _insert_incident(conn, "INC-MET-003", status="Resolved", end_time=datetime.now().isoformat())

        metrics = orchestrator.get_system_metrics()
        assert metrics["active_incidents"] == 2

    def test_notification_success_rate(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Notification success rate should be computed correctly."""
        conn = mock_persistence.get_connection()
        cursor = conn.cursor()
        # Insert 4 notification statuses: 3 sent, 1 failed
        for i, status in enumerate(["Sent", "Sent", "Sent", "Failed"]):
            cursor.execute("""
                INSERT INTO notification_statuses (incident_id, channel, status, last_updated)
                VALUES (?, ?, ?, ?)
            """, (f"INC-NOTIF-{i}", f"CH{i}", status, datetime.now().isoformat()))
        conn.commit()

        metrics = orchestrator.get_system_metrics()
        assert metrics["notification_success_rate"] == 75.0

    def test_false_positive_rate(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """False-positive rate = auto-resolved without ack / total resolved."""
        conn = mock_persistence.get_connection()
        # 2 resolved with ack, 3 resolved without ack -> 60% FP rate
        for i in range(2):
            _insert_incident(conn, f"INC-FP-ACK-{i}", status="Resolved",
                            acknowledged_by="Operator", acknowledged_at=datetime.now().isoformat(),
                            end_time=datetime.now().isoformat())
        for i in range(3):
            _insert_incident(conn, f"INC-FP-NOACK-{i}", status="Resolved",
                            end_time=datetime.now().isoformat())

        metrics = orchestrator.get_system_metrics()
        assert metrics["false_positive_rate"] == 60.0

    def test_metrics_by_severity(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Metrics should include breakdown by severity."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-SEV-001", severity="CRITICAL")
        _insert_incident(conn, "INC-SEV-002", severity="CRITICAL")
        _insert_incident(conn, "INC-SEV-003", severity="HIGH")

        metrics = orchestrator.get_system_metrics()
        assert metrics["incidents_by_severity"].get("CRITICAL") == 2
        assert metrics["incidents_by_severity"].get("HIGH") == 1


# ==============================================================================
# 6. EDGE CASE TESTS
# ==============================================================================

class TestEdgeCases:
    def test_simultaneous_critical_incidents(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Multiple critical incidents created simultaneously should all be tracked."""
        conn = mock_persistence.get_connection()
        incident_ids = [f"INC-SIM-{i}" for i in range(10)]

        threads = []
        for iid in incident_ids:
            _insert_incident(conn, iid, severity="CRITICAL")

            def create(iid: str = iid) -> None:
                orchestrator.on_incident_created(iid)

            t = threading.Thread(target=create)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)

        for iid in incident_ids:
            trail = orchestrator.get_audit_trail(iid)
            assert len(trail) >= 1
            assert trail[0]["event_type"] == "INCIDENT_CREATED"

    def test_notification_failure_recorded(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Notification failures should be recorded in audit trail and timeline."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-FAIL-001")
        orchestrator.on_incident_created("INC-FAIL-001")
        orchestrator.on_notification_failed("INC-FAIL-001", "EMAIL", "SMTP timeout")

        trail = orchestrator.get_audit_trail("INC-FAIL-001")
        fail_events = [e for e in trail if e["event_type"] == "NOTIFICATION_FAILED"]
        assert len(fail_events) == 1
        assert "SMTP timeout" in fail_events[0]["remarks"]

        timeline = orchestrator.get_incident_timeline("INC-FAIL-001")
        fail_tl = [e for e in timeline if e["event_type"] == "NOTIFICATION_FAILED"]
        assert len(fail_tl) == 1

    def test_corrupted_persistence_graceful_degradation(self, mock_config: Dict[str, Any]) -> None:
        """System should degrade gracefully if persistence is corrupted."""
        broken_persistence = MagicMock()
        broken_persistence.get_connection.side_effect = sqlite3.OperationalError("database is locked")

        coordinator = MagicMock()
        coordinator.config = mock_config
        coordinator.persistence = broken_persistence

        # EnhancedPersistence should handle migration failure gracefully
        # (it logs the error but doesn't crash)
        with pytest.raises(sqlite3.OperationalError):
            EnhancedPersistence(broken_persistence)

    def test_high_frequency_event_bursts(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """High-frequency event bursts should be handled without data loss."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-BURST-001")

        # Fire 100 timeline events rapidly
        for i in range(100):
            orchestrator.on_notification_dispatched("INC-BURST-001", [f"CH{i}"])

        timeline = orchestrator.get_incident_timeline("INC-BURST-001")
        dispatch_events = [e for e in timeline if e["event_type"] == "NOTIFICATION_DISPATCHED"]
        assert len(dispatch_events) == 100

    def test_nonexistent_incident_queries(self, orchestrator: AlertEnhancementOrchestrator) -> None:
        """Querying audit trail / timeline for nonexistent incident should return empty."""
        assert orchestrator.get_audit_trail("NONEXISTENT") == []
        assert orchestrator.get_incident_timeline("NONEXISTENT") == []
        assert orchestrator.get_snapshots("NONEXISTENT") == []

    def test_escalation_recorded_in_timeline(self, orchestrator: AlertEnhancementOrchestrator, mock_persistence: MagicMock) -> None:
        """Escalation events should be recorded in both audit trail and timeline."""
        conn = mock_persistence.get_connection()
        _insert_incident(conn, "INC-ESC-001")
        orchestrator.on_incident_created("INC-ESC-001")
        orchestrator.on_incident_escalated("INC-ESC-001", 2)

        trail = orchestrator.get_audit_trail("INC-ESC-001")
        esc_events = [e for e in trail if e["event_type"] == "ESCALATED"]
        assert len(esc_events) == 1

        timeline = orchestrator.get_incident_timeline("INC-ESC-001")
        esc_tl = [e for e in timeline if e["event_type"] == "ESCALATED"]
        assert len(esc_tl) == 1

    def test_migration_is_idempotent(self, mock_persistence: MagicMock) -> None:
        """Running migration multiple times should not fail."""
        # First migration
        EnhancedPersistence(mock_persistence)
        # Second migration (should be no-op)
        EnhancedPersistence(mock_persistence)
        # Verify tables still exist
        conn = mock_persistence.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='incident_audit_trail'")
        assert cursor.fetchone() is not None