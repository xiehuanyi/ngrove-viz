#!/usr/bin/env python3
"""Add the Cloud TPU v5e-4 Track A (6 h) runs to the committed aggregate.

Reads archived nGrove episodes (each archive holds run-meta.json and
episodes/<id>/{state.json,events.jsonl}) and replaces the `tpu-a-6h` lane
in rsi/data.json. Only numeric results, candidate history and public run
metadata are exported, never transcripts, workspaces or paths.

  python3 tools/import_tpu_episodes.py MODEL=ARCHIVE_DIR [MODEL=ARCHIVE_DIR ...]
  python3 tools/build_rsi.py
"""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = "tpu-a-6h"
RUNTIME = "1 host × 4 Google Cloud TPU v5e (v5litepod-4)"
TOOLS = {"opencode": "OpenCode 1.18.27", "codex": "Codex CLI 0.159.2",
         "cursor": "Cursor CLI 2026.09.23"}
INFERENCE = {"https://api.ohmygpt.com": "OhMyGPT relay", "https://opencode.ai": "OpenCode Go"}
SUBSCRIPTION = {"codex": "ChatGPT Pro subscription", "cursor": "Cursor subscription"}


def load_episode(archive):
    states = sorted(archive.glob("episodes/*/state.json"))
    if len(states) != 1:
        raise ValueError(f"{archive}: expected exactly one episode, found {len(states)}")
    state = json.loads(states[0].read_text())
    events = [json.loads(line) for line in (states[0].parent / "events.jsonl").read_text().splitlines()
              if line.strip()]
    meta = json.loads((archive / "run-meta.json").read_text())
    return state, events, meta


def row(model, state, events, meta):
    if state.get("outcome") != "success" or state.get("test_raw_metrics") is None:
        raise ValueError(f"{model}: only completed episodes with TEST are exported")
    final_id = state.get("final_candidate_id")
    ended = [e for e in events if e["type"] == "LEASE_ENDED"]
    points = []
    for c in sorted(state.get("analysis_trajectory") or [], key=lambda c: c["commit_index"]):
        nll = (c.get("analysis_raw_metrics") or {}).get("mean_nll")
        if nll is None:
            continue
        cost = c.get("analysis_cost") or {}
        per_task = cost.get("time_per_task")
        elapsed = c["elapsed_seconds"]
        points.append({
            "index": c["commit_index"],
            "candidate_id": c["candidate_id"].removeprefix("sha256:")[:12],
            "lease": c.get("source_lease"),
            "hours": sum(e["used_seconds"] for e in ended if e["elapsed_seconds"] <= elapsed) / 3600,
            "research_hours": elapsed / 3600,
            "nll": nll, "score": c.get("analysis_performance_score"), "ppl": math.exp(nll),
            "seconds_per_task": per_task, "ms": None if per_task is None else 1000 * per_task,
            "evaluation_seconds": cost.get("candidate_wall_seconds"),
            "tasks_per_second": cost.get("tasks_per_second"),
            "input_tokens_per_second": cost.get("input_tokens_per_second"),
            "task_count": cost.get("task_count"),
            "final": c["candidate_id"] == final_id,
        })
    test_nll = state["test_raw_metrics"]["mean_nll"]
    test_cost = state.get("test_cost") or {}
    per_task = test_cost.get("time_per_task")
    timing = state.get("timing_summary") or {}
    agent = meta["agent"]
    runner = agent["runner"]
    tool = "opencode" if runner == "container" else agent["tool"]
    if runner == "container":
        usage = state.get("inference_usage") or {}
        total, output, calls = usage.get("total_tokens"), usage.get("output_tokens"), usage.get("model_calls")
        source = INFERENCE[(meta.get("inference") or {})["base_url"]]
    else:
        usage = state.get("agent_usage") or {}
        complete = usage.get("usage_complete") and tool != "cursor"  # Cursor reports only its last request
        total = usage.get("total_tokens") if complete else None
        output = usage.get("output_tokens") if complete else None
        calls = None
        source = SUBSCRIPTION[tool]
    final = next((p for p in points if p["final"]), points[-1] if points else None)
    ai = state["artifact_identities"]
    return {
        "model": model, "track": "A", "track_config": LANE,
        "comparison_key": {"challenge_id": "lm-pretrain", "runtime_profile": "tpu-v5e-x4",
                           "track": "A", "track_config": LANE},
        "challenge_manifest_sha256": None,
        "task_manifest_sha256": ai["task_manifest_sha256"],
        "max_leases": None, "status": state["status"], "outcome": state["outcome"],
        "test_nll": test_nll, "score": state.get("test_performance_score"),
        "seconds_per_task": per_task, "ms": None if per_task is None else 1000 * per_task,
        "ppl": math.exp(test_nll),
        "evaluation_seconds": test_cost.get("candidate_wall_seconds"),
        "tasks_per_second": test_cost.get("tasks_per_second"),
        "input_tokens_per_second": test_cost.get("input_tokens_per_second"),
        "task_count": test_cost.get("task_count"),
        "budget_hours": state["environment"]["configuration"]["budget"]["total_seconds"] / 3600,
        "lease_hours": timing.get("training_lease_seconds", 0) / 3600,
        "research_hours": timing.get("official_elapsed_seconds", 0) / 3600,
        "leases": state["leases_used"], "candidates": len(state.get("candidates") or {}),
        "first_analysis": points[0]["nll"] if points else None,
        "final_analysis": final["nll"] if final else None,
        "reasoning_effort": agent.get("reasoning_effort"), "points": points,
        "reasoning_tokens": None, "output_tokens": output, "total_tokens": total,
        "agent_turns": None, "model_calls": calls,
        "runtime": RUNTIME, "runner": runner, "agent_tool": TOOLS[tool],
        "inference_source": source, "core_revision": meta["core_revision"][:12],
        "comparable_harness": runner == "container",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", help="MODEL=ARCHIVE_DIR")
    args = parser.parse_args()
    data_path = ROOT / "rsi" / "data.json"
    data = json.loads(data_path.read_text())
    rows, identities = [], set()
    for spec in args.runs:
        model, _, path = spec.partition("=")
        state, events, meta = load_episode(Path(path))
        ai = state["artifact_identities"]
        identities.add(json.dumps([ai["task_manifest_sha256"], ai["train_manifest_sha256"],
                                   ai["evaluator_sha256"], ai["hidden_evaluation"],
                                   state["environment"]["configuration_sha256"]], sort_keys=True))
        rows.append(row(model, state, events, meta))
    if len(identities) != 1:
        raise ValueError("TPU runs differ in task, data, evaluator or environment identity")
    if len({r["model"] for r in rows}) != len(rows):
        raise ValueError("one run per model")
    data["rows"] = [r for r in data["rows"] if r["track_config"] != LANE] + rows
    data["tpu"] = {
        "runtime": RUNTIME, "track_config": LANE, "budget_hours": 6.0,
        "task": "lm-pretrain (JAX image, task-tpu-jax)",
        "core_revisions": sorted({r["core_revision"] for r in rows}),
        "selection": "Latest completed attempt per model; attempts stopped by relay balance or quota "
                     "and the Track B pilot are excluded.",
        "excluded_attempts": [
            {"model": m, "outcome": "dnf", "reason": "relay HTTP 402 (balance)"}
            for m in ("claude-opus-5", "kimi-k3", "deepseek-v4.1-flash", "glm-5.3",
                      "claude-sonnet-5", "gpt-6.1-sol", "deepseek-v4-pro", "gpt-5.6-terra")
        ] + [{"model": "kimi-k3", "outcome": "dnf", "reason": "relay HTTP 402 (balance), rerun"},
             {"model": "glm-5.3", "outcome": "stopped", "reason": "OpenCode Go 5-hour quota, operator stop"}],
    }
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"{len(rows)} TPU rows written; total rows {len(data['rows'])}")


if __name__ == "__main__":
    main()
