"""
Deterministic decision gate.

Every action proposed by the agent must pass through this gate before it can
be shown as an accepted decision. The gate:
  * uses only the explicit rules written in this file (G1-G7),
  * never reads the agent's confidence score,
  * never calls the agent (and the agent module never imports this module),
  * gives the same decision for the same inputs, every time.

When a proposal is rejected, the gate does not try to repair it. It applies
its own documented default response for the situation instead.

These are PROVISIONAL rules for an academic demonstration. They are not
certified industrial safety rules. The gate never sends commands to real
equipment: its output is advisory text for a person to act on.
"""

import json

from scenario import FIELD_LABELS, missing_fields

RULESET_NAME = "Provisional academic demonstration rules v0.1"

# Advisory actions the gate is able to accept.
# "level" is the strength of the response:
#   0 = routine, 1 = inform, 2 = escalate to a person, 3 = urgent evacuation review
ADVISORY_ACTIONS = {
    "LOG_OBSERVATION": {"level": 0, "text": "Record the assessment and continue routine monitoring."},
    "NOTIFY_OPERATOR": {"level": 1, "text": "Inform the control-room operator."},
    "REQUEST_MANUAL_GAS_CHECK": {"level": 1, "text": "Ask the operator to arrange a manual gas reading in Zone 4."},
    "ESCALATE_TO_SUPERVISOR": {"level": 2, "text": "Refer the situation to the shift supervisor for a decision."},
    "RECOMMEND_HOT_WORK_SUSPENSION": {"level": 2, "text": "Advise the permit issuer to suspend hot work until the situation is reviewed."},
    "RECOMMEND_EVACUATION_REVIEW": {"level": 3, "text": "Ask the shift supervisor to urgently review whether Zone 4 should be evacuated."},
}

# Actions the agent may never authorise, whatever the risk or its confidence.
PROHIBITED_ACTIONS = {
    "AUTHORIZE_HOT_WORK": "Approving or extending a hot-work permit is a decision for an authorised person.",
    "SUSPEND_HOT_WORK_PERMIT": "Changing a permit is a decision for the permit issuer; the agent may only recommend it.",
    "RESTART_VENTILATION_FAN": "This is an equipment command, and this system never controls equipment.",
    "TRIGGER_EMERGENCY_SHUTDOWN": "This is an equipment command. Shutdowns belong to certified safety systems and authorised people.",
    "SILENCE_GAS_ALARM": "Alarms may never be silenced or suppressed by the agent.",
    "BYPASS_SAFETY_INTERLOCK": "Bypassing an interlock needs formal authorisation by a person.",
    "DECLARE_AREA_SAFE": "Declaring an area safe is the responsibility of an authorised person.",
}

# G5: the weakest response level allowed for each risk category.
MINIMUM_LEVEL = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}

# G4: the weakest response level allowed when any input is not reported.
INCOMPLETE_DATA_LEVEL = 2

# The gate's own default response for each level, used when it rejects a proposal.
DEFAULT_ACTION_FOR_LEVEL = {
    0: "LOG_OBSERVATION",
    1: "NOTIFY_OPERATOR",
    2: "ESCALATE_TO_SUPERVISOR",
    3: "RECOMMEND_EVACUATION_REVIEW",
}

# G1: the only fields a proposal may contain.
ALLOWED_FIELDS = ["action", "reason", "confidence"]

GATE_RULES = {
    "G1": "The proposal must be a JSON object with a text 'action' and a text 'reason'. 'confidence' is optional. No other fields are allowed.",
    "G2": "The action must be listed in the gate's action catalogue (allowlist). Unknown actions are rejected.",
    "G3": "Prohibited actions (permit approval, equipment commands, alarm or interlock override, declaring an area safe) are always rejected.",
    "G4": f"If any scenario input is not reported, the action must be at least level {INCOMPLETE_DATA_LEVEL} (escalation to a person).",
    "G5": "The action's level must reach the minimum for the risk category: LOW 0, MODERATE 1, HIGH 2, CRITICAL 3.",
    "G6": "The action must match the scenario facts: hot-work suspension cannot be recommended when the permit is closed.",
    "G7": "All checks G1-G6 passed: the proposal is accepted as advice for a person to act on.",
}

CHECK_ORDER = ["G1", "G2", "G3", "G4", "G5", "G6"]


def check_proposal(agent_output, risk_category, scenario):
    """Check one agent proposal against rules G1-G7 and return the decision.

    agent_output  - the agent's raw output (text, or an already-parsed dictionary)
    risk_category - the category from the risk engine (never from the agent)
    scenario      - the cleaned scenario inputs

    No rule reads the agent's confidence.
    """
    proposal, format_problem = read_proposal(agent_output)
    checks = run_checks(proposal, format_problem, risk_category, scenario)
    last_check = checks[-1]
    proposed_action = proposal["action"] if proposal else None

    # Show the checks that were not reached because an earlier one failed.
    for rule_id in CHECK_ORDER[len(checks):]:
        checks.append({"rule_id": rule_id, "result": "not reached", "note": GATE_RULES[rule_id]})

    required_level = required_level_for(risk_category, scenario)

    if last_check["result"] == "fail":
        decision = "REJECTED"
        rule_id = last_check["rule_id"]
        explanation = last_check["note"]
        final_action = DEFAULT_ACTION_FOR_LEVEL[required_level]
    else:
        decision = "ACCEPTED"
        rule_id = "G7"
        explanation = f"'{proposed_action}' passed checks G1-G6. It is accepted as advice for a person to act on."
        final_action = proposed_action

    return {
        "decision": decision,
        "rule_id": rule_id,
        "rule_text": GATE_RULES[rule_id],
        "explanation": explanation,
        "plain_explanation": plain_explanation(rule_id, proposed_action, format_problem, risk_category, scenario),
        "proposed_action": proposed_action,
        "required_level": required_level,
        "final_action": final_action,
        "final_action_text": ADVISORY_ACTIONS[final_action]["text"],
        "checks": checks,
        "ruleset": RULESET_NAME,
    }


def plain_explanation(rule_id, action, format_problem, risk_category, scenario):
    """The deciding rule explained in everyday words, for the page."""
    if risk_category in MINIMUM_LEVEL:
        risk_words = f"{risk_category.lower()} risk"
    else:
        risk_words = "an unrecognised risk level"

    if rule_id == "G1":
        if format_problem == "the agent output is empty":
            return "Rejected because the agent did not give a proposal."
        return "Rejected because the agent's answer was not a valid proposal, so it could not be checked."
    if rule_id == "G2":
        return f"Rejected because '{readable(action)}' is not one of the actions the system is allowed to recommend."
    if rule_id == "G3":
        return f"Rejected because the agent proposed '{readable(action)}', which it is never allowed to do. {PROHIBITED_ACTIONS[action]}"
    if rule_id == "G4":
        names = ", ".join(FIELD_LABELS[field].lower() for field in missing_fields(scenario))
        return (f"Rejected because some information is missing ({names}), "
                "and the proposed action does not pass the situation to a person.")
    if rule_id == "G5":
        needed = DEFAULT_ACTION_FOR_LEVEL[MINIMUM_LEVEL.get(risk_category, MINIMUM_LEVEL["CRITICAL"])]
        return f"Rejected because '{readable(action)}' is too weak a response for {risk_words}. At least '{readable(needed)}' is needed."
    if rule_id == "G6":
        return "Rejected because the proposal is about suspending hot work, but the hot-work permit is closed."
    return f"Accepted because the proposed action is allowed, fits the situation and is strong enough for {risk_words}."


def readable(action):
    """ESCALATE_TO_SUPERVISOR -> 'escalate to supervisor'"""
    return short_text(action).replace("_", " ").lower()


def read_proposal(agent_output):
    """Rule G1: read the agent's raw output as a proposal.

    Returns (proposal, None) when the output is well-formed, or
    (None, "description of the problem") when it is not.
    The gate never guesses what a malformed proposal was meant to say.
    """
    if isinstance(agent_output, str):
        text = agent_output.strip()
        if not text:
            return None, "the agent output is empty"
        try:
            agent_output = json.loads(text)
        except ValueError:
            return None, "the agent output is not valid JSON"

    if not isinstance(agent_output, dict):
        return None, "the proposal must be a JSON object"

    extra_fields = [str(key) for key in agent_output if key not in ALLOWED_FIELDS]
    if extra_fields:
        return None, "unexpected field(s): " + ", ".join(sorted(extra_fields))

    action = agent_output.get("action")
    if not isinstance(action, str) or not action.strip():
        return None, "'action' must be a non-empty text value"

    reason = agent_output.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None, "'reason' must be a non-empty text value"

    # 'confidence' is allowed so it can be shown on the receipt, but no rule uses it.
    return {"action": action, "reason": reason, "confidence": agent_output.get("confidence")}, None


def run_checks(proposal, format_problem, risk_category, scenario):
    """Apply checks G1-G6 in order and stop at the first one that fails.

    Returns a list of {"rule_id", "result", "note"}, where result is "pass" or "fail".
    """
    checks = []

    # G1 - the proposal must be well-formed.
    if format_problem:
        checks.append(failed("G1", f"Malformed proposal: {format_problem}. The gate does not guess or repair malformed output."))
        return checks
    checks.append(passed("G1", "The proposal is well-formed."))
    action = proposal["action"]

    # G2 - the action must be in the catalogue (allowlist).
    if action not in ADVISORY_ACTIONS and action not in PROHIBITED_ACTIONS:
        checks.append(failed("G2", f"'{short_text(action)}' is not in the action catalogue. The gate uses an allowlist, so any unlisted action is rejected, even one that sounds harmless."))
        return checks
    checks.append(passed("G2", f"'{action}' is in the action catalogue."))

    # G3 - prohibited actions are always rejected.
    if action in PROHIBITED_ACTIONS:
        checks.append(failed("G3", f"'{action}' is a prohibited action. {PROHIBITED_ACTIONS[action]} The agent may only propose advisory actions."))
        return checks
    checks.append(passed("G3", "The action is advisory, not prohibited."))
    level = ADVISORY_ACTIONS[action]["level"]

    # G4 - incomplete data needs at least an escalation to a person.
    missing = missing_fields(scenario)
    if missing and level < INCOMPLETE_DATA_LEVEL:
        names = ", ".join(FIELD_LABELS[field] for field in missing)
        checks.append(failed("G4", f"Not reported: {names}. With incomplete data the gate requires at least level {INCOMPLETE_DATA_LEVEL} (escalation to a person), but '{action}' is level {level}."))
        return checks
    if missing:
        checks.append(passed("G4", f"Some inputs are not reported, and '{action}' (level {level}) involves a person."))
    else:
        checks.append(passed("G4", "All scenario inputs are reported."))

    # G5 - the response must be strong enough for the risk category.
    minimum = MINIMUM_LEVEL.get(risk_category, MINIMUM_LEVEL["CRITICAL"])
    category_name = risk_category if risk_category in MINIMUM_LEVEL else f"an unrecognised category ('{risk_category}', treated as CRITICAL)"
    if level < minimum:
        checks.append(failed("G5", f"'{action}' is level {level}, but {category_name} risk needs at least level {minimum} (for example {DEFAULT_ACTION_FOR_LEVEL[minimum]})."))
        return checks
    checks.append(passed("G5", f"Level {level} meets the minimum level {minimum} for {category_name} risk."))

    # G6 - the action must match the scenario facts.
    if action == "RECOMMEND_HOT_WORK_SUSPENSION" and scenario.get("hot_work_permit") == "closed":
        checks.append(failed("G6", "The proposal recommends suspending hot work, but the scenario shows the hot-work permit is closed."))
        return checks
    checks.append(passed("G6", "The action matches the scenario facts."))

    return checks


def required_level_for(risk_category, scenario):
    """The weakest response level acceptable for this situation (used for the default)."""
    level = MINIMUM_LEVEL.get(risk_category, MINIMUM_LEVEL["CRITICAL"])
    if missing_fields(scenario):
        level = max(level, INCOMPLETE_DATA_LEVEL)
    return level


def passed(rule_id, note):
    return {"rule_id": rule_id, "result": "pass", "note": note}


def failed(rule_id, note):
    return {"rule_id": rule_id, "result": "fail", "note": note}


def short_text(value):
    """Shorten a value for use in a message."""
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."
