"""
The analysis pipeline. It connects the separate modules in a fixed order:

    Scenario -> Risk engine -> Agent proposal -> Deterministic gate -> Final decision

There is no path around the gate: every proposal is checked by
decision_gate.check_proposal() before a final decision is produced.
"""

from agent import get_proposal
from decision_gate import check_proposal
from risk_engine import assess_risk
from scenario import clean_scenario


def run_analysis(raw_inputs, proposal_source="gemma", manual_text=""):
    """Run the whole workflow once and return the result (a dictionary)."""

    # 1. Scenario: clean the inputs (blank or invalid -> not reported).
    scenario, input_notes = clean_scenario(raw_inputs)

    # 2. Risk engine: rule-based assessment of the scenario.
    risk = assess_risk(scenario)

    # 3. Agent: propose an action. The agent sees the scenario and the risk
    #    result, but it never sees or calls the gate.
    proposal = get_proposal(proposal_source, scenario, risk, manual_text)

    # 4. Gate (the "Safety Check"): check the agent's raw output. The risk category
    #    comes from the risk engine, not from the agent, and the confidence is not used.
    gate = check_proposal(proposal["raw_output"], risk["category"], scenario)

    # 5. Final decision: taken only from the gate's result.
    final_decision = {
        "action": gate["final_action"],
        "description": gate["final_action_text"],
        "explanation": explain_final_decision(risk, gate),
    }

    return {
        "scenario": scenario,
        "input_notes": input_notes,
        "risk": risk,
        "proposal": proposal,
        "gate": gate,
        "final_decision": final_decision,
    }


def explain_final_decision(risk, gate):
    """Explain the final decision in everyday words, based on the actual results."""
    situation = f"the risk is {risk['category'].lower()}"
    if risk["missing_fields"]:
        situation += " and some information is missing"

    action_text = gate["final_action_text"]
    text = f"Because {situation}, the recommended action is to {action_text[0].lower()}{action_text[1:]}"

    if gate["decision"] == "ACCEPTED":
        text += " This was the agent's proposal, and it passed the safety check."
    else:
        text += " The agent's proposal did not pass the safety check, so the system uses its own safe default instead."

    return text + " A person makes the final call; the system does not control any equipment."
