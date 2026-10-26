from decimal import Decimal, ROUND_HALF_UP

ANNUAL_RATE = Decimal("0.20")  # запасная ставка, если у продукта своей нет
MONTHS_IN_YEAR = Decimal("12")


def calculate_annuity_payment(
    amount_rub: int,
    term_months: int,
    annual_rate: Decimal = ANNUAL_RATE,
) -> int:
    """
    Считает ежемесячный аннуитетный платеж по формуле:
    A = S * (i * (1 + i)^n) / ((1 + i)^n - 1)
    Округление половины вверх (ROUND_HALF_UP) до целого рубля.
    """
    if amount_rub <= 0 or term_months <= 0:
        return 0

    s = Decimal(str(amount_rub))
    n = Decimal(str(term_months))
    i = annual_rate / MONTHS_IN_YEAR

    # (1 + i)^n
    compound_interest = (Decimal("1") + i) ** n

    # K = (i * compound_interest) / (compound_interest - 1)
    k = (i * compound_interest) / (compound_interest - Decimal("1"))

    # A = S * K
    payment = s * k

    # Округление половины вверх до целого рубля
    return int(payment.quantize(Decimal("1"), rounding=ROUND_HALF_UP))