"""Comparators, unit conversion and date helpers."""

from datetime import date

import pytest

from app.engine.comparators import compare, describe
from app.engine.dates import age_on, is_stale, parse_date, within_days
from app.engine.units import UnitConversionError, convert, normalize_unit, to_canonical
from app.schemas.clinical import NormalizedRule


def rule(**kw) -> NormalizedRule:
    return NormalizedRule(**kw)


@pytest.mark.parametrize("value,expected", [
    (17, False), (18, True), (69, True), (70, True), (70.5, False), (71, False),
])
def test_age_between_inclusive_boundaries(value, expected):
    r = rule(attribute="age", operator="between", value=18, value_max=70, unit="years", inclusive=True)
    assert compare(value, r) is expected


def test_between_exclusive_and_unstated_boundaries():
    exclusive = rule(attribute="age", operator="between", value=18, value_max=70, inclusive=False)
    assert compare(70, exclusive) is False
    unstated = rule(attribute="age", operator="between", value=18, value_max=70, inclusive=None)
    assert compare(70, unstated) is None  # boundary with unknown inclusivity is undecidable
    assert compare(50, unstated) is True


@pytest.mark.parametrize("value,expected", [(29.9, False), (30, True), (30.1, True), (28, False)])
def test_egfr_not_below_30(value, expected):
    assert compare(value, rule(attribute="egfr", operator="gte", value=30, unit="mL/min/1.73m2")) is expected


def test_other_operators():
    assert compare(29, rule(attribute="egfr", operator="lt", value=30)) is True
    assert compare(30, rule(attribute="egfr", operator="lt", value=30)) is False
    assert compare(3, rule(attribute="bilirubin", operator="lte", value=3)) is True
    assert compare(3.01, rule(attribute="bilirubin", operator="gt", value=3)) is True
    assert compare(5, rule(attribute="hba1c", operator="eq", value=5)) is True


def test_describe():
    egfr_rule = rule(attribute="egfr", operator="gte", value=30, unit="mL/min/1.73m2")
    assert describe(egfr_rule) == "eGFR >= 30 mL/min/1.73m2"
    assert "inclusive" in describe(rule(attribute="age", operator="between", value=18, value_max=70, inclusive=True))


def test_rule_shape_validation():
    with pytest.raises(ValueError):
        NormalizedRule(attribute="egfr", operator="gte", value="thirty")
    with pytest.raises(ValueError):
        NormalizedRule(attribute="age", operator="between", value=18)


def test_creatinine_umol_to_mg_dl():
    assert convert("creatinine", 88.4, "µmol/L", "mg/dL") == pytest.approx(1.0)
    assert convert("creatinine", 176.8, "umol/l", "mg/dL") == pytest.approx(2.0)
    value, unit = to_canonical("creatinine", 132.6, "μmol/L")
    assert value == pytest.approx(1.5) and unit == "mg/dL"


def test_unit_normalization_and_refusal():
    assert normalize_unit("mL/min/1.73 m²") == "mL/min/1.73m2"
    assert normalize_unit("ML/MIN/1.73M2") == "mL/min/1.73m2"
    with pytest.raises(UnitConversionError):
        convert("egfr", 30, "mg/dL", "mL/min/1.73m2")  # no validated conversion exists
    with pytest.raises(UnitConversionError):
        to_canonical("egfr", 30, None)  # never assume a unit


def test_dates():
    assert parse_date("2026-09-25") == date(2026, 9, 25)
    assert age_on(date(1957, 10, 2), date(2026, 10, 1)) == 68
    assert age_on(date(1957, 10, 1), date(2026, 10, 1)) == 69
    assert is_stale(date(2026, 6, 1), date(2026, 10, 1), 90) is True
    assert is_stale(date(2026, 9, 1), date(2026, 10, 1), 90) is False
    assert within_days(date(2026, 9, 20), date(2026, 10, 1), 14) is True
    assert within_days(date(2026, 8, 1), date(2026, 10, 1), 14) is False
    assert within_days(None, date(2026, 10, 1), 14) is None
