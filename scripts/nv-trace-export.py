#!/usr/bin/env python3
"""Export one arena run as a single OTLP/JSON trace (OBS-08, `nv trace export`).

Usage:
  NIDAVELLIR_API_URL=http://127.0.0.1:8000 NIDAVELLIR_API_KEY=<operator key> \\
    python3 scripts/nv-trace-export.py <arena_id> [-o trace.otlp.json]

The file is OTLP/HTTP JSON (`resourceSpans`), importable by OTLP-capable tools
(Jaeger, Grafana Tempo, Phoenix). It works after teardown: spans are retained
with the arena record. Spans that produced a finding carry `nv.finding.title`
and `nv.finding.verdict`. The key must be an operator or admin key.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export an arena run as one OTLP trace.")
    parser.add_argument("arena_id")
    parser.add_argument("-o", "--output", help="file to write (default: stdout)")
    args = parser.parse_args(argv)
    base = os.environ.get("NIDAVELLIR_API_URL", "http://127.0.0.1:8000").rstrip("/")
    key = os.environ.get("NIDAVELLIR_API_KEY")
    if not key:
        print("set NIDAVELLIR_API_KEY to an operator key", file=sys.stderr)
        return 2
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        print("NIDAVELLIR_API_URL must be http(s)", file=sys.stderr)
        return 2
    url = f"{base}/arenas/{urllib.parse.quote(args.arena_id, safe='')}/trace"
    request = urllib.request.Request(url, headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310
            # scheme checked above
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"export failed: HTTP {exc.code}", file=sys.stderr)
        return 1
    spans = [s for rs in body["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]
    text = json.dumps(body, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    traces = {s["traceId"] for s in spans}
    print(f"exported {len(spans)} spans in {len(traces)} trace(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
