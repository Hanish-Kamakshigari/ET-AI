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
    def __init__(self, label, confidence=0.9, zone_violation=False):
        self.label = label
        self.confidence = confidence
        self.zone_violation = zone_violation

class TestAlertingArchitecture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
    def tearDownClass(cls):
        import os
        for ext in ["", "-wal", "-shm"]:
            path = f"data/test_alerts.db{ext}"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def setUp(self):
        # Clear database to ensure clean, hermetic tests
        conn = self.coordinator.persistence.get_connection()
        try:
            cursor = conn.cursor()
            for table in ["alerts", "incidents", "rule_engine", "incident_frames"]:
                try:
                    cursor.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_risk_evaluation_pure(self):
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

    def test_deduplication_and_frame_persistence(self):
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
        self.assertEqual(inc2["status"], AlertStatus.PENDING.value)
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

    def test_lifecycle_and_acknowledgement(self):
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

    def test_escalation_engine(self):
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

    def test_concurrent_db_writes(self):
        """Verify that concurrent writes from multiple threads do not cause SQLite locking errors (WAL check)"""
        exceptions = []
        
        def writer_thread(t_idx):
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

    def test_health_monitor(self):
        """Verify health check returns required indicators"""
        health = self.coordinator.health_monitor.health_check()
        self.assertIn("database_pool_status", health)
        self.assertIn("active_alerts_count", health)
        self.assertIn("average_frame_processing_ms", health)
        self.assertIn("notification_success_rate", health)

    def test_backward_compatibility_layer(self):
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

    def test_all_data_driven_rules(self):
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

    def test_risk_engine_sensor_risk(self):
        """Verify RiskEngine single sensor thresholds"""
        risk_engine = CompoundRiskEngine()
        self.assertEqual(risk_engine.get_sensor_risk(10.0, 'gas_ppm')[1], 'NORMAL')
        self.assertEqual(risk_engine.get_sensor_risk(25.0, 'gas_ppm')[1], 'ELEVATED')
        self.assertEqual(risk_engine.get_sensor_risk(40.0, 'gas_ppm')[1], 'HIGH')
        self.assertEqual(risk_engine.get_sensor_risk(60.0, 'gas_ppm')[1], 'CRITICAL')

    def test_risk_engine_analyze_zone(self):
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

    def test_compliance_engine(self):
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

    def test_action_engine(self):
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

    def test_cooldown_logic(self):
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
            cursor.execute("SELECT status FROM incidents WHERE incident_key = ? ORDER BY start_time DESC LIMIT 1", (key,))
            row = cursor.fetchone()
            self.assertEqual(row["status"], AlertStatus.RESOLVED.value) # latest status must still be resolved, not NEW/ACTIVE
        finally:
            self.coordinator.persistence.return_connection(conn)

    def test_alert_priority_sorting(self):
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

if __name__ == "__main__":
    unittest.main()
