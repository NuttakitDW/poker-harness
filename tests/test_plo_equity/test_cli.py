import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from plo_equity.cards import canonical_hand, class_key, parse_hand
from plo_equity.cli import main
from plo_equity.simulation import TrialStats


class CliTest(unittest.TestCase):
    def test_query_reports_equity_confidence_interval(self):
        key = class_key(canonical_hand(parse_hand("AsAhKsKh")))
        rows = {key: TrialStats(100, 70.5, 70.25, 70, 1)}
        output = io.StringIO()
        with patch("plo_equity.cli._load", return_value=rows), redirect_stdout(output):
            self.assertEqual(main(["query", "AsAhKsKh"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["samples"], 100)
        self.assertLess(result["equity_ci95_low"], result["equity"])
        self.assertGreater(result["equity_ci95_high"], result["equity"])
        self.assertEqual(result["opponents"], 1)


if __name__ == "__main__":
    unittest.main()
