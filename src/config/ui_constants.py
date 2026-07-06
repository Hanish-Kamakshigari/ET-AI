# -*- coding: utf-8 -*-
"""
SurakshaAI Central constants and configuration keys for the UI
"""

SENSOR_ZONES = ['Zone_A', 'Zone_B', 'Zone_C', 'Reactor_Area', 'Storage_Area']
STATIC_ZONES = ['Control_Room']
ALL_ZONES = STATIC_ZONES + SENSOR_ZONES

ZONE_LABELS = {
    'Zone_A': 'Battery-4',
    'Zone_B': 'Battery-5',
    'Zone_C': 'Battery-6',
    'Reactor_Area': 'Reactor Block',
    'Control_Room': 'Control Room',
    'Storage_Area': 'Storage Area',
}

ZONE_STATUS_ORDER = [
    ('Zone_A', 'Battery-4'),
    ('Zone_B', 'Battery-5'),
    ('Zone_C', 'Battery-6'),
    ('Reactor_Area', 'Reactor Block'),
    ('Storage_Area', 'Storage Area'),
    ('Control_Room', 'Control Room'),
]

RULE_META = {
    'TRIPLE_THREAT': ('Triple-Threat Evacuation', 'Maint + Gas>35ppm + Temp>95°C + Crew>5'),
    'MAINTENANCE_GAS_LEAK': ('Maintenance Gas Intersection', 'Maint + Gas>35ppm'),
    'PERMIT_GAS_COMBINATION': ('Hot Work Permit Gas', 'Permit + Gas>40ppm'),
    'OVERHEATING_WITH_GAS': ('Overheating Gas Risk', 'Temp>98°C + Gas>25ppm'),
    'WORKER_OVER_CROWDING': ('Crew Overcrowding', 'Crew>9 + Gas>25ppm'),
    'SHIFT_CHANGE_RISK': ('Shift Change Telemetry', 'Shift change + Gas>30ppm'),
}
