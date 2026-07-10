"""
SurakshaAI Alerting System Enhancements — Production Quality Layer

Non-invasive enhancement module that adds:
1. Alert acknowledgment audit trail (who, when, remarks, response duration)
2. Snapshot attachment storage (captured frame alongside incident)
3. Incident timeline (detection → notifications → ack → resolution)
4. System metrics dashboard (active incidents, response times, success rates, FP rate)
5. Rule versioning (stores rule version that generated each incident for audits)

Design principle: This module sits ON TOP of the existing AlertCoordinator.
It reads from the same SQLite database and adds new tables/columns via
migration-safe ALTER statements. The existing system continues to work
unchanged — these features are opt-in.
"""

import os
import json
import sqlite3
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger("AlertEnhancements")

# Singleton instance — populated lazily by get_enhancement_orchestrator()
_enhancement_orchestrator = None


# ==============================================================================
# RULE VERSIONING
# ==============================================================================

class RuleVersionRegistry:
    """
    Tracks rule configuration versions so each incident can record which
    version of the safety rules triggered it. Essential for post-incident
    audits when rules evolve over time.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._version_cache: Optional[str] = None

    def compute_version(self) -> str:
        """Compute a deterministic hash of the rules config for versioning."""
        rules = self.config.get("rules", {})
        rules_json = json.dumps(rules, sort_keys=True, default=str)
        return hashlib.sha256(rules_json.encode()).hexdigest()[:12]

    def get_version(self) -> str:
        if self._version_cache is None:
            self._version_cache = self.compute_version()
        return self._version_cache

    def get_version_metadata(self) -> Dict[str, Any]:
        return {
            "rule_version": self.get_version(),
            "rules_snapshot": self.config.get("rules", {}),
            "generated_at": datetime.now().isoformat()
        }


# ==============================================================================
# ENHANCED PERSISTENCE (Migration-Safe)
# ==============================================================================

class EnhancedPersistence:
    """
    Wraps the existing PersistenceLayer to add new tables and columns
    without modifying the original schema. Uses ALTER TABLE ... ADD COLUMN
    with IF NOT EXISTS semantics via try/except.
    """

    def __init__(self, persistence_layer):
        self.persistence = persistence_layer
        self._migrate()

    def _migrate(self):
        """Add new columns and tables for enhancement features."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()

            # --- Add rule_version column to incidents ---
            try:
                cursor.execute("ALTER TABLE incidents ADD COLUMN rule_version TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # --- Add ack_remarks column to incidents ---
            try:
                cursor.execute("ALTER TABLE incidents ADD COLUMN ack_remarks TEXT")
            except sqlite3.OperationalError:
                pass

            # --- Add response_duration_seconds column to incidents ---
            try:
                cursor.execute("ALTER TABLE incidents ADD COLUMN response_duration_seconds REAL")
            except sqlite3.OperationalError:
                pass

            # --- Add snapshot_path column to incidents ---
            try:
                cursor.execute("ALTER TABLE incidents ADD COLUMN snapshot_path TEXT")
            except sqlite3.OperationalError:
                pass

            # --- Audit trail table ---
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_audit_trail (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                actor TEXT,
                remarks TEXT,
                metadata TEXT,
                FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
            )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_incident ON incident_audit_trail(incident_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_event ON incident_audit_trail(event_type);"
            )

            # --- Incident timeline table ---
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_timeline (
                timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                event_description TEXT,
                event_metadata TEXT,
                FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
            )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_incident ON incident_timeline(incident_id);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_time ON incident_timeline(event_timestamp);"
            )

            # --- Snapshot metadata table ---
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                snapshot_path TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                frame_number INTEGER,
                image_format TEXT DEFAULT 'jpg',
                file_size_bytes INTEGER,
                FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
            )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_incident ON incident_snapshots(incident_id);"
            )

            # --- Rule version history table ---
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS rule_versions (
                version_hash TEXT PRIMARY KEY,
                rules_snapshot TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                deactivated_at TEXT,
                is_active INTEGER DEFAULT 1
            )
            """)

            conn.commit()
            logger.info("Enhancement migration completed successfully")
        except Exception as e:
            logger.error(f"Enhancement migration failed: {e}")
            conn.rollback()
        finally:
            self.persistence.return_connection(conn)

    def record_audit_event(
        self,
        incident_id: str,
        event_type: str,
        actor: str = "system",
        remarks: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Record a single audit event for an incident."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO incident_audit_trail
                    (incident_id, event_type, event_timestamp, actor, remarks, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                incident_id,
                event_type,
                datetime.now().isoformat(),
                actor,
                remarks,
                json.dumps(metadata or {})
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to record audit event: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def get_audit_trail(self, incident_id: str) -> List[Dict[str, Any]]:
        """Retrieve the full audit trail for an incident."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM incident_audit_trail WHERE incident_id = ? ORDER BY event_timestamp ASC",
                (incident_id,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            self.persistence.return_connection(conn)

    def record_timeline_event(
        self,
        incident_id: str,
        event_type: str,
        event_description: str = "",
        event_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Record a timeline event for an incident."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO incident_timeline
                    (incident_id, event_type, event_timestamp, event_description, event_metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (
                incident_id,
                event_type,
                datetime.now().isoformat(),
                event_description,
                json.dumps(event_metadata or {})
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to record timeline event: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def get_incident_timeline(self, incident_id: str) -> List[Dict[str, Any]]:
        """Retrieve the full chronological timeline for an incident."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM incident_timeline WHERE incident_id = ? ORDER BY event_timestamp ASC",
                (incident_id,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            self.persistence.return_connection(conn)

    def save_snapshot(
        self,
        incident_id: str,
        snapshot_path: str,
        frame_number: Optional[int] = None,
        image_format: str = "jpg"
    ) -> bool:
        """Record a snapshot attachment for an incident."""
        file_size = 0
        if os.path.exists(snapshot_path):
            file_size = os.path.getsize(snapshot_path)

        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO incident_snapshots
                    (incident_id, snapshot_path, captured_at, frame_number, image_format, file_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                incident_id,
                snapshot_path,
                datetime.now().isoformat(),
                frame_number,
                image_format,
                file_size
            ))

            # Also update the incident record with snapshot path
            cursor.execute(
                "UPDATE incidents SET snapshot_path = ? WHERE incident_id = ?",
                (snapshot_path, incident_id)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save snapshot record: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def get_snapshots(self, incident_id: str) -> List[Dict[str, Any]]:
        """Retrieve all snapshots for an incident."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM incident_snapshots WHERE incident_id = ? ORDER BY captured_at ASC",
                (incident_id,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            self.persistence.return_connection(conn)

    def register_rule_version(self, version_hash: str, rules_snapshot: Dict[str, Any]) -> bool:
        """Register a new rule version in the history table."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            # Deactivate previous active versions
            cursor.execute(
                "UPDATE rule_versions SET is_active = 0, deactivated_at = ?",
                (datetime.now().isoformat(),)
            )
            # Insert new active version
            cursor.execute("""
                INSERT OR REPLACE INTO rule_versions
                    (version_hash, rules_snapshot, activated_at, is_active)
                VALUES (?, ?, ?, 1)
            """, (
                version_hash,
                json.dumps(rules_snapshot, default=str),
                datetime.now().isoformat()
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to register rule version: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def stamp_incident_with_rule_version(self, incident_id: str, rule_version: str) -> bool:
        """Stamp an incident with the rule version that generated it."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE incidents SET rule_version = ? WHERE incident_id = ?",
                (rule_version, incident_id)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to stamp rule version: {e}")
            conn.rollback()
            return False
        finally:
            self.persistence.return_connection(conn)

    def get_active_rule_version(self) -> Optional[Dict[str, Any]]:
        """Get the currently active rule version."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM rule_versions WHERE is_active = 1 ORDER BY activated_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            self.persistence.return_connection(conn)

    def get_all_rule_versions(self) -> List[Dict[str, Any]]:
        """Get all rule version history."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rule_versions ORDER BY activated_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            self.persistence.return_connection(conn)


# ==============================================================================
# SYSTEM METRICS PROVIDER
# ==============================================================================

class SystemMetricsProvider:
    """
    Provides operational metrics for the system metrics dashboard:
    - active incidents count
    - average response time
    - notification success rate
    - false-positive rate
    - average resolution time
    """

    def __init__(self, persistence_layer):
        self.persistence = persistence_layer

    def get_metrics(self) -> Dict[str, Any]:
        """Compute all system metrics in a single pass."""
        conn = self.persistence.get_connection()
        try:
            cursor = conn.cursor()

            # Active incidents count
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM incidents WHERE status NOT IN ('Resolved', 'Archived')"
            )
            active_count = cursor.fetchone()["cnt"]

            # Average response time (start_time -> acknowledged_at)
            cursor.execute("""
                SELECT AVG(
                    (julianday(acknowledged_at) - julianday(start_time)) * 86400
                ) as avg_response
                FROM incidents
                WHERE acknowledged_at IS NOT NULL AND start_time IS NOT NULL
            """)
            row = cursor.fetchone()
            avg_response_time = row["avg_response"] if row and row["avg_response"] else 0.0

            # Average resolution time (start_time -> end_time)
            cursor.execute("""
                SELECT AVG(
                    (julianday(end_time) - julianday(start_time)) * 86400
                ) as avg_resolution
                FROM incidents
                WHERE end_time IS NOT NULL AND start_time IS NOT NULL
            """)
            row = cursor.fetchone()
            avg_resolution_time = row["avg_resolution"] if row and row["avg_resolution"] else 0.0

            # Notification success rate
            cursor.execute("SELECT COUNT(*) as total FROM notification_statuses")
            total_notifications = cursor.fetchone()["total"]
            cursor.execute("SELECT COUNT(*) as sent FROM notification_statuses WHERE status = 'Sent'")
            sent_notifications = cursor.fetchone()["sent"]
            notification_success_rate = (
                (sent_notifications / total_notifications * 100.0) if total_notifications > 0 else 0.0
            )

            # False-positive rate
            # (incidents that were auto-resolved without acknowledgment vs total resolved)
            cursor.execute("SELECT COUNT(*) as total FROM incidents WHERE status = 'Resolved'")
            total_resolved = cursor.fetchone()["total"]
            cursor.execute(
                "SELECT COUNT(*) as fp FROM incidents WHERE status = 'Resolved' AND acknowledged_by IS NULL"
            )
            auto_resolved = cursor.fetchone()["fp"]
            false_positive_rate = (
                (auto_resolved / total_resolved * 100.0) if total_resolved > 0 else 0.0
            )

            # Incidents by severity
            cursor.execute("""
                SELECT severity, COUNT(*) as cnt
                FROM incidents
                WHERE status NOT IN ('Resolved', 'Archived')
                GROUP BY severity
            """)
            by_severity = {row["severity"]: row["cnt"] for row in cursor.fetchall()}

            # Incidents by zone
            cursor.execute("""
                SELECT zone, COUNT(*) as cnt
                FROM incidents
                WHERE status NOT IN ('Resolved', 'Archived')
                GROUP BY zone
            """)
            by_zone = {row["zone"]: row["cnt"] for row in cursor.fetchall()}

            # Total incidents all-time
            cursor.execute("SELECT COUNT(*) as total FROM incidents")
            total_incidents = cursor.fetchone()["total"]

            return {
                "active_incidents": active_count,
                "total_incidents_all_time": total_incidents,
                "average_response_time_seconds": round(avg_response_time, 2),
                "average_resolution_time_seconds": round(avg_resolution_time, 2),
                "notification_success_rate": round(notification_success_rate, 2),
                "false_positive_rate": round(false_positive_rate, 2),
                "incidents_by_severity": by_severity,
                "incidents_by_zone": by_zone,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to compute system metrics: {e}")
            return {
                "active_incidents": 0,
                "total_incidents_all_time": 0,
                "average_response_time_seconds": 0.0,
                "average_resolution_time_seconds": 0.0,
                "notification_success_rate": 0.0,
                "false_positive_rate": 0.0,
                "incidents_by_severity": {},
                "incidents_by_zone": {},
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }
        finally:
            self.persistence.return_connection(conn)


# ==============================================================================
# ENHANCEMENT ORCHESTRATOR
# ==============================================================================

_enhancement_orchestrator: Optional["AlertEnhancementOrchestrator"] = None


class AlertEnhancementOrchestrator:
    """
    Central orchestrator that ties together all enhancement features.
    Designed to be called optionally after the existing AlertCoordinator
    completes its work -- zero disruption to the working system.

    Usage:
        from src.alert_enhancements import get_enhancement_orchestrator
        enhancer = get_enhancement_orchestrator()
        enhancer.on_incident_created(incident_id, rule_version, snapshot_path)
        enhancer.on_incident_acknowledged(incident_id, operator, remarks)
        enhancer.on_incident_resolved(incident_id)
        enhancer.on_notification_sent(incident_id, channel)
        metrics = enhancer.get_system_metrics()
        timeline = enhancer.get_incident_timeline(incident_id)
        audit = enhancer.get_audit_trail(incident_id)
    """

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.persistence = EnhancedPersistence(coordinator.persistence)
        self.rule_registry = RuleVersionRegistry(coordinator.config)
        self.metrics_provider = SystemMetricsProvider(coordinator.persistence)

        # Register current rule version
        version = self.rule_registry.get_version()
        self.persistence.register_rule_version(version, self.rule_registry.get_version_metadata())

    def on_incident_created(
        self,
        incident_id: str,
        rule_version: Optional[str] = None,
        snapshot_path: Optional[str] = None,
        frame_number: Optional[int] = None
    ) -> None:
        """Call after a new incident is created by AlertCoordinator."""
        rv = rule_version or self.rule_registry.get_version()

        # Stamp rule version
        self.persistence.stamp_incident_with_rule_version(incident_id, rv)

        # Record audit event
        self.persistence.record_audit_event(
            incident_id, "INCIDENT_CREATED", actor="system",
            remarks="Incident created by AlertCoordinator",
            metadata={"rule_version": rv}
        )

        # Record timeline event
        self.persistence.record_timeline_event(
            incident_id, "DETECTION",
            event_description="Hazard detected by risk evaluator",
            event_metadata={"rule_version": rv}
        )

        # Save snapshot if provided
        if snapshot_path:
            self.persistence.save_snapshot(incident_id, snapshot_path, frame_number)
            self.persistence.record_timeline_event(
                incident_id, "SNAPSHOT_CAPTURED",
                event_description=f"Frame snapshot saved to {snapshot_path}",
                event_metadata={"frame_number": frame_number}
            )

    def on_notification_dispatched(self, incident_id: str, channels: List[str]) -> None:
        """Call after notifications are dispatched."""
        for channel in channels:
            self.persistence.record_timeline_event(
                incident_id, "NOTIFICATION_DISPATCHED",
                event_description=f"Notification dispatched to {channel}",
                event_metadata={"channel": channel}
            )

    def on_notification_sent(self, incident_id: str, channel: str) -> None:
        """Call when a notification is confirmed sent."""
        self.persistence.record_timeline_event(
            incident_id, "NOTIFICATION_SENT",
            event_description=f"Notification confirmed sent via {channel}",
            event_metadata={"channel": channel}
        )

    def on_notification_failed(self, incident_id: str, channel: str, error: str) -> None:
        """Call when a notification fails after retries."""
        self.persistence.record_audit_event(
            incident_id, "NOTIFICATION_FAILED", actor="system",
            remarks=f"Notification failed on {channel}: {error}",
            metadata={"channel": channel, "error": error}
        )
        self.persistence.record_timeline_event(
            incident_id, "NOTIFICATION_FAILED",
            event_description=f"Notification failed via {channel}: {error}",
            event_metadata={"channel": channel, "error": error}
        )

    def on_incident_acknowledged(
        self,
        incident_id: str,
        operator_name: str,
        remarks: str = ""
    ) -> None:
        """Call after an incident is acknowledged."""
        # Fetch incident to compute response duration
        incident = self.coordinator.persistence.fetch_incident_by_id(incident_id)
        response_duration = None
        if incident and incident.get("start_time"):
            try:
                start = datetime.fromisoformat(incident["start_time"])
                response_duration = (datetime.now() - start).total_seconds()
            except Exception:
                pass

        # Update incident with ack remarks and response duration
        conn = self.persistence.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE incidents SET ack_remarks = ?, response_duration_seconds = ? WHERE incident_id = ?",
                (remarks, response_duration, incident_id)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to update ack remarks: {e}")
            conn.rollback()
        finally:
            self.persistence.persistence.return_connection(conn)

        # Record audit event
        self.persistence.record_audit_event(
            incident_id, "ACKNOWLEDGED", actor=operator_name,
            remarks=remarks,
            metadata={"response_duration_seconds": response_duration}
        )

        # Record timeline event
        self.persistence.record_timeline_event(
            incident_id, "ACKNOWLEDGED",
            event_description=f"Acknowledged by {operator_name}",
            event_metadata={
                "operator": operator_name,
                "remarks": remarks,
                "response_duration_seconds": response_duration
            }
        )

    def on_incident_escalated(self, incident_id: str, new_tier: int) -> None:
        """Call when an incident is escalated."""
        self.persistence.record_audit_event(
            incident_id, "ESCALATED", actor="system",
            remarks=f"Incident escalated to tier {new_tier}",
            metadata={"new_tier": new_tier}
        )
        self.persistence.record_timeline_event(
            incident_id, "ESCALATED",
            event_description=f"Escalated to tier {new_tier}",
            event_metadata={"new_tier": new_tier}
        )

    def on_incident_resolved(self, incident_id: str) -> None:
        """Call after an incident is resolved."""
        # Compute total resolution duration
        incident = self.coordinator.persistence.fetch_incident_by_id(incident_id)
        resolution_duration = None
        if incident and incident.get("start_time"):
            try:
                start = datetime.fromisoformat(incident["start_time"])
                resolution_duration = (datetime.now() - start).total_seconds()
            except Exception:
                pass

        self.persistence.record_audit_event(
            incident_id, "RESOLVED", actor="system",
            remarks="Incident resolved",
            metadata={"resolution_duration_seconds": resolution_duration}
        )
        self.persistence.record_timeline_event(
            incident_id, "RESOLVED",
            event_description="Incident resolved",
            event_metadata={"resolution_duration_seconds": resolution_duration}
        )

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get operational metrics for the system metrics dashboard."""
        return self.metrics_provider.get_metrics()

    def get_incident_timeline(self, incident_id: str) -> List[Dict[str, Any]]:
        """Get the full chronological timeline for an incident."""
        return self.persistence.get_incident_timeline(incident_id)

    def get_audit_trail(self, incident_id: str) -> List[Dict[str, Any]]:
        """Get the full audit trail for an incident."""
        return self.persistence.get_audit_trail(incident_id)

    def get_snapshots(self, incident_id: str) -> List[Dict[str, Any]]:
        """Get all snapshots for an incident."""
        return self.persistence.get_snapshots(incident_id)

    def get_rule_version_history(self) -> List[Dict[str, Any]]:
        """Get the history of all rule versions."""
        return self.persistence.get_all_rule_versions()

    def get_active_rule_version(self) -> Optional[Dict[str, Any]]:
        """Get the currently active rule version."""
        return self.persistence.get_active_rule_version()


def get_enhancement_orchestrator() -> AlertEnhancementOrchestrator:
    """Get or create the singleton enhancement orchestrator."""
    global _enhancement_orchestrator
    if _enhancement_orchestrator is None:
        from src.alert_coordinator import get_alert_coordinator
        coordinator = get_alert_coordinator()
        _enhancement_orchestrator = AlertEnhancementOrchestrator(coordinator)
    orchestrator = _enhancement_orchestrator
    assert orchestrator is not None, "Failed to initialise AlertEnhancementOrchestrator"
    return orchestrator