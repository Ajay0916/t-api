import time


class SiteHealth:
    """Tracks failing sites and applies a cooldown before retrying."""

    def __init__(self, cooldown=300):
        self.cooldown = cooldown
        self._cooldown_until = {}
        self._fail_count = {}
        self._last_error = {}
        self._manual = set()

    def manual_block(self, site):
        self._manual.add(site)

    def manual_unblock(self, site):
        self._manual.discard(site)

    def is_manually_blocked(self, site):
        return site in self._manual

    def mark_success(self, site):
        self._cooldown_until.pop(site, None)
        self._fail_count[site] = 0
        self._last_error.pop(site, None)

    def mark_failure(self, site, error=None):
        n = self._fail_count.get(site, 0) + 1
        self._fail_count[site] = n
        backoff = min(self.cooldown * n, 3600)
        self._cooldown_until[site] = time.monotonic() + backoff
        if error:
            self._last_error[site] = str(error)[:120]

    def is_blocked(self, site):
        if site in self._manual:
            return True
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
        manual = site in self._manual
        if until is None or now >= until:
            return {
                "blocked": manual,
                "manual_blocked": manual,
                "cooldown_remaining": 0,
                "fail_count": self._fail_count.get(site, 0),
                "last_error": self._last_error.get(site, ""),
            }
        return {
            "blocked": True,
            "manual_blocked": manual,
            "cooldown_remaining": int(until - now),
            "fail_count": self._fail_count.get(site, 0),
            "last_error": self._last_error.get(site, ""),
        }


site_health = SiteHealth(cooldown=300)
