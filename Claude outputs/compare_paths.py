#!/usr/bin/env python3
"""
Compare how every location behaves on both sides of the front door.

For each location found in nginx.conf it sends the URI (with and without the
trailing slash) through the front door twice, forced with X-Canary to each
side, without following redirects, and reports:
  - status / Location / body hash on each side, and whether they match
  - Location values that leak an internal port or host

    python3 tools/compare_paths.py --conf nginx/nginx.conf
    python3 tools/compare_paths.py --conf nginx/nginx.conf --path /api/v1/ping --leak xxx.com.tw:8080
"""
import argparse
import hashlib
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def locations(conf_text, skip_ports):
    """Prefix / exact locations from server blocks that do NOT listen on the front-door port."""
    text = re.sub(r"#[^\n]*", "", conf_text)
    out, i = [], 0
    for m in re.finditer(r"\bserver\s*\{", text):
        depth, j = 1, m.end()
        while depth and j < len(text):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        block = text[m.end():j]
        ports = set(re.findall(r"\blisten\s+(?:[\d.]+:)?(\d+)", block))
        if not ports or ports & skip_ports:
            continue
        for lm in re.finditer(r"\blocation\s+(=\s*|\^~\s*)?([^\s{~@]+)\s*\{", block):
            out.append(lm.group(2))
    return sorted(set(out))


def variants(path):
    base = path.rstrip("/") or "/"
    vs = {base}
    if base != "/":
        vs.add(base + "/")
    return sorted(vs)


def fetch(url, host, canary, timeout):
    req = urllib.request.Request(url, headers={"Host": host, "X-Canary": canary})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.headers.get("Location") or "", hashlib.sha1(r.read()).hexdigest()[:8]
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location") or "", hashlib.sha1(e.read()).hexdigest()[:8]
    except Exception as e:
        return None, "", type(e).__name__


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conf", type=Path, default=ROOT / "nginx" / "nginx.conf")
    ap.add_argument("--front", default="http://localhost:8081", help="front door base URL")
    ap.add_argument("--front-port", default="8081", help="front door listen port (its server block is skipped)")
    ap.add_argument("--host", default="localhost:8081", help="Host header clients normally send")
    ap.add_argument("--a", default="80", help="X-Canary value for side A (new_80)")
    ap.add_argument("--b", default="8080", help="X-Canary value for side B (legacy_8080)")
    ap.add_argument("--path", action="append", default=[], help="extra path to test (repeatable)")
    ap.add_argument("--leak", action="append", default=[":8080", ":80/", "127.0.0.1", "xxx.com.tw"],
                    help="substring that must not appear in Location (repeatable)")
    ap.add_argument("--timeout", type=float, default=5)
    args = ap.parse_args()

    paths = locations(args.conf.read_text(), {args.front_port}) + args.path
    if not paths:
        sys.exit(f"no locations found in {args.conf}")
    print(f"{len(paths)} locations from {args.conf}; side A = X-Canary {args.a}, side B = X-Canary {args.b}\n")
    print(f"{'path':<28} {'A status':>8} {'B status':>8}  match  Location A | Location B")

    problems = 0
    for p in paths:
        for v in variants(p):
            ra = fetch(args.front + v, args.host, args.a, args.timeout)
            rb = fetch(args.front + v, args.host, args.b, args.timeout)
            same = ra == rb
            leaks = [s for s in args.leak for loc in (ra[1], rb[1]) if s and s in loc]
            empty = [side for side, r in (("A", ra), ("B", rb)) if r[0] in (301, 302, 303, 307, 308) and not r[1]]
            down = [side for side, r in (("A", ra), ("B", rb)) if r[0] is None]
            flag = "OK  " if same and not leaks and not empty and not down else "FAIL"
            problems += flag == "FAIL"
            print(f"{v:<28} {str(ra[0]):>8} {str(rb[0]):>8}  {flag}   {ra[1] or '-'} | {rb[1] or '-'}")
            if not same and ra[:2] == rb[:2]:
                print(f"{'':<28} body differs: {ra[2]} vs {rb[2]}")
            for s in sorted(set(leaks)):
                print(f"{'':<28} LEAK: Location contains {s!r}")
            for side in down:
                print(f"{'':<28} side {side}: no response ({(ra if side == 'A' else rb)[2]})")
            for side in empty:
                print(f"{'':<28} side {side}: redirect without a Location header")
    print(f"\n{problems} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
