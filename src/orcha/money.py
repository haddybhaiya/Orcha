"""Money, currency formatting, and deterministic exchange rate resolver."""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from orcha.models import ExchangeRate


class ExchangeRateError(Exception):
    """Base exception for exchange rate resolution errors."""


class ExchangeRateNotFoundError(ExchangeRateError):
    """Raised when an exchange rate is not available for a given currency pair and date."""


def quantize_money(amount: Decimal, places: int = 2) -> Decimal:
    """Quantize Decimal to a fixed number of decimal places using ROUND_HALF_UP.

    Preserves exact value without floating-point conversion.
    """
    exp = Decimal("10") ** -places
    return amount.quantize(exp, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal | None, currency: str | None = None) -> str:
    """Format Decimal cleanly without trailing zeros if integer, or with exact representation."""
    if amount is None:
        return "none"
    amt_str = f"{amount:f}".rstrip("0").rstrip(".") if "." in f"{amount:f}" else f"{amount:f}"
    if currency:
        return f"{currency} {amt_str}"
    return amt_str


class ExchangeRateResolver:
    """Deterministic resolver for dated currency exchange rates using exchange_rates.csv.

    Rules:
    1. same currency -> identity (rate = Decimal("1"))
    2. exact supplied pair/date -> use supplied rate (target = amount * rate)
    3. respect direction strictly (from_currency -> to_currency)
    4. if allow_inverse is True, allows inverted lookup (target = amount / inverse_rate)
    5. zero network calls, zero external API queries
    6. missing required conversion raises ExchangeRateNotFoundError
    """

    def __init__(
        self,
        rates: Sequence[ExchangeRate] | None = None,
        allow_inverse: bool = False,
    ) -> None:
        self.allow_inverse = allow_inverse
        self._rates: dict[tuple[date, str, str], Decimal] = {}
        self._pairs: set[tuple[str, str]] = set()
        self._dates: set[date] = set()

        if rates:
            for r in rates:
                self.add_rate(r)

    def add_rate(self, rate: ExchangeRate) -> None:
        """Register a single exchange rate."""
        key = (rate.rate_date, rate.from_currency, rate.to_currency)
        self._rates[key] = rate.rate
        self._pairs.add((rate.from_currency, rate.to_currency))
        self._dates.add(rate.rate_date)

    @property
    def supported_pairs(self) -> set[tuple[str, str]]:
        return set(self._pairs)

    @property
    def supported_dates(self) -> set[date]:
        return set(self._dates)

    def has_rate(self, from_currency: str, to_currency: str, rate_date: date) -> bool:
        """Check whether a rate is available for the given pair and date."""
        if from_currency == to_currency:
            return True
        key = (rate_date, from_currency, to_currency)
        if key in self._rates:
            return True
        if self.allow_inverse:
            inv_key = (rate_date, to_currency, from_currency)
            return inv_key in self._rates
        return False

    def get_rate(self, from_currency: str, to_currency: str, rate_date: date) -> Decimal:
        """Retrieve the conversion rate multiplier for from_currency -> to_currency on rate_date."""
        if from_currency == to_currency:
            return Decimal("1")

        key = (rate_date, from_currency, to_currency)
        if key in self._rates:
            return self._rates[key]

        if self.allow_inverse:
            inv_key = (rate_date, to_currency, from_currency)
            if inv_key in self._rates:
                inv_rate = self._rates[inv_key]
                if inv_rate == Decimal("0"):
                    raise ExchangeRateError(
                        f"Inverse rate is zero for {to_currency}->{from_currency} on {rate_date}"
                    )
                return Decimal("1") / inv_rate

        raise ExchangeRateNotFoundError(
            f"No exchange rate found for {from_currency} -> {to_currency} on {rate_date}"
        )

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        rate_date: date,
    ) -> Decimal:
        """Convert amount using exact Decimal multiplication."""
        if from_currency == to_currency:
            return amount

        rate = self.get_rate(from_currency, to_currency, rate_date)
        return amount * rate
