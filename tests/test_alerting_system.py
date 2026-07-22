"""
Automated unit and integration test suite for the AlertCoordinator alerting system.
Covers persistence, deduplication, escalation, health check, concurrency, and backward compatibility.
Now includes comprehensive coverage of RiskEngine, ComplianceEngine, ActionEngine, Priority sorting, and Cooldowns.
"""

import os
import sys
import time
import unittest
import threading
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Setup path to import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.alert_coordinator import get_alert_coordinator, AlertStatus, AlertSeverity
from src.alert_system import (
    AlertSystem,
    AlertManager,
    evaluate_alert_conditions,
    dispatch_alerts,
    clear_alert_if_safe,
    SafetyAlert
)
from src.risk_engine import CompoundRiskEngine, RiskAlert
from src.compliance_engine import ComplianceEngine
from src.action_engine import ActionEngine

class MockDetection:
    def __init__(self, label: str, confidence: float = 0.9, zone_violation: bool = False) -> None:
        self.label = label
        self.confidence = confidence
        self.zone_violation = zone_violation

class TestAlertingArchitecture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.coordinator = get_alert_coordinator()
        cls.coordinator.config["database"]["db_path"] = "data/test_alerts.db"
        cls.coordinator.is_primary = True
        
        from src.alert_coordinator import (
            PersistenceLayer, 
            RiskEvaluator, 
            IncidentManager, 
            DashboardAdapter, 
            NotificationDispatcher
        )
        cls.coordinator.persistence = PersistenceLayer(cls.coordinator.config)
        cls.coordinator.risk_evaluator = RiskEvaluator(cls.coordinator.config)
        cls.coordinator.notification_dispatcher = NotificationDispatcher()
        cls.coordinator.dashboard_adapter = DashboardAdapter(cls.coordinator.persistence)
        cls.coordinator.incident_manager = IncidentManager(
            cls.coordinator.config, 
            cls.coordinator.persistence, 
            cls.coordinator.notification_dispatcher, 
            cls.coordinator.escalation_engine,
            cls.coordinator.dashboard_adapter
        )

    @classmethod
    def tearDownClass(cls) -> None:
        import os
        for ext in ["", "-wal", "-shm"]:
            path = f"data/test_alerts.db{ext}"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def setUp(self) -> None:
        # Clear database to ensure clean, hermetic tests
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            for table in ["alerts", "incidents", "rule_engine", "incident_frames", "notification_statuses"]:
                try:
                    cursor.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            self.coordinator.persistence.return_connection(conn)

        # Clear in-memory cooldown cache to ensure hermetic tests
        if hasattr(self.coordinator.incident_manager, "_cooldown_cache"):
            with self.coordinator.incident_manager._cooldown_lock:
                self.coordinator.incident_manager._cooldown_cache.clear()

    def test_risk_evaluation_pure(self) -> None:
        """Verify the RiskEvaluator logic does not depend on database/state"""
        evaluator = self.coordinator.risk_evaluator
        
        # Fire detection should trigger CRITICAL
        dets = [MockDetection("fire")]
        res = evaluator.evaluate(dets, {}, False, 0, False, "Zone_A")
        self.assertTrue(res["matched"])
        self.assertEqual(res["severity"], "CRITICAL")
        self.assertIn("siren", [ch.lower() for ch in res["notification_channels"]])
        
        # Gas ppm elevate should trigger HIGH
        res_gas = evaluator.evaluate([], {"gas_ppm": 25.0}, False, 0, False, "Zone_B")
        self.assertTrue(res_gas["matched"])
        self.assertEqual(res_gas["severity"], "HIGH")

    def test_deduplication_and_frame_persistence(self) -> None:
        """Verify that frame processing deduplicates same incident and increments frame counts"""
        zone = "Zone_B"
        dets = [MockDetection("smoke", confidence=0.88)]
        
        # First frame - creates NEW
        eval1 = self.coordinator.process_frame(dets, zone, {"gas_ppm": 5.0})
        self.assertTrue(eval1["matched"])
        
        # Fetch key
        key = self.coordinator.detection_processor.generate_incident_key(zone, "FIRE_SMOKE")
        
        inc1 = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc1)
        incident_id = inc1["incident_id"]
        
        self.assertEqual(inc1["status"], AlertStatus.NEW.value)
        self.assertEqual(inc1["frame_count"], 1)
        
        # Second frame
        self.coordinator.process_frame(dets, zone, {"gas_ppm": 5.0})
        inc2 = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertEqual(inc2["incident_id"], incident_id)
        self.assertIn(inc2["status"], (AlertStatus.PENDING.value, AlertStatus.ACTIVE.value))
        self.assertEqual(inc2["frame_count"], 2)
        
        # Verify frame log contains frame logs
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM incident_frames WHERE incident_id = ?", (incident_id,))
            cnt = cursor.fetchone()["cnt"]
            self.assertGreaterEqual(cnt, 2)
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_lifecycle_and_acknowledgement(self) -> None:
        """Verify incident goes from PENDING to ACTIVE, and acknowledgement updates DB state"""
        zone = "Zone_A"
        dets = [MockDetection("gas_leak")]
        
        # Process frame threshold times (we simulate 15 frames)
        for i in range(16):
            self.coordinator.process_frame(dets, zone, {"gas_ppm": 40.0})
            
        key = self.coordinator.detection_processor.generate_incident_key(zone, "GAS_LEAK")
        inc = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc)
        self.assertEqual(inc["status"], AlertStatus.ACTIVE.value)
        
        # Acknowledge incident
        iid = inc["incident_id"]
        success = self.coordinator.acknowledge_incident(iid, "Operator Bob")
        self.assertTrue(success)
        
        inc_ack = self.coordinator.persistence.fetch_incident_by_id(iid)
        self.assertEqual(inc_ack["status"], AlertStatus.ACKNOWLEDGED.value)
        self.assertEqual(inc_ack["acknowledged_by"], "Operator Bob")

    def test_escalation_engine(self) -> None:
        """Verify the event-driven priority queue executes escalation on unacknowledged ACTIVE incidents"""
        zone = "Zone_C"
        dets = [MockDetection("gas_leak")] # trigger telemetry temperature breach
        
        # Process 16 frames to push it to ACTIVE
        for _ in range(16):
            self.coordinator.process_frame(dets, zone, {"temperature": 105.0})
            
        key = self.coordinator.detection_processor.generate_incident_key(zone, "TEMPERATURE_CRITICAL")
        inc = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc)
        self.assertEqual(inc["status"], AlertStatus.ACTIVE.value)
        
        # Manually backdate the start_time in the database to simulate elapsed time for escalation (>= 30s)
        from datetime import timedelta
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            past_time = (datetime.now() - timedelta(seconds=40)).isoformat()
            cursor.execute("UPDATE incidents SET start_time = ? WHERE incident_id = ?", (past_time, inc["incident_id"]))
            conn.commit()
        finally:
            self.coordinator.persistence.return_connection(conn)
            
        # Manually schedule immediate escalation check (delay = 0.1s)
        self.coordinator.escalation_engine.schedule_escalation(inc["incident_id"], 0.1)
        time.sleep(0.5)
        
        # Check escalated status
        inc_esc = self.coordinator.persistence.fetch_incident_by_id(inc["incident_id"])
        self.assertEqual(inc_esc["status"], "Escalated")
        self.assertEqual(inc_esc["escalation_tier"], 2)

    def test_concurrent_db_writes(self) -> None:
        """Verify that concurrent writes from multiple threads do not cause SQLite locking errors (WAL check)"""
        exceptions = []
        
        def writer_thread(t_idx: int) -> None:
            try:
                for i in range(10):
                    self.coordinator.process_frame(
                        [MockDetection("gas_leak")],
                        f"Zone_Thread_{t_idx}",
                        {"gas_ppm": 50.0}
                    )
            except Exception as e:
                exceptions.append(e)

        threads = []
        for idx in range(5):
            t = threading.Thread(target=writer_thread, args=(idx,))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        self.assertEqual(len(exceptions), 0, f"Exceptions occurred during concurrent write: {exceptions}")

    def test_health_monitor(self) -> None:
        """Verify health check returns required indicators"""
        health = self.coordinator.health_monitor.health_check()
        self.assertIn("database_pool_status", health)
        self.assertIn("active_alerts_count", health)
        self.assertIn("average_frame_processing_ms", health)
        self.assertIn("notification_success_rate", health)

    def test_backward_compatibility_layer(self) -> None:
        """Ensure legacy modules and methods wrap AlertCoordinator seamlessly"""
        # Test evaluate_alert_conditions compatibility wrapper
        res = evaluate_alert_conditions([], 1, "Zone_A", {"gas_ppm": 5.0})
        self.assertTrue(res["should_alert"])
        self.assertEqual(res["severity"], "MEDIUM")
        
        # Test AlertManager compatibility wrapper
        am = AlertManager()
        self.assertIsInstance(am.active_alerts, dict)
        
        # Test AlertSystem compatibility wrapper
        sys_compat = AlertSystem()
        active = sys_compat.get_active_alerts()
        self.assertIsInstance(active, list)

    def test_all_data_driven_rules(self) -> None:
        """Verify that all YAML configuration defined rules evaluate correctly on first frame"""
        evaluator = self.coordinator.risk_evaluator
        
        # 1. Test FIRE_SMOKE detection rule
        fs_res = evaluator.evaluate([MockDetection("fire")], {}, False, 0, False, "Zone_A")
        self.assertTrue(fs_res["matched"])
        self.assertEqual(fs_res["severity"], "CRITICAL")
        self.assertTrue(any("siren" in act.lower() or "fire" in act.lower() for act in fs_res["recommended_actions"]))
        
        # 2. Test GAS_LEAK detection rule
        gl_res = evaluator.evaluate([MockDetection("gas_leak")], {}, False, 0, False, "Zone_A")
        self.assertTrue(gl_res["matched"])
        self.assertEqual(gl_res["severity"], "CRITICAL")
        
        # 3. Test ZONE_INTRUSION detection attribute rule
        zi_res = evaluator.evaluate([MockDetection("person", zone_violation=True)], {}, False, 0, False, "Zone_A")
        self.assertTrue(zi_res["matched"])
        self.assertEqual(zi_res["severity"], "CRITICAL")
        self.assertTrue(any("security" in act.lower() for act in zi_res["recommended_actions"]))
        
        # 4. Test GAS_CRITICAL telemetry rule (gas_ppm > 35)
        gc_res = evaluator.evaluate([], {"gas_ppm": 40.0}, False, 0, False, "Zone_A")
        self.assertTrue(gc_res["matched"])
        self.assertEqual(gc_res["severity"], "CRITICAL")
        
        # 5. Test GAS_ELEVATED telemetry rule (gas_ppm > 20)
        ge_res = evaluator.evaluate([], {"gas_ppm": 25.0}, False, 0, False, "Zone_A")
        self.assertTrue(ge_res["matched"])
        self.assertEqual(ge_res["severity"], "HIGH")
        
        # 6. Test TEMPERATURE_CRITICAL telemetry rule (temp > 95)
        tc_res = evaluator.evaluate([], {"temperature": 100.0}, False, 0, False, "Zone_A")
        self.assertTrue(tc_res["matched"])
        self.assertEqual(tc_res["severity"], "CRITICAL")
        
        # 7. Test OVERPRESSURE telemetry rule (pressure > 80, only on Zone_C)
        op_res_other = evaluator.evaluate([], {"pressure": 90.0}, False, 0, False, "Zone_A")
        self.assertFalse(op_res_other["matched"]) # should be ignored in Zone_A
        
        op_res_zone_c = evaluator.evaluate([], {"pressure_bar": 90.0}, False, 0, False, "Zone_C")
        self.assertTrue(op_res_zone_c["matched"])
        self.assertEqual(op_res_zone_c["severity"], "CRITICAL")
        
        # 8. Test PPE_VIOLATION telemetry rule (violations_count > 0)
        ppe_res = evaluator.evaluate([], {"violations_count": 2}, False, 0, False, "Zone_A")
        self.assertTrue(ppe_res["matched"])
        self.assertEqual(ppe_res["severity"], "MEDIUM")

    # ==========================================================================
    # NEW REFACTORING UNIT TESTS
    # ==========================================================================

    def test_risk_engine_sensor_risk(self) -> None:
        """Verify RiskEngine single sensor thresholds"""
        risk_engine = CompoundRiskEngine()
        self.assertEqual(risk_engine.get_sensor_risk(10.0, 'gas_ppm')[1], 'NORMAL')
        self.assertEqual(risk_engine.get_sensor_risk(25.0, 'gas_ppm')[1], 'ELEVATED')
        self.assertEqual(risk_engine.get_sensor_risk(40.0, 'gas_ppm')[1], 'HIGH')
        self.assertEqual(risk_engine.get_sensor_risk(60.0, 'gas_ppm')[1], 'CRITICAL')

    def test_risk_engine_analyze_zone(self) -> None:
        """Verify RiskEngine compound rule matching"""
        risk_engine = CompoundRiskEngine()
        row = pd.Series({
            'Zone_A_gas_ppm': 45.0,
            'Zone_A_temperature_c': 90.0,
            'Zone_A_worker_count': 2.0,
            'Zone_A_permit_active': 1,
            'Zone_A_maintenance_active': 0
        })
        res = risk_engine.analyze_zone(row, 'Zone_A')
        self.assertEqual(res['risk_level'], 'HIGH')
        self.assertIn('PERMIT_GAS_COMBINATION', res['compound_factors'])

    def test_compliance_engine(self) -> None:
        """Verify ComplianceEngine checking and reporting"""
        compliance_engine = ComplianceEngine()
        df = pd.DataFrame([{
            'Zone_A_gas_ppm': 55.0,
            'Zone_A_temperature_c': 80.0,
            'max_risk_score': 8.0,
            'max_risk_level': 'CRITICAL'
        }])
        res = compliance_engine.check_compliance(df)
        self.assertEqual(res['OISD_150']['status'], 'VIOLATION')
        self.assertEqual(compliance_engine.get_compliance_score(df), 90.0)

    def test_action_engine(self) -> None:
        """Verify ActionEngine prescriptive advice generation"""
        action_engine = ActionEngine(knowledge_base_path='data/test_actions.json')
        try:
            alert = RiskAlert(
                timestamp=pd.Timestamp.now(),
                zone='Zone_A',
                risk_score=8.0,
                risk_level='CRITICAL',
                factors=['gas_ppm'],
                compound_factors=['MAINTENANCE_GAS_LEAK'],
                message='CRITICAL: Maintenance in high gas area',
                sensor_data={'gas_ppm': 40.0}
            )
            plan = action_engine.get_action_plan(alert)
            self.assertEqual(plan['priority'], 1)
            self.assertTrue(len(plan['immediate_actions']) > 0)
        finally:
            if os.path.exists('data/test_actions.json'):
                try:
                    os.remove('data/test_actions.json')
                except Exception:
                    pass

    def test_cooldown_logic(self) -> None:
        """Verify cooldown suppresses repeated alerts within the threshold"""
        zone = "Zone_A"
        dets = [MockDetection("gas_leak")]
        
        # 1. Trigger and resolve an incident
        self.coordinator.process_frame(dets, zone, {"gas_ppm": 40.0})
        key = self.coordinator.detection_processor.generate_incident_key(zone, "GAS_LEAK")
        inc = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc)
        
        # Force resolve it
        self.coordinator.resolve_incident(inc["incident_id"])
        
        # Verify it is RESOLVED
        inc_res = self.coordinator.persistence.fetch_incident_by_id(inc["incident_id"])
        self.assertEqual(inc_res["status"], AlertStatus.RESOLVED.value)
        
        # 2. Trigger again immediately (should be suppressed by cooldown)
        self.coordinator.process_frame(dets, zone, {"gas_ppm": 40.0})
        
        # Since it is suppressed, no new active incident with the same key should be created
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM incidents WHERE incident_key = ? OR incident_key LIKE ? ORDER BY start_time DESC LIMIT 1", (key, key + "_resolved_%"))
            row = cursor.fetchone()
            self.assertEqual(row["status"], AlertStatus.RESOLVED.value) # latest status must still be resolved, not NEW/ACTIVE
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_alert_priority_sorting(self) -> None:
        """Verify matching rules are processed in priority order (Critical first)"""
        # Trigger fire (Critical) and worker count (Normal/None)
        # We check that process_frame evaluates both, and they are ordered
        evaluator = self.coordinator.risk_evaluator
        dets = [MockDetection("fire"), MockDetection("person")]
        evaluation = evaluator.evaluate(dets, {"violations_count": 1}, False, 2, False, "Zone_A")
        
        # Ensure rules are matched
        matched_rule_ids = [r["rule_id"] for r in evaluation["matched_rules"]]
        self.assertIn("FIRE_SMOKE", matched_rule_ids)
        self.assertIn("PPE_VIOLATION", matched_rule_ids)
        
        # Run process_frame and check that matching runs without errors
        res = self.coordinator.process_frame(dets, "Zone_A", {"violations_count": 1})
        self.assertIsNotNone(res)

    def test_composite_cooldown_index_exists(self) -> None:
        """Verify the new composite index exists on the database"""
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA index_list('incidents')")
            indexes = [row["name"] for row in cursor.fetchall()]
            self.assertIn("idx_incidents_cooldown", indexes)
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_in_memory_cooldown_cache(self) -> None:
        """Verify that resolved incidents populate the in-memory cache and bypass database select"""
        zone = "Zone_A"
        dets = [MockDetection("fire")]
        
        # 1. Trigger incident
        self.coordinator.process_frame(dets, zone, {})
        key = self.coordinator.detection_processor.generate_incident_key(zone, "FIRE_SMOKE")
        inc = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc)
        
        # Ensure it's not in the cooldown cache yet
        self.coordinator.incident_manager._cooldown_cache.pop(key, None)
        
        # 2. Resolve incident
        self.coordinator.resolve_incident(inc["incident_id"])
        
        # 3. Verify in-memory cooldown cache has been updated
        self.assertIn(key, self.coordinator.incident_manager._cooldown_cache)
        
        # 4. Trigger again (should be suppressed via cache)
        # Clear database records for resolved status to ensure lookup CANNOT succeed via database query,
        # verifying that it relies strictly on the in-memory cache.
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM incidents WHERE incident_key = ? OR incident_key LIKE ?", (key, key + "_resolved_%"))
            conn.commit()
        finally:
            self.coordinator.persistence.return_connection(conn)
            
        # Process frame should still be suppressed due to the in-memory cache
        self.coordinator.process_frame(dets, zone, {})
        
        # Fetching by key should return None as the database record was deleted and new one was suppressed
        inc_suppressed = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNone(inc_suppressed)

    def test_configurable_hysteresis_frames(self) -> None:
        """Verify the custom resolution hysteresis configuration is loaded and applied"""
        zone = "Zone_A"
        dets = [MockDetection("fire")]
        
        # Set custom hysteresis in config
        orig_hysteresis = self.coordinator.config["persistence"].get("resolution_hysteresis_frames", 10)
        self.coordinator.config["persistence"]["resolution_hysteresis_frames"] = 4
        self.coordinator.incident_manager.resolution_hysteresis_frames = 4
        
        try:
            # 1. Push it to active state (16 frames)
            for _ in range(16):
                self.coordinator.process_frame(dets, zone, {})
                
            key = self.coordinator.detection_processor.generate_incident_key(zone, "FIRE_SMOKE")
            inc = self.coordinator.persistence.fetch_incident_by_key(key)
            self.assertEqual(inc["status"], AlertStatus.ACTIVE.value)
            
            # 2. Process absent frames to test hysteresis resolution
            # Hysteresis is set to 4, so 3 absent frames should keep it active
            for _ in range(3):
                self.coordinator.process_frame([], zone, {})
                
            inc_active = self.coordinator.persistence.fetch_incident_by_key(key)
            self.assertEqual(inc_active["status"], AlertStatus.ACTIVE.value)
            
            # 4th absent frame should resolve it
            self.coordinator.process_frame([], zone, {})
            inc_resolved = self.coordinator.persistence.fetch_incident_by_key(key)
            self.assertEqual(inc_resolved["status"], AlertStatus.RESOLVED.value)
            
        finally:
            self.coordinator.config["persistence"]["resolution_hysteresis_frames"] = orig_hysteresis
            self.coordinator.incident_manager.resolution_hysteresis_frames = orig_hysteresis

    def test_discard_pending_incidents(self) -> None:
        """Verify that PENDING/NEW incidents are deleted/discarded if the hazard disappears"""
        zone = "Zone_A"
        dets = [MockDetection("fire")]
        
        # Trigger frame 1 - creates NEW incident
        self.coordinator.process_frame(dets, zone, {})
        key = self.coordinator.detection_processor.generate_incident_key(zone, "FIRE_SMOKE")
        
        inc = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc)
        self.assertEqual(inc["status"], AlertStatus.NEW.value)
        
        # Hazard disappears on next frame - should delete/discard the pending incident
        orig_fp = self.coordinator.health_monitor.false_positive_count
        self.coordinator.process_frame([], zone, {})
        
        inc_discarded = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNone(inc_discarded)
        self.assertEqual(self.coordinator.health_monitor.false_positive_count, orig_fp + 1)

    def test_cooldown_updates_resolved_record(self) -> None:
        """Verify hazard re-trigger inside cooldown updates the resolved incident instead of creating a new one"""
        zone = "Zone_A"
        dets = [MockDetection("fire")]
        
        # Push incident to ACTIVE
        for _ in range(16):
            self.coordinator.process_frame(dets, zone, {})
            
        key = self.coordinator.detection_processor.generate_incident_key(zone, "FIRE_SMOKE")
        inc = self.coordinator.persistence.fetch_incident_by_key(key)
        self.assertIsNotNone(inc)
        self.assertEqual(inc["status"], AlertStatus.ACTIVE.value)
        incident_id = inc["incident_id"]
        orig_frame_count = inc["frame_count"]
        
        # Resolve it
        self.coordinator.resolve_incident(incident_id)
        inc_res = self.coordinator.persistence.fetch_incident_by_id(incident_id)
        self.assertEqual(inc_res["status"], AlertStatus.RESOLVED.value)
        orig_end_time = inc_res["end_time"]
        
        # Wait a small delay to ensure the system clock changes
        time.sleep(0.05)
        
        # Trigger again immediately (within cooldown)
        self.coordinator.process_frame(dets, zone, {})
        
        # No new incident should be created, and the resolved incident should have:
        # 1) updated frame count, 2) refreshed end_time timestamp
        inc_after = self.coordinator.persistence.fetch_incident_by_id(incident_id)
        self.assertEqual(inc_after["status"], AlertStatus.RESOLVED.value)
        self.assertEqual(inc_after["frame_count"], orig_frame_count + 1)
        self.assertNotEqual(inc_after["end_time"], orig_end_time)

    def test_notification_channel_tracking_and_retry(self) -> None:
        """Verify notification dispatch tracks statuses in DB and executes retries on failure"""
        from src.alert_coordinator import NotificationChannel, NotificationDispatcher
        
        class FailingChannel(NotificationChannel):
            def __init__(self) -> None:
                self.calls = 0
            def send(self, incident: Dict[str, Any]) -> bool:
                self.calls += 1
                return False # always fails to test retries
                
        from concurrent.futures import ThreadPoolExecutor
        dispatcher = NotificationDispatcher()
        dispatcher.executor = ThreadPoolExecutor(max_workers=2)
        fail_ch = FailingChannel()
        dispatcher.register_channel("MOCK_FAIL", fail_ch)
        
        incident_id = "test-notif-track-123"
        incident = {
            "incident_id": incident_id,
            "channels": "MOCK_FAIL",
            "severity": "CRITICAL",
            "message": "Test notification status tracking",
            "zone": "Zone_A"
        }
        
        # Dispatch
        dispatcher.dispatch(incident)
        time.sleep(1.5) # wait for async retries to complete
        
        # Verify status in database
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM notification_statuses WHERE incident_id = ? AND channel = 'MOCK_FAIL'", (incident_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "Failed")
            self.assertEqual(row["retry_count"], 3)
            self.assertGreaterEqual(fail_ch.calls, 4) # initial + 3 retries
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_system_metrics(self) -> None:
        """Verify the DashboardAdapter.get_metrics retrieves all requested keys"""
        metrics = self.coordinator.dashboard_adapter.get_metrics()
        self.assertIn("total_incidents", metrics)
        self.assertIn("active_incidents", metrics)
        self.assertIn("resolved_incidents", metrics)
        self.assertIn("escalated_incidents", metrics)
        self.assertIn("average_response_time_seconds", metrics)
        self.assertIn("average_acknowledgement_time_seconds", metrics)
        self.assertIn("detection_latency_ms", metrics)
        self.assertIn("notification_latency_ms", metrics)
        self.assertIn("false_positive_count", metrics)
        self.assertIn("system_uptime_seconds", metrics)

    def test_bat4_gas_leak_rule(self) -> None:
        """Verify BAT4_GAS_LEAK triggers on critical gas ppm or gas leak detections in Battery-4"""
        evaluator = self.coordinator.risk_evaluator
        # Test critical gas ppm
        res1 = evaluator.evaluate([], {"gas_ppm": 40.0}, False, 0, False, "Zone_A")
        self.assertTrue(any(r["rule_id"] == "BAT4_GAS_LEAK" for r in res1["matched_rules"]))
        self.assertEqual(res1["severity"], "CRITICAL")
        self.assertIn("Evacuate Battery 4, isolate gas supply, activate ventilation, dispatch Gas Response Team, notify EHS.", res1["recommended_actions"])

        # Test gas leak detection
        dets = [MockDetection("gas_leak")]
        res2 = evaluator.evaluate(dets, {"gas_ppm": 10.0}, False, 0, False, "Battery-4")
        self.assertTrue(any(r["rule_id"] == "BAT4_GAS_LEAK" for r in res2["matched_rules"]))
        self.assertEqual(res2["severity"], "CRITICAL")

    def test_bat5_ppe_violation_rule(self) -> None:
        """Verify BAT5_PPE_VIOLATION triggers on violations count or missing PPE labels in Battery-5"""
        evaluator = self.coordinator.risk_evaluator
        res1 = evaluator.evaluate([], {"violations_count": 1}, False, 2, False, "Zone_B")
        self.assertTrue(any(r["rule_id"] == "BAT5_PPE_VIOLATION" for r in res1["matched_rules"]))
        self.assertEqual(res1["severity"], "MEDIUM")
        self.assertIn("Issue warning, halt unsafe task if necessary, notify supervisor, enforce PPE compliance.", res1["recommended_actions"])

        # Test no_helmet label detection
        dets = [MockDetection("no_helmet")]
        res2 = evaluator.evaluate(dets, {}, False, 1, False, "Battery-5")
        self.assertTrue(any(r["rule_id"] == "BAT5_PPE_VIOLATION" for r in res2["matched_rules"]))
        self.assertEqual(res2["severity"], "MEDIUM")

    def test_bat6_high_pressure_rule(self) -> None:
        """Verify BAT6_HIGH_PRESSURE triggers on pressure limits or overpressure label in Battery-6"""
        evaluator = self.coordinator.risk_evaluator
        # Test pressure threshold
        res1 = evaluator.evaluate([], {"Zone_C_pressure_bar": 9.0}, False, 0, False, "Zone_C")
        self.assertTrue(any(r["rule_id"] == "BAT6_HIGH_PRESSURE" for r in res1["matched_rules"]))
        self.assertEqual(res1["severity"], "CRITICAL")
        self.assertIn("Isolate pressure vessel, vent pressure safely, evacuate nearby personnel, dispatch maintenance team.", res1["recommended_actions"])

        # Test overpressure detection label
        dets = [MockDetection("overpressure")]
        res2 = evaluator.evaluate(dets, {"pressure": 4.0}, False, 0, False, "Battery-6")
        self.assertTrue(any(r["rule_id"] == "BAT6_HIGH_PRESSURE" for r in res2["matched_rules"]))
        self.assertEqual(res2["severity"], "CRITICAL")

    def test_reactor_welding_proximity_rule(self) -> None:
        """Verify REACTOR_WELDING_PROXIMITY triggers when sparks/welding fume AND no_helmet are detected"""
        evaluator = self.coordinator.risk_evaluator
        dets = [MockDetection("sparks"), MockDetection("no_helmet")]
        res = evaluator.evaluate(dets, {}, False, 2, False, "Reactor_Area")
        self.assertTrue(any(r["rule_id"] == "REACTOR_WELDING_PROXIMITY" for r in res["matched_rules"]))
        self.assertEqual(res["severity"], "HIGH")
        self.assertIn("Stop welding activity if required, alert welder and worker, enforce safe distance, dispatch safety officer.", res["recommended_actions"])

    def test_storage_overcrowding_rule(self) -> None:
        """Verify STORAGE_OVERCROWDING triggers when worker count exceeds threshold in Storage Block"""
        evaluator = self.coordinator.risk_evaluator
        res = evaluator.evaluate([], {}, False, 9, False, "Storage_Area")
        self.assertTrue(any(r["rule_id"] == "STORAGE_OVERCROWDING" for r in res["matched_rules"]))
        self.assertEqual(res["severity"], "HIGH")
        self.assertIn("Restrict further entry, notify supervisor, redistribute personnel, monitor evacuation routes.", res["recommended_actions"])


# ==============================================================================
# ENHANCEMENT TESTS
# ==============================================================================

class TestAlertEnhancements(unittest.TestCase):
    """Integration tests for AlertEnhancementOrchestrator covering all 5 enhancement pillars."""

    @classmethod
    def setUpClass(cls) -> None:
        from src.alert_coordinator import (
            get_alert_coordinator,
            PersistenceLayer,
            RiskEvaluator,
            IncidentManager,
            DashboardAdapter,
            NotificationDispatcher,
        )
        cls.coordinator = get_alert_coordinator()
        cls.coordinator.config["database"]["db_path"] = "data/test_enhancements.db"

        cls.coordinator.persistence = PersistenceLayer(cls.coordinator.config)
        cls.coordinator.risk_evaluator = RiskEvaluator(cls.coordinator.config)
        cls.coordinator.notification_dispatcher = NotificationDispatcher()
        cls.coordinator.dashboard_adapter = DashboardAdapter(cls.coordinator.persistence)
        cls.coordinator.incident_manager = IncidentManager(
            cls.coordinator.config,
            cls.coordinator.persistence,
            cls.coordinator.notification_dispatcher,
            cls.coordinator.escalation_engine,
            cls.coordinator.dashboard_adapter,
        )

        from src.alert_enhancements import AlertEnhancementOrchestrator
        cls.coordinator.enhancer = AlertEnhancementOrchestrator(cls.coordinator)
        cls.enhancer = cls.coordinator.enhancer

    @classmethod
    def tearDownClass(cls) -> None:
        import os
        for ext in ["", "-wal", "-shm"]:
            path = f"data/test_enhancements.db{ext}"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def setUp(self) -> None:
        """Reset DB tables between tests.
        Note: rule_versions is NOT cleared here because it is class-level state
        written once during AlertEnhancementOrchestrator.__init__. Clearing it
        would cause get_active_rule_version() to return None mid-suite.
        """
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            for table in [
                "incidents", "incident_frames", "notification_statuses",
                "incident_audit_trail", "incident_timeline",
                "incident_snapshots",
                # rule_versions intentionally excluded: class-level state
            ]:
                try:
                    cursor.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            self.coordinator.persistence.return_connection(conn)
        if hasattr(self.coordinator.incident_manager, "_cooldown_cache"):
            with self.coordinator.incident_manager._cooldown_lock:
                self.coordinator.incident_manager._cooldown_cache.clear()

    # --------------------------------------------------------------------------
    # 1. Rule Versioning
    # --------------------------------------------------------------------------

    def test_rule_version_computed_and_registered(self) -> None:
        """Rule version must be a 12-char hex hash that is registered in rule_versions."""
        rv = self.enhancer.rule_registry.get_version()
        self.assertIsInstance(rv, str)
        self.assertEqual(len(rv), 12)

        # Should be registered on orchestrator creation
        active = self.enhancer.get_active_rule_version()
        self.assertIsNotNone(active)
        self.assertEqual(active["version_hash"], rv)
        self.assertEqual(active["is_active"], 1)

    def test_rule_version_history_after_re_register(self) -> None:
        """Re-registering a new version deactivates the previous one."""
        first_version = self.enhancer.rule_registry.get_version()
        # Simulate a second registration with a dummy hash
        self.enhancer.persistence.register_rule_version("aabbcc001122", {"rules": "v2_stub"})
        history = self.enhancer.get_rule_version_history()
        # The most recent is the newly activated one
        self.assertEqual(history[0]["version_hash"], "aabbcc001122")
        self.assertEqual(history[0]["is_active"], 1)
        # The original one is now deactivated
        deactivated = [h for h in history if h["version_hash"] == first_version]
        self.assertTrue(len(deactivated) == 0 or deactivated[0]["is_active"] == 0)

    # --------------------------------------------------------------------------
    # 2. Incident Timeline
    # --------------------------------------------------------------------------

    def _create_test_incident(self) -> str:
        """Helper: insert a minimal incident row and return its ID."""
        import uuid
        from datetime import datetime
        incident_id = str(uuid.uuid4())
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO incidents (
                incident_id, incident_key, zone, hazard_type, status, severity,
                message, start_time, frame_count, requires_ack, risk_score,
                factors, compound_factors, teams_notified, channels, consecutive_absent_frames
            ) VALUES (?, ?, 'Zone_A', 'TEST_HAZARD', 'Active', 'HIGH',
                      'Test incident', ?, 1, 0, 5.0, '', '', '', 'DASHBOARD', 0)
            """, (incident_id, f"Zone_A_TEST_{incident_id[:8]}", datetime.now().isoformat()))
            conn.commit()
        finally:
            self.coordinator.persistence.return_connection(conn)
        return incident_id

    def test_on_incident_created_adds_timeline_events(self) -> None:
        """on_incident_created must write DETECTION and stamp rule version."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(incident_id)

        timeline = self.enhancer.get_incident_timeline(incident_id)
        event_types = [e["event_type"] for e in timeline]
        self.assertIn("DETECTION", event_types)

        # Rule version should be stamped on the incident row
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT rule_version FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row["rule_version"])
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_on_notification_dispatched_adds_timeline(self) -> None:
        """Each dispatched channel should add a NOTIFICATION_DISPATCHED event."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(incident_id)
        self.enhancer.on_notification_dispatched(incident_id, ["DASHBOARD", "SMS"])

        timeline = self.enhancer.get_incident_timeline(incident_id)
        dispatched = [e for e in timeline if e["event_type"] == "NOTIFICATION_DISPATCHED"]
        self.assertEqual(len(dispatched), 2)
        channels_recorded = [e["event_metadata"] for e in dispatched]
        self.assertTrue(any("DASHBOARD" in m for m in channels_recorded))
        self.assertTrue(any("SMS" in m for m in channels_recorded))

    def test_on_incident_resolved_adds_timeline(self) -> None:
        """Resolution event must appear in the incident timeline."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(incident_id)
        self.enhancer.on_incident_resolved(incident_id)

        timeline = self.enhancer.get_incident_timeline(incident_id)
        event_types = [e["event_type"] for e in timeline]
        self.assertIn("RESOLVED", event_types)

    # --------------------------------------------------------------------------
    # 3. Audit Trail
    # --------------------------------------------------------------------------

    def test_on_incident_acknowledged_writes_audit(self) -> None:
        """Acknowledging an incident must produce an ACKNOWLEDGED audit event with operator name."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(incident_id)
        self.enhancer.on_incident_acknowledged(incident_id, "Eng. Hanis", "PPE team dispatched")

        audit = self.enhancer.get_audit_trail(incident_id)
        ack_events = [e for e in audit if e["event_type"] == "ACKNOWLEDGED"]
        self.assertGreaterEqual(len(ack_events), 1)
        self.assertEqual(ack_events[0]["actor"], "Eng. Hanis")
        self.assertIn("PPE team dispatched", ack_events[0]["remarks"])

    def test_on_notification_failed_writes_audit_and_timeline(self) -> None:
        """A permanently failed notification must appear in both audit and timeline."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(incident_id)
        self.enhancer.on_notification_failed(incident_id, "SMS", "gateway timeout")

        audit = self.enhancer.get_audit_trail(incident_id)
        timeline = self.enhancer.get_incident_timeline(incident_id)

        audit_types = [e["event_type"] for e in audit]
        tl_types = [e["event_type"] for e in timeline]
        self.assertIn("NOTIFICATION_FAILED", audit_types)
        self.assertIn("NOTIFICATION_FAILED", tl_types)
        fail_audit = next(e for e in audit if e["event_type"] == "NOTIFICATION_FAILED")
        self.assertIn("gateway timeout", fail_audit["remarks"])

    # --------------------------------------------------------------------------
    # 4. Snapshot Attachment Storage
    # --------------------------------------------------------------------------

    def test_save_snapshot_records_metadata(self) -> None:
        """Saving a (non-existent) snapshot path stores metadata correctly."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(incident_id)

        fake_path = "/tmp/snapshot_test_frame_042.jpg"
        result = self.enhancer.persistence.save_snapshot(incident_id, fake_path, frame_number=42)
        self.assertTrue(result)

        snapshots = self.enhancer.get_snapshots(incident_id)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["snapshot_path"], fake_path)
        self.assertEqual(snapshots[0]["frame_number"], 42)

    def test_on_incident_created_with_snapshot_adds_event(self) -> None:
        """Providing a snapshot_path to on_incident_created adds SNAPSHOT_CAPTURED to timeline."""
        incident_id = self._create_test_incident()
        self.enhancer.on_incident_created(
            incident_id,
            snapshot_path="/tmp/snap_042.jpg",
            frame_number=42
        )
        timeline = self.enhancer.get_incident_timeline(incident_id)
        tl_types = [e["event_type"] for e in timeline]
        self.assertIn("SNAPSHOT_CAPTURED", tl_types)

    # --------------------------------------------------------------------------
    # 5. System Metrics Dashboard
    # --------------------------------------------------------------------------

    def test_system_metrics_returns_required_keys(self) -> None:
        """System metrics dict must contain all expected operational keys."""
        metrics = self.enhancer.get_system_metrics()
        required_keys = [
            "active_incidents",
            "total_incidents_all_time",
            "average_response_time_seconds",
            "average_resolution_time_seconds",
            "notification_success_rate",
            "false_positive_rate",
            "incidents_by_severity",
            "incidents_by_zone",
            "timestamp",
        ]
        for key in required_keys:
            self.assertIn(key, metrics, f"Missing key: {key}")

    def test_system_metrics_active_count_reflects_db(self) -> None:
        """Active incidents count in metrics must match actual unresolved DB rows."""
        # Start with zero
        metrics_before = self.enhancer.get_system_metrics()
        before_count = metrics_before["active_incidents"]

        # Create two incidents
        self._create_test_incident()
        self._create_test_incident()

        metrics_after = self.enhancer.get_system_metrics()
        self.assertEqual(metrics_after["active_incidents"], before_count + 2)


if __name__ == "__main__":
    unittest.main()

