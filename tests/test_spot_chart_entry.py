"""The Makefile chart entry must boot with both voice modules and root solver packages."""

from pathlib import Path
import os
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChartEntryTest(unittest.TestCase):
    def test_make_chart_starts_and_quits(self):
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        made = subprocess.run(["make", "chart"], cwd=ROOT, input="/q\n", text=True,
                              capture_output=True, timeout=10, env=environment)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        self.assertNotIn("ModuleNotFoundError", made.stdout + made.stderr)


if __name__ == "__main__":
    unittest.main()
