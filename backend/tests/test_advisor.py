import unittest

from app.advisor import UNKNOWN_QUESTION, advise, keeps_the_question, reply_uses_only_brief_numbers
from app.config import settings

settings.advisor_llm_url = ""


class AdvisorMathTest(unittest.TestCase):
    def test_greeting_stays_on_the_script(self):
        result = advise(None, None, None, "привет")
        self.assertIsNone(result["answers"]["goal"])
        self.assertEqual(result["brief"]["say"], "ask_goal")
        self.assertIn("Здравствуйте", result["reply"])
        self.assertIn("на что", result["reply"].lower())
        self.assertEqual(result["voice"], "formula")

    def test_unknown_words_ask_again(self):
        result = advise(None, None, None, "ыыыы")
        self.assertIsNone(result["answers"]["goal"])
        self.assertEqual(result["brief"]["say"], "unparsed")
        self.assertIn("Выберите", result["reply"])
        self.assertFalse(result["done"])
        self.assertEqual(result["voice"], "formula")

    def test_equipment_words_ask_for_amount(self):
        result = advise(None, None, None, "нужен станок для цеха")
        self.assertEqual(result["answers"]["goal"], "equipment")
        self.assertEqual(result["brief"]["say"], "ask_amount")
        self.assertEqual(result["brief"]["annual_rate_pct"], 16)
        self.assertIn("500 000", result["reply"])
        self.assertIn("5 000 000", result["reply"])

    def test_startup_amount_outside_the_offer_is_rejected(self):
        result = advise("startup", None, None, "5 000 000")
        self.assertIsNone(result["answers"]["amount_rub"])
        self.assertEqual(result["brief"]["say"], "amount_out_of_range")
        self.assertEqual(result["brief"]["max_amount_rub"], 1_000_000)
        self.assertIsNone(result["product"])

    def test_overdraft_half_year_fits(self):
        result = advise("overdraft", 500_000, None, "полгода")
        self.assertEqual(result["answers"]["term_months"], 6)
        self.assertFalse(result["done"])
        self.assertEqual(result["brief"]["say"], "ask_profit")
        self.assertEqual(result["product"]["code"], "overdraft")
        self.assertEqual(result["product"]["annual_rate_pct"], 22)

    def test_equipment_offer_uses_catalog_rate(self):
        result = advise("equipment", 2_000_000, 24, "")
        self.assertFalse(result["done"])
        self.assertEqual(result["brief"]["say"], "ask_profit")
        self.assertEqual(result["product"]["annual_rate_pct"], 16)
        self.assertEqual(result["product"]["max_term_months"], 60)
        self.assertIn("16%", result["reply"])
        self.assertNotIn("20%", result["reply"])

    def test_replace_loan_is_refinance_not_working_capital(self):
        result = advise(None, None, None, "хочу заменить действующий кредит")
        self.assertEqual(result["answers"]["goal"], "refinance")

    def test_invented_number_is_not_a_faithful_reply(self):
        brief = {"say": "offer", "annual_rate_pct": 16, "amount_rub": 2_000_000}
        self.assertFalse(reply_uses_only_brief_numbers("Ставка 99%, берите.", brief))
        self.assertTrue(reply_uses_only_brief_numbers("Ставка 16% на 2000000.", brief))

    def test_paraphrase_must_keep_the_same_question(self):
        draft = "На что нужны деньги? Можно выбрать вариант ниже."
        self.assertFalse(keeps_the_question(draft, "Вы хотите знать, почему вам нужны деньги?"))
        self.assertTrue(keeps_the_question(draft, "Подскажите, на что нужны деньги?"))
        phone = "Какой номер записать? Подойдёт только готовый профиль."
        self.assertFalse(keeps_the_question(phone, "Какой номер профильного договора записать?"))
        self.assertTrue(keeps_the_question(phone, "Какой номер записать из готовых профилей?"))
        offer = "Подходит «Кредит на оборудование»: ставка 16%."
        self.assertTrue(keeps_the_question(offer, "Кредит на оборудование, ставка 16%."))

    def test_demo_phone_and_mock_sms_file_the_draft(self):
        picked = advise(None, None, None, "нужен станок для цеха")
        amount = advise(picked["answers"]["goal"], None, None, "2000000", purpose=picked["answers"]["purpose"])
        term = advise(
            amount["answers"]["goal"],
            amount["answers"]["amount_rub"],
            None,
            "24",
            purpose=amount["answers"]["purpose"],
        )
        self.assertEqual(term["brief"]["say"], "ask_profit")
        profit = advise(
            term["answers"]["goal"],
            term["answers"]["amount_rub"],
            term["answers"]["term_months"],
            "400000",
            purpose=term["answers"]["purpose"],
        )
        self.assertEqual(profit["brief"]["say"], "ask_phone")
        unknown = advise(
            profit["answers"]["goal"],
            profit["answers"]["amount_rub"],
            profit["answers"]["term_months"],
            "79990000000",
            purpose=profit["answers"]["purpose"],
            profitability_rub=profit["answers"]["profitability_rub"],
        )
        self.assertIsNone(unknown["answers"]["phone"])
        self.assertEqual(unknown["brief"]["say"], "phone_unknown")
        self.assertIn("Номер не найден.", unknown["reply"])
        known = advise(
            unknown["answers"]["goal"],
            unknown["answers"]["amount_rub"],
            unknown["answers"]["term_months"],
            "79001000001",
            purpose=unknown["answers"]["purpose"],
            profitability_rub=unknown["answers"]["profitability_rub"],
        )
        self.assertEqual(known["answers"]["phone"], "79001000001")
        self.assertEqual(known["brief"]["say"], "ask_sms")
        self.assertIn("0000", known["reply"])
        filed = advise(
            known["answers"]["goal"],
            known["answers"]["amount_rub"],
            known["answers"]["term_months"],
            "0000",
            purpose=known["answers"]["purpose"],
            profitability_rub=known["answers"]["profitability_rub"],
            phone=known["answers"]["phone"],
        )
        self.assertTrue(filed["done"])
        self.assertEqual(filed["voice"], "formula")
        self.assertEqual(filed["file"]["phone"], "79001000001")
        self.assertEqual(filed["file"]["product"], "equipment")
        self.assertEqual(filed["file"]["loan_amount_rub"], 2_000_000)
        self.assertEqual(filed["file"]["loan_term_months"], 24)
        self.assertEqual(filed["file"]["profitability_rub"], 400_000)

    def test_product_question_without_model_does_not_invent(self):
        result = advise("equipment", None, None, "какая ставка на оборудование?")
        self.assertEqual(result["answers"]["goal"], "equipment")
        self.assertIsNone(result["answers"]["amount_rub"])
        self.assertEqual(result["reply"], UNKNOWN_QUESTION)
        self.assertEqual(result["voice"], "formula")

    def test_apply_intent_asks_the_next_field(self):
        result = advise(
            "working_capital",
            None,
            None,
            "Круто давай оформлять что от меня требуется?",
        )
        self.assertEqual(result["answers"]["goal"], "working_capital")
        self.assertIsNone(result["answers"]["amount_rub"])
        self.assertEqual(result["brief"]["say"], "ask_amount")
        self.assertIn("Оформляем", result["reply"])
        self.assertIn("Какая сумма", result["reply"])
        self.assertNotIn("карточках", result["reply"])
        self.assertEqual(result["voice"], "formula")

    def test_question_history_does_not_move_the_form(self):
        result = advise(
            "equipment",
            None,
            None,
            "какая погода в сочи?",
            history=[
                {"role": "user", "text": "какая ставка на оборудование?"},
                {"role": "assistant", "text": "Ставка на кредит на оборудование составляет 16% годовых."},
            ],
        )
        self.assertEqual(result["answers"]["goal"], "equipment")
        self.assertIsNone(result["answers"]["amount_rub"])
        self.assertEqual(result["reply"], UNKNOWN_QUESTION)
        self.assertEqual(result["voice"], "formula")
