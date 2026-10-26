"""Подбор продукта до входа.

Формула решает, что спросить и какой продукт назвать. Маленькая модель
только пересказывает уже посчитанный brief и не имеет права добавить число.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from app.catalog import product_by_code, public_product
from app.config import settings
from app.demo import DEMO_PHONES, public_profiles
from app.scoring.pipeline import flow_from_plan

logger = logging.getLogger("credit-cabinet")
_voice_warned = False

GOALS = (
    ("refinance", "Заменить действующий кредит", ("рефин", "перекредит", "замен", "погас", "закрыть кредит")),
    ("overdraft", "Закрыть кассовый разрыв", ("кассов", "разрыв", "овердраф")),
    ("contract", "Исполнить договор", ("контракт", "договор", "поставк")),
    ("equipment", "Купить оборудование", ("станок", "оборуд", "транспорт", "оснащ")),
    ("startup", "Запустить новое дело", ("запуск", "стартап", "новое дело", "с нуля", "новый бизнес")),
    ("working_capital", "Закупки и текущие платежи", ("закуп", "аренд", "оборот", "зарплат", "текущ")),
)

SMS_CODE = "0000"
UNKNOWN_QUESTION = "Вопрос не понят. Попробуйте переформулировать."
CHATTER = (
    (("привет", "здравств", "добрый"), "Здравствуйте. Я на связи и подберу кредит по шагам."),
    (("спасибо", "благодар"), "Пожалуйста, идём дальше."),
    (("кто ты", "ты кто", "ты бот"), "Я текстовый подбор Альфа-Бизнес и отвечаю заготовленными фразами."),
    (("помощь", "что умеешь", "как это работает"), "Напишите, на что нужны деньги, или нажмите кнопку. Дальше спрошу сумму и срок."),
)


def rub(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _numbers_in(text: str) -> set[int]:
    compact = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    return {int(item) for item in re.findall(r"\d+", compact)}


def _brief_numbers(brief: dict) -> set[int]:
    found: set[int] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int):
            found.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(brief)
    return found


def keeps_the_question(draft: str, text: str) -> bool:
    if "не найден" in draft.lower() and "не найден" not in text.lower():
        return False
    if "?" not in draft:
        return True
    if "?" not in text:
        return False
    stems = ("на что", "какая", "какой", "какие", "сколько", "на какой")
    needed = [stem for stem in stems if stem in draft.lower()]
    if not needed:
        return True
    lowered = text.lower()
    draft_lower = draft.lower()
    for word in ("номер", "код", "выручк"):
        if word in draft_lower and word not in lowered:
            return False
    for word in ("договор", "почему"):
        if word in lowered and word not in draft_lower:
            return False
    return any(stem in lowered for stem in needed)


def reply_uses_only_brief_numbers(text: str, brief: dict) -> bool:
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 400:
        return False
    lowered = cleaned.lower()
    if "{" in cleaned or "ask_" in lowered or "json" in lowered:
        return False
    return _numbers_in(cleaned).issubset(_brief_numbers(brief))


def parse_amount(text: str) -> Optional[int]:
    raw = text.lower().replace("\u00a0", " ")
    million = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:млн|миллион)", raw)
    if million:
        return int(round(float(million.group(1).replace(",", ".")) * 1_000_000))
    thousand = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:тыс|тысяч)", raw)
    if thousand:
        return int(round(float(thousand.group(1).replace(",", ".")) * 1_000))
    grouped = re.search(r"\d[\d\s]{2,}", raw)
    if not grouped:
        return None
    digits = re.sub(r"\s+", "", grouped.group())
    if not digits.isdigit():
        return None
    return int(digits)


def parse_term(text: str) -> Optional[int]:
    raw = text.lower().replace("\u00a0", " ")
    if "полгода" in raw or "пол года" in raw:
        return 6
    years = re.search(r"(\d+)\s*(?:год|года|лет)", raw)
    if years:
        return int(years.group(1)) * 12
    months = re.search(r"(\d+)\s*мес", raw)
    if months:
        return int(months.group(1))
    bare = re.search(r"\d+", raw)
    if not bare:
        return None
    value = int(bare.group())
    if 1 <= value <= 60:
        return value
    return None


def parse_phone(text: str) -> Optional[str]:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return digits
    return None


def chatter_line(text: str) -> Optional[str]:
    raw = text.lower()
    for words, line in CHATTER:
        if any(word in raw for word in words):
            return line
    return None


def parse_goal(text: str) -> Optional[str]:
    raw = text.lower().strip()
    codes = {code for code, _title, _words in GOALS}
    if raw in codes:
        return raw
    for code, _title, words in GOALS:
        if any(word in raw for word in words):
            return code
    return None


def _spec(goal: Optional[str]) -> Optional[dict]:
    if not goal:
        return None
    return product_by_code(goal)


def _goal_title(goal: str) -> str:
    for code, title, _words in GOALS:
        if code == goal:
            return title
    spec = product_by_code(goal)
    return spec["title"] if spec else goal


def _goal_choices() -> list[dict]:
    return [{"id": code, "label": title} for code, title, _words in GOALS]


def _amount_choices(spec: dict) -> list[dict]:
    return [{"id": str(step), "label": f"{rub(step)} ₽"} for step in spec["limit_steps"]]


def _term_choices(spec: dict) -> list[dict]:
    middle = (spec["min_term_months"] + spec["max_term_months"]) // 2
    values: list[int] = []
    for value in (spec["min_term_months"], middle, spec["max_term_months"]):
        if value not in values:
            values.append(value)
    return [{"id": str(value), "label": f"{value} мес."} for value in values]


def _range_issue(goal: str, amount: Optional[int], term: Optional[int]) -> Optional[str]:
    spec = _spec(goal)
    if spec is None:
        return None
    if amount is not None and not spec["min_amount_rub"] <= amount <= spec["max_amount_rub"]:
        return "amount"
    if term is not None and not spec["min_term_months"] <= term <= spec["max_term_months"]:
        return "term"
    return None


def _needs(goal: Optional[str], field: str) -> bool:
    spec = _spec(goal)
    return bool(spec and field in spec["fields"])


def _plan_ok(text: Optional[str]) -> bool:
    return flow_from_plan(text) is not None


def _sms_ok(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.lower())
    return compact in {SMS_CODE, f"код{SMS_CODE}"}


def _phone_choices() -> list[dict]:
    return [{"id": item["phone"], "label": item["full_name"]} for item in public_profiles()]


def _offer_facts(spec: dict, amount: int, term: int, say: str) -> dict:
    return {
        "say": say,
        "product_title": spec["title"],
        "annual_rate_pct": spec["annual_rate_pct"],
        "amount_rub": amount,
        "term_months": term,
        "min_amount_rub": spec["min_amount_rub"],
        "max_amount_rub": spec["max_amount_rub"],
        "min_term_months": spec["min_term_months"],
        "max_term_months": spec["max_term_months"],
    }


def _capture_purpose(goal: Optional[str], purpose: Optional[str], message: str) -> Optional[str]:
    if purpose or not _needs(goal, "purpose") or not goal:
        return purpose
    codes = {code for code, _title, _words in GOALS}
    if message and parse_goal(message) == goal and message.lower().strip() not in codes:
        return message.strip()[:300]
    return _goal_title(goal)


def _brief(
    goal: Optional[str],
    amount: Optional[int],
    term: Optional[int],
    purpose: Optional[str],
    profit: Optional[int],
    plan: Optional[str],
    phone: Optional[str],
    problem: Optional[str],
) -> tuple[dict, list[dict]]:
    spec = _spec(goal)
    if problem == "amount" and spec is not None:
        return {
            "say": "amount_out_of_range",
            "product_title": spec["title"],
            "min_amount_rub": spec["min_amount_rub"],
            "max_amount_rub": spec["max_amount_rub"],
        }, _amount_choices(spec)
    if problem == "term" and spec is not None:
        return {
            "say": "term_out_of_range",
            "product_title": spec["title"],
            "min_term_months": spec["min_term_months"],
            "max_term_months": spec["max_term_months"],
        }, _term_choices(spec)
    if goal is None or spec is None:
        say = "unparsed" if problem == "unparsed" else "ask_goal"
        return {"say": say}, _goal_choices()
    if amount is None:
        return {
            "say": "ask_amount",
            "need": _goal_title(goal),
            "product_title": spec["title"],
            "annual_rate_pct": spec["annual_rate_pct"],
            "min_amount_rub": spec["min_amount_rub"],
            "max_amount_rub": spec["max_amount_rub"],
        }, _amount_choices(spec)
    if term is None:
        return {
            "say": "ask_term",
            "product_title": spec["title"],
            "amount_rub": amount,
            "min_term_months": spec["min_term_months"],
            "max_term_months": spec["max_term_months"],
        }, _term_choices(spec)
    if _needs(goal, "purpose") and not purpose:
        return {
            "say": "ask_purpose",
            "product_title": spec["title"],
        }, []
    if _needs(goal, "profitability_rub") and profit is None:
        return _offer_facts(spec, amount, term, "ask_profit"), []
    if _needs(goal, "business_plan") and not _plan_ok(plan):
        facts = _offer_facts(spec, amount, term, "ask_plan")
        facts["example_revenue_rub"] = 180_000
        return facts, []
    if phone is None:
        say = "phone_unknown" if problem == "phone" else "ask_phone"
        return {"say": say, "product_title": spec["title"]}, _phone_choices()
    say = "sms_rejected" if problem == "sms" else "ask_sms"
    return {"say": say, "product_title": spec["title"], "sms_code": 0}, [{"id": SMS_CODE, "label": SMS_CODE}]


def decide(
    goal: Optional[str],
    amount_rub: Optional[int],
    term_months: Optional[int],
    text: str,
    purpose: Optional[str] = None,
    profitability_rub: Optional[int] = None,
    business_plan: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    goal = goal if _spec(goal) else None
    amount = amount_rub
    term = term_months
    purpose = (purpose or "").strip() or None
    profit = profitability_rub
    plan = (business_plan or "").strip() or None
    phone = phone if phone in DEMO_PHONES else None
    message = text.strip()
    problem = None
    aside = None
    filing = False

    if message:
        if goal is None:
            parsed = parse_goal(message)
            if parsed is None:
                problem = "unparsed"
            else:
                goal = parsed
        elif amount is None:
            parsed_amount = parse_amount(message)
            if parsed_amount is None:
                problem = "unparsed"
            else:
                amount = parsed_amount
        elif term is None:
            parsed_term = parse_term(message)
            if parsed_term is None:
                problem = "unparsed"
            else:
                term = parsed_term
        elif _needs(goal, "profitability_rub") and profit is None:
            parsed_profit = parse_amount(message)
            if parsed_profit is None or parsed_profit <= 0:
                problem = "unparsed"
            else:
                profit = parsed_profit
        elif _needs(goal, "business_plan") and not _plan_ok(plan):
            if _plan_ok(message):
                plan = message[:500]
            else:
                problem = "unparsed"
        elif phone is None:
            parsed_phone = parse_phone(message)
            if parsed_phone is None:
                problem = "unparsed"
            elif parsed_phone not in DEMO_PHONES:
                problem = "phone"
            else:
                phone = parsed_phone
        elif _sms_ok(message):
            filing = True
        elif wants_application(message):
            problem = "chatter"
            aside = "Оформляем."
        else:
            problem = "sms"
        if problem == "unparsed":
            if wants_application(message):
                problem = "chatter"
                aside = "Оформляем."
            else:
                line = chatter_line(message)
                if line:
                    problem = "chatter"
                    aside = line

    purpose = _capture_purpose(goal, purpose, message)
    issue = _range_issue(goal, amount, term) if goal and problem is None else None
    if issue == "amount":
        amount = None
        problem = "amount"
        filing = False
    elif issue == "term":
        term = None
        problem = "term"
        filing = False

    if filing and _spec(goal) is not None and amount is not None and term is not None:
        brief = _offer_facts(_spec(goal), amount, term, "filed")
        choices: list[dict] = []
        done = True
    else:
        filing = False
        brief, choices = _brief(goal, amount, term, purpose, profit, plan, phone, problem)
        done = False
    if aside:
        brief = {**brief, "aside": aside}
    ready = _spec(goal) is not None and amount is not None and term is not None and problem not in {"amount", "term"}
    payload = {
        "answers": {
            "goal": goal,
            "amount_rub": amount,
            "term_months": term,
            "purpose": purpose,
            "profitability_rub": profit,
            "business_plan": plan,
            "phone": phone,
        },
        "brief": brief,
        "choices": choices,
        "product": public_product(_spec(goal)) if ready and _spec(goal) else None,
        "done": done,
    }
    if filing and phone and goal and amount is not None and term is not None:
        payload["file"] = {
            "product": goal,
            "loan_amount_rub": amount,
            "loan_term_months": term,
            "phone": phone,
            "purpose": purpose or "",
            "profitability_rub": profit,
            "business_plan": plan or "",
        }
    return payload


def template_reply(brief: dict) -> str:
    kind = brief.get("say")
    if kind == "ask_profit":
        body = (
            f"«{brief['product_title']}» подходит: ставка {brief['annual_rate_pct']}%, "
            f"сумма {rub(brief['amount_rub'])} ₽ на {brief['term_months']} месяцев. "
            "Какая выручка в месяц?"
        )
    elif kind == "ask_plan":
        body = (
            f"«{brief['product_title']}» подходит: ставка {brief['annual_rate_pct']}%, "
            f"сумма {rub(brief['amount_rub'])} ₽ на {brief['term_months']} месяцев. "
            f"Какой запуск планируете? Напишите выручку числом, например {brief['example_revenue_rub']}."
        )
    elif kind == "ask_purpose":
        body = f"Какая цель кредита на «{brief['product_title']}», своими словами?"
    elif kind == "ask_phone":
        body = f"«{brief['product_title']}» можно оформлять. Какой номер записать? Подойдёт только готовый профиль."
    elif kind == "phone_unknown":
        body = "Номер не найден. Какой номер записать?"
    elif kind == "ask_sms":
        body = "Номер записал. СМС не отправляем. Какой код пришёл? Для демо напишите 0000."
    elif kind == "sms_rejected":
        body = "Код не совпал. Какой код пришёл? Для демо напишите 0000."
    elif kind == "filed":
        body = (
            f"Заявка записана на этот номер. «{brief['product_title']}»: "
            f"ставка {brief['annual_rate_pct']}%, сумма {rub(brief['amount_rub'])} ₽ "
            f"на {brief['term_months']} месяцев."
        )
    elif kind == "ask_amount":
        body = (
            f"Для «{brief['product_title']}» сумма от {rub(brief['min_amount_rub'])} "
            f"до {rub(brief['max_amount_rub'])} ₽, ставка {brief['annual_rate_pct']}%. "
            "Какая сумма нужна?"
        )
    elif kind == "ask_term":
        body = (
            f"Сумма {rub(brief['amount_rub'])} ₽. "
            f"Срок для «{brief['product_title']}» — от {brief['min_term_months']} "
            f"до {brief['max_term_months']} месяцев. На какой срок?"
        )
    elif kind == "amount_out_of_range":
        body = (
            f"Для «{brief['product_title']}» сумма от {rub(brief['min_amount_rub'])} "
            f"до {rub(brief['max_amount_rub'])} ₽. Назовите сумму внутри этой вилки."
        )
    elif kind == "term_out_of_range":
        body = (
            f"Для «{brief['product_title']}» срок от {brief['min_term_months']} "
            f"до {brief['max_term_months']} месяцев. Назовите срок внутри этой вилки."
        )
    elif kind == "offer":
        body = (
            f"Подходит «{brief['product_title']}»: ставка {brief['annual_rate_pct']}%, "
            f"сумма {rub(brief['amount_rub'])} ₽ на {brief['term_months']} месяцев. "
            f"По продукту можно от {rub(brief['min_amount_rub'])} до {rub(brief['max_amount_rub'])} ₽ "
            f"и от {brief['min_term_months']} до {brief['max_term_months']} месяцев."
        )
    elif kind == "unparsed":
        body = "Не уловил задачу. Выберите, на что нужны деньги, или напишите своими словами."
    else:
        body = "На что нужны деньги? Можно выбрать вариант ниже или написать своими словами."
    aside = brief.get("aside")
    if isinstance(aside, str) and aside.strip():
        return f"{aside.strip()} {body}"
    return body


def speak(brief: dict) -> tuple[str, str]:
    fallback = template_reply(brief)
    url = settings.advisor_llm_url
    if not url:
        return fallback, "formula"
    payload = json.dumps({"brief": brief, "draft": fallback}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        global _voice_warned
        if not _voice_warned:
            _voice_warned = True
            logger.warning("advisor voice unavailable")
        return fallback, "formula"
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not reply_uses_only_brief_numbers(text, brief):
        return fallback, "formula"
    cleaned = text.strip()
    if len(cleaned) < 20 or not keeps_the_question(fallback, cleaned):
        return fallback, "formula"
    return cleaned, "qwen"


def wants_application(text: str) -> bool:
    raw = text.lower().replace("ё", "е")
    if any(part in raw for part in ("оформл", "заявк", "анкет")):
        return True
    if "от меня" in raw and any(part in raw for part in ("что", "нужн", "требу", "надо")):
        return True
    return any(part in raw for part in ("давай дальше", "давайте дальше", "продолжим", "продолжаем", "заполня"))


def looks_like_question(text: str) -> bool:
    raw = text.lower().replace("ё", "е")
    if "?" in raw:
        return True
    markers = (
        "какая", "какой", "какие", "какое", "сколько", "зачем", "почему",
        "можно ли", "нужен ли", "нужна ли", "нужно ли", "есть ли",
        "что такое", "чем отлич", "расскажи", "поясни", "подскажи",
    )
    return any(marker in raw for marker in markers)


def is_bare_slot(text: str) -> bool:
    if parse_phone(text) or _sms_ok(text):
        return True
    if parse_amount(text) and re.search(r"[а-яё]", text.lower()) is None:
        return True
    if (
        parse_term(text)
        and len(text) <= 16
        and not any(word in text.lower() for word in ("кака", "сколько", "почему", "зачем", "можно"))
    ):
        return True
    return False


def answer_url() -> str:
    url = settings.advisor_llm_url.rstrip("/")
    if not url:
        return ""
    base, _slash, _leaf = url.rpartition("/")
    if not base:
        return ""
    return base + "/answer"


def recent_dialogue(history: Optional[list]) -> list[dict]:
    if not isinstance(history, list):
        return []
    turns = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text")
        if role not in ("user", "assistant") or not isinstance(text, str):
            continue
        cleaned = text.strip()[:300]
        if cleaned:
            turns.append({"role": role, "text": cleaned})
    return turns


def lookup_product_answer(question: str, history: Optional[list] = None) -> Optional[dict]:
    url = answer_url()
    if not url:
        return None
    payload = json.dumps(
        {"question": question, "history": recent_dialogue(history)},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        global _voice_warned
        if not _voice_warned:
            _voice_warned = True
            logger.warning("advisor voice unavailable")
        return None
    return body if isinstance(body, dict) else None


def advise(
    goal: Optional[str],
    amount_rub: Optional[int],
    term_months: Optional[int],
    text: str,
    purpose: Optional[str] = None,
    profitability_rub: Optional[int] = None,
    business_plan: Optional[str] = None,
    phone: Optional[str] = None,
    history: Optional[list] = None,
) -> dict:
    if looks_like_question(text) and not is_bare_slot(text) and not wants_application(text):
        decision = decide(
            goal,
            amount_rub,
            term_months,
            "",
            purpose,
            profitability_rub,
            business_plan,
            phone,
        )
        looked = lookup_product_answer(text, history)
        status = looked.get("status") if isinstance(looked, dict) else None
        answer = looked.get("text") if isinstance(looked, dict) else None
        if status == "answer" and isinstance(answer, str) and answer.strip():
            voice = "qwen" if looked.get("from") == "model" else "formula"
            reply = answer.strip()
        else:
            reply, voice = UNKNOWN_QUESTION, "formula"
        return {**decision, "reply": reply, "voice": voice}
    decision = decide(
        goal,
        amount_rub,
        term_months,
        text,
        purpose,
        profitability_rub,
        business_plan,
        phone,
    )
    reply, voice = speak(decision["brief"])
    return {**decision, "reply": reply, "voice": voice}
