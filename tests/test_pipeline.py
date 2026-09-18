"""
End-to-end tests of the whole workflow:
    Scenario -> Risk engine -> Agent proposal -> Deterministic gate -> Final decision
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import agent  # noqa: E402
from pipeline import run_analysis  # noqa: E402
from sample_scenarios import SAMPLE_SCENARIOS  # noqa: E402


def run(scenario_key, source="mock_scenario", manual_text=""):
    return run_analysis(SAMPLE_SCENARIOS[scenario_key], source, manual_text)


def summary(result):
    return (
        result["risk"]["category"],
        result["gate"]["proposed_action"],
        result["gate"]["decision"],
        result["gate"]["rule_id"],
        result["final_decision"]["action"],
    )


class PipelineTests(unittest.TestCase):

    def test_each_preset_with_the_scenario_based_mock_agent(self):
        expected = {
            # preset: (risk, proposed action, gate decision, gate rule, final action)
            "normal": ("LOW", "LOG_OBSERVATION", "ACCEPTED", "G7", "LOG_OBSERVATION"),
            "compound": ("HIGH", "RECOMMEND_HOT_WORK_SUSPENSION", "ACCEPTED", "G7", "RECOMMEND_HOT_WORK_SUSPENSION"),
            "critical_gas": ("CRITICAL", "RECOMMEND_EVACUATION_REVIEW", "ACCEPTED", "G7", "RECOMMEND_EVACUATION_REVIEW"),
            "missing_info": ("HIGH", "NOTIFY_OPERATOR", "REJECTED", "G4", "ESCALATE_TO_SUPERVISOR"),
        }
        for key, values in expected.items():
            with self.subTest(preset=key):
                result = run(key)
                self.assertEqual(summary(result), values)

    def test_every_fixed_mock_response_is_checked_by_the_gate(self):
        expected = {
            "mock_prohibited_permit": ("REJECTED", "G3"),
            "mock_prohibited_shutdown": ("REJECTED", "G3"),
            "mock_unknown": ("REJECTED", "G2"),
            "mock_malformed": ("REJECTED", "G1"),
        }
        for preset_key in SAMPLE_SCENARIOS:
            for source, (decision, rule_id) in expected.items():
                with self.subTest(preset=preset_key, source=source):
                    result = run(preset_key, source)
                    self.assertEqual(result["proposal"]["kind"], "mock")
                    self.assertEqual((result["gate"]["decision"], result["gate"]["rule_id"]), (decision, rule_id))
                    # A rejected proposal never becomes the final decision.
                    self.assertNotEqual(result["final_decision"]["action"], result["gate"]["proposed_action"])
                    self.assertEqual(result["final_decision"]["action"], result["gate"]["final_action"])

    def test_result_contains_every_required_part(self):
        result = run("compound")
        self.assertEqual(set(result["scenario"]), set(SAMPLE_SCENARIOS["compound"]))  # scenario inputs
        self.assertEqual(result["risk"]["category"], "HIGH")                           # risk category
        self.assertGreater(len(result["risk"]["findings"]), 0)                         # contributing factors
        self.assertTrue(result["proposal"]["raw_output"])                              # agent proposal
        for key in ["decision", "explanation", "rule_id"]:                              # gate decision, explanation, rule
            self.assertTrue(result["gate"][key])
        self.assertTrue(result["final_decision"]["action"])

    def test_manual_input_goes_through_the_same_gate(self):
        result = run("compound", "manual", '{"action": "DECLARE_AREA_SAFE", "reason": "typed", "confidence": 1}')
        self.assertEqual(result["proposal"]["kind"], "manual")
        self.assertEqual((result["gate"]["decision"], result["gate"]["rule_id"]), ("REJECTED", "G3"))

    def test_unavailable_gemma_is_handled_safely(self):
        # Point the agent at a port where nothing is listening.
        with mock.patch.object(agent, "OLLAMA_URL", "http://127.0.0.1:9"):
            result = run("compound", "gemma")
        self.assertEqual(result["proposal"]["kind"], "gemma")
        self.assertIsNotNone(result["proposal"]["error"])
        self.assertEqual(result["proposal"]["raw_output"], "")
        self.assertEqual((result["gate"]["decision"], result["gate"]["rule_id"]), ("REJECTED", "G1"))
        self.assertEqual(result["final_decision"]["action"], "ESCALATE_TO_SUPERVISOR")

    def test_repeated_runs_give_identical_results(self):
        for key in SAMPLE_SCENARIOS:
            with self.subTest(preset=key):
                first = run(key)
                for _ in range(10):
                    self.assertEqual(run(key), first)

    def test_final_explanation_matches_the_actual_result(self):
        accepted = run("critical_gas")
        text = accepted["final_decision"]["explanation"]
        self.assertIn("the risk is critical", text)
        self.assertIn("passed the safety check", text)
        self.assertIn("review whether Zone 4 should be evacuated", text)

        rejected = run("missing_info")
        text = rejected["final_decision"]["explanation"]
        self.assertIn("the risk is high and some information is missing", text)
        self.assertIn("did not pass the safety check", text)
        self.assertIn("shift supervisor", text)

        # The explanation never claims that anything was done to real equipment.
        for key in SAMPLE_SCENARIOS:
            text = run(key)["final_decision"]["explanation"].lower()
            self.assertIn("does not control any equipment", text)
            self.assertNotIn("evacuated zone", text)


@unittest.skipUnless(agent.gemma_status()[0], "Gemma is not available (Ollama not running or model not installed)")
class GemmaLiveTests(unittest.TestCase):
    """Runs only when Ollama and the Gemma model are available on this computer."""

    def test_real_gemma_output_is_checked_by_the_gate(self):
        for key in SAMPLE_SCENARIOS:
            with self.subTest(preset=key):
                result = run(key, "gemma")
                self.assertIsNone(result["proposal"]["error"])
                self.assertIn(result["gate"]["decision"], ("ACCEPTED", "REJECTED"))
                if result["gate"]["decision"] == "ACCEPTED":
                    self.assertEqual(result["final_decision"]["action"], result["gate"]["proposed_action"])
                else:
                    self.assertEqual(result["final_decision"]["action"], result["gate"]["final_action"])


if __name__ == "__main__":
    unittest.main()
