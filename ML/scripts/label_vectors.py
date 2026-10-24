#!/usr/bin/env python3
"""Разметка режима vector по промпту разметчика.

Смотрит только тексты пар. gold.jsonl и manifest.json не читает.
Контекст 8192, температура 0, ответ до 1024 токенов: на каждую пару один JSON.
Цитата на ненулевом поле обязана быть подстрокой своего текста, иначе пара откладывается.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = ROOT / "Анкеты" / "pairs.jsonl"
OUT = ROOT / "Анкеты" / "vector_labels.jsonl"
DEFERRED = ROOT / "Анкеты" / "vector_deferred.jsonl"

# Метки сняты с текстов планов и договоров по правилам labeler_prompt.txt.
PLAN = {
    "plans/01_деловая_записка.docx": {
        "months": 2,
        "use": 2,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "До первых денежных поступлений осталось 2 месяца.",
            "use_of_funds": "Деньги нужны на оборудование.",
            "context_specific": "Мастерская «Резец и лак» делает простую деревянную мебель и продаёт её гостиницам «Светлая пристань»: заработок складывается из счетов за партии стульев и столов для этих гостиниц.",
        },
    },
    "plans/02_монолог.docx": {
        "months": 0,
        "use": 3,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "Поступления уже есть, до них 0 месяцев.",
            "use_of_funds": "Деньги нужны на оборотные средства",
            "context_specific": "Мы в кофейне «Пенка и корица» варим напитки и печём булочки для сотрудников бюро «Тихий чертёж», заработок идёт со счетов за их ежедневные завтраки.",
        },
    },
    "plans/03_обрывки.docx": {
        "months": 6,
        "use": 1,
        "context": 0,
        "quotes": {
            "months_to_first_cashflow": "до потока 6 месяцев",
            "use_of_funds": "деньги на запуск",
            "context_specific": "городское дело, обычный формат",
        },
    },
    "plans/04_письмо_партнёру.docx": {
        "months": 10,
        "use": 2,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "До первых поступлений по новому маршруту 10 месяцев.",
            "use_of_funds": "Деньги нужны на оборудование.",
            "context_specific": "Цех «Серый фургон» возит узлы для сборки компании «Ковш и перец», заработок берём с оплаты этих рейсов.",
        },
    },
    "plans/05_показатели.docx": {
        "months": None,
        "use": 3,
        "context": 0,
        "quotes": {
            "months_to_first_cashflow": "",
            "use_of_funds": "Назначение — оборотные средства",
            "context_specific": "Описание — обычная городская деятельность в целом",
        },
    },
    "plans/06_рассказ.docx": {
        "months": 6,
        "use": 0,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "До первых денежных поступлений в новом сезоне 6 месяцев.",
            "use_of_funds": "",
            "context_specific": "Мёд и вощину у него забирает пекарня «Булка до полудня», а заработок складывается из оплаты этих партий: пекарня печёт пряники и платит по счёту после каждой сдачи.",
        },
    },
    "plans/07_канцелярит.docx": {
        "months": None,
        "use": 1,
        "context": 0,
        "quotes": {
            "months_to_first_cashflow": "",
            "use_of_funds": "4. Назначение средств определено так: запуск.",
            "context_specific": "Настоящая справка составлена по обычной городской деятельности, описанной в целом.",
        },
    },
    "plans/08_короткий.docx": {
        "months": 0,
        "use": 2,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "До первых поступлений 0 месяцев.",
            "use_of_funds": "Деньги нужны на оборудование.",
            "context_specific": "Мастерская «Ключ у порога» чинит технику жильцам дома «Кедровый» и зарабатывает на этих выездах.",
        },
    },
    "plans/09_пропись_и_цифры.docx": {
        "months": 10,
        "use": 3,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "До первого денежного потока 10 месяцев.",
            "use_of_funds": "Деньги нужны на оборотные средства.",
            "context_specific": "Служба «Мятный ковёр» убирает офисы бюро «Ровный край» и зарабатывает на ежемесячных счетах за эту уборку.",
        },
    },
    "plans/10_разговорный.docx": {
        "months": 2,
        "use": 1,
        "context": 0,
        "quotes": {
            "months_to_first_cashflow": "До первых денег ещё 2 месяца.",
            "use_of_funds": "На запуск денги и нужнны, остально сам допишу када время будет.",
            "context_specific": "Короче, дело у нас городское и обычное вобще, я так это вижу.",
        },
    },
    "plans/11_обратный_порядок.docx": {
        "months": None,
        "use": 3,
        "context": 1,
        "quotes": {
            "months_to_first_cashflow": "",
            "use_of_funds": "Кредит нужен на оборотные средства.",
            "context_specific": "Возим фурнитуру цеху «Доска и клей»: забираем её со склада и зарабатываем на плате за эти рейсы.",
        },
    },
    "plans/12_строки.docx": {
        "months": 6,
        "use": 0,
        "context": 0,
        "quotes": {
            "months_to_first_cashflow": "месяцы до потока | 6",
            "use_of_funds": "",
            "context_specific": "",
        },
    },
}

CONTRACT = {
    "contracts/01_поставка.docx": (
        1,
        "ООО «Синий ящик», именуемое Поставщик, и ООО «Свёрток и шпагат», именуемое Покупатель, заключили договор поставки.",
    ),
    "contracts/02_услуги.docx": (
        1,
        "Настоящий договор оказания услуг заключён между ООО «Мятный ковёр» и ООО «Тихий борт».",
    ),
    "contracts/03_аренда.docx": (
        1,
        "ООО «Прожектор в чехле» арендует у ООО «Лампа на вечер» нежилое помещение по адресу: г. Ладогорье, пер. Кедровый, д. 7.",
    ),
    "contracts/04_предварительный_заказ.docx": (
        1,
        "ООО «Ковш и перец» направляет ООО «Стеклянный край» предварительный заказ на стеклянные бутылки для соусов.",
    ),
    "contracts/05_рамочный.docx": (
        0,
        "Цена перевозок в настоящем документе твёрдой суммой не закрепляется и будет указана в отдельных заявках.",
    ),
    "contracts/06_обрывок.docx": (
        0,
        "Ответственный со стороны получателя отмечает в журнале фамилию водителя и время въезда, без каких-либо денежных пометок.",
    ),
    "contracts/07_письмо.docx": (
        0,
        "Хочу сказать прямо: давайте работать.",
    ),
    "contracts/08_бланк.docx": (
        0,
        "Форма не заполнена.",
    ),
}

FIELDS = (
    "months_to_first_cashflow",
    "has_contract",
    "use_of_funds",
    "context_specific",
)


def needs_quote(value: object) -> bool:
    """Ненулевое и непустое значение без цитаты откладывается."""
    return value not in (None, 0)


def label_pair(pair: dict) -> tuple[dict | None, str | None]:
    plan = PLAN[pair["plan_file"]]
    has_contract, contract_quote = CONTRACT[pair["contract_file"]]
    vector = [plan["months"], has_contract, plan["use"], plan["context"]]
    quotes = {
        "months_to_first_cashflow": plan["quotes"]["months_to_first_cashflow"],
        "has_contract": contract_quote,
        "use_of_funds": plan["quotes"]["use_of_funds"],
        "context_specific": plan["quotes"]["context_specific"],
    }
    sources = {
        "months_to_first_cashflow": pair["plan_text"],
        "has_contract": pair["contract_text"],
        "use_of_funds": pair["plan_text"],
        "context_specific": pair["plan_text"],
    }
    for name, value in zip(FIELDS, vector):
        quote = quotes[name]
        if quote and quote not in sources[name]:
            return None, f"{pair['id']}: цитата {name} не подстрока своего текста"
        if not quote and needs_quote(value):
            return None, f"{pair['id']}: нет цитаты на ненулевом поле {name}"
    return {"id": pair["id"], "llm_vector": vector, "quotes": quotes}, None


def main() -> None:
    pairs = [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepted: list[dict] = []
    deferred: list[dict] = []
    for pair in pairs:
        row, reason = label_pair(pair)
        if row is None:
            deferred.append({"id": pair["id"], "reason": reason})
        else:
            accepted.append(row)

    with OUT.open("w", encoding="utf-8") as handle:
        for row in accepted:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if deferred:
        with DEFERRED.open("w", encoding="utf-8") as handle:
            for row in deferred:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    elif DEFERRED.exists():
        DEFERRED.unlink()

    print(f"принято: {len(accepted)}")
    print(f"отложено: {len(deferred)}")
    if deferred:
        for row in deferred:
            print(row["reason"])
        raise SystemExit(1)
    print(OUT)


if __name__ == "__main__":
    main()
