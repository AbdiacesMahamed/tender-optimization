"""Run the hard stress-test cases through the real Bedrock tool-use loop.

Reuses everything in ``evals.harness`` (the Bedrock client, recording executor,
three-layer scoring, reporting) but pulls cases from ``evals.stress_cases``
instead of ``evals.cases``. Keeps the stress suite isolated from the baseline.

    python -m evals.run_stress                  # all stress cases
    python -m evals.run_stress --case s1_find_priciest_then_cap
    python -m evals.run_stress --repeat 3        # flakiness check
    python -m evals.run_stress --json evals/stress.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Optional

from . import harness as H
from . import fixture as F
from . import stress_cases as SC


def run_all(case_filter: Optional[str] = None, repeat: int = 1,
            verbose: bool = True) -> List["H.CaseResult"]:
    client = H.BedrockChatClient()
    if not client.has_credentials:
        print("ERROR: No Bedrock credentials found. Add AWS_BEDROCK_API_KEY (or "
              "AWS_accessKeyId / AWS_secretAccessKey) to tests/.env.")
        sys.exit(2)

    wd, rd = F.working_data(), F.rate_data()
    selected = [c for c in SC.all_cases()
                if case_filter is None or c.id == case_filter]
    if not selected:
        print(f"ERROR: No stress case matches id '{case_filter}'.")
        sys.exit(2)

    if verbose:
        print(f"Model: {client.model_id}  |  Region: {client.region}")
        print(f"STRESS: running {len(selected)} case(s) x {repeat} -> "
              f"{len(selected) * repeat} call(s)\n")

    results: List[H.CaseResult] = []
    for case in selected:
        for i in range(repeat):
            t0 = time.time()
            r = H.run_case(client, case, wd, rd)
            dt = time.time() - t0
            results.append(r)
            if verbose:
                H._print_case(r, dt, run_idx=i if repeat > 1 else None)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Tender Assistant STRESS eval harness")
    ap.add_argument("--case", help="run a single stress case by id")
    ap.add_argument("--repeat", type=int, default=1, help="runs per case (flakiness)")
    ap.add_argument("--json", help="write structured results to this path")
    ap.add_argument("--quiet", action="store_true", help="suppress per-case output")
    args = ap.parse_args(argv)

    results = run_all(case_filter=args.case, repeat=args.repeat, verbose=not args.quiet)
    summary = H.summarize(results)

    print("=" * 60)
    print(f"STRESS RESULT: {summary['passed']}/{summary['total']} checks-passing runs "
          f"({summary['pass_rate'] * 100:.0f}%)")
    if args.repeat > 1:
        for cid, ratio in summary["by_case"].items():
            print(f"  {cid}: {ratio}")

    if args.json:
        payload = {
            "summary": summary,
            "results": [
                {
                    "case_id": r.case_id, "prompt": r.prompt, "intent": r.intent,
                    "passed": r.passed, "tools_used": r.tools_used,
                    "answer": r.answer, "error": r.error,
                    "tool_calls": [{"name": c["name"], "input": c["input"]}
                                   for c in r.tool_calls],
                    "failed_checks": [
                        {"label": ch.label, "detail": ch.detail}
                        for ch in r.checks if not ch.passed
                    ],
                }
                for r in results
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nWrote structured results to {args.json}")

    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
