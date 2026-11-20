import re
from datetime import date, datetime
from typing import Annotated
from urllib.parse import urlencode

from ninja.params.models import Query as QueryField
from ninja.params.models import QueryModel
from pydantic import BeforeValidator, ConfigDict

from .contract import MAX_LIMIT, MAX_RANGE_DAYS, ApiError

_INT_RE = re.compile(r"[+-]?\d+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _strict_int(value):
    if isinstance(value, bool):
        raise ValueError("must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_RE.fullmatch(value):
        return int(value)
    raise ValueError("must be an integer")


def _strict_bool(value):
    if isinstance(value, bool):
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("must be true or false")


def _strict_date(value):
    if isinstance(value, datetime):
        raise ValueError("must be a YYYY-MM-DD date")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_RE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("must be a YYYY-MM-DD date")


def _empty_to_none(value):
    if value == "":
        return None
    return value


IntParam = Annotated[int, BeforeValidator(_strict_int)]
OptIntParam = Annotated[int | None, BeforeValidator(_strict_int)]
BoolParam = Annotated[bool, BeforeValidator(_strict_bool)]
OptFilterParam = Annotated[str | None, BeforeValidator(_empty_to_none)]
OptBoolParam = Annotated[bool | None, BeforeValidator(_strict_bool)]
DateParam = Annotated[date, BeforeValidator(_strict_date)]
OptDateParam = Annotated[date | None, BeforeValidator(_strict_date)]


class StrictQueryModel(QueryModel):
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def get_request_data(cls, request, api, path_params):
        data = super().get_request_data(request, api, path_params)
        allowed = {field.alias or name for name, field in cls.model_fields.items()}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ApiError(
                422,
                "validation_error",
                "Unknown query parameter: " + ", ".join(unknown),
                details=unknown,
            )
        collection_fields = getattr(cls, "__ninja_collection_fields__", None) or []
        for key in data:
            if key not in collection_fields and len(request.GET.getlist(key)) > 1:
                raise ApiError(
                    422,
                    "validation_error",
                    "Repeated query parameter: " + key,
                    details=[key],
                )
        return data


class StrictQuery(QueryField):
    _model = StrictQueryModel

    @classmethod
    def _param_source(cls):
        return "query"


class NoQuery(StrictQueryModel):
    pass


MIN_YEAR = 2
MAX_YEAR = 9999
DEFAULT_CURVE_YEARS = 4
MAX_CURVE_YEARS = 10


def validate_year(year):
    if year < MIN_YEAR or year > MAX_YEAR:
        raise ApiError(422, "validation_error", f"year must be between {MIN_YEAR} and {MAX_YEAR}")


def validate_date_range(start, end):
    if start is None or end is None:
        return
    if start > end:
        raise ApiError(422, "validation_error", "start must be less than or equal to end")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ApiError(
            422,
            "validation_error",
            f"date range may not exceed {MAX_RANGE_DAYS} days",
        )


def validate_pagination(limit, offset):
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError(422, "validation_error", f"limit must be between 1 and {MAX_LIMIT}")
    if offset < 0:
        raise ApiError(422, "validation_error", "offset must be non-negative")


def sort_query(keys, default):
    allowed = ", ".join(sorted(keys))
    return StrictQuery(
        None,
        description=(
            "Sort key, optionally prefixed with '-' for descending order. "
            f"Allowed keys: {allowed}. Default: {default}. "
            "Ties are always broken by id ascending."
        ),
    )


def parse_sort(value, allowed, default):
    if value is None:
        return default, False
    descending = value.startswith("-")
    key = value[1:] if descending else value
    if key not in allowed:
        raise ApiError(422, "validation_error", f"Unsupported sort key: {key}")
    return key, descending


def build_page(request, items, count, limit, offset):
    has_more = offset + limit < count

    def continuation(new_offset):
        params = {key: request.GET.getlist(key) for key in request.GET}
        params.pop("offset", None)
        params.setdefault("limit", [str(limit)])
        params["offset"] = [str(new_offset)]
        return request.path + "?" + urlencode(params, doseq=True)

    return {
        "items": items,
        "count": count,
        "next": continuation(offset + limit) if has_more else None,
        "previous": continuation(max(0, offset - limit)) if offset > 0 else None,
        "has_more": has_more,
    }


def parse_curve_years(value, focus_year):
    if value is None:
        return [
            year
            for year in range(focus_year - DEFAULT_CURVE_YEARS + 1, focus_year + 1)
            if year >= MIN_YEAR
        ]
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(part == "" for part in parts):
        raise ApiError(422, "validation_error", "years must be a comma-separated list of years")
    years = []
    for part in parts:
        if not _INT_RE.fullmatch(part):
            raise ApiError(422, "validation_error", "years must be a comma-separated list of years")
        year = int(part)
        validate_year(year)
        if year > focus_year:
            raise ApiError(
                422,
                "validation_error",
                f"years may not be later than the compared year ({focus_year})",
            )
        if year not in years:
            years.append(year)
    if len(years) > MAX_CURVE_YEARS:
        raise ApiError(
            422,
            "validation_error",
            f"years may list at most {MAX_CURVE_YEARS} years",
            details=sorted(years),
        )
    return sorted(years)
