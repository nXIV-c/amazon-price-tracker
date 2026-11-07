"""Alert decision logic, kept free of I/O so it is trivial to test."""
from __future__ import annotations


def decide_alert(target_price: float, price: float | None, already_alerted: bool) -> tuple[bool, bool]:
    """Decide whether to notify the user.

    A user is alerted once per drop: after the alert, the product stays "alerted"
    until its price rises above the target again.

    Returns:
        ``(send_alert, alerted_state_to_store)``.
    """
    if price is None:  # unavailable: nothing to say, keep the previous state
        return False, already_alerted
    if price <= target_price:
        return (not already_alerted), True
    return False, False
