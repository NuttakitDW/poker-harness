"""Generate auditable tables and SVGs from completed frozen study cells."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ACTIONS = ("fold", "call", "raise_2bb")
POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB")
TIERS = ("Premium", "Speculative", "Marginal", "Trash")


def _expected(manifest: dict) -> tuple[tuple, ...]:
    cohort = tuple(tuple(row) for row in manifest["cohort"])
    mode = manifest["mode"]
    if mode == "pilot":
        raise ValueError("pilot results are not paper results")
    if mode == "sensitivity":
        anchors = {"premium_aakk", "speculative_aa82", "marginal_jj63", "trash_9753"}
        return tuple((*hand, "BTN", 76, seed) for hand in cohort if hand[0] in anchors
                     for seed in manifest["seeds"])
    return tuple((*hand, position, remaining, seed) for hand in cohort
                 for position in manifest["positions"] for remaining in manifest["stages"]
                 for seed in manifest["seeds"])


def _id(cell: tuple) -> str:
    hand_id, _, _, position, remaining, seed = cell
    return f"{hand_id}__{position.lower()}__left{remaining}__seed{seed}"


def _load(directory: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((directory / "cells").glob("*.json"))]
    expected = {_id(cell): cell for cell in _expected(manifest)}
    seen = set()
    for row in rows:
        cell_id = row.get("cell_id")
        if cell_id not in expected or cell_id in seen:
            raise ValueError(f"foreign or duplicate cell: {cell_id}")
        seen.add(cell_id)
        hand_id, cards, tier, position, remaining, seed = expected[cell_id]
        config = row.get("config", {})
        if (row.get("source_sha256") != manifest["source_sha256"]
                or (row.get("hand_id"), row.get("cards"), row.get("tier"), row.get("position"),
                    row.get("players_remaining"), row.get("seed"))
                != (hand_id, cards, tier, position, remaining, seed)
                or row.get("eval_attempts_requested") != manifest["eval_attempts"]
                or config.get("max_nodes") != manifest["max_nodes"]
                or config.get("time_limit") != manifest["timeout_seconds"]
                or config.get("opening_raise_mode") != manifest["opening_raise_mode"]
                or config.get("players_remaining") != remaining or config.get("seed") != seed):
            raise ValueError(f"cell does not match manifest: {cell_id}")
    return manifest, rows


def _mean_range(values: list[float]) -> tuple[float | None, float | None, float | None]:
    return ((statistics.mean(values), min(values), max(values)) if values else (None, None, None))


def aggregate(rows: list[dict], manifest: dict) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[(row.get("hand_id"), row.get("cards"), row.get("tier"), row.get("position"),
                row.get("players_remaining"))].append(row)
    expected_groups = {(hand_id, cards, tier, position, remaining)
                       for hand_id, cards, tier, position, remaining, _ in _expected(manifest)}
    out = []
    for key in sorted(expected_groups):
        group = groups.get(key, [])
        complete = [row for row in group if row.get("status") == "complete"]
        actions = Counter(row["selected_action"] for row in complete)
        agreement = max(actions.values(), default=0)
        modes = sorted(action for action, count in actions.items() if count == agreement)
        modal = modes[0] if len(modes) == 1 else "split:" + "/".join(modes) if modes else None
        record = dict(zip(("hand_id", "cards", "tier", "position", "players_remaining"), key),
                      cells_expected=3, cells_found=len(group), cells_complete=len(complete),
                      modal_action=modal, modal_agreement=agreement)
        for action in ACTIONS:
            values = [row["action_ev_dollars"][action] for row in complete
                      if action in row.get("action_ev_dollars", {})]
            mean, low, high = _mean_range(values)
            record.update({f"{action}_ev_mean": mean, f"{action}_ev_min": low,
                           f"{action}_ev_max": high})
        for label, pair in (("raise_minus_limp", ("raise_2bb", "call")),
                            ("limp_minus_fold", ("call", "fold"))):
            differences = [row["action_ev_dollars"][pair[0]] - row["action_ev_dollars"][pair[1]]
                           for row in complete]
            ses = [row.get("pairwise_se_dollars", {}).get(f"{pair[0]}|{pair[1]}")
                   for row in complete]
            ses = [value for value in ses if value is not None]
            mean, low, high = _mean_range(differences)
            record.update({f"{label}_mean": mean, f"{label}_min": low, f"{label}_max": high,
                           f"{label}_paired_se_mean": statistics.mean(ses) if ses else None})
        record["fallback_mean"] = (statistics.mean(row["uniform_fallback_fraction"] for row in complete)
                                   if complete else None)
        record["ess_mean"] = (statistics.mean(row["effective_sample_size"] for row in complete)
                              if complete else None)
        out.append(record)
    return out


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def _pair_se(row: dict, first: str, second: str):
    values = row.get("pairwise_se_dollars", {})
    return values.get(f"{first}|{second}", values.get(f"{second}|{first}"))


def _flatten_completed(rows: list[dict]) -> list[dict]:
    """Return a tidy, scalar-only record for every completed seed cell."""
    flat = []
    for row in rows:
        if row.get("status") != "complete":
            continue
        ev = row.get("action_ev_dollars", {})
        amounts = row.get("action_amounts_bb", {})
        training = row.get("training", {})
        flat.append({
            "cell_id": row["cell_id"], "hand_id": row["hand_id"], "cards": row["cards"],
            "tier": row["tier"], "position": row["position"],
            "players_remaining": row["players_remaining"], "seed": row["seed"],
            "selected_action": row["selected_action"],
            "selected_amount_bb": row.get("selected_amount_bb"),
            "fold_ev_dollars": ev.get("fold"), "limp_ev_dollars": ev.get("call"),
            "raise_2bb_ev_dollars": ev.get("raise_2bb"),
            "fold_amount_bb": amounts.get("fold"), "limp_amount_bb": amounts.get("call"),
            "raise_2bb_amount_bb": amounts.get("raise_2bb"),
            "raise_minus_limp_paired_se_dollars": _pair_se(row, "raise_2bb", "call"),
            "limp_minus_fold_paired_se_dollars": _pair_se(row, "call", "fold"),
            "raise_minus_fold_paired_se_dollars": _pair_se(row, "raise_2bb", "fold"),
            "effective_sample_size": row.get("effective_sample_size"),
            "uniform_fallback_fraction": row.get("uniform_fallback_fraction"),
            "evaluation_attempts_completed": row.get("evaluation_attempts_completed"),
            "eval_attempts_requested": row.get("eval_attempts_requested"),
            "training_nodes": training.get("nodes"),
            "training_iterations": training.get("iterations_completed"),
            "training_stop_reason": training.get("stop_reason"),
            "wall_seconds": row.get("wall_seconds"),
            "peak_rss_mb": row.get("peak_rss_mb"),
            "source_sha256": row.get("source_sha256"),
        })
    return flat


def _fmt(value) -> str:
    return "--" if value is None else f"{value:.2f}" if isinstance(value, float) else str(value)


def _mean_with_range(row: dict, prefix: str) -> str:
    mean, low, high = row[f"{prefix}_mean"], row[f"{prefix}_min"], row[f"{prefix}_max"]
    return "--" if mean is None else f"{mean:.2f} [{low:.2f},{high:.2f}]"


def _latex_by_position(rows: list[dict], path: Path, cohort_order: list[str]) -> None:
    lines = ["% Generated from completed cells; mean [seed range], not a pooled confidence interval.",
             "\\noindent R, L, and F denote raise to 2bb, limp, and fold. Contrasts and SEs are in payout dollars. Parenthesized SE is the mean of per-seed paired SEs, not a pooled SE; FB and ESS are seed means."]
    for remaining in (76, 60):
        for position in POSITIONS:
            subset = [row for row in rows if row["players_remaining"] == remaining
                      and row["position"] == position]
            subset.sort(key=lambda row: cohort_order.index(row["hand_id"]))
            lines += [f"\\subsection*{{{position}, {remaining} players remaining}}",
                      "{\\footnotesize", "\\begin{tabular}{llrrrrr}", "\\toprule",
                      "Hand & Tier & $\\Delta$(R$-$L) [range] (SE) & $\\Delta$(L$-$F) [range] (SE) & Modal & FB / ESS & Complete \\\\",
                      "\\midrule"]
            for row in subset:
                raw_action = row["modal_action"]
                action_label = ({"fold": "F", "call": "L", "raise_2bb": "R"}.get(raw_action)
                                or ("Split" if raw_action and raw_action.startswith("split:") else "--"))
                rl_se = row["raise_minus_limp_paired_se_mean"]
                lf_se = row["limp_minus_fold_paired_se_mean"]
                rl = "--" if row["raise_minus_limp_mean"] is None else (
                    f"{row['raise_minus_limp_mean']:.2f} [{row['raise_minus_limp_min']:.2f},"
                    f"{row['raise_minus_limp_max']:.2f}] ({'--' if rl_se is None else f'{rl_se:.2f}'})")
                lf = "--" if row["limp_minus_fold_mean"] is None else (
                    f"{row['limp_minus_fold_mean']:.2f} [{row['limp_minus_fold_min']:.2f},"
                    f"{row['limp_minus_fold_max']:.2f}] ({'--' if lf_se is None else f'{lf_se:.2f}'})")
                diagnostic = ("--" if row["fallback_mean"] is None else
                              f"{100*row['fallback_mean']:.0f}\\% / {row['ess_mean']:.0f}")
                lines.append(f"{row['cards']} & {row['tier']} & {rl} & {lf} & "
                             f"{action_label} ({row['modal_agreement']}/3) & {diagnostic} & "
                             f"{row['cells_complete']}/3 \\\\")
            lines += ["\\bottomrule", "\\end{tabular}", "}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _plot_heatmap(rows: list[dict], remaining: int, path_base: Path,
                  cohort_order: list[str]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    by_hand = {row["hand_id"]: (row["hand_id"], row["cards"], row["tier"]) for row in rows}
    hands = [by_hand[hand_id] for hand_id in cohort_order]
    lookup = {(row["hand_id"], row["position"]): row for row in rows
              if row["players_remaining"] == remaining}
    keys = (None, "fold", "call", "raise_2bb", "split")
    color = {key: index for index, key in enumerate(keys)}
    values = []
    annotations = []
    for row_index, (hand_id, cards, tier) in enumerate(hands):
        value_row, annotation_row = [], []
        for column, position in enumerate(POSITIONS):
            record = lookup.get((hand_id, position), {})
            action = record.get("modal_action")
            agreement = record.get("modal_agreement", 0)
            color_key = "split" if action and action.startswith("split:") else action
            label = {"fold": "Fold", "call": "Limp", "raise_2bb": "Raise 2"}.get(action,
                    "Split" if color_key == "split" else "Missing")
            fallback = record.get("fallback_mean")
            completed = record.get("cells_complete", 0)
            fallback_text = "" if fallback is None else f"\nFB {100*fallback:.0f}%"
            value_row.append(color[color_key])
            annotation_row.append(f"{label} ({agreement}/{completed}; n={completed}/3){fallback_text}")
        values.append(value_row); annotations.append(annotation_row)
    palette = ListedColormap(("#dddddd", "#d9e7f5", "#b8dfc2", "#f4b8b8", "#f7e7a9"))
    fig, axis = plt.subplots(figsize=(10, 5.4), constrained_layout=True)
    axis.imshow(values, cmap=palette, vmin=-.5, vmax=len(keys)-.5, aspect="auto")
    axis.set_xticks(range(len(POSITIONS)), POSITIONS, fontsize=10)
    axis.set_yticks(range(len(hands)), [f"{cards}  ({tier})" for _, cards, tier in hands], fontsize=9)
    for row_index, row in enumerate(annotations):
        for column, label in enumerate(row):
            axis.text(column, row_index, label, ha="center", va="center", fontsize=8)
    axis.set_title(f"Diagnostic seed argmax at {remaining} remaining (not a strategy chart)", fontsize=13)
    axis.set_xlabel("First-in seat")
    axis.set_ylabel("Declared hand cohort order")
    axis.set_xticks([x - .5 for x in range(1, len(POSITIONS))], minor=True)
    axis.set_yticks([y - .5 for y in range(1, len(hands))], minor=True)
    axis.grid(which="minor", color="white", linewidth=2)
    axis.tick_params(which="minor", bottom=False, left=False)
    legend = [Patch(facecolor=palette(color[key]), label=label) for key, label in
              (("fold", "Fold"), ("call", "Limp"), ("raise_2bb", "Raise to 2bb"),
               ("split", "Tied seed vote"), (None, "Missing"))]
    axis.legend(handles=legend, loc="upper center", bbox_to_anchor=(.5, -.11), ncol=5,
                frameon=False, fontsize=8)
    path_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_base.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path_base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def analyze(main: Path, output: Path, sensitivity: Path | None = None) -> dict:
    manifest, raw = _load(main)
    aggregated = aggregate(raw, manifest)
    cohort_order = [row[0] for row in manifest["cohort"]]
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "all_cells_audit.csv", raw)
    _write_csv(output / "completed_cells.csv", _flatten_completed(raw))
    _write_csv(output / "hand_position_stage_summary.csv", aggregated)
    _latex_by_position(aggregated, output / "position_tables.tex", cohort_order)
    for remaining in (76, 60):
        _plot_heatmap(aggregated, remaining, output / f"modal_actions_left{remaining}", cohort_order)
    status = Counter(row.get("status", "unknown") for row in raw)
    result = {"main_manifest": manifest, "main_status_counts": dict(status),
              "main_cells_found": len(raw), "aggregate_rows": len(aggregated)}
    if sensitivity is not None:
        sensitivity_manifest, sensitivity_rows = _load(sensitivity)
        if sensitivity_manifest["source_sha256"] != manifest["source_sha256"]:
            raise ValueError("main and sensitivity runs use different frozen source")
        main_by_id = {row["cell_id"]: row for row in raw}
        comparisons = []
        for row in sensitivity_rows:
            base = main_by_id.get(row["cell_id"])
            record = {"cell_id": row["cell_id"], "main_status": base.get("status") if base else "missing",
                      "sensitivity_status": row.get("status")}
            if base and base.get("status") == row.get("status") == "complete":
                record.update({"main_action": base["selected_action"],
                               "sensitivity_action": row["selected_action"],
                               "action_agrees": base["selected_action"] == row["selected_action"],
                               "main_fallback": base["uniform_fallback_fraction"],
                               "sensitivity_fallback": row["uniform_fallback_fraction"]})
                for action in ACTIONS:
                    record[f"{action}_ev_change"] = (row["action_ev_dollars"][action]
                                                      - base["action_ev_dollars"][action])
            comparisons.append(record)
        _write_csv(output / "sensitivity_comparison.csv", comparisons)
        result["sensitivity_manifest"] = sensitivity_manifest
        result["sensitivity_cells_found"] = len(sensitivity_rows)
    (output / "analysis_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sensitivity", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.main, args.output, args.sensitivity), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
