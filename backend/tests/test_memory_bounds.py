import unittest

from app.main import RateLimiter


class MemoryBoundTests(unittest.TestCase):
    def test_rate_limiter_evicts_idle_keys(self) -> None:
        limiter = RateLimiter(max_requests=10, window=60, max_keys=2)
        limiter.allow("a")
        limiter.allow("b")
        limiter.allow("c")
        self.assertLessEqual(len(limiter.hits), 2)


if __name__ == "__main__":
    unittest.main()
