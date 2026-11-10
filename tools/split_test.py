#!/usr/bin/env python3
"""
Hit the front door (:8081) like a normal client, then trace every request
through the nginx JSON access log (nginx/log/access.json) to show how it was handled.

    python3 tools/split_test.py -n 20
"""
import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPLIT_TO_PORT = {"legacy_80": "80", "legacy_8080": "8080"}


def make_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("split_test")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s")
    for handler in (logging.StreamHandler(sys.stdout),
                    logging.FileHandler(path, encoding="utf-8")):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger


def send(url: str, req_id: str, timeout: float):
    req = urllib.request.Request(url, headers={"X-Request-Id": req_id})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, body = resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read().decode(errors="replace")
    except Exception as exc:
        status, body = None, f"{type(exc).__name__}: {exc}"
    return status, body, (time.monotonic() - start) * 1000


def read_records(log_path: Path, offset: int, wanted: set) -> dict:
    records = {}
    if not log_path.exists():
        return records
    with log_path.open("rb") as f:
        f.seek(offset)
        for raw in f:
            try:
                rec = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            rid = rec.get("request_id")
            if rid in wanted:
                records.setdefault(rid, []).append(rec)
    return records


def wait_for_records(log_path: Path, offset: int, ids: list, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        records = read_records(log_path, offset, set(ids))
        if all(len(records.get(i, [])) >= 2 for i in ids) or time.monotonic() > deadline:
            return records
        time.sleep(0.3)


def trace(idx, total, res, recs, log):
    front = next((r for r in recs if r.get("port") == "8081"), None)
    inner = next((r for r in recs if r.get("port") in ("80", "8080")), None)

    problems = []
    if res["status"] != 200:
        problems.append(f"client got status {res['status']}")
    if front is None:
        problems.append("no :8081 record in nginx log")
    if inner is None:
        problems.append("no :80 / :8080 record in nginx log")
    if front and inner:
        expected = SPLIT_TO_PORT.get(front.get("split"))
        if expected != inner.get("port"):
            problems.append(f"split={front.get('split')} but handled on :{inner.get('port')}")
        if inner.get("peer") != "127.0.0.1":
            problems.append(f"legacy hop peer={inner.get('peer')}, expected 127.0.0.1 (front door)")
        if inner.get("client") != front.get("client"):
            problems.append(f"real client not restored: front={front.get('client')} legacy={inner.get('client')}")
    if inner and not inner.get("served_by", "").startswith("healthchecker"):
        problems.append(f"legacy hop upstream={inner.get('upstream_addr')!r} is not a healthchecker")

    log.info("[%d/%d] %s client GET :8081 -> status=%s (%.1f ms) %s",
             idx, total, res["id"], res["status"], res["ms"], "OK" if not problems else "FAIL")
    if front:
        log.info("    hop1 :%-4s %-9s client=%s split=%s -> upstream %s status=%s (%ss)",
                 front["port"], front["hop"], front["client"], front["split"],
                 front["upstream_addr"], front["upstream_status"], front["request_time"])
    if inner:
        log.info("    hop2 :%-4s %-9s client=%s peer=%s -> upstream %s (%s) status=%s (%ss)",
                 inner["port"], inner["hop"], inner["client"], inner["peer"],
                 inner["upstream_addr"], inner["served_by"], inner["upstream_status"],
                 inner["request_time"])
    log.info("    response %s", res["body"][:120].strip())
    for p in problems:
        log.error("    %s", p)
    return problems, front, inner


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8081/healthcheck/status/200")
    ap.add_argument("-n", "--count", type=int, default=20)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--access-log", type=Path, default=ROOT / "nginx" / "log" / "access.json")
    ap.add_argument("--output", type=Path, default=ROOT / "nginx" / "log" / "split_test.log")
    args = ap.parse_args()

    log = make_logger(args.output)
    offset = args.access_log.stat().st_size if args.access_log.exists() else 0
    log.info("sending %d requests to %s", args.count, args.url)

    results = []
    for _ in range(args.count):
        rid = f"t-{uuid.uuid4().hex[:12]}"
        status, body, ms = send(args.url, rid, args.timeout)
        results.append({"id": rid, "status": status, "body": body, "ms": ms})
        time.sleep(args.interval)

    records = wait_for_records(args.access_log, offset, [r["id"] for r in results], args.timeout)
    if not records:
        log.error("no matching lines in %s — is ./nginx/log mounted to /var/log/nginx?", args.access_log)

    failed = 0
    by_split, by_port, by_server, by_status = Counter(), Counter(), Counter(), Counter()
    for i, res in enumerate(results, 1):
        problems, front, inner = trace(i, len(results), res, records.get(res["id"], []), log)
        failed += bool(problems)
        by_status[res["status"]] += 1
        if front:
            by_split[front.get("split")] += 1
        if inner:
            by_port[inner.get("port")] += 1
            by_server[inner.get("served_by")] += 1

    log.info("summary: total=%d ok=%d failed=%d", len(results), len(results) - failed, failed)
    log.info("  client status : %s", dict(by_status))
    log.info("  split decision: %s", dict(by_split))
    log.info("  handled on    : %s", {f':{k}': v for k, v in by_port.items()})
    log.info("  served by     : %s", dict(sorted(by_server.items())))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
