import unittest

from app.services.cache_utils import put_bounded


class CacheUtilsTests(unittest.TestCase):
    def test_put_bounded_evicts_oldest_entry(self) -> None:
        cache = {"old": 1, "middle": 2}

        put_bounded(cache, "new", 3, max_entries=2)

        self.assertEqual(cache, {"middle": 2, "new": 3})

    def test_replacing_entry_does_not_evict_another_key(self) -> None:
        cache = {"a": 1, "b": 2}

        put_bounded(cache, "a", 3, max_entries=2)

        self.assertEqual(cache, {"a": 3, "b": 2})


if __name__ == "__main__":
    unittest.main()
