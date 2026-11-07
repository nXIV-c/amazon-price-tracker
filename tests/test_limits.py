from tracker import limits
from tracker.limits import RateLimiter


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def test_a_second_action_inside_the_cooldown_is_limited():
    clock = FakeClock()
    limiter = RateLimiter(3, clock)
    assert limiter.is_limited("add") is False
    clock.now += 2.9
    assert limiter.is_limited("add") is True


def test_the_action_is_allowed_again_after_the_cooldown():
    clock = FakeClock()
    limiter = RateLimiter(3, clock)
    assert limiter.is_limited("add") is False
    clock.now += 3
    assert limiter.is_limited("add") is False


def test_keys_are_limited_independently():
    limiter = RateLimiter(3, FakeClock())
    assert limiter.is_limited(1) is False
    assert limiter.is_limited(2) is False
    assert limiter.is_limited(1) is True


def test_refused_attempts_do_not_extend_the_cooldown():
    clock = FakeClock()
    limiter = RateLimiter(3, clock)
    assert limiter.is_limited(1) is False  # t = 0
    clock.now += 2
    assert limiter.is_limited(1) is True  # t = 2, refused
    clock.now += 1.1
    assert limiter.is_limited(1) is False  # t = 3.1: counted from the first action, not from the refusal


def test_expired_entries_are_forgotten():
    clock = FakeClock()
    limiter = RateLimiter(3, clock)
    for user_id in range(limits._PRUNE_ABOVE):
        limiter.is_limited(user_id)
    clock.now += 10
    limiter.is_limited("new user")
    assert len(limiter._last) == 1
