"""
Tests for scenario cleaning and the rule-based risk engine.

Required test cases 1-4 are the tests named test_01 ... test_04.
Run all tests from the project folder with:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

# Make the modules in backend/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from risk_engine import RISK_RULES, assess_risk  # noqa: E402
from sample_scenarios import SAMPLE_SCENARIOS  # noqa: E402
from scenario import ALL_FIELDS, PRESETS, clean_scenario  # noqa: E402


def preset_scenario(key, **changes):
    """A cleaned preset scenario, optionally with some values changed."""
    values = dict(SAMPLE_SCENARIOS[key], **changes)
    scenario, _ = clean_scenario(values)
    return scenario


class RiskEngineTests(unittest.TestCase):

    def test_01_normal_scenario_is_low_risk(self):
        risk = assess_risk(preset_scenario("normal"))
        self.assertEqual(risk["category"], "LOW")
        self.assertEqual(risk["findings"], [])
        self.assertTrue(risk["data_complete"])

    def test_02_compound_hazard_is_high_although_gas_alone_is_low(self):
        risk = assess_risk(preset_scenario("compound"))
        self.assertEqual(risk["category"], "HIGH")
        # 4% LEL on its own stays LOW, like a single-sensor alarm would...
        self.assertEqual(risk["gas_only_category"], "LOW")
        # ...but the combination rules raise the category.
        self.assertEqual(risk["deciding_rules"], ["C2", "C3", "C7"])
        # No individual condition reaches HIGH on its own.
        individual = [f for f in risk["findings"] if f["type"] == "individual"]
        self.assertTrue(all(f["severity"] in ("LOW", "MODERATE") for f in individual))

    def test_03_critical_gas_scenario_is_critical(self):
        risk = assess_risk(preset_scenario("critical_gas"))
        self.assertEqual(risk["category"], "CRITICAL")
        self.assertIn("I1", risk["deciding_rules"])  # gas at or above 20% LEL
        self.assertIn("C1", risk["deciding_rules"])  # hot work open in high gas

    def test_04_missing_information_is_handled_conservatively(self):
        risk = assess_risk(preset_scenario("missing_info"))
        self.assertEqual(risk["category"], "HIGH")
        self.assertFalse(risk["data_complete"])
        self.assertEqual(risk["missing_fields"], ["gas_lel", "gas_trend", "fan_status"])
        self.assertEqual(risk["deciding_rules"], ["M1"])
        self.assertIsNone(risk["gas_only_category"])

    def test_any_single_missing_input_raises_normal_scenario_to_high(self):
        for field in ALL_FIELDS:
            with self.subTest(field=field):
                risk = assess_risk(preset_scenario("normal", **{field: None}))
                self.assertEqual(risk["category"], "HIGH")

    def test_invalid_values_are_treated_as_not_reported(self):
        values = dict(SAMPLE_SCENARIOS["normal"], gas_lel=-5, ventilation_pct="abc",
                      fan_status="broken", gas_trend=True)
        scenario, notes = clean_scenario(values)
        for field in ["gas_lel", "ventilation_pct", "fan_status", "gas_trend"]:
            self.assertIsNone(scenario[field], field)
        self.assertEqual(len(notes), 4)
        self.assertEqual(assess_risk(scenario)["category"], "HIGH")

    def test_values_typed_as_text_are_accepted(self):
        scenario, notes = clean_scenario(dict(SAMPLE_SCENARIOS["compound"], gas_lel="4", fan_status=" Failed "))
        self.assertEqual(scenario["gas_lel"], 4.0)
        self.assertEqual(scenario["fan_status"], "failed")
        self.assertEqual(notes, [])

    def test_gas_thresholds(self):
        cases = [(0, "LOW"), (4.9, "LOW"), (5, "MODERATE"), (9.9, "MODERATE"),
                 (10, "HIGH"), (19.9, "HIGH"), (20, "CRITICAL"), (100, "CRITICAL")]
        for gas, expected in cases:
            with self.subTest(gas=gas):
                self.assertEqual(assess_risk(preset_scenario("normal", gas_lel=gas))["category"], expected)

    def test_one_abnormal_condition_alone_stays_below_high(self):
        changes = {"gas_trend": "rising", "ventilation_pct": 60, "fan_status": "failed",
                   "hot_work_permit": "open", "maintenance_fault": "present", "shift_condition": "changeover"}
        for field, value in changes.items():
            with self.subTest(field=field):
                risk = assess_risk(preset_scenario("normal", **{field: value}))
                self.assertIn(risk["category"], ("LOW", "MODERATE"))

    def test_low_result_with_a_minor_condition_has_no_deciding_rule(self):
        risk = assess_risk(preset_scenario("normal", hot_work_permit="open"))
        self.assertEqual(risk["category"], "LOW")
        self.assertEqual([f["rule_id"] for f in risk["findings"]], ["I8"])
        self.assertEqual(risk["deciding_rules"], [])

    def test_normal_operation_preset_matches_the_normal_sample(self):
        self.assertEqual(list(PRESETS), ["normal"])
        self.assertEqual(PRESETS["normal"]["values"], SAMPLE_SCENARIOS["normal"])

    def test_plain_explanations_only_use_matched_conditions(self):
        normal = assess_risk(preset_scenario("normal"))["explanation"]
        self.assertIn("normal ranges", normal)

        critical = assess_risk(preset_scenario("critical_gas"))["explanation"]
        self.assertIn("critically high (24% LEL)", critical)
        self.assertIn("rising", critical)
        self.assertIn("hot work is permitted", critical)
        self.assertNotIn("fan", critical)          # the fan is operational in this scenario
        self.assertNotIn("maintenance", critical)  # no fault is reported

        compound = assess_risk(preset_scenario("compound"))["explanation"]
        self.assertIn("the extraction fan has failed", compound)
        self.assertNotIn("critically", compound)

        missing = assess_risk(preset_scenario("missing_info"))["explanation"]
        self.assertIn("gas concentration, gas trend and fan status", missing)

        # No rule IDs appear in the plain explanation.
        for text in [normal, critical, compound, missing]:
            for rule in RISK_RULES:
                self.assertNotRegex(text, rf"\b{rule['id']}\b")

    def test_every_finding_matches_a_documented_rule(self):
        documented = {rule["id"]: rule["result"] for rule in RISK_RULES}
        for key in SAMPLE_SCENARIOS:
            for finding in assess_risk(preset_scenario(key))["findings"]:
                with self.subTest(preset=key, rule=finding["rule_id"]):
                    self.assertEqual(finding["severity"], documented[finding["rule_id"]])

    def test_risk_engine_is_deterministic(self):
        for key in SAMPLE_SCENARIOS:
            first = assess_risk(preset_scenario(key))
            for _ in range(20):
                self.assertEqual(assess_risk(preset_scenario(key)), first)


if __name__ == "__main__":
    unittest.main()
