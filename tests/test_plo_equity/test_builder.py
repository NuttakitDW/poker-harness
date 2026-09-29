import tempfile
import unittest
from pathlib import Path

from plo_equity.builder import build
from plo_equity.cache import Cache, Metadata
from plo_equity.cards import enumerate_classes


class BuilderTest(unittest.TestCase):
    def test_small_build_resumes_without_resampling(self):
        chosen = enumerate_classes()[:4]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite"
            fresh_path = Path(folder) / "fresh.sqlite"
            build(path, samples=40, global_seed=43, opponents=1, workers=1, classes=chosen)
            build(path, samples=100, global_seed=43, opponents=1, workers=1, classes=chosen)
            build(fresh_path, samples=100, global_seed=43, opponents=1, workers=1, classes=chosen)
            cache = Cache(path, Metadata(global_seed=43, opponents=1))
            fresh = Cache(fresh_path, Metadata(global_seed=43, opponents=1))
            self.assertEqual({row.n for row in cache.load().values()}, {100})
            self.assertEqual(cache.load(), fresh.load())
            cache.close()
            fresh.close()


if __name__ == "__main__":
    unittest.main()
