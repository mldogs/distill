#!/usr/bin/env python3
"""
Simple HTTP benchmark helper for tg_stock API endpoints.

Example:
  python scripts/bench_api.py \
    --url "https://api.example.com/feed?period=weekly&limit=50&offset=0&formula=v4&sort_by=score" \
    --url "https://api.example.com/stats" \
    -n 200 -c 10 --warmup 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from dataclasses import dataclass
from typing import Iterable

import httpx


@dataclass(frozen=True)
class BenchResult:
    url: str
    requests: int
    concurrency: int
    warmup: int
    ok: int
    errors: int
    status_counts: dict[int, int]
    bytes_avg: float
    latency_ms_min: float
    latency_ms_mean: float
    latency_ms_p50: float
    latency_ms_p90: float
    latency_ms_p95: float
    latency_ms_p99: float
    latency_ms_max: float


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return d0 + d1


def _parse_headers(pairs: Iterable[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in pairs:
        if ":" not in raw:
            raise ValueError(f"Invalid header (expected 'Key: Value'): {raw!r}")
        key, value = raw.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def _clean_url(url: str) -> str:
    """
    Make copy/pasted multi-line URLs work.

    Users sometimes split URLs across lines in shell commands; argparse preserves the
    newline/indentation which makes the URL invalid. We remove all whitespace.
    """
    return "".join(url.split())


async def _bench_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
    headers: dict[str, str],
) -> tuple[float, int, int]:
    async with sem:
        started = time.perf_counter()
        resp = await client.get(url, headers=headers)
        elapsed_s = time.perf_counter() - started
        return (elapsed_s * 1000.0, resp.status_code, len(resp.content))


async def bench_url(
    url: str,
    *,
    requests: int,
    concurrency: int,
    warmup: int,
    timeout_s: float,
    verify_tls: bool,
    headers: dict[str, str],
) -> BenchResult:
    limits = httpx.Limits(max_connections=max(concurrency, 10), max_keepalive_connections=max(concurrency, 10))
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=timeout_s, verify=verify_tls, limits=limits) as client:
        for _ in range(warmup):
            try:
                await client.get(url, headers=headers)
            except Exception:
                # warmup should not fail the run (e.g. cold deploy)
                pass

        tasks = [
            asyncio.create_task(_bench_one(client, sem, url, headers))
            for _ in range(requests)
        ]

        lat_ms: list[float] = []
        status_counts: dict[int, int] = {}
        bytes_total = 0

        ok = 0
        errors = 0
        for fut in asyncio.as_completed(tasks):
            try:
                elapsed_ms, status, size = await fut
                lat_ms.append(elapsed_ms)
                status_counts[status] = status_counts.get(status, 0) + 1
                bytes_total += size
                if 200 <= status < 300:
                    ok += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

    lat_ms_sorted = sorted(lat_ms)
    bytes_avg = (bytes_total / len(lat_ms)) if lat_ms else 0.0

    return BenchResult(
        url=url,
        requests=requests,
        concurrency=concurrency,
        warmup=warmup,
        ok=ok,
        errors=errors,
        status_counts=dict(sorted(status_counts.items(), key=lambda kv: kv[0])),
        bytes_avg=bytes_avg,
        latency_ms_min=min(lat_ms_sorted) if lat_ms_sorted else float("nan"),
        latency_ms_mean=statistics.mean(lat_ms_sorted) if lat_ms_sorted else float("nan"),
        latency_ms_p50=_percentile(lat_ms_sorted, 50),
        latency_ms_p90=_percentile(lat_ms_sorted, 90),
        latency_ms_p95=_percentile(lat_ms_sorted, 95),
        latency_ms_p99=_percentile(lat_ms_sorted, 99),
        latency_ms_max=max(lat_ms_sorted) if lat_ms_sorted else float("nan"),
    )


def _print_result(res: BenchResult) -> None:
    def f(x: float) -> str:
        if math.isnan(x):
            return "n/a"
        return f"{x:.1f}"

    print()
    print(res.url)
    print(f"  n={res.requests} c={res.concurrency} warmup={res.warmup}")
    print(f"  ok={res.ok} errors={res.errors} status={res.status_counts}")
    print(
        "  latency_ms"
        f" min={f(res.latency_ms_min)}"
        f" p50={f(res.latency_ms_p50)}"
        f" p90={f(res.latency_ms_p90)}"
        f" p95={f(res.latency_ms_p95)}"
        f" p99={f(res.latency_ms_p99)}"
        f" mean={f(res.latency_ms_mean)}"
        f" max={f(res.latency_ms_max)}"
    )
    print(f"  bytes_avg={res.bytes_avg:.0f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark tg_stock API endpoints.")
    parser.add_argument(
        "--url",
        action="append",
        required=True,
        help="Full URL to benchmark (can be repeated).",
    )
    parser.add_argument("-n", "--requests", type=int, default=200, help="Number of measured requests.")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Concurrent workers.")
    parser.add_argument("--warmup", type=int, default=10, help="Warmup requests before measuring.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Extra header, e.g. 'Authorization: Bearer ...' (can be repeated).",
    )
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification.")
    parser.add_argument("--json-out", type=str, default=None, help="Write results to JSON file.")
    args = parser.parse_args()

    if args.requests <= 0:
        raise SystemExit("--requests must be > 0")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be > 0")
    if args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")

    try:
        headers = _parse_headers(args.header)
    except ValueError as e:
        raise SystemExit(str(e))

    results: list[BenchResult] = []
    for url in args.url:
        url = _clean_url(url)
        results.append(
            asyncio.run(
                bench_url(
                    url,
                    requests=args.requests,
                    concurrency=args.concurrency,
                    warmup=args.warmup,
                    timeout_s=args.timeout,
                    verify_tls=not args.insecure,
                    headers=headers,
                )
            )
        )

    for res in results:
        _print_result(res)

    if args.json_out:
        payload = [res.__dict__ for res in results]
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
