"""
Example scenarios used by the tests. Only "normal" is offered on the page (as
the Normal operation preset); the others are entered there by editing the inputs.
None means "not reported".
"""

SAMPLE_SCENARIOS = {
    "normal": {
        "gas_lel": 1.0, "gas_trend": "stable", "ventilation_pct": 92, "fan_status": "operational",
        "hot_work_permit": "closed", "maintenance_fault": "absent", "shift_condition": "normal",
    },
    # 4% LEL alone is low, but several conditions together make the risk HIGH.
    "compound": {
        "gas_lel": 4.0, "gas_trend": "rising", "ventilation_pct": 62, "fan_status": "failed",
        "hot_work_permit": "open", "maintenance_fault": "present", "shift_condition": "changeover",
    },
    "critical_gas": {
        "gas_lel": 24.0, "gas_trend": "rising", "ventilation_pct": 70, "fan_status": "operational",
        "hot_work_permit": "open", "maintenance_fault": "absent", "shift_condition": "normal",
    },
    "missing_info": {
        "gas_lel": None, "gas_trend": None, "ventilation_pct": 75, "fan_status": None,
        "hot_work_permit": "open", "maintenance_fault": "absent", "shift_condition": "normal",
    },
}
