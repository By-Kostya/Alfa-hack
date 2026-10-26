import unittest

from app.scoring.pipeline import evaluate_math_pipeline, flow_from_plan, run_scoring_pipeline


class MathPipelineTest(unittest.TestCase):
    def test_contract_payment_and_approve(self):
        result = evaluate_math_pipeline(800_000, 12, 160_000)
        self.assertEqual(result["pipeline"], "math")
        self.assertTrue(result["fallback"])
        self.assertEqual(result["monthly_payment_rub"], 74_108)
        self.assertEqual(result["limit_rub"], 800_000)
        self.assertEqual(result["decision"], "approve")

    def test_reduced_when_request_is_above_step(self):
        result = evaluate_math_pipeline(2_000_000, 12, 160_000)
        self.assertEqual(result["limit_rub"], 800_000)
        self.assertEqual(result["decision"], "reduced")

    def test_unknown_without_flow(self):
        result = evaluate_math_pipeline(800_000, 12, None)
        self.assertIsNone(result["limit_rub"])
        self.assertEqual(result["decision"], "unknown")

    def test_plan_number_becomes_credit(self):
        self.assertEqual(flow_from_plan("Выручка 180000 руб. в месяц"), 180_000)
        result = run_scoring_pipeline(
            product="startup",
            loan_amount_rub=800_000,
            loan_term_months=12,
            business_plan="Выручка 180000 руб. в месяц, кафе у метро.",
        )
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(result["limit_rub"], 800_000)
        self.assertEqual(result["report"]["flow_basis"], "inferred")

    def test_reject_non_positive_flow(self):
        result = evaluate_math_pipeline(800_000, 12, 0)
        self.assertEqual(result["limit_rub"], 0)
        self.assertEqual(result["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
