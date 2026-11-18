"""Hardware gateway adapter: persist an ID before HTTP, then flush a finite outbox.

A physical driver calls enqueue(sensor.read_temperature()) and flush(). This module
does not claim to include or validate a driver for any particular sensor hardware.
"""

import argparse
import json
import random
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.domain import validate


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Gateway redirects are disabled to protect device credentials")


class Gateway:
    def __init__(self, endpoint, unit, site, credential, spool):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Use the trusted HTTPS API origin without credentials or query parameters")
        self.endpoint, self.unit, self.site, self.credential = endpoint.rstrip("/"), unit, site, credential
        path = Path(spool)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS readings (position INTEGER PRIMARY KEY, reading_id TEXT UNIQUE, body TEXT)"
        )
        self.opener = build_opener(NoRedirect())

    def enqueue(self, temperature, observed_at=None):
        if self.db.execute("SELECT count(*) FROM readings").fetchone()[0] >= 100:
            raise RuntimeError("The bounded gateway outbox is full; restore connectivity before sampling again")
        reading = validate(
            {
                "schema_version": 1,
                "reading_id": uuid.uuid4().hex,
                "unit_id": self.unit,
                "site_id": self.site,
                "temperature": temperature,
                "observed_at": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            time.time(),
        )
        self.db.execute(
            "INSERT INTO readings (reading_id, body) VALUES (?, ?)", (reading["reading_id"], json.dumps(reading))
        )
        self.db.commit()
        return reading["reading_id"]

    def flush(self, maximum=100):
        if type(maximum) is not int or not 1 <= maximum <= 100:
            raise ValueError("Flush limit must be 1–100 readings")
        sent = 0
        for position, body in self.db.execute(
            "SELECT position, body FROM readings ORDER BY position LIMIT ?", (maximum,)
        ).fetchall():
            for attempt in range(3):
                try:
                    req = Request(
                        self.endpoint + "/readings",
                        data=body.encode(),
                        headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.credential},
                    )
                    with self.opener.open(req, timeout=8) as result:
                        if result.status != 202:
                            raise RuntimeError("Unexpected ingestion response; reading retained in outbox")
                    break
                except HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                        raise RuntimeError(f"Ingestion returned {exc.code}; reading retained in outbox") from None
                except (URLError, TimeoutError):
                    if attempt == 2:
                        raise RuntimeError("Gateway offline; reading retained in outbox") from None
                time.sleep(random.uniform(0, 0.25 * 2**attempt))
            self.db.execute("DELETE FROM readings WHERE position = ?", (position,))
            self.db.commit()
            sent += 1
        return sent

    def close(self):
        self.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--spool", type=Path, default=Path(".local/gateway.sqlite"))
    parser.add_argument("--temperature", type=float, help="One measurement from a hardware driver, in Celsius")
    parser.add_argument("--flush-limit", type=int, default=100)
    args = parser.parse_args()
    keys = json.loads(args.credentials.read_text())
    gateway = Gateway(args.endpoint, args.unit, args.site, keys[args.unit], args.spool)
    try:
        if args.temperature is not None:
            gateway.enqueue(args.temperature)
        print(json.dumps({"delivered": gateway.flush(args.flush_limit)}))
    finally:
        gateway.close()


if __name__ == "__main__":
    main()
