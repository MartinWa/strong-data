from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()

DASH = "—"


def _decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        return None


def _group(text):
    whole, _, fraction = text.partition(".")
    whole = f"{int(whole):,}"
    return f"{whole}.{fraction}" if fraction else whole


@register.filter
def num(value, decimals=None):
    number = _decimal(value)
    if number is None:
        return DASH
    if decimals is None:
        text = f"{number.normalize():f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    else:
        places = int(decimals)
        quantized = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        text = f"{quantized:f}"
    return _group(text)


@register.filter
def kg(value):
    if _decimal(value) is None:
        return DASH
    return f"{num(value)} kg"


@register.filter
def isodate(value, style="auto"):
    if not value:
        return DASH
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d" if style == "day" else "%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)
