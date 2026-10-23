"""Repeatable HTTPX load test for the ingestion API.

Example:
    python -m scripts.load_test --api-key sp_xxx --events 5000 --concurrency 20 --batch-size 50 \
        --duplicate-ratio 0.05 --seed 42 --username admin --password "..."

Reports request throughput/latency, accepted/duplicate/rejected counts, 429/503 (backpressure) counts and,
when admin credentials are supplied, end-to-end processing throughput (events reaching PROCESSED/DEAD_LETTER).
Results depend on your machine; always report the numbers you actually measured.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

import httpx

TYPES = ["order.created", "payment.succeeded", "user.activity", "app.error", "service.health"]


def make_event(rng: random.Random, run_id: str, n: int) -> dict:
    t = TYPES[n % len(TYPES)]
    payload = {
        "order.created": {"order_id": f"o-{n}", "amount": round(rng.uniform(5, 500), 2), "currency": "USD"},
        "payment.succeeded": {"payment_id": f"p-{n}", "amount": round(rng.uniform(5, 500), 2), "currency": "USD"},
        "user.activity": {"user_id": f"u-{rng.randint(1, 500)}", "action": rng.choice(["login", "view", "click"])},
        "app.error": {"service": "api", "message": "boom"},
        "service.health": {"service": "db", "status": rng.choice(["up", "up", "up", "degraded"])},
    }[t]
    return {"event_id": f"{run_id}-{n}", "event_type": t, "source": f"svc-{n % 5}", "schema_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(), "payload": payload}


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


async def main(a: argparse.Namespace) -> None:
    rng = random.Random(a.seed)
    run_id = f"lt{a.seed}-{uuid.uuid4().hex[:6]}"
    events = [make_event(rng, run_id, i) for i in range(a.events)]
    for i in range(len(events)):  # deterministic duplicates
        if i and rng.random() < a.duplicate_ratio:
            events[i] = dict(events[rng.randrange(i)])
    chunks = [events[i:i + a.batch_size] for i in range(0, len(events), a.batch_size)] if a.batch_size > 1 else [[e] for e in events]

    headers = {"X-API-Key": a.api_key}
    latencies: list[float] = []
    status_codes: Counter = Counter()
    totals: Counter = Counter()
    sem = asyncio.Semaphore(a.concurrency)

    async with httpx.AsyncClient(base_url=a.url, headers=headers, timeout=30,
                                 limits=httpx.Limits(max_connections=a.concurrency * 2, keepalive_expiry=3.0)) as client:  # expiry < uvicorn's 5s keep-alive
        async def send(chunk: list[dict]) -> None:
            async with sem:
                r = None
                for attempt in range(a.max_retries + 1):
                    t0 = time.perf_counter()
                    try:
                        if len(chunk) == 1 and a.batch_size == 1:
                            r = await client.post("/api/v1/events", json=chunk[0])
                        else:
                            r = await client.post("/api/v1/events/batch", json={"events": chunk})
                    except httpx.TransportError:  # e.g. a keep-alive connection the server already closed
                        totals["transport_errors"] += 1
                        await asyncio.sleep(0.2)
                        continue
                    latencies.append((time.perf_counter() - t0) * 1000)
                    status_codes[r.status_code] += 1
                    if r.status_code in (429, 503) and attempt < a.max_retries:
                        totals["backpressure_retries"] += 1
                        await asyncio.sleep(float(r.headers.get("Retry-After", "1")))
                        continue
                    break
                if r is not None and r.status_code in (200, 202):
                    body = r.json()
                    if "results" in body:
                        totals["accepted"] += body["accepted"]; totals["duplicate"] += body["duplicates"]
                        totals["rejected"] += body["rejected"]
                    else:
                        totals[body["status"]] += 1

        start = time.perf_counter()
        await asyncio.gather(*(send(c) for c in chunks))
        elapsed = time.perf_counter() - start

        print("\n=== Ingestion ===")
        print(f"requests            : {len(latencies)} in {elapsed:.2f}s  ({len(latencies) / elapsed:.1f} req/s)")
        print(f"events submitted    : {len(events)}  ({len(events) / elapsed:.1f} events/s)")
        print(f"status codes        : {dict(status_codes)}")
        print(f"accepted/dup/reject : {totals['accepted']}/{totals['duplicate']}/{totals['rejected']}")
        print(f"backpressure retries: {totals['backpressure_retries']}  (429/503 responses)")
        print(f"transport errors    : {totals['transport_errors']}  (retried)")
        print(f"latency ms          : avg {statistics.mean(latencies):.1f}  p50 {pct(latencies, 50):.1f}  "
              f"p95 {pct(latencies, 95):.1f}  p99 {pct(latencies, 99):.1f}  max {max(latencies):.1f}")

        if a.username and a.password:
            r = await client.post("/api/v1/auth/login", json={"username": a.username, "password": a.password}, headers={})
            r.raise_for_status()
            auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
            unique_expected = totals["accepted"]
            t_proc = time.perf_counter()
            peak_util = 0.0
            while time.perf_counter() - t_proc < a.drain_timeout:
                q = (await client.get("/api/v1/analytics/queue-status", headers=auth)).json()
                peak_util = max(peak_util, q["utilization"])
                done = q["db_counts"]["PROCESSED"] + q["db_counts"]["DEAD_LETTER"]
                if done >= unique_expected and q["queue_size"] == 0:
                    break
                await asyncio.sleep(0.25)
            drain = time.perf_counter() - t_proc
            ov = (await client.get("/api/v1/analytics/overview", headers=auth, params={"from": datetime.fromtimestamp(time.time() - elapsed - drain - 60, timezone.utc).isoformat()})).json()
            lat = (await client.get("/api/v1/analytics/processing-latency", headers=auth)).json()["overall"]
            print("\n=== Processing ===")
            print(f"drain time after ingest : {drain:.2f}s  (total pipeline {(elapsed + drain):.2f}s -> "
                  f"{unique_expected / (elapsed + drain):.1f} events/s end-to-end)")
            print(f"peak queue utilisation  : {peak_util:.0%} (polled)")
            print(f"processed/failed/pending: {ov['processed']}/{ov['failed']}/{ov['pending']}  failure_rate={ov['failure_rate']}")
            print(f"processing latency ms   : p50 {lat['p50_ms']}  p95 {lat['p95_ms']}  p99 {lat['p99_ms']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--api-key", required=True)
    p.add_argument("--events", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=1, help="1 = single-event endpoint")
    p.add_argument("--duplicate-ratio", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--max-retries", type=int, default=5, help="retries on 429/503")
    p.add_argument("--username"); p.add_argument("--password")
    p.add_argument("--drain-timeout", type=float, default=120)
    asyncio.run(main(p.parse_args()))
