# -*- coding: utf-8 -*-
"""
SurakshaAI — Smart Permit Intelligence (SIMOPS)
Intelligent permit analysis with automatic conflict detection for simultaneous operations.

Features:
- Comprehensive permit tracking with all required fields
- SIMOPS (Simultaneous Operations) conflict detection
- Automatic compound risk generation for conflicts
- Integration with existing alert system
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import streamlit as st


class PermitStatus(Enum):
    """Permit lifecycle states."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class HazardCategory(Enum):
    """Hazard categories for permit classification."""
    HOT_WORK = "Hot Work"
    CONFINED_SPACE = "Confined Space"
    ELECTRICAL = "Electrical"
    HEIGHT_WORK = "Height Work"
    MAINTENANCE = "Maintenance"
    CHEMICAL = "Chemical"


@dataclass
class WorkPermit:
    """Complete work permit with all operational fields."""
    permit_id: str
    permit_type: str  # HOT_WORK, CONFINED_SPACE, etc.
    work_description: str
    zone: str
    validity_start: str
    validity_end: str
    responsible_team: str
    equipment: List[str] = field(default_factory=list)
    hazard_category: str = ""
    risk_level: str = "LOW"
    status: str = "PENDING"
    workers_assigned: int = 0
    created_at: str = ""


# SIMOPS Conflict Matrix - defines dangerous combinations
SIMOPS_CONFLICTS = [
    {
        'id': 'HOT_WORK_GAS_LEAK',
        'conditions': {
            'permit_types': ['HOT_WORK', 'WELDING'],
            'sensor_thresholds': {'gas_ppm': 20}
        },
        'severity': 'CRITICAL',
        'message': 'Hot work cannot proceed with gas levels above 20 ppm',
        'action': 'Halt hot work immediately, verify gas clearance before resuming'
    },
    {
        'id': 'HOT_WORK_HIGH_TEMP',
        'conditions': {
            'permit_types': ['HOT_WORK', 'WELDING'],
            'sensor_thresholds': {'temperature_c': 85}
        },
        'severity': 'HIGH',
        'message': 'Temperature exceeds safe limits for hot work operations',
        'action': 'Reduce temperature before continuing hot work'
    },
    {
        'id': 'CONFINED_SPACE_LOW_OXYGEN',
        'conditions': {
            'permit_types': ['CONFINED_SPACE'],
            'sensor_thresholds': {'gas_ppm': (18, 22)}  # oxygen range approx
        },
        'severity': 'CRITICAL',
        'message': 'Confined space entry unsafe - abnormal atmospheric conditions',
        'action': 'Ventilate area and verify safe atmosphere before entry'
    },
    {
        'id': 'MAINTENANCE_WORKER_Congestion',
        'conditions': {
            'permit_types': ['MAINTENANCE'],
            'worker_threshold': 8
        },
        'severity': 'MEDIUM',
        'message': 'Too many workers in maintenance area - congestion risk',
        'action': 'Limit workers in maintenance zone to maximum 8'
    },
    {
        'id': 'ELECTRICAL_ACTIVE_CREW',
        'conditions': {
            'permit_types': ['ELECTRICAL'],
            'worker_threshold': 0  # any workers present
        },
        'severity': 'HIGH',
        'message': 'Electrical work cannot proceed with workers in proximity',
        'action': 'Establish safety perimeter before electrical isolation work'
    },
]


# Permit database (in production, this would be a real database)
_PERMIT_REGISTRY: Dict[str, WorkPermit] = {}


def create_permit(
    permit_type: str,
    work_description: str,
    zone: str,
    responsible_team: str,
    workers: int = 1,
    duration_hours: int = 8,
    hazard_category: Optional[str] = None
) -> WorkPermit:
    """Create a new work permit with auto-generated ID."""
    global _PERMIT_REGISTRY

    permit_id = f"PER-{zone}-{datetime.now().strftime('%Y%m%d%H%M')}"
    now = datetime.now()
    validity_end = (now + timedelta(hours=duration_hours)).strftime('%Y-%m-%d %H:%M')

    permit = WorkPermit(
        permit_id=permit_id,
        permit_type=permit_type,
        work_description=work_description,
        zone=zone,
        validity_start=now.strftime('%Y-%m-%d %H:%M'),
        validity_end=validity_end,
        responsible_team=responsible_team,
        hazard_category=hazard_category or permit_type,
        workers_assigned=workers,
        created_at=now.strftime('%H:%M:%S')
    )

    _PERMIT_REGISTRY[permit_id] = permit
    return permit


def get_active_permits(zone: Optional[str] = None) -> List[WorkPermit]:
    """Get all active permits, optionally filtered by zone."""
    global _PERMIT_REGISTRY

    active = [p for p in _PERMIT_REGISTRY.values() if p.status == PermitStatus.ACTIVE.value]

    if zone:
        active = [p for p in active if p.zone == zone]

    return active


def detect_simops_conflicts(
    zone: str,
    telemetry: Dict[str, float],
    worker_count: int,
    active_permits: Optional[List[WorkPermit]] = None
) -> List[Dict[str, Any]]:
    """Detect SIMOPS conflicts for a zone based on active permits and conditions."""
    conflicts = []

    if active_permits is None:
        active_permits = get_active_permits(zone)

    for conflict in SIMOPS_CONFLICTS:
        permit_types_required = conflict['conditions'].get('permit_types', [])

        # Check if any active permit matches conflict types
        matching_permit = any(
            p.permit_type in permit_types_required or p.hazard_category in permit_types_required
            for p in active_permits
        )

        if not matching_permit:
            continue

        # Check sensor thresholds
        sensor_thresholds = conflict['conditions'].get('sensor_thresholds', {})
        threshold_violated = False

        for sensor, threshold in sensor_thresholds.items():
            sensor_value = telemetry.get(sensor, 0)

            if isinstance(threshold, (int, float)):
                if sensor_value >= threshold:
                    threshold_violated = True
                    break
            elif isinstance(threshold, tuple):
                if sensor_value < threshold[0] or sensor_value > threshold[1]:
                    threshold_violated = True
                    break

        # Check worker threshold
        worker_threshold = conflict['conditions'].get('worker_threshold')
        if worker_threshold is not None:
            if worker_threshold == 0 and worker_count > 0:
                threshold_violated = True
            elif worker_count > worker_threshold:
                threshold_violated = True

        if threshold_violated:
            conflicts.append({
                'conflict_id': conflict['id'],
                'zone': zone,
                'severity': conflict['severity'],
                'message': conflict['message'],
                'action': conflict['action'],
                'permit_types': permit_types_required,
                'detected_at': datetime.now().strftime('%H:%M:%S')
            })

    return conflicts


def generate_compound_risk_from_conflict(
    conflict: Dict[str, Any],
    zone: str,
    telemetry: Dict[str, float]
) -> Dict[str, Any]:
    """Convert a SIMOPS conflict into a compound risk alert."""
    severity_map = {'CRITICAL': 15, 'HIGH': 10, 'MEDIUM': 6}

    return {
        'alert_id': f"SIMOPS-{conflict['conflict_id']}-{zone}",
        'zone': zone,
        'risk_level': conflict['severity'],
        'risk_score': severity_map.get(conflict['severity'], 6),
        'factors': [conflict['conflict_id'], 'SIMOPS_DETECTED'],
        'compound_factors': [conflict['conflict_id']],
        'message': conflict['message'],
        'recommended_action': conflict['action'],
        'confidence': 0.92,
    }


def render_permit_intelligence_panel() -> None:
    """Render the permit intelligence panel in the dashboard."""
    from src.config.ui_constants import ZONE_LABELS

    # Theme constants
    BG = "linear-gradient(135deg,#0f1f38,#0a1628)"
    BORDER = "#1e3a5f"
    TEXT_DIM = "#64748b"
    ACCENT = "#3b82f6"
    GREEN = "#22c55e"
    ORANGE = "#f97316"
    RED = "#ef4444"
    RADIUS = "12px"

    selected_zone = st.session_state.get('cctv_zone_selector', 'Zone_A')
    zone_permits = get_active_permits(selected_zone)

    # Header
    st.markdown(f"""
    <div style="background:{BG}; border:1px solid {BORDER}; border-radius:{RADIUS};
                padding:10px 14px; font-family:Outfit,sans-serif; margin-bottom:6px;">
        <div style="color:#94a3b8; font-size:11px; font-weight:600; letter-spacing:1px;">
            📋 SMART PERMIT INTELLIGENCE — {ZONE_LABELS.get(selected_zone, selected_zone)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Active permits list
    if not zone_permits:
        st.markdown(f"""
        <div style="background:{BG}; border:1px solid {BORDER}; border-radius:{RADIUS};
                    padding:10px 14px; font-family:Outfit,sans-serif; margin-bottom:6px;">
            <div style="color:{GREEN}; font-size:11px;">No active permits in this zone</div>
        </div>
        """, unsafe_allow_html=True)
        return

    for permit in zone_permits:
        # Determine if permit has conflicts
        latest = st.session_state.get('_last_telemetry', {})
        workers = int(latest.get(selected_zone + '_worker_count', 0))
        conflicts = detect_simops_conflicts(
            selected_zone,
            {k: v for k, v in latest.items() if selected_zone in k or k in ('gas_ppm', 'temperature_c')},
            workers,
            [permit]
        )

        conflict_html = ""
        if conflicts:
            for c in conflicts:
                sev_color = RED if c['severity'] == 'CRITICAL' else ORANGE if c['severity'] == 'HIGH' else "#eab308"
                conflict_html += f"""<div style='color:{sev_color}; font-size:9px; margin-top:4px;'>
                    ⚠ SIMOPS: {c['message']}</div>"""

        st.markdown(f"""
        <div style="background:{BG}; border:1px solid {BORDER}; border-radius:{RADIUS};
                    padding:10px 14px; font-family:Outfit,sans-serif; margin-bottom:6px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                <span style="color:#e2e8f0; font-size:10px; font-weight:600;">{permit.permit_id}</span>
                <span style="color:{GREEN if permit.status == 'ACTIVE' else '#64748b'}; font-size:9px;">{permit.status}</span>
            </div>
            <div style="color:#94a3b8; font-size:9px; margin-bottom:2px;">{permit.permit_type}</div>
            <div style="color:{TEXT_DIM}; font-size:8px; margin-bottom:2px;">{permit.work_description}</div>
            <div style="color:{TEXT_DIM}; font-size:8px;">Team: {permit.responsible_team} | Workers: {permit.workers_assigned}</div>
            {conflict_html}
        </div>
        """, unsafe_allow_html=True)


def init_default_permits() -> None:
    """Initialize default permits for the demo scenario."""
    global _PERMIT_REGISTRY

    # Create default permits if not already present
    if not _PERMIT_REGISTRY:
        create_permit(
            permit_type='HOT_WORK',
            work_description='Pipeline welding maintenance',
            zone='Zone_A',
            responsible_team='Alpha Team',
            workers=4,
            duration_hours=4
        ).status = PermitStatus.ACTIVE.value

        create_permit(
            permit_type='WELDING',
            work_description='Reactor maintenance welding',
            zone='Reactor_Area',
            responsible_team='Gamma Team',
            workers=2,
            duration_hours=6
        ).status = PermitStatus.ACTIVE.value

        create_permit(
            permit_type='CONFINED_SPACE',
            work_description='Storage tank inspection',
            zone='Storage_Area',
            responsible_team='Delta Team',
            workers=3,
            duration_hours=2
        ).status = PermitStatus.ACTIVE.value