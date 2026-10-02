from __future__ import annotations

import base64
import http.client
import itertools
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "final_table"))

import ft_server  # noqa: E402
import table_reader  # noqa: E402

from plo_icm.game import Action, PLOState  # noqa: E402
from plo_premium_proof.finaltable import (  # noqa: E402
    FinalTableSpec,
    SpecError,
    icm_table,
    solve,
)
from plo_premium_proof.fullkernels import (  # noqa: E402
    _utility,
    icm_equity,
    no_outcomes,
    scratch_size,
)
from plo_premium_proof.fulltree import FullTree, FullTreeConfig  # noqa: E402

PAYOUTS = (1531.94, 1136.36, 842.99, 625.36, 463.91, 344.15, 255.30)


def brute_icm(stacks, prizes):
    """Malmuth-Harville by listing every finishing order."""
    equity = [0.0] * len(stacks)
    for order in itertools.permutations(range(len(stacks))):
        chance, left = 1.0, sum(stacks)
        for seat in order:
            chance *= stacks[seat] / left
            left -= stacks[seat]
        for place, seat in enumerate(order):
            equity[seat] += chance * (prizes[place] if place < len(prizes) else 0.0)
    return equity


class IcmTest(unittest.TestCase):
    def test_matches_every_finishing_order(self):
        stacks = [30.0, 12, 55, 8, 20, 40, 25]
        prizes = np.asarray(PAYOUTS)
        work = np.empty(scratch_size(7))
        chips = np.asarray(stacks)
        got = [icm_equity(chips, chips, prizes, seat, work) for seat in range(7)]
        np.testing.assert_allclose(got, brute_icm(stacks, PAYOUTS), rtol=1e-12)
        self.assertAlmostEqual(sum(got), sum(PAYOUTS))

    def test_busted_players_finish_below_survivors_by_starting_stack(self):
        start = np.asarray([30.0, 12, 55, 8, 20, 40, 25])
        work = np.empty(scratch_size(7))
        prizes = np.asarray(PAYOUTS)
        # 30bb and 12bb both bust into the 55bb stack: the 30bb player takes 6th, 12bb 7th.
        final = np.asarray([0.0, 0, 97, 8, 20, 40, 25])
        self.assertAlmostEqual(icm_equity(final, start, prizes, 0, work), PAYOUTS[5])
        self.assertAlmostEqual(icm_equity(final, start, prizes, 1, work), PAYOUTS[6])
        tied = np.asarray([0.0, 0, 67, 8, 20, 40, 25])
        even = np.asarray([30.0, 30, 7, 8, 20, 40, 25])
        self.assertAlmostEqual(icm_equity(tied, even, prizes, 0, work), (PAYOUTS[5] + PAYOUTS[6]) / 2)

    def test_winner_takes_first(self):
        work = np.empty(scratch_size(3))
        final, start = np.asarray([0.0, 60, 0]), np.asarray([20.0, 20, 20])
        self.assertAlmostEqual(icm_equity(final, start, np.asarray([50.0, 30, 20]), 1, work), 50.0)


class SevenSeatGameTest(unittest.TestCase):
    def test_blinds_and_order_follow_the_seat_count(self):
        state = PLOState.new((30, 12, 55, 8, 20, 40, 25), sb=.5, bb=1, ante=.12, ante_mode="individual",
                             opening_raise_mode="pot_only")
        self.assertEqual(state.to_act, tuple(range(7)))
        self.assertAlmostEqual(state.pot, 1.5 + 7 * .12)
        self.assertAlmostEqual(state.action_amount(Action.POT), 3.5)  # antes stay out of the pot size

    def test_heads_up_big_blind_acts_first_after_the_flop(self):
        state = PLOState.new((10, 10), sb=.5, bb=1, ante=0, ante_mode="individual", opening_raise_mode="pot_only")
        self.assertEqual(state.to_act, (0, 1))
        state = state.apply(Action.CALL).apply(Action.CHECK)
        self.assertEqual((state.street, state.to_act), (1, (1, 0)))

    def test_three_handed_postflop_starts_at_the_small_blind(self):
        state = PLOState.new((10, 10, 10), sb=.5, bb=1, ante=0, ante_mode="individual", opening_raise_mode="pot_only")
        state = state.apply(Action.CALL).apply(Action.CALL).apply(Action.CHECK)
        self.assertEqual(state.to_act, (1, 2, 0))


class ShortTableTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = FullTreeConfig(stacks=(6.0, 3.0, 9.0), raise_caps=(2, 1, 0, 0), ante_bb=0.1)
        cls.tree = FullTree.build(cls.config, cache_dir=None)

    def test_uneven_stacks_and_first_in_nodes(self):
        tree = self.tree
        self.assertEqual(tree.seats, 3)
        np.testing.assert_allclose(tree.start_stacks, [6.0, 3.0, 9.0])
        np.testing.assert_allclose(tree.behind[0], [5.9, 2.4, 7.9])
        self.assertEqual(list(tree.actor[tree.first_in_nodes]), [0, 1])

    def test_chips_are_conserved_at_every_terminal(self):
        tree = self.tree
        terminal = np.flatnonzero(tree.actor < 0)
        totals = tree.behind[terminal].sum(axis=1) + tree.sidepot_amount[terminal].sum(axis=1)
        np.testing.assert_allclose(totals, 18.0)

    def test_icm_utility_scores_the_final_stacks(self):
        tree = self.tree
        node = int(tree.children[0, 0])  # BTN folds
        node = int(tree.children[node, 0])  # SB folds: BB wins blinds and antes
        self.assertLess(tree.actor[node], 0)
        prizes = np.asarray([50.0, 30, 20])
        scratch = np.empty(scratch_size(3))
        ranks = np.arange(3, dtype=np.int64)
        final = np.asarray([5.9, 2.4, 9.7])
        for seat in range(3):
            got = _utility(node, seat, tree.start_stacks, tree.behind, tree.sidepot_count, tree.sidepot_amount,
                           tree.sidepot_eligible_mask, ranks, prizes, scratch, *no_outcomes())
            self.assertAlmostEqual(got, brute_icm(list(final), prizes)[seat])


class SpecTest(unittest.TestCase):
    def test_validation(self):
        good = {"stacks": [30, 12, 55], "payouts": [50, 30, 20]}
        self.assertEqual(FinalTableSpec.from_dict(good).seat_names, ("BTN", "SB", "BB"))
        for bad in ({**good, "stacks": [30]}, {**good, "payouts": [10, 20]}, {**good, "hero": "UTG"},
                    {**good, "stacks": [30, 0, 5]}, {"payouts": [1]}, {**good, "raise_caps": [4, 5, 1, 1]}):
            with self.subTest(bad=bad), self.assertRaises(SpecError):
                FinalTableSpec.from_dict(bad)

    def test_only_paid_places_for_players_left(self):
        spec = FinalTableSpec(stacks=(10, 20, 30), payouts=PAYOUTS)
        np.testing.assert_allclose(spec.prizes, PAYOUTS[:3])
        self.assertAlmostEqual(sum(icm_table(spec.stacks, spec.prizes)), sum(PAYOUTS[:3]))


class SolveTest(unittest.TestCase):
    def test_a_short_solve_writes_status_and_explorer_result(self):
        spec = FinalTableSpec(stacks=(4.0, 2.5, 6.0), payouts=(50, 30, 20), ante_bb=0.1,
                              raise_caps=(2, 1, 0, 0), minutes=0.5, threads=2, hero="SB", hand="AsKsQd9c")
        ticks = itertools.count(step=10.0)
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder)
            status = solve(spec, out, epoch_deals=200, clock=lambda: next(ticks))
            self.assertEqual(status["state"], "done")
            self.assertGreater(status["deals"], 0)
            result = json.loads((out / "result.json").read_text())
            self.assertEqual(result["seats"], ["BTN", "SB", "BB"])
            self.assertEqual(result["spec"]["hand"], "AsKsQd9c")
            blob = base64.b64decode(result["strategy"])
            self.assertEqual(len(blob), len(result["nodes"]) * result["buckets"] * 3)
            self.assertAlmostEqual(sum(result["icm"]), 100.0)
            root = result["nodes"][0]
            self.assertEqual([o["action"] for o in root["options"]], ["fold", "call", "pot"])

    def test_stop_file_ends_the_run_early(self):
        spec = FinalTableSpec(stacks=(4.0, 2.5, 6.0), payouts=(50, 30, 20), raise_caps=(2, 1, 0, 0),
                              minutes=60, threads=1)
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder)
            (out / "stop").touch()
            status = solve(spec, out, epoch_deals=50)
            self.assertEqual((status["state"], status["epochs"]), ("stopped", 1))


class TableReaderTest(unittest.TestCase):
    def reply(self, **changes):
        data = {
            "players": [
                {"name": "hero", "stack": 400000, "bet": 0, "cards": ["As", "Ks", "Qd", "9c"]},
                {"name": "p2", "stack": 1200000, "bet": 20000, "cards": None},
                {"name": "p3", "stack": 600000, "bet": 40000, "cards": None},
                {"name": "p4", "stack": 800000, "bet": 0, "cards": None},
            ],
            "button": "hero", "stack_unit": "chips", "blinds": {"sb": 20000, "bb": 40000, "ante": 5000},
        }
        data.update(changes)
        return "```json\n" + json.dumps(data) + "\n```"

    def test_seats_follow_the_button_clockwise(self):
        self.assertEqual(table_reader.seat_order(4, 0), [1, 2, 3, 0])  # BTN, SB, BB, CO
        self.assertEqual(table_reader.seat_order(2, 1), [1, 0])
        table = table_reader.parse(self.reply())
        self.assertEqual([s["position"] for s in table["seats"]], ["CO", "BTN", "SB", "BB"])
        self.assertEqual(table["hero"], "BTN")
        self.assertEqual([s["stack_bb"] for s in table["seats"]], [20.0, 10.0, 30.5, 16.0])
        self.assertEqual((table["hand"], table["ante_bb"], table["notes"]), ("AsKsQd9c", 0.125, []))

    def test_missing_big_blind_and_cards_are_reported(self):
        table = table_reader.parse(self.reply(blinds={"sb": None, "bb": None, "ante": 5000},
                                              players=[{"name": "hero", "stack": 5, "bet": 0, "cards": None},
                                                       {"name": "p2", "stack": 7, "bet": 0}]))
        self.assertIsNone(table["seats"][0]["stack_bb"])
        self.assertEqual(len(table["notes"]), 3)

    def test_unreadable_replies_raise(self):
        for text in ("not json", self.reply(button="nobody"), self.reply(players=[])):
            with self.subTest(text=text[:20]), self.assertRaises(table_reader.ReadError):
                table_reader.parse(text)


class LocalServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.jobs = ft_server.Jobs(pathlib.Path(cls.folder.name))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ft_server.make_handler(cls.jobs))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.folder.cleanup()

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        connection.request(method, path, json.dumps(body) if body is not None else None)
        response = connection.getresponse()
        return response, response.read()

    def test_page_statics_and_info(self):
        response, body = self.request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Copyright", body)
        self.assertIn(b"/static/plo-explorer.js", body)
        response, _ = self.request("GET", "/static/plo-explorer.js")
        self.assertEqual(response.getheader("Content-Type"), "text/javascript; charset=utf-8")
        info = json.loads(self.request("GET", "/api/info")[1])
        self.assertEqual(info["payouts"][:7], list(PAYOUTS))
        self.assertEqual(len(info["payouts"]), 51)
        self.assertIsNone(info["running"])

    def test_progress_endpoint(self):
        data = json.loads(self.request("GET", "/api/progress")[1])
        self.assertIn("library", data)
        self.assertIn("training", data)
        self.assertGreater(data["disk_free_gb"], 0)
        _, body = self.request("GET", "/")
        self.assertIn(b'id="train-view"', body)

    def test_icm_prices_the_field_mid_tournament(self):
        table = {"stacks": [30, 12, 55, 20, 8, 41], "payouts": list(ft_server.DEFAULT_PAYOUTS)}
        final = json.loads(self.request("POST", "/api/icm", {"spec": table})[1])["icm"]
        self.assertAlmostEqual(sum(final), sum(ft_server.DEFAULT_PAYOUTS[:6]), places=6)
        mtt = json.loads(self.request("POST", "/api/icm", {"spec": {
            **table, "players_left": 60, "field_stack_bb": 31}})[1])["icm"]
        self.assertEqual(len(mtt), 6)
        self.assertLess(sum(mtt), sum(final))
        response, _ = self.request("POST", "/api/icm", {"spec": {**table, "players_left": 60}})
        self.assertEqual(response.status, 400)

    def test_bad_requests_are_refused_with_a_reason(self):
        response, body = self.request("POST", "/api/solve", {"spec": {"stacks": [5], "payouts": [1]}})
        self.assertEqual(response.status, 400)
        self.assertIn("players", json.loads(body)["error"])
        response, body = self.request("POST", "/api/detect", {"image": "data:text/plain;base64,aGk="})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.request("GET", "/api/jobs/../status")[0].status, 404)
        self.assertEqual(self.request("GET", "/static/../server.py")[0].status, 404)

    def test_finished_solves_are_listed_and_served(self):
        folder = self.jobs.folder / "20261001-120000"
        folder.mkdir()
        (folder / "spec.json").write_text(json.dumps({"stacks": [5, 6], "payouts": [2, 1]}))
        (folder / "status.json").write_text(json.dumps({"state": "done", "seconds": 60}))
        (folder / "result.json").write_text(json.dumps({"nodes": []}))
        status = json.loads(self.request("GET", "/api/jobs/20261001-120000/status")[1])
        self.assertEqual((status["state"], status["has_result"], status["running"]), ("done", True, False))
        self.assertEqual(json.loads(self.request("GET", "/api/jobs/20261001-120000/result")[1]), {"nodes": []})
        listing = json.loads(self.request("GET", "/api/info")[1])["jobs"]
        self.assertEqual([job["id"] for job in listing], ["20261001-120000"])


if __name__ == "__main__":
    unittest.main()
