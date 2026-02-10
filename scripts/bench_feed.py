#!/usr/bin/env python3
"""
Simple HTTP benchmark for /feed.

Designed to be dependency-free (stdlib only) so it can run on the host machine.

Example:
  python scripts/bench_feed.py --base-url http://localhost:8001 --runs 50
"""

from __future__ import annotations

import argparse
import http.client
import math
import statistics
import time
import urllib.parse


def _pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile for already-sorted values."""
    if not values:
        raise ValueError("values is empty")
    if p <= 0:
        return values[0]
    if p >= 100:
        return values[-1]
    k = math.ceil((p / 100.0) * len(values)) - 1
    k = max(0, min(k, len(values) - 1))
    return values[k]


def _make_connection(base_url: str) -> tuple[http.client.HTTPConnection, str]:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit(f"Unsupported scheme in base url: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise SystemExit(f"Invalid base url: {base_url!r}")

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    base_path = parsed.path.rstrip("/")

    if parsed.scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=30), base_path
    return http.client.HTTPConnection(host, port, timeout=30), base_path


def _bench_case(
    conn: http.client.HTTPConnection,
    base_path: str,
    *,
    name: str,
    path: str,
    warmup: int,
    runs: int,
) -> None:
    timings_ms: list[float] = []

    # Warm-up
    for _ in range(max(0, warmup)):
        conn.request("GET", f"{base_path}{path}", headers={"Accept": "application/json"})
        resp = conn.getresponse()
        resp.read()  # consume body for keep-alive
        if resp.status != 200:
            raise SystemExit(f"{name}: warmup failed: HTTP {resp.status}")

    # Timed runs
    for _ in range(runs):
        t0 = time.perf_counter()
        conn.request("GET", f"{base_path}{path}", headers={"Accept": "application/json"})
        resp = conn.getresponse()
        resp.read()
        t1 = time.perf_counter()
        if resp.status != 200:
            raise SystemExit(f"{name}: failed: HTTP {resp.status}")
        timings_ms.append((t1 - t0) * 1000.0)

    timings_ms.sort()
    total_s = sum(timings_ms) / 1000.0
    rps = (runs / total_s) if total_s > 0 else float("inf")

    p50 = _pct(timings_ms, 50)
    p95 = _pct(timings_ms, 95)
    p99 = _pct(timings_ms, 99)

    mean = statistics.fmean(timings_ms)
    mn = timings_ms[0]
    mx = timings_ms[-1]

    print(f"\n{name}")
    print(f"  url: {path}")
    print(f"  runs: {runs} (warmup {warmup})")
    print(f"  ms: min {mn:.1f} | p50 {p50:.1f} | mean {mean:.1f} | p95 {p95:.1f} | p99 {p99:.1f} | max {mx:.1f}")
    print(f"  rps: {rps:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark tg_stock /feed endpoint")
    parser.add_argument("--base-url", default="http://localhost:8001", help="API base url (default: http://localhost:8001)")
    parser.add_argument("--runs", type=int, default=50, help="Timed requests per case (default: 50)")
    parser.add_argument("--warmup", type=int, default=5, help="Warm-up requests per case (default: 5)")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Include weekly/monthly and larger offsets/limits (slower)",
    )
    args = parser.parse_args()

    conn, base_path = _make_connection(args.base_url)

    cases: list[tuple[str, str]] = [
        ("v4 stored score (top)", "/feed?period=daily&limit=10&offset=0&formula=v4&sort_by=score&sort_dir=desc"),
        ("v4 stored score (offset 100)", "/feed?period=daily&limit=10&offset=100&formula=v4&sort_by=score&sort_dir=desc"),
        ("v4 stored reactions (top)", "/feed?period=daily&limit=10&offset=0&formula=v4&sort_by=reactions&sort_dir=desc"),
        ("v4 stored reactions (offset 100)", "/feed?period=daily&limit=10&offset=100&formula=v4&sort_by=reactions&sort_dir=desc"),
        ("v1 dynamic score (top)", "/feed?period=daily&limit=10&offset=0&formula=v1&sort_by=score&sort_dir=desc"),
        ("v1 dynamic views (top)", "/feed?period=daily&limit=10&offset=0&formula=v1&sort_by=views&sort_dir=desc"),
    ]

    if args.extended:
        cases.extend(
            [
                ("v4 stored score weekly (top)", "/feed?period=weekly&limit=10&offset=0&formula=v4&sort_by=score&sort_dir=desc"),
                ("v4 stored score weekly (offset 200)", "/feed?period=weekly&limit=10&offset=200&formula=v4&sort_by=score&sort_dir=desc"),
                ("v4 stored views weekly (offset 200)", "/feed?period=weekly&limit=10&offset=200&formula=v4&sort_by=views&sort_dir=desc"),
                ("v4 stored score monthly (top)", "/feed?period=monthly&limit=10&offset=0&formula=v4&sort_by=score&sort_dir=desc"),
                ("v4 stored score monthly (offset 500)", "/feed?period=monthly&limit=10&offset=500&formula=v4&sort_by=score&sort_dir=desc"),
                ("v4 stored score monthly (offset 1000)", "/feed?period=monthly&limit=10&offset=1000&formula=v4&sort_by=score&sort_dir=desc"),
                ("v4 stored score monthly (limit 50)", "/feed?period=monthly&limit=50&offset=0&formula=v4&sort_by=score&sort_dir=desc"),
                ("v1 dynamic score weekly (top)", "/feed?period=weekly&limit=10&offset=0&formula=v1&sort_by=score&sort_dir=desc"),
                ("v1 dynamic views monthly (offset 500)", "/feed?period=monthly&limit=10&offset=500&formula=v1&sort_by=views&sort_dir=desc"),
            ]
        )

    print(f"Base URL: {args.base_url}")
    for name, path in cases:
        _bench_case(conn, base_path, name=name, path=path, warmup=args.warmup, runs=args.runs)

    conn.close()


if __name__ == "__main__":
    main()
