"""
core/clients/datadiff.py — the client for DataDiff Pro's API (roadmap D1).

DataDiff is a shared, stateless service (its own `rt-datadiff` containers, 2 replicas behind the gateway). Other
code compares data through this client instead of importing core.pipeline:

    from core.clients.datadiff import DataDiffClient, DataDiffError
    dd = DataDiffClient()                                   # TOOLBOX_DATADIFF_URL, else in-process (standalone/dev)
    dd.compare_text(left_csv, right_csv, "csv", "csv", strict_mode=True)
    dd.compare_data(left_rows, right_rows, environment_yaml=yml)   # already-parsed rows (DB rows, files)

API (OpenAPI at <base>/docs): POST /api/v1/compare (text), POST /api/v1/compare/structured (parsed values),
GET /api/v1/health. Every response is {"ok": true, ...result} or {"ok": false, "error": "..."} (HTTP 422).

Big compares (roadmap D2) run as background jobs — the input goes to S3 storage, the `worker` diffs it, any replica
returns the result:

    job = dd.submit_data(left_rows, right_rows)        # or submit_text(...)  → job id at once
    dd.job(job)                                        # {"status": "queued|running|done|failed|cancelled", ...}
    result = dd.wait(job, timeout=3600)                # polls, then fetches the result (DataDiffError if it failed)
    dd.cancel(job)

Structured values that JSON cannot carry (Decimal, datetime/date/time, timedelta, UUID, bytes — what database
rows contain) are sent TAGGED ({"__dd__": "decimal", "v": "1.10"}) and turned back into the same Python objects on
the server, so a compare over HTTP sees exactly the values an in-process run_compare() saw (Decimal("1.10") must
not quietly become the float 1.1). Values inside the RESULT that JSON cannot carry come back as strings.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import uuid
from decimal import Decimal
from typing import Any

TAG = "__dd__"
API = "/api/v1"
OPTIONS = ("mapper_csv", "mapper_direction", "strict_mode", "multi_match_rule", "deep_mode", "environment_yaml",
           "null_missing_equivalent")


class DataDiffError(ValueError):
    """The comparison could not run (bad input, bad options, service unreachable). Message is user-facing."""


# ---- value codec (client encodes, server decodes) ------------------------------------------------------------

def encode_value(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, (int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): encode_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [encode_value(x) for x in v]
    if isinstance(v, Decimal):
        return {TAG: "decimal", "v": str(v)}
    if isinstance(v, dt.datetime):
        return {TAG: "datetime", "v": v.isoformat()}
    if isinstance(v, dt.date):
        return {TAG: "date", "v": v.isoformat()}
    if isinstance(v, dt.time):
        return {TAG: "time", "v": v.isoformat()}
    if isinstance(v, dt.timedelta):
        return {TAG: "timedelta", "v": v.total_seconds()}
    if isinstance(v, uuid.UUID):
        return {TAG: "uuid", "v": str(v)}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {TAG: "bytes", "v": base64.b64encode(bytes(v)).decode()}
    return str(v)  # anything else exotic: its text, as json.dumps(default=str) did for the CLI


_DECODERS = {
    "decimal": Decimal, "datetime": dt.datetime.fromisoformat, "date": dt.date.fromisoformat,
    "time": dt.time.fromisoformat, "timedelta": lambda s: dt.timedelta(seconds=s), "uuid": uuid.UUID,
    "bytes": base64.b64decode,
}


def decode_value(v: Any) -> Any:
    if isinstance(v, dict):
        if TAG in v and len(v) == 2 and "v" in v and v[TAG] in _DECODERS:
            return _DECODERS[v[TAG]](v["v"])
        return {k: decode_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [decode_value(x) for x in v]
    return v


def to_json_safe(obj: Any) -> Any:
    """For RESULTS: anything json can't serialize becomes its string (Decimal('1.10') → '1.10')."""
    return json.loads(json.dumps(obj, default=str))


# ---- client -----------------------------------------------------------------------------------------------------

class DataDiffClient:
    def __init__(self, base_url: str | None = None, timeout: float = 900.0):
        url = base_url if base_url is not None else os.environ.get("TOOLBOX_DATADIFF_URL", "")
        self.base_url = url.rstrip("/")
        self.timeout = timeout

    @property
    def mode(self) -> str:
        return "http" if self.base_url else "local"

    def _options(self, options: dict[str, Any]) -> dict[str, Any]:
        bad = set(options) - set(OPTIONS)
        if bad:
            raise TypeError(f"unknown DataDiff option(s): {sorted(bad)}")
        return {k: v for k, v in options.items() if v is not None}

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        try:
            r = httpx.post(f"{self.base_url}{API}{path}", json=body, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise DataDiffError(f"DataDiff service unreachable at {self.base_url}: {exc}") from exc
        try:
            out = r.json()
        except ValueError:
            raise DataDiffError(f"DataDiff answered HTTP {r.status_code} without JSON: {r.text[:200]}") from None
        if not out.get("ok"):
            raise DataDiffError(out.get("error") or out.get("detail") or f"DataDiff failed (HTTP {r.status_code})")
        return out

    def compare_text(self, left_data: str, right_data: str, left_format: str, right_format: str,
                     **options: Any) -> dict[str, Any]:
        """Raw text on both sides (json | xml | csv | yaml | env), exactly like the DataDiff page."""
        opts = self._options(options)
        if self.mode == "local":
            from core.normalizer import normalize
            from core.pipeline import PipelineError, run_compare

            left, err = normalize(left_data, left_format)
            if err:
                raise DataDiffError(f"Left side — {err}")
            right, err = normalize(right_data, right_format)
            if err:
                raise DataDiffError(f"Right side — {err}")
            try:
                return {"ok": True, **to_json_safe(run_compare(left, right, **opts))}
            except PipelineError as exc:
                raise DataDiffError(str(exc)) from exc
        return self._post("/compare", {"left_data": left_data, "right_data": right_data,
                                       "left_format": left_format, "right_format": right_format, **opts})

    def compare_data(self, left: Any, right: Any, **options: Any) -> dict[str, Any]:
        """Already-parsed values on both sides (lists of row dicts, nested objects)."""
        opts = self._options(options)
        if self.mode == "local":
            from core.pipeline import PipelineError, run_compare

            try:
                return {"ok": True, **to_json_safe(run_compare(left, right, **opts))}
            except PipelineError as exc:
                raise DataDiffError(str(exc)) from exc
        return self._post("/compare/structured", {"left": encode_value(left), "right": encode_value(right), **opts})

    # ---- background jobs (roadmap D2) -------------------------------------------------------------------------
    def _submit(self, body: dict[str, Any]) -> str:
        if self.mode == "local":
            from api import jobs

            kind = body.pop("type")
            return jobs.submit(kind, body)
        return self._post("/jobs", body)["job_id"]

    def submit_text(self, left_data: str, right_data: str, left_format: str, right_format: str,
                    **options: Any) -> str:
        return self._submit({"type": "compare", "left_data": left_data, "right_data": right_data,
                             "left_format": left_format, "right_format": right_format, **self._options(options)})

    def submit_data(self, left: Any, right: Any, **options: Any) -> str:
        return self._submit({"type": "compare_structured", "left": encode_value(left), "right": encode_value(right),
                             **self._options(options)})

    def job(self, job_id: str) -> dict[str, Any]:
        if self.mode == "local":
            from api import jobs

            return {"ok": True, **jobs.status(job_id)}
        import httpx

        r = httpx.get(f"{self.base_url}{API}/jobs/{job_id}", timeout=30)
        out = r.json()
        if not out.get("ok"):
            raise DataDiffError(out.get("error") or f"HTTP {r.status_code}")
        return out

    def result(self, job_id: str) -> dict[str, Any]:
        if self.mode == "local":
            import gzip

            from api import jobs

            path = jobs.result_path(job_id)
            if path is None:
                raise DataDiffError("The result is gone (deleted or expired).")
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        import httpx

        r = httpx.get(f"{self.base_url}{API}/jobs/{job_id}/result", timeout=self.timeout)
        out = r.json()
        if r.status_code != 200 or not out.get("ok"):
            raise DataDiffError(out.get("error") or f"HTTP {r.status_code}")
        return out

    def wait(self, job_id: str, timeout: float = 3600.0, poll: float = 1.0) -> dict[str, Any]:
        import time

        end = time.monotonic() + timeout
        while True:
            st = self.job(job_id)
            if st["status"] == "done":
                return self.result(job_id)
            if st["status"] in ("failed", "cancelled"):
                raise DataDiffError(st.get("error") or f"The compare job was {st['status']}.")
            if time.monotonic() > end:
                raise DataDiffError(f"The compare job is still {st['status']} after {timeout:.0f}s (id {job_id}).")
            time.sleep(poll)

    def cancel(self, job_id: str) -> bool:
        if self.mode == "local":
            from api import jobs

            return jobs.cancel(job_id)
        import httpx

        return bool(httpx.delete(f"{self.base_url}{API}/jobs/{job_id}", timeout=30).json().get("cancelled"))

    def health(self) -> dict[str, Any]:
        if self.mode == "local":
            return {"ok": True, "mode": "local"}
        import httpx

        return httpx.get(f"{self.base_url}{API}/health", timeout=10).json()
