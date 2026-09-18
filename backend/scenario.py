"""
Zone 4 scenario: the input fields, the preset scenarios and input cleaning.

Every value in this file is a SIMULATED demonstration input. The numbers are
illustrative only. They are not validated industrial safety thresholds, and
nothing here is connected to real sensors or equipment.
"""

# The seven Zone 4 inputs, in the order they are shown on screen.
ALL_FIELDS = [
    "gas_lel",
    "gas_trend",
    "ventilation_pct",
    "fan_status",
    "hot_work_permit",
    "maintenance_fault",
    "shift_condition",
]

FIELD_LABELS = {
    "gas_lel": "Gas concentration",
    "gas_trend": "Gas trend",
    "ventilation_pct": "Ventilation",
    "fan_status": "Fan status",
    "hot_work_permit": "Hot-work permit",
    "maintenance_fault": "Maintenance fault",
    "shift_condition": "Shift condition",
}

# Number inputs and their allowed range (minimum, maximum).
#   gas_lel         - gas concentration as a percentage of the Lower Explosive Limit
#   ventilation_pct - ventilation airflow as a percentage of the design airflow
NUMBER_RANGES = {
    "gas_lel": (0, 100),
    "ventilation_pct": (0, 100),
}

# Choice inputs and their allowed options.
CHOICE_OPTIONS = {
    "gas_trend": ["rising", "stable"],
    "fan_status": ["operational", "failed"],
    "hot_work_permit": ["open", "closed"],
    "maintenance_fault": ["present", "absent"],
    "shift_condition": ["normal", "changeover"],
}

# The preset offered on the page. None would mean "not reported" (missing information).
# Other conditions are entered by editing the inputs on the page.
PRESETS = {
    "normal": {
        "label": "Normal operation",
        "values": {
            "gas_lel": 1.0,
            "gas_trend": "stable",
            "ventilation_pct": 92,
            "fan_status": "operational",
            "hot_work_permit": "closed",
            "maintenance_fault": "absent",
            "shift_condition": "normal",
        },
    },
}

DEFAULT_PRESET = "normal"


def clean_scenario(raw_inputs):
    """Turn raw inputs (for example JSON sent by the browser) into a clean scenario.

    Returns (scenario, notes):
      scenario - a dictionary with one entry per field. None means "not reported".
      notes    - messages about any values that could not be used.

    Blank or invalid values become None. They are never replaced with a "safe"
    default, because missing information must be handled conservatively.
    """
    if not isinstance(raw_inputs, dict):
        raw_inputs = {}

    scenario = {}
    notes = []
    for field in ALL_FIELDS:
        value = raw_inputs.get(field)
        if value is None or value == "":
            scenario[field] = None
        elif field in NUMBER_RANGES:
            scenario[field] = clean_number(field, value, notes)
        else:
            scenario[field] = clean_choice(field, value, notes)
    return scenario, notes


def clean_number(field, value, notes):
    """Return value as a number inside the field's range, or None (with a note)."""
    minimum, maximum = NUMBER_RANGES[field]
    number = None
    if not isinstance(value, bool):  # True/False are not valid readings
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = None

    # The range check also rejects NaN and infinity.
    if number is None or not (minimum <= number <= maximum):
        notes.append(
            f"{FIELD_LABELS[field]}: '{short_text(value)}' is not a number from {minimum} "
            f"to {maximum}, so it is treated as not reported."
        )
        return None
    return number


def clean_choice(field, value, notes):
    """Return value if it is one of the field's options, otherwise None (with a note)."""
    text = str(value).strip().lower()
    if text in CHOICE_OPTIONS[field]:
        return text
    options = " / ".join(CHOICE_OPTIONS[field])
    notes.append(
        f"{FIELD_LABELS[field]}: '{short_text(value)}' is not one of {options}, "
        "so it is treated as not reported."
    )
    return None


def short_text(value):
    """Shorten a value for use in a message."""
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def missing_fields(scenario):
    """Return the names of the inputs that are not reported."""
    return [field for field in ALL_FIELDS if scenario.get(field) is None]

