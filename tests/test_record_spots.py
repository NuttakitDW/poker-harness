"""The guided recorder: scenario cards, their labels, and resuming a session."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import record_spots  # noqa: E402
import spot_eval  # noqa: E402
sys.path.insert(0, str(ROOT))


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = record_spots.scenarios()

    def test_there_are_enough_and_ids_are_unique_and_stable(self):
        self.assertGreaterEqual(len(self.scenarios), 50)
        ids = [s.id for s in self.scenarios]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [s.id for s in record_spots.scenarios()])

    def test_every_supported_feature_is_covered(self):
        groups = {s.group for s in self.scenarios}
        for group in ("first-in", "facing-one", "multiway", "table-size", "ante", "tiny-stack",
                      "deep-push-fold", "hand"):
            with self.subTest(group=group):
                self.assertIn(group, groups)

    def test_labels_use_only_fields_the_scorer_knows(self):
        for scenario in self.scenarios:
            with self.subTest(id=scenario.id):
                self.assertTrue(set(scenario.expected) <= set(spot_eval.FIELDS))
                self.assertIn("hero", scenario.expected)
                self.assertIn("stack", scenario.expected)

    def test_a_shover_always_acts_before_the_hero(self):
        for scenario in self.scenarios:
            seats = record_spots.table_seats(scenario.expected.get("players") or 8)
            for shover in scenario.expected.get("shovers", []):
                with self.subTest(id=scenario.id, shover=shover):
                    self.assertLess(seats.index(shover), seats.index(scenario.expected["hero"]))

    def test_phrasing_hints_rotate(self):
        self.assertGreaterEqual(len({s.style for s in self.scenarios}), 4)


class CardTests(unittest.TestCase):
    def test_the_card_names_everything_the_speaker_must_say(self):
        scenario = record_spots.Scenario(
            "x", "facing-one", {"hero": "BB", "stack": 7.5, "shovers": ["BTN"], "hands": ["K9o"],
                                "ante": 0.125, "ante_mode": "each", "players": 6}, "พูดสั้น ๆ")
        card = record_spots.card(scenario)
        for text in ("BB", "7.5", "BTN", "K9 offsuit", "6", "12.5%", "พูดสั้น ๆ"):
            with self.subTest(text=text):
                self.assertIn(text, card)

    def test_hand_labels_become_spoken_names(self):
        self.assertEqual(record_spots.hand_words(["AKs"]), "AK suited")
        self.assertEqual(record_spots.hand_words(["QQ"]), "pocket QQ")
        self.assertEqual(record_spots.hand_words(["KQs", "KQo"]), "KQ (ไม่ต้องบอกดอก)")


class SessionTests(unittest.TestCase):
    def test_kept_recordings_are_saved_and_skipped_next_time(self):
        with tempfile.TemporaryDirectory() as folder:
            labels = Path(folder) / "recorded.jsonl"
            first = record_spots.scenarios()[0]
            record_spots.save(labels, first, audio="voice/s001.ogg", heard="BTN all-in 10bb")
            self.assertEqual(record_spots.done(labels), {first.id})
            row = json.loads(labels.read_text(encoding="utf-8"))
            self.assertEqual(row["expected"], first.expected)
            self.assertEqual(row["audio"], "voice/s001.ogg")
            self.assertEqual(row["heard"], "BTN all-in 10bb")

    def test_the_review_line_marks_each_field(self):
        scenario = record_spots.Scenario("x", "first-in", {"hero": "BTN", "stack": 10}, "")
        line = record_spots.review_line(scenario, {**spot_eval.empty(), "hero": "BTN", "stack": 9})
        self.assertIn("hero BTN ✓", line)
        self.assertIn("stack 9 ✗ (ต้องได้ 10)", line)


if __name__ == "__main__":
    unittest.main()
