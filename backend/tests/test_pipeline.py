import unittest

from pydantic import ValidationError

from app.catalog import product_by_code
from app.models import ApplicationCreateRequest
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
            loan_amount_rub=1_000_000,
            loan_term_months=12,
            business_plan="Выручка 180000 руб. в месяц, кафе у метро.",
        )
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(result["monthly_payment_rub"], 94_560)
        self.assertEqual(result["limit_rub"], 1_000_000)
        self.assertEqual(result["report"]["flow_basis"], "inferred")

    def test_startup_rate_reduces_between_steps(self):
        result = run_scoring_pipeline(
            product="startup",
            loan_amount_rub=800_000,
            loan_term_months=18,
            profitability_rub=40_000,
        )
        self.assertEqual(result["monthly_payment_rub"], 53_362)
        self.assertEqual(result["limit_rub"], 500_000)
        self.assertEqual(result["decision"], "reduced")

    def test_offers_differ_and_cap_the_request(self):
        equipment = product_by_code("equipment")
        overdraft = product_by_code("overdraft")
        self.assertEqual(equipment["max_term_months"], 60)
        self.assertEqual(equipment["annual_rate_pct"], 16)
        self.assertEqual(equipment["max_amount_rub"], 5_000_000)
        self.assertLess(overdraft["max_term_months"], equipment["max_term_months"])
        self.assertNotEqual(overdraft["annual_rate_pct"], equipment["annual_rate_pct"])
        self.assertLess(overdraft["max_amount_rub"], equipment["max_amount_rub"])
        ApplicationCreateRequest(
            product="equipment",
            loan_amount_rub=5_000_000,
            loan_term_months=60,
            purpose="Станок",
            profitability_rub=500_000,
        )
        with self.assertRaises(ValidationError):
            ApplicationCreateRequest(
                product="overdraft",
                loan_amount_rub=100_000,
                loan_term_months=24,
                profitability_rub=50_000,
            )

    def test_phone_and_numbers_reject_text(self):
        from app.models import SessionCreateRequest

        SessionCreateRequest(phone="79001000001")
        for bad in ("+79001000001", "89001000001", "7900100000", "телефон", "79001000001 "):
            with self.assertRaises(ValidationError):
                SessionCreateRequest(phone=bad)
        with self.assertRaises(ValidationError):
            ApplicationCreateRequest(
                product="overdraft",
                loan_amount_rub="сто тысяч",
                loan_term_months=6,
                profitability_rub=50_000,
            )
        with self.assertRaises(ValidationError):
            ApplicationCreateRequest(
                product="overdraft",
                loan_amount_rub=100_000,
                loan_term_months="год",
                profitability_rub=50_000,
            )

    def test_reject_non_positive_flow(self):
        result = evaluate_math_pipeline(800_000, 12, 0)
        self.assertEqual(result["limit_rub"], 0)
        self.assertEqual(result["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
