from tracker.alerts import decide_alert


def test_alerts_once_when_price_reaches_target():
    assert decide_alert(100, 90, already_alerted=False) == (True, True)
    assert decide_alert(100, 100, already_alerted=False) == (True, True)


def test_does_not_repeat_the_alert():
    assert decide_alert(100, 90, already_alerted=True) == (False, True)


def test_rearms_when_price_goes_back_above_target():
    assert decide_alert(100, 120, already_alerted=True) == (False, False)


def test_unavailable_keeps_state():
    assert decide_alert(100, None, already_alerted=True) == (False, True)
    assert decide_alert(100, None, already_alerted=False) == (False, False)
