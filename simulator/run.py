"""Bounded deterministic workload; credentials supplied from a local ignored JSON file."""

import argparse
import json
import random
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCENARIO = [4, 7, 4] + [7] * 12 + [4] * 5


def readings(start, run_id, rounds=20, units=5, interval=30):
    for tick in range(rounds):
        for unit in range(units):
            freezer = unit % 2 == 1
            temperature = SCENARIO[min(tick, len(SCENARIO) - 1)] if unit == 0 else (-20 if freezer else 4)
            yield (
                tick,
                {
                    "reading_id": uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{unit}:{tick}").hex,
                    "unit_id": f"unit-{unit + 1}",
                    "site_id": "demo-site",
                    "schema_version": 1,
                    "observed_at": (start + timedelta(seconds=tick * interval)).isoformat().replace("+00:00", "Z"),
                    "temperature": temperature,
                },
            )


def send(url, token, reading):
    body = json.dumps(reading).encode()
    for attempt in range(3):
        try:
            with urlopen(
                Request(
                    url + "/readings",
                    data=body,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
                ),
                timeout=8,
            ) as result:
                if result.status == 202:
                    return
                raise RuntimeError("unexpected response")
        except HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise RuntimeError(f"non-retryable HTTP {exc.code}") from None
            if attempt == 2:
                raise RuntimeError(f"HTTP {exc.code}; attempts exhausted") from None
        except (URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("network attempts exhausted") from None
        time.sleep(random.uniform(0, 0.5 * 2**attempt))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url")
    p.add_argument("--credentials")
    p.add_argument("--interval", type=int, default=30)
    p.add_argument("--duration", type=int, default=600)
    p.add_argument("--max-readings", type=int, default=100)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not 1 <= args.interval <= 30 or not 1 <= args.duration <= 600 or not 1 <= args.max_readings <= 100:
        p.error("interval 1..30, duration 1..600, max-readings 1..100 required")
    if not args.dry_run and (not args.url or not args.url.startswith("https://") or not args.credentials):
        p.error("HTTPS URL and credential file required")
    credentials = {} if args.dry_run else json.load(open(args.credentials))
    start = datetime.now(timezone.utc)
    deadline = time.monotonic() + args.duration
    run_id = uuid.uuid4().hex

    class DurationReached(Exception):
        pass

    def stop(signum, frame):
        raise DurationReached()

    # macOS/Linux: the process exits at the wall-clock bound even during DNS/HTTP waits.
    previous = signal.signal(signal.SIGALRM, stop) if not args.dry_run else None
    if not args.dry_run:
        signal.setitimer(signal.ITIMER_REAL, args.duration)
    try:
        for n, (tick, r) in enumerate(
            readings(start, run_id, rounds=args.duration // args.interval, interval=args.interval)
        ):
            if n >= args.max_readings:
                break
            if not args.dry_run:
                wait = (start + timedelta(seconds=tick * args.interval) - datetime.now(timezone.utc)).total_seconds()
                if wait > 0:
                    time.sleep(wait)
                if time.monotonic() >= deadline:
                    break
                send(args.url.rstrip("/"), credentials[r["unit_id"]], r)
            print(json.dumps(r))
    except DurationReached:
        print(json.dumps({"status": "duration_limit_reached"}))
    finally:
        if not args.dry_run:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    main()
