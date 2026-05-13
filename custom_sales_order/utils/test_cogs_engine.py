# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Unit tests for the pure-Python COGS engine.

Run with:  pytest custom_sales_order/utils/test_cogs_engine.py -v
"""

import pytest

from custom_sales_order.utils.cogs_engine import (
    calculate_cogs,
    describe_cogs_method,
    validate_costs,
)


# ---------------------------------------------------------------------------
# calculate_cogs — parametrized acceptance criteria
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "test_id, expected, actual, completed, expected_cogs",
    [
        ("AC-01", 10000, 8000, 0, 10000),
        ("AC-02", 8000, 12000, 0, 12000),
        ("AC-03", 10000, 9500, 1, 9500),
        ("AC-04", 10000, 0, 0, 10000),
        ("AC-05", 0, 0, 0, 0),
        ("AC-06", 10000, 0, 1, 0),
    ],
    ids=lambda val: val if isinstance(val, str) and val.startswith("AC") else "",
)
def test_calculate_cogs(test_id, expected, actual, completed, expected_cogs):
    """Verify COGS calculation against acceptance criteria table."""
    assert calculate_cogs(expected, actual, completed) == expected_cogs


# ---------------------------------------------------------------------------
# calculate_cogs — negative cost validation
# ---------------------------------------------------------------------------


def test_negative_expected_cost_raises():
    """Negative expected_cost must raise ValueError."""
    with pytest.raises(ValueError, match="Expected cost must be non-negative"):
        calculate_cogs(-100, 500, 0)


def test_negative_actual_cost_raises():
    """Negative actual_cost must raise ValueError."""
    with pytest.raises(ValueError, match="Actual cost must be non-negative"):
        calculate_cogs(500, -100, 0)


# ---------------------------------------------------------------------------
# validate_costs
# ---------------------------------------------------------------------------


def test_validate_costs_completed_zero_actual_warns():
    """Completed order with zero actual cost should return one warning."""
    result = validate_costs(10000, 0, 1)
    assert len(result) == 1
    assert result[0].startswith("WARNING")


def test_validate_costs_in_progress_no_warnings():
    """In-progress order with normal costs should return no warnings."""
    result = validate_costs(10000, 5000, 0)
    assert result == []


def test_validate_costs_negative_expected():
    """Negative expected cost should return an error string."""
    result = validate_costs(-100, 500, 0)
    assert len(result) >= 1
    assert any(msg.startswith("ERROR") for msg in result)


def test_validate_costs_negative_actual():
    """Negative actual cost should return an error string."""
    result = validate_costs(500, -100, 0)
    assert len(result) >= 1
    assert any(msg.startswith("ERROR") for msg in result)


def test_validate_costs_both_negative():
    """Both costs negative should return two error strings."""
    result = validate_costs(-100, -200, 0)
    assert len(result) == 2
    assert all(msg.startswith("ERROR") for msg in result)


# ---------------------------------------------------------------------------
# describe_cogs_method
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected, actual, completed",
    [
        (10000, 8000, 0),
        (8000, 12000, 0),
        (10000, 9500, 1),
        (10000, 0, 0),
        (0, 0, 0),
        (10000, 0, 1),
    ],
)
def test_describe_cogs_method_returns_non_empty(expected, actual, completed):
    """describe_cogs_method must return a non-empty string for every valid combo."""
    result = describe_cogs_method(expected, actual, completed)
    assert isinstance(result, str)
    assert len(result) > 0


def test_describe_cogs_method_in_progress():
    """In-progress description should contain 'Conservative'."""
    result = describe_cogs_method(10000, 8000, 0)
    assert "Conservative" in result
    assert "10000" in result


def test_describe_cogs_method_completed():
    """Completed description should contain 'Actual Cost'."""
    result = describe_cogs_method(10000, 9500, 1)
    assert "Actual Cost" in result
    assert "9500" in result


def test_describe_cogs_method_zero():
    """Zero cost description should indicate no JE posted."""
    result = describe_cogs_method(0, 0, 0)
    assert "Zero Cost" in result
