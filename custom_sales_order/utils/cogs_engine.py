# Copyright (c) 2026, Nest Software Development and contributors
# For license information, please see license.txt

"""
Pure-Python COGS calculation engine.

This module has **zero Frappe imports** so it can be tested with plain pytest
without bootstrapping a Frappe site.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_cogs(
    expected_cost: float,
    actual_cost: float,
    is_completed: bool | int,
) -> float:
    """Return the COGS value to post in the Journal Entry.

    Rules
    -----
    * If either cost is negative → ``ValueError``.
    * If the order is completed (``is_completed`` truthy) → use ``actual_cost``.
    * Otherwise → use ``max(expected_cost, actual_cost)`` (conservative).

    Parameters
    ----------
    expected_cost : float
        The salesperson's estimated cost at order creation.
    actual_cost : float
        The confirmed final cost (may be zero if not yet known).
    is_completed : bool | int
        ``1`` / ``True`` when the order is marked as completed.

    Returns
    -------
    float
        The COGS amount to debit in the GL.

    Raises
    ------
    ValueError
        If either cost is negative.
    """
    expected_cost = float(expected_cost)
    actual_cost = float(actual_cost)

    if expected_cost < 0:
        raise ValueError(
            f"Expected cost must be non-negative, got {expected_cost}"
        )
    if actual_cost < 0:
        raise ValueError(
            f"Actual cost must be non-negative, got {actual_cost}"
        )

    if is_completed:
        return actual_cost

    return max(expected_cost, actual_cost)


def describe_cogs_method(
    expected_cost: float,
    actual_cost: float,
    is_completed: bool | int,
) -> str:
    """Return a human-readable description of the COGS method for the JE remark.

    Examples
    --------
    >>> describe_cogs_method(10000, 8000, False)
    'Conservative (In Progress): max(expected=10000, actual=8000) = 10000'
    >>> describe_cogs_method(10000, 9500, True)
    'Actual Cost (Completed): 9500'
    >>> describe_cogs_method(0, 0, False)
    'Zero Cost: no JE posted'
    """
    expected_cost = float(expected_cost)
    actual_cost = float(actual_cost)
    cogs = calculate_cogs(expected_cost, actual_cost, is_completed)

    if cogs == 0:
        return "Zero Cost: no JE posted"

    if is_completed:
        return f"Actual Cost (Completed): {actual_cost:g}"

    return (
        f"Conservative (In Progress): "
        f"max(expected={expected_cost:g}, actual={actual_cost:g}) = {cogs:g}"
    )


def validate_costs(
    expected_cost: float,
    actual_cost: float,
    is_completed: bool | int,
) -> list[str]:
    """Validate the cost fields and return a list of warning/error strings.

    An empty list means no issues. The caller should inspect each string:

    * Strings starting with ``"ERROR"`` indicate hard failures (throw).
    * Strings starting with ``"WARNING"`` indicate soft warnings (msgprint).

    Parameters
    ----------
    expected_cost : float
        The salesperson's estimated cost.
    actual_cost : float
        The confirmed final cost.
    is_completed : bool | int
        Completion flag.

    Returns
    -------
    list[str]
        A (possibly empty) list of diagnostic messages.
    """
    messages: list[str] = []
    expected_cost = float(expected_cost)
    actual_cost = float(actual_cost)

    if expected_cost < 0:
        messages.append(
            f"ERROR: Expected cost must be non-negative, got {expected_cost}"
        )
    if actual_cost < 0:
        messages.append(
            f"ERROR: Actual cost must be non-negative, got {actual_cost}"
        )

    if is_completed and actual_cost == 0:
        messages.append(
            "WARNING: Order is marked as completed but Actual Cost is zero. "
            "COGS will be posted as 0."
        )

    return messages
