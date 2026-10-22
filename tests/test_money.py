"""Tests for money quantization, Decimal formatting, and ExchangeRateResolver."""

from datetime import date
from decimal import Decimal

import pytest

from orcha.models import ExchangeRate
from orcha.money import (
    ExchangeRateNotFoundError,
    ExchangeRateResolver,
    format_money,
    quantize_money,
)


def test_quantize_money() -> None:
    amt = Decimal("123.4567")
    q = quantize_money(amt, places=2)
    assert q == Decimal("123.46")

    amt_int = Decimal("100")
    q_int = quantize_money(amt_int, places=2)
    assert q_int == Decimal("100.00")


def test_format_money() -> None:
    assert format_money(None) == "none"
    assert format_money(Decimal("100")) == "100"
    assert format_money(Decimal("100.50"), "USD") == "USD 100.5"
    assert format_money(Decimal("15952906.67"), "IDR") == "IDR 15952906.67"


def test_fx_resolver_identity() -> None:
    resolver = ExchangeRateResolver()
    assert resolver.get_rate("USD", "USD", date(2024, 1, 1)) == Decimal("1")
    assert resolver.convert(Decimal("500"), "EUR", "EUR", date(2024, 1, 1)) == Decimal("500")


def test_fx_resolver_known_conversion() -> None:
    rate = ExchangeRate(
        rate_date=date(2023, 10, 15),
        from_currency="EUR",
        to_currency="ZAR",
        rate=Decimal("20.00"),
    )
    resolver = ExchangeRateResolver([rate])
    converted = resolver.convert(Decimal("50.00"), "EUR", "ZAR", date(2023, 10, 15))
    assert converted == Decimal("1000.00")
    assert isinstance(converted, Decimal)


def test_fx_resolver_direction_and_missing() -> None:
    rate = ExchangeRate(
        rate_date=date(2023, 10, 15),
        from_currency="EUR",
        to_currency="ZAR",
        rate=Decimal("20.00"),
    )
    resolver = ExchangeRateResolver([rate], allow_inverse=False)

    # Inverted direction should fail when allow_inverse=False
    with pytest.raises(ExchangeRateNotFoundError, match="No exchange rate found"):
        resolver.get_rate("ZAR", "EUR", date(2023, 10, 15))

    # Missing date should fail
    with pytest.raises(ExchangeRateNotFoundError, match="No exchange rate found"):
        resolver.get_rate("EUR", "ZAR", date(2024, 1, 1))


def test_fx_resolver_inverse_allowed() -> None:
    rate = ExchangeRate(
        rate_date=date(2023, 10, 15),
        from_currency="EUR",
        to_currency="ZAR",
        rate=Decimal("20.00"),
    )
    resolver = ExchangeRateResolver([rate], allow_inverse=True)
    inv_rate = resolver.get_rate("ZAR", "EUR", date(2023, 10, 15))
    assert inv_rate == Decimal("1") / Decimal("20.00")
    converted = resolver.convert(Decimal("1000"), "ZAR", "EUR", date(2023, 10, 15))
    assert converted == Decimal("50")
