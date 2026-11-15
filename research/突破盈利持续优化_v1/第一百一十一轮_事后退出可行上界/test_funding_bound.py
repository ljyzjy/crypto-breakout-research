"""Funding coverage and exact settlement-time treatment for the bound."""
import hashlib
import json
from pathlib import Path

import audit_oracle
import run_oracle

H = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    sym, mon = "TEST", "2022-01"
    start = 1640995800000
    end = start + 5 * 60000
    prev = {"ts": start - 600000, "funding_interval_hours": 8}
    nxt = {"ts": start + 8 * 3600000, "funding_interval_hours": 8}
    statuses = {("fundingRate", sym, mon): "verified"}
    env, _ = run_oracle.previous.risk.risk_namespace()
    cases = [([prev, nxt], statuses, "known"),
             ([prev, {"ts": start, "funding_interval_hours": 8}, nxt], statuses, "unknown_funding_event"),
             ([prev, {"ts": end, "funding_interval_hours": 8}, nxt], statuses, "unknown_funding_event"),
             ([prev, nxt], {}, "unknown_funding_source"),
             ([], statuses, "unknown_funding_coverage")]
    for rows, source, expected in cases:
        funds = {(sym, mon): rows}
        assert run_oracle.funding_status(sym, start, end, funds, source, env["funding_ok"]) == expected
        assert audit_oracle.funding_class(sym, start, end, funds, source) == expected
    out = {"all_checks_pass": True, "cases_checked": len(cases), "code_sha256": sha(Path(__file__)),
           "runner_sha256": sha(H / "run_oracle.py"), "audit_sha256": sha(H / "audit_oracle.py"),
           "cases": ["no settlement", "settlement at entry", "settlement at exit", "missing source", "missing coverage"]}
    (H / "资金费边界合成核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
