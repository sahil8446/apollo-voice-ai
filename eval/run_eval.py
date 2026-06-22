#!/usr/bin/env python3
"""Re-runnable evaluation harness for the Apollo voice-agent backend.

Runs a suite of scripted scenarios against the LIVE API (default
http://localhost:8000) and scores the dimensions the rubric cares about:

  * task_success     — did the requested action complete (book/reschedule/cancel)?
  * tool_correctness — did each call hit the right endpoint with valid params and
                       return the expected status/body, against real DB state?
  * conflict_handling — when a slot is taken, are valid alternatives offered?
  * robustness        — vague input, mid-call change, error recovery, bad ids.
  * latency           — per-call round-trip; we report p50/p95 (the voice SLO).

Why these: a voice booking agent is judged by whether the caller leaves with the
right appointment, never dead-ends on a conflict or error, and isn't left in
dead air. Each dimension maps to one of those. Limits are documented in the
README (it tests the backend contract, not STT/TTS/LLM behaviour — that lives in
Retell's own simulation suite).

Usage:
    python run_eval.py --base-url https://your-app.up.railway.app
    python run_eval.py            # defaults to localhost:8000

Exits non-zero if any scenario fails, so it drops into CI cleanly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
VAR_RE = re.compile(r"^\{\{(\w+)\}\}$")

# Logical action -> how to issue it against the REST API.
ACTIONS: dict[str, dict[str, str]] = {
    "find_doctor": {"method": "GET", "path": "/doctors"},
    "check_availability": {"method": "GET", "path": "/availability"},
    "book": {"method": "POST", "path": "/appointments"},
    "reschedule": {"method": "PUT", "path": "/appointments/{appointment_id}"},
    "cancel": {"method": "DELETE", "path": "/appointments/{appointment_id}"},
    "lookup": {"method": "GET", "path": "/appointments"},
}


def interpolate(value: Any, ctx: dict[str, Any]) -> Any:
    """Replace a whole-string {{var}} token with its captured value (typed)."""
    if isinstance(value, str):
        m = VAR_RE.match(value)
        if m:
            return ctx.get(m.group(1))
        return value
    if isinstance(value, dict):
        return {k: interpolate(v, ctx) for k, v in value.items()}
    return value


def json_path(data: Any, path: str) -> Any:
    """Resolve a dotted path with [index] support, e.g. 'doctors[0].id'."""
    cur = data
    for part in path.split("."):
        m = re.match(r"(\w+)(?:\[(\d+)\])?$", part)
        if not m:
            return None
        key, idx = m.group(1), m.group(2)
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
        if idx is not None:
            if isinstance(cur, list) and len(cur) > int(idx):
                cur = cur[int(idx)]
            else:
                return None
    return cur


def check_assertion(resp_json: Any, assertion: dict) -> tuple[bool, str]:
    path, op = assertion["path"], assertion["op"]
    actual = json_path(resp_json, path)
    if op == "eq":
        ok = actual == assertion["value"]
    elif op == "ne":
        ok = actual != assertion["value"]
    elif op == "exists":
        ok = actual is not None
    elif op == "non_empty":
        ok = bool(actual)
    elif op == "empty":
        ok = not actual
    elif op == "gte":
        ok = actual is not None and actual >= assertion["value"]
    elif op == "contains":
        ok = assertion["value"] in (actual or "")
    else:
        return False, f"unknown op {op}"
    detail = "" if ok else f"{path} ({op} {assertion.get('value')!r}) got {actual!r}"
    return ok, detail


class Harness:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.latencies: list[float] = []
        self.created_appointments: list[int] = []

    def call(self, action: str, args: dict, path_args: dict) -> tuple[int, Any, float]:
        spec = ACTIONS[action]
        path = spec["path"].format(**{k: str(v) for k, v in path_args.items()})
        method = spec["method"]

        kwargs: dict[str, Any] = {}
        if method == "GET":
            kwargs["params"] = {k: v for k, v in args.items() if v is not None}
        elif method in ("POST", "PUT"):
            kwargs["json"] = args

        start = time.perf_counter()
        resp = self.client.request(method, path, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.latencies.append(elapsed_ms)
        try:
            body = resp.json()
        except Exception:
            body = {"_raw": resp.text}
        return resp.status_code, body, elapsed_ms

    def run_scenario(self, scenario: dict, ctx_seed: dict) -> dict:
        ctx = dict(ctx_seed)
        steps_out: list[dict] = []
        passed = True

        for i, step in enumerate(scenario["steps"]):
            action = step["action"]
            args = interpolate(step.get("args", {}), ctx)
            path_args = interpolate(step.get("path_args", {}), ctx)

            status, body, latency = self.call(action, args, path_args)

            # Track created appointments for cleanup.
            if action == "book" and status == 201:
                appt_id = json_path(body, "appointment.id")
                if appt_id:
                    self.created_appointments.append(appt_id)

            # Capture values for later steps.
            for var, path in step.get("capture", {}).items():
                ctx[var] = json_path(body, path)

            # Evaluate assertions.
            step_pass = True
            failures: list[str] = []
            expect = step.get("expect", {})
            if "status" in expect and status != expect["status"]:
                step_pass = False
                failures.append(f"status expected {expect['status']} got {status}")
            for assertion in expect.get("json", []):
                ok, detail = check_assertion(body, assertion)
                if not ok:
                    step_pass = False
                    failures.append(detail)

            passed = passed and step_pass
            steps_out.append(
                {
                    "step": i,
                    "action": action,
                    "status": status,
                    "latency_ms": round(latency, 1),
                    "passed": step_pass,
                    "failures": failures,
                }
            )
            if not step_pass:
                break  # later steps depend on this one; stop the scenario

        return {
            "name": scenario["name"],
            "dimension": scenario.get("dimension", "task_success"),
            "passed": passed,
            "steps": steps_out,
        }

    def cleanup(self) -> None:
        """Cancel everything this run booked, so the suite is repeatable."""
        for appt_id in self.created_appointments:
            try:
                self.client.request("DELETE", f"/appointments/{appt_id}")
            except Exception:
                pass

    def close(self) -> None:
        self.client.close()


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round((pct / 100) * (len(s) - 1)))
    return round(s[k], 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apollo voice-agent eval harness.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--scenarios", default=str(HERE / "scenarios.json"), help="Scenario file."
    )
    parser.add_argument(
        "--no-cleanup", action="store_true", help="Keep appointments created by the run."
    )
    args = parser.parse_args()

    spec = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    scenarios = spec["scenarios"]

    # Unique phone PER SCENARIO so scenarios don't see each other's bookings,
    # and unique per run so re-runs don't collide on prior state.
    run_ts = datetime.now(timezone.utc)
    run_stamp = run_ts.strftime("%H%M%S")

    harness = Harness(args.base_url)

    # Fail fast if the backend isn't reachable.
    try:
        harness.client.get("/health").raise_for_status()
    except Exception as exc:
        print(f"ERROR: backend not reachable at {args.base_url} ({exc})")
        return 2

    print(f"Running {len(scenarios)} scenarios against {args.base_url}\n")
    results = []
    for idx, scenario in enumerate(scenarios):
        ctx_seed = {"run_phone": f"9{run_stamp}{idx:02d}"}
        r = harness.run_scenario(scenario, ctx_seed)
        results.append(r)
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['name']:<28} ({r['dimension']})")
        if not r["passed"]:
            for s in r["steps"]:
                if not s["passed"]:
                    print(f"         step {s['step']} {s['action']}: {s['failures']}")

    if not args.no_cleanup:
        harness.cleanup()

    # --- Aggregate metrics ---
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_dim: dict[str, dict[str, int]] = {}
    for r in results:
        d = by_dim.setdefault(r["dimension"], {"passed": 0, "total": 0})
        d["total"] += 1
        d["passed"] += int(r["passed"])

    summary = {
        "timestamp": run_ts.isoformat(),
        "base_url": args.base_url,
        "scenarios_total": total,
        "scenarios_passed": passed,
        "task_success_rate": round(passed / total, 3) if total else 0.0,
        "by_dimension": by_dim,
        "latency_ms": {
            "count": len(harness.latencies),
            "p50": percentile(harness.latencies, 50),
            "p95": percentile(harness.latencies, 95),
            "max": round(max(harness.latencies), 1) if harness.latencies else 0.0,
        },
        "results": results,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_file = RESULTS_DIR / f"eval_{run_ts.strftime('%Y%m%dT%H%M%SZ')}.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    latest = RESULTS_DIR / "latest.json"
    latest.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n--- Summary ---")
    print(f"  Scenarios: {passed}/{total} passed")
    for dim, d in by_dim.items():
        print(f"  {dim:<20} {d['passed']}/{d['total']}")
    print(
        f"  Latency: p50={summary['latency_ms']['p50']}ms "
        f"p95={summary['latency_ms']['p95']}ms"
    )
    print(f"  Results written to {out_file.relative_to(HERE)}")

    harness.close()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
