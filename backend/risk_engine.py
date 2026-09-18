"""
Risk engine - a transparent, rule-based first version.

This is NOT a trained machine-learning model. The risk category always comes
from the explicit rules listed in RISK_RULES, so every result can be traced
back to the rules that produced it.

How a result is produced:
  1. Individual rules (I1-I10) look at each input on its own.
  2. Combination rules (C1-C7) look for conditions that are dangerous together.
  3. Rule M1 raises the category when inputs are not reported.
  4. The risk category is the most severe result among all rules that matched.

All thresholds are PROVISIONAL values for an academic demonstration. They are
not validated or certified industrial safety thresholds.
"""

from scenario import FIELD_LABELS, missing_fields

# Risk categories, from least to most severe.
CATEGORIES = ["LOW", "MODERATE", "HIGH", "CRITICAL"]

# Provisional demonstration thresholds (not certified set points).
GAS_ELEVATED_LEL = 5          # % LEL
GAS_HIGH_LEL = 10             # % LEL
GAS_CRITICAL_LEL = 20         # % LEL
VENTILATION_REDUCED_PCT = 80  # below this, ventilation counts as reduced
VENTILATION_POOR_PCT = 50     # below this, ventilation counts as poor
MANY_CONDITIONS = 4           # this many individual conditions at once -> HIGH

# Every rule in plain words. This list is shown on the rules panel and in the
# README. The code below applies exactly these rules.
RISK_RULES = [
    {"id": "I1", "condition": f"Gas concentration at or above {GAS_CRITICAL_LEL}% LEL", "result": "CRITICAL"},
    {"id": "I2", "condition": f"Gas concentration from {GAS_HIGH_LEL}% to below {GAS_CRITICAL_LEL}% LEL", "result": "HIGH"},
    {"id": "I3", "condition": f"Gas concentration from {GAS_ELEVATED_LEL}% to below {GAS_HIGH_LEL}% LEL", "result": "MODERATE"},
    {"id": "I4", "condition": "Gas trend is rising", "result": "LOW"},
    {"id": "I5", "condition": f"Ventilation below {VENTILATION_POOR_PCT}%", "result": "MODERATE"},
    {"id": "I6", "condition": f"Ventilation from {VENTILATION_POOR_PCT}% to below {VENTILATION_REDUCED_PCT}%", "result": "LOW"},
    {"id": "I7", "condition": "Extraction fan has failed", "result": "MODERATE"},
    {"id": "I8", "condition": "Hot-work permit is open (possible ignition source)", "result": "LOW"},
    {"id": "I9", "condition": "Maintenance fault is present", "result": "LOW"},
    {"id": "I10", "condition": "Shift changeover is in progress", "result": "LOW"},
    {"id": "C1", "condition": f"Hot work open AND gas at or above {GAS_HIGH_LEL}% LEL", "result": "CRITICAL"},
    {"id": "C2", "condition": f"Hot work open AND gas rising or at or above {GAS_ELEVATED_LEL}% LEL (when C1 does not apply)", "result": "HIGH"},
    {"id": "C3", "condition": "Gas rising AND extraction fan failed", "result": "HIGH"},
    {"id": "C4", "condition": f"Gas rising AND ventilation below {VENTILATION_REDUCED_PCT}% (fan not failed)", "result": "MODERATE"},
    {"id": "C5", "condition": "Maintenance fault present AND hot work open", "result": "MODERATE"},
    {"id": "C6", "condition": "Shift changeover AND (hot work open OR maintenance fault present)", "result": "MODERATE"},
    {"id": "C7", "condition": f"{MANY_CONDITIONS} or more individual conditions (I-rules) at the same time", "result": "HIGH"},
    {"id": "M1", "condition": "Any input not reported: raise the category to at least HIGH", "result": "HIGH"},
]


def assess_risk(scenario):
    """Assess a cleaned scenario (see scenario.clean_scenario) and return the result."""
    findings = check_individual_conditions(scenario)
    individual_count = len(findings)
    findings += check_combinations(scenario, individual_count)

    # M1: missing information is never assumed to be safe.
    missing = missing_fields(scenario)
    if missing:
        names = ", ".join(FIELD_LABELS[field] for field in missing)
        findings.append(make_finding(
            "M1", "missing data",
            f"Not reported: {names}. Missing information is never assumed to be safe.",
            "HIGH",
        ))

    category = most_severe(findings)

    # The rules that set the category. LOW is the starting point, so no rule "sets" it.
    deciding_rules = []
    if category != "LOW":
        deciding_rules = [f["rule_id"] for f in findings if f["severity"] == category]

    # For comparison only: the category the gas reading would give on its own,
    # like a simple single-sensor alarm (None if gas is not reported).
    gas_only_category = None
    if scenario["gas_lel"] is not None:
        gas_only_category = "LOW"
        for finding in findings:
            if finding["rule_id"] in ("I1", "I2", "I3"):
                gas_only_category = finding["severity"]

    return {
        "category": category,
        "explanation": plain_explanation(scenario, findings, category),
        "summary": summarise(category, deciding_rules, findings),
        "deciding_rules": deciding_rules,
        "findings": findings,
        "missing_fields": missing,
        "data_complete": not missing,
        "gas_only_category": gas_only_category,
        "method": "Rule-based (provisional demonstration rules, not a trained model)",
    }


def check_individual_conditions(s):
    """Rules I1-I10: look at each input on its own."""
    findings = []

    gas = s["gas_lel"]
    if gas is not None:
        if gas >= GAS_CRITICAL_LEL:
            findings.append(make_finding("I1", "individual", f"Gas concentration is {gas:g}% LEL, at or above the critical level of {GAS_CRITICAL_LEL}% LEL.", "CRITICAL"))
        elif gas >= GAS_HIGH_LEL:
            findings.append(make_finding("I2", "individual", f"Gas concentration is {gas:g}% LEL, at or above the high level of {GAS_HIGH_LEL}% LEL.", "HIGH"))
        elif gas >= GAS_ELEVATED_LEL:
            findings.append(make_finding("I3", "individual", f"Gas concentration is {gas:g}% LEL, at or above the elevated level of {GAS_ELEVATED_LEL}% LEL.", "MODERATE"))

    if s["gas_trend"] == "rising":
        findings.append(make_finding("I4", "individual", "Gas concentration is rising.", "LOW"))

    ventilation = s["ventilation_pct"]
    if ventilation is not None:
        if ventilation < VENTILATION_POOR_PCT:
            findings.append(make_finding("I5", "individual", f"Ventilation is poor ({ventilation:g}%, below {VENTILATION_POOR_PCT}%).", "MODERATE"))
        elif ventilation < VENTILATION_REDUCED_PCT:
            findings.append(make_finding("I6", "individual", f"Ventilation is reduced ({ventilation:g}%, below {VENTILATION_REDUCED_PCT}%).", "LOW"))

    if s["fan_status"] == "failed":
        findings.append(make_finding("I7", "individual", "The extraction fan has failed.", "MODERATE"))
    if s["hot_work_permit"] == "open":
        findings.append(make_finding("I8", "individual", "A hot-work permit is open, so an ignition source may be present.", "LOW"))
    if s["maintenance_fault"] == "present":
        findings.append(make_finding("I9", "individual", "A maintenance fault is reported.", "LOW"))
    if s["shift_condition"] == "changeover":
        findings.append(make_finding("I10", "individual", "A shift changeover is in progress.", "LOW"))

    return findings


def check_combinations(s, individual_count):
    """Rules C1-C7: look for conditions that are dangerous together.

    A rule only matches when all of its conditions are reported and true.
    Inputs that are not reported are handled by rule M1 instead.
    """
    findings = []

    gas = s["gas_lel"]
    ventilation = s["ventilation_pct"]
    hot_work_open = s["hot_work_permit"] == "open"
    gas_rising = s["gas_trend"] == "rising"
    fan_failed = s["fan_status"] == "failed"
    fault_present = s["maintenance_fault"] == "present"
    changeover = s["shift_condition"] == "changeover"
    gas_high = gas is not None and gas >= GAS_HIGH_LEL
    gas_elevated = gas is not None and gas >= GAS_ELEVATED_LEL
    ventilation_reduced = ventilation is not None and ventilation < VENTILATION_REDUCED_PCT

    if hot_work_open and gas_high:
        findings.append(make_finding("C1", "combination", "Hot work is open in a high gas concentration: an ignition source where the gas level is high.", "CRITICAL"))
    elif hot_work_open and (gas_rising or gas_elevated):
        findings.append(make_finding("C2", "combination", "Hot work is open while the gas level is rising or elevated: an ignition source while gas is building up.", "HIGH"))

    if gas_rising and fan_failed:
        findings.append(make_finding("C3", "combination", "Gas is rising and the extraction fan has failed, so gas may accumulate.", "HIGH"))
    elif gas_rising and ventilation_reduced:
        findings.append(make_finding("C4", "combination", "Gas is rising while ventilation is reduced.", "MODERATE"))

    if fault_present and hot_work_open:
        findings.append(make_finding("C5", "combination", "A maintenance fault is present while hot work is open.", "MODERATE"))

    if changeover and (hot_work_open or fault_present):
        findings.append(make_finding("C6", "combination", "Shift changeover during hot work or with an open fault: handover information may be incomplete.", "MODERATE"))

    if individual_count >= MANY_CONDITIONS:
        findings.append(make_finding("C7", "combination", f"{individual_count} individual conditions are present at the same time (limit: {MANY_CONDITIONS}).", "HIGH"))

    return findings


def make_finding(rule_id, rule_type, description, severity):
    return {"rule_id": rule_id, "type": rule_type, "description": description, "severity": severity}


def most_severe(findings):
    """Return the most severe category among the findings (LOW if there are none)."""
    category = "LOW"
    for finding in findings:
        if CATEGORIES.index(finding["severity"]) > CATEGORIES.index(category):
            category = finding["severity"]
    return category


def plain_explanation(scenario, findings, category):
    """Explain the result in everyday words for the page.

    Only conditions that actually matched a rule are mentioned, so the
    explanation never gives a reason that the inputs do not support.
    """
    if not findings:
        return "All readings are within their normal ranges. No safety concerns were found."

    matched = {finding["rule_id"]: finding for finding in findings}
    gas = scenario["gas_lel"]
    ventilation = scenario["ventilation_pct"]
    sentences = []

    if "I1" in matched:
        sentences.append(f"Gas levels are critically high ({gas:g}% LEL).")
    elif "I2" in matched:
        sentences.append(f"Gas levels are high ({gas:g}% LEL).")
    elif "I3" in matched:
        sentences.append(f"Gas levels are elevated ({gas:g}% LEL).")

    condition_words = {
        "I4": "the gas level is rising",
        "I5": f"ventilation is poor ({ventilation:g}%)" if ventilation is not None else "",
        "I6": f"ventilation is reduced ({ventilation:g}%)" if ventilation is not None else "",
        "I7": "the extraction fan has failed",
        "I8": "hot work is permitted",
        "I9": "a maintenance fault is reported",
        "I10": "a shift changeover is in progress",
    }
    conditions = [condition_words[rule_id] for rule_id in matched if rule_id in condition_words]
    if conditions:
        text = join_words(conditions)
        if sentences:
            sentences.append(f"In addition, {text}.")
        else:
            sentences.append(text[0].upper() + text[1:] + ".")

    # Explain only the combinations that set the risk level.
    combination_sentences = {
        "C1": "Hot work in a high gas concentration could ignite the gas.",
        "C2": "Hot work while the gas level is rising or elevated creates a risk of ignition.",
        "C3": "Because the fan has failed, the rising gas may build up.",
        "C4": "The rising gas may build up because ventilation is reduced.",
        "C5": "A maintenance fault during hot work adds to the danger.",
        "C6": "A shift changeover at the same time may lead to incomplete handover information.",
        "C7": "Several problems are happening at the same time, which increases the overall risk.",
    }
    for rule_id, finding in matched.items():
        if rule_id in combination_sentences and finding["severity"] == category:
            sentences.append(combination_sentences[rule_id])

    if "M1" in matched:
        names = join_words([FIELD_LABELS[field].lower() for field in missing_fields(scenario)])
        sentences.append(f"Some information is missing ({names}), so the system cannot confirm that the area is safe.")

    if category == "LOW":
        sentences.append("On their own, these conditions are not a serious concern.")

    return " ".join(sentences)


def join_words(items):
    """['a', 'b', 'c'] -> 'a, b and c'"""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def summarise(category, deciding_rules, findings):
    """One technical sentence explaining which rules set the category (used in the agent prompt)."""
    if not findings:
        return "No rule matched: every reported input is within its normal range."
    if category == "LOW":
        return "Only minor conditions were found. No rule raised the risk above LOW."
    word = "rules" if len(deciding_rules) > 1 else "rule"
    return f"The category is {category} because of {word} {', '.join(deciding_rules)} (the most severe {word} that matched)."
