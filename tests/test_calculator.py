"""Phase 3 calculator tests: exact numbers, no LLM, no network."""
import pytest
from fastapi.testclient import TestClient

from app.calculator import (
    CostItem,
    FinancialInput,
    break_even,
    budget_summary,
    compliance_flags,
    full_financials,
    monthly_scenarios,
    payback_months,
    suggest_price,
    unit_economics,
)
from app.main import app

client = TestClient(app)


# ---------- Healthy-meal example from our report ----------

def test_unit_economics_healthy_meal():
    u = unit_economics(unit_cost=100, selling_price=170)
    assert u.profit_per_unit == 70
    assert u.margin_percent == 41.2
    assert u.warnings == []


def test_break_even_healthy_meal():
    b = break_even(fixed_monthly_costs=3000, profit_per_unit=70)
    assert b.possible is True
    assert b.units_per_month == 43  # 3000 / 70 = 42.86 -> round up
    assert b.units_per_day == 2     # 43 / 26 = 1.65 -> round up


# ---------- Edge cases ----------

def test_price_below_cost_warns():
    u = unit_economics(unit_cost=100, selling_price=90)
    assert u.profit_per_unit == -10
    assert u.warnings and "lose money" in u.warnings[0]


def test_price_equal_to_cost_warns():
    assert unit_economics(100, 100).warnings


@pytest.mark.parametrize("profit", [0, -20])
def test_break_even_impossible_without_profit(profit):
    b = break_even(fixed_monthly_costs=3000, profit_per_unit=profit)
    assert b.possible is False
    assert b.units_per_month is None and b.units_per_day is None
    assert "not possible" in b.message


def test_break_even_zero_fixed_costs():
    b = break_even(0, 50)
    assert (b.units_per_month, b.units_per_day) == (0, 0)


def test_over_budget_warning():
    s = budget_summary(
        [CostItem(name="Cart", amount_inr=15000), CostItem(name="Stock", amount_inr=8000, kind="monthly")],
        budget_inr=20000,
    )
    assert s.one_time_total == 15000 and s.monthly_total == 8000
    assert s.startup_need == 23000
    assert s.remaining == -3000
    assert s.over_budget is True
    assert s.percent_used == 115.0
    assert "Over budget" in s.warnings[0]


def test_low_reserve_warning():
    s = budget_summary([CostItem(name="Stove", amount_inr=18500)], budget_inr=20000)
    assert s.remaining == 1500 and not s.over_budget
    assert "reserve" in s.warnings[0]


def test_healthy_budget_has_no_warnings():
    s = budget_summary([CostItem(name="Stove", amount_inr=5000)], budget_inr=20000)
    assert s.remaining == 15000 and s.percent_used == 25.0 and s.warnings == []


def test_payback():
    assert payback_months(30000, 10000) == 3.0
    assert payback_months(25000, 10000) == 2.5
    assert payback_months(30000, 0) is None
    assert payback_months(30000, -500) is None


# ---------- Price suggestion ----------

def test_suggest_price_rounds_to_nearest_5():
    p = suggest_price(100)  # 100 / 0.6 = 166.67 -> 165
    assert p.suggested_price == 165
    assert suggest_price(50, 50).suggested_price == 100   # exactly 100
    assert suggest_price(41, 20).suggested_price == 50    # 51.25 -> 50
    assert suggest_price(43, 20).suggested_price == 55    # 53.75 -> 55


def test_suggest_price_clamps_to_market():
    low = suggest_price(100, 40, market_low=180, market_high=250)
    assert low.suggested_price == 180 and "market low" in low.reason
    high = suggest_price(100, 40, market_low=100, market_high=150)
    assert high.suggested_price == 150 and "market high" in high.reason
    inside = suggest_price(100, 40, market_low=150, market_high=200)
    assert inside.suggested_price == 165


def test_suggest_price_warns_when_market_is_below_cost():
    p = suggest_price(100, 40, market_high=90)
    assert p.suggested_price == 90 and p.warnings


def test_suggest_price_rejects_bad_margin():
    with pytest.raises(ValueError):
        suggest_price(100, 100)


# ---------- Scenarios and compliance ----------

def test_monthly_scenarios():
    m = monthly_scenarios(100, 170, 3000, 5, 10, 15)
    low, expected, high = m.scenarios
    assert (low.units_per_month, low.revenue, low.total_cost, low.profit) == (130, 22100, 16000, 6100)
    assert (expected.revenue, expected.profit) == (44200, 15200)
    assert high.profit == 24300
    assert "ESTIMATES" in m.note


def test_compliance_small_food_business():
    flags = compliance_flags(500_000, is_food_business=True, is_service=False).flags
    assert any("not needed yet" in f for f in flags)
    assert any("FSSAI Registration" in f for f in flags)


def test_compliance_bigger_businesses():
    goods = compliance_flags(3_000_000, is_food_business=True, is_service=False).flags
    assert any("depends on which limit your State uses" in f for f in goods)
    assert any("FSSAI License" in f for f in goods)
    assert any("needed" in f for f in compliance_flags(5_000_000, False, False).flags)
    service = compliance_flags(2_500_000, is_food_business=False, is_service=True).flags
    assert any("GST registration is needed" in f for f in service)


# ---------- full_financials + endpoint ----------

MEAL_INPUT = {
    "budget_inr": 20000,
    "cost_items": [
        {"name": "Stove and utensils", "amount_inr": 6000, "kind": "one_time"},
        {"name": "Kitchen rent share", "amount_inr": 3000, "kind": "monthly"},
    ],
    "unit_cost": 100,
    "selling_price": 170,
    "units_per_day_low": 5,
    "units_per_day_expected": 10,
    "units_per_day_high": 15,
    "is_food_business": True,
}


def test_full_financials_healthy_meal():
    s = full_financials(FinancialInput(**MEAL_INPUT))
    assert s.unit.profit_per_unit == 70
    assert s.break_even.units_per_month == 43  # fixed costs taken from the monthly items (3000)
    assert s.payback_months == round(6000 / 15200, 1)
    assert s.compliance.annual_revenue_estimate == 44200 * 12
    assert "ESTIMATES" in s.disclaimer


def test_full_financials_uses_suggested_price_when_missing():
    data = {**MEAL_INPUT, "selling_price": None}
    s = full_financials(FinancialInput(**data))
    assert s.unit.selling_price == 165


def test_calculate_endpoint():
    r = client.post("/api/calculate", json=MEAL_INPUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unit"]["margin_percent"] == 41.2
    assert body["break_even"]["units_per_day"] == 2


def test_calculate_endpoint_validation():
    assert client.post("/api/calculate", json={**MEAL_INPUT, "budget_inr": 0}).status_code == 422
    bad_range = {**MEAL_INPUT, "market_low": 300, "market_high": 200}
    assert client.post("/api/calculate", json=bad_range).status_code == 400
