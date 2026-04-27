#!/usr/bin/env python3
"""
Universal PromQL → retcode check for cmd_check_alert.

Queries Prometheus instant API and compares each result series' value against
up to two thresholds, returning:
  0  OK
  1  WARNING   (some series crossed --threshold-warning but not critical)
  2  CRITICAL  (some series crossed --threshold-critical,
                OR no-data without --no-data-ok,
                OR any HTTP / decode error)

cmd_check_alert maps these via `severity_per_retcode` in pillar.

Args:
  --url                 Prometheus base URL
  --user/--pass         optional basic auth
  --query               PromQL (instant)
  --op                  gt | lt | ge | le | eq | ne — comparison direction
  --threshold-warning   numeric, optional (only 0/2 if omitted)
  --threshold-critical  numeric, optional (only 0/1 if omitted)
  --no-data-ok          treat empty result as OK (matches Grafana noDataState=OK)
  --exec-err-ok         treat query failures (network/HTTP/parse) as OK
                          (matches Grafana execErrState=OK)
  --timeout             HTTP timeout seconds (default 30)
  --label               label shown in output for context
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from base64 import b64encode

OPS = {
    "gt": (lambda v, t: v > t,  ">"),
    "lt": (lambda v, t: v < t,  "<"),
    "ge": (lambda v, t: v >= t, ">="),
    "le": (lambda v, t: v <= t, "<="),
    "eq": (lambda v, t: v == t, "=="),
    "ne": (lambda v, t: v != t, "!="),
}


def query(args):
    url = args.url.rstrip("/") + "/api/v1/query"
    data = urllib.parse.urlencode({"query": args.query}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if args.user:
        token = b64encode(f"{args.user}:{args.passwd}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=args.timeout) as resp:
        return json.loads(resp.read().decode())


def fmt_fired(r, v):
    lbls = ",".join(f"{k}={vv}" for k, vv in (r.get("metric") or {}).items())
    return f"{lbls or 'value'}={v:g}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="passwd", default="")
    ap.add_argument("--query", required=True)
    ap.add_argument("--op", choices=list(OPS.keys()), required=True)
    ap.add_argument("--threshold-warning",  dest="warn", type=float, default=None)
    ap.add_argument("--threshold-critical", dest="crit", type=float, default=None)
    ap.add_argument("--no-data-ok", action="store_true")
    ap.add_argument("--exec-err-ok", dest="exec_err_ok", action="store_true",
                    help="treat query failures (network/HTTP/parse errors) as OK "
                         "(matches Grafana execErrState=OK)")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--label", default="value")
    args = ap.parse_args()

    if args.warn is None and args.crit is None:
        print("ERROR: at least one of --threshold-warning / --threshold-critical required")
        sys.exit(2)

    try:
        payload = query(args)
    except Exception as e:
        if args.exec_err_ok:
            print(f"OK exec-err ({args.label}): {e}")
            sys.exit(0)
        print(f"CRIT query: {e}")
        sys.exit(2)

    res = payload.get("data", {}).get("result", []) or []
    op_fn, op_sym = OPS[args.op]

    if not res:
        if args.no_data_ok:
            print(f"OK no-data ({args.label})")
            sys.exit(0)
        print(f"CRIT no-data ({args.label})")
        sys.exit(2)

    fired_crit, fired_warn, values = [], [], []
    for r in res:
        try:
            v = float(r["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        values.append(v)
        if args.crit is not None and op_fn(v, args.crit):
            fired_crit.append(fmt_fired(r, v))
        elif args.warn is not None and op_fn(v, args.warn):
            fired_warn.append(fmt_fired(r, v))

    if fired_crit:
        print(f"CRIT {op_sym} {args.crit:g}: {' | '.join(fired_crit[:3])}")
        sys.exit(2)
    if fired_warn:
        print(f"WARN {op_sym} {args.warn:g}: {' | '.join(fired_warn[:3])}")
        sys.exit(1)

    parts = []
    if args.warn is not None:
        parts.append(f"warn {op_sym} {args.warn:g}")
    if args.crit is not None:
        parts.append(f"crit {op_sym} {args.crit:g}")
    vrange = f"max={max(values):g}" if values else "no values"
    print(f"OK {vrange} ({', '.join(parts)}, {len(res)} series)")
    sys.exit(0)


if __name__ == "__main__":
    main()

