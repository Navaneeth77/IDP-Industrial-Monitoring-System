"""
Agent module - produces a PROPOSED action. It never makes the final decision.

The page uses one source:
  * GEMMA - a local Gemma model run by Ollama on this computer.

Two further sources are kept only for the automated tests, so that every
path of the safety check can be tested without a model. They are not shown
on the page:
  * MOCK responses - fixed valid, prohibited, unknown and malformed examples.
  * MANUAL - a proposal written directly by a test.

Every source returns raw text, as a language model would. The pipeline passes
that text to the decision gate unchanged. This module does not import the
gate, and the gate's rules are not part of the agent's prompt.
"""

import json
import os
import urllib.request

from scenario import ALL_FIELDS, FIELD_LABELS

PROPOSAL_SOURCES = {
    "mock_scenario": "Mock agent - scenario-based proposal (predefined logic, not a language model)",
    "mock_prohibited_permit": "Mock agent - fixed example of a prohibited action: approve hot work",
    "mock_prohibited_shutdown": "Mock agent - fixed example of a prohibited action: emergency shutdown command",
    "mock_unknown": "Mock agent - fixed example of an unknown action",
    "mock_malformed": "Mock agent - fixed example of malformed output",
    "manual": "Manual test input (written by a test, not produced by an agent)",
    "gemma": "Gemma - local language model run by Ollama",
}

# Fixed responses of the mock agent. The confidence values are placeholders.
MOCK_RESPONSES = {
    "mock_prohibited_permit": json.dumps({
        "action": "AUTHORIZE_HOT_WORK",
        "reason": "Continue hot work under the current permit to avoid delaying the maintenance schedule.",
        "confidence": 0.97,
    }),
    "mock_prohibited_shutdown": json.dumps({
        "action": "TRIGGER_EMERGENCY_SHUTDOWN",
        "reason": "Shut down the Zone 4 process equipment immediately.",
        "confidence": 0.99,
    }),
    "mock_unknown": json.dumps({
        "action": "SCHEDULE_TOOLBOX_TALK",
        "reason": "Brief the next shift about gas hazards at the toolbox talk.",
        "confidence": 0.88,
    }),
    # Cut off part-way through, like a model answer that stopped early.
    "mock_malformed": '{"action": "ESCALATE_TO_SUPERVISOR", "reason": "Gas is rising near the hot-wo',
}

# Local Gemma settings. They can be changed with environment variables.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "gemma3:1b")
GEMMA_TIMEOUT_SECONDS = 60

# The actions the agent is told it may suggest. This is the agent's own list:
# the gate keeps its own catalogue and rules in decision_gate.py.
AGENT_ACTIONS = {
    "LOG_OBSERVATION": "record the assessment and continue routine monitoring",
    "NOTIFY_OPERATOR": "show an advisory message to the control-room operator",
    "REQUEST_MANUAL_GAS_CHECK": "ask for a manual gas reading",
    "ESCALATE_TO_SUPERVISOR": "refer the situation to the shift supervisor",
    "RECOMMEND_HOT_WORK_SUSPENSION": "advise the permit issuer to suspend hot work",
    "RECOMMEND_EVACUATION_REVIEW": "advise the supervisor to review evacuation of Zone 4",
}


def get_proposal(source, scenario, risk, manual_text=""):
    """Get a proposal from the chosen source. Returns a dictionary:

        source     - the source key, for example "mock_scenario"
        kind       - "mock", "manual" or "gemma"
        label      - a short description of the source
        raw_output - the text given to the gate, unchanged
        error      - None, or a message if the source failed
    """
    proposal = {
        "source": source,
        "kind": "unknown",
        "label": PROPOSAL_SOURCES.get(source, "Unknown source"),
        "raw_output": "",
        "error": None,
    }

    if source == "mock_scenario":
        proposal["kind"] = "mock"
        proposal["raw_output"] = mock_scenario_proposal(scenario, risk)
    elif source in MOCK_RESPONSES:
        proposal["kind"] = "mock"
        proposal["raw_output"] = MOCK_RESPONSES[source]
    elif source == "manual":
        proposal["kind"] = "manual"
        proposal["raw_output"] = manual_text
    elif source == "gemma":
        proposal["kind"] = "gemma"
        available, message = gemma_status()
        if not available:
            proposal["error"] = "Gemma is not available. " + message
        else:
            try:
                proposal["raw_output"] = ask_gemma(scenario, risk)
            except Exception as error:  # any failure: the gate then sees an empty output
                proposal["error"] = f"Gemma did not respond ({error})."
    else:
        proposal["error"] = f"Unknown proposal source '{source}'."

    return proposal


def mock_scenario_proposal(scenario, risk):
    """Choose a predefined proposal from the risk engine's result.

    This imitates a simple agent; it is not a language model. On purpose, it
    handles missing data weakly (it only proposes notifying the operator), so
    that the gate's conservative rule for incomplete data can be demonstrated.
    """
    category = risk["category"]
    rules = ", ".join(risk["deciding_rules"])

    if risk["missing_fields"]:
        action, confidence = "NOTIFY_OPERATOR", 0.70
        reason = "Some readings are not reported; the operator should be told so they can be restored."
    elif category == "CRITICAL":
        action, confidence = "RECOMMEND_EVACUATION_REVIEW", 0.93
        reason = f"The risk engine reports CRITICAL risk (rules {rules}); people in Zone 4 may be in danger."
    elif category == "HIGH" and scenario["hot_work_permit"] == "open":
        action, confidence = "RECOMMEND_HOT_WORK_SUSPENSION", 0.86
        reason = f"The risk engine reports HIGH risk (rules {rules}) while hot work is open; hot work should pause until the cause is found."
    elif category == "HIGH":
        action, confidence = "ESCALATE_TO_SUPERVISOR", 0.82
        reason = f"The risk engine reports HIGH risk (rules {rules}); the shift supervisor should decide the response."
    elif category == "MODERATE":
        action, confidence = "NOTIFY_OPERATOR", 0.78
        reason = f"The risk engine reports MODERATE risk (rules {rules}); the operator should be aware."
    else:
        action, confidence = "LOG_OBSERVATION", 0.91
        reason = "The risk engine reports LOW risk; continue routine monitoring."

    return json.dumps({"action": action, "reason": reason, "confidence": confidence})


def gemma_status():
    """Check whether Ollama is running and the Gemma model is installed.

    Returns (available, message).
    """
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=2) as response:
            installed = [model.get("name") for model in json.load(response).get("models", [])]
    except Exception:
        return False, "Ollama is not running or cannot be reached from the server."
    if GEMMA_MODEL not in installed:
        return False, f"Ollama is running, but the model {GEMMA_MODEL} is not installed."
    return True, f"{GEMMA_MODEL} is available through Ollama on this computer."


def ask_gemma(scenario, risk):
    """Send the scenario and the risk result to Gemma and return its raw answer text."""
    request_body = {
        "model": GEMMA_MODEL,
        "prompt": build_gemma_prompt(scenario, risk),
        "stream": False,
        # Ask Ollama for a JSON object with these three fields. The gate still
        # checks the answer, because the model can put anything in them.
        "format": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "reason": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reason", "confidence"],
        },
        "options": {"temperature": 0, "seed": 1},  # as repeatable as possible
    }
    request = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=GEMMA_TIMEOUT_SECONDS) as response:
        answer = json.load(response)
    return answer.get("response", "")


def build_gemma_prompt(scenario, risk):
    """The text sent to Gemma: the scenario, the risk result and the action list."""
    lines = [
        "You are an advisory assistant for a SIMULATED industrial area called Zone 4.",
        "You cannot control equipment or approve permits. Propose ONE advisory action for a person to consider.",
        "",
        "Simulated inputs:",
    ]
    for field in ALL_FIELDS:
        value = scenario[field]
        lines.append(f"- {FIELD_LABELS[field]}: {'not reported' if value is None else value}")

    lines += [
        "",
        f"Risk engine category: {risk['category']}",
        f"Risk engine explanation: {risk['summary']}",
        "Risk engine findings:",
    ]
    for finding in risk["findings"]:
        lines.append(f"- {finding['rule_id']} ({finding['severity']}): {finding['description']}")
    if not risk["findings"]:
        lines.append("- none")

    lines += ["", "Choose exactly one action from this list:"]
    for action, meaning in AGENT_ACTIONS.items():
        lines.append(f"- {action}: {meaning}")

    lines += [
        "",
        'Reply with JSON only: {"action": "<one action name from the list>", '
        '"reason": "<one short sentence>", "confidence": <number from 0 to 1>}',
    ]
    return "\n".join(lines)
