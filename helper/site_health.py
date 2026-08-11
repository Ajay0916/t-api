import time


class SiteHealth:
    """Tracks failing sites and applies a cooldown before retrying."""

    def __init__(self, cooldown=300):
        self.cooldown = cooldown
        self._cooldown_until = {}
        self._fail_count = {}

    def mark_success(self, site):
        self._cooldown_until.pop(site, None)
        self._fail_count[site] = 0

    def mark_failure(self, site):
        n = self._fail_count.get(site, 0) + 1
        self._fail_count[site] = n
        backoff = min(self.cooldown * n, 3600)
        self._cooldown_until[site] = time.monotonic() + backoff

    def is_blocked(self, site):
        until = self._cooldown_until.get(site)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        self._cooldown_until.pop(site, None)
        return False

    def status(self, site):
        now = time.monotonic()
        until = self._cooldown_until.get(site)
        if until is None or now >= until:
            return {
                "blocked": False,
                "cooldown_remaining": 0,
                "fail_count": self._fail_count.get(site, 0),
            }
        return {
            "blocked": True,
            "cooldown_remaining": int(until - now),
            "fail_count": self._fail_count.get(site, 0),
        }


site_health = SiteHealth(cooldown=300)
