"""
S3-compatible object storage for files (uploads, dumps, DataFrame snapshots) — roadmap B1; used from B2/B5/B8.

Talks only the S3 API through boto3, so the server is swappable by config: bundled SeaweedFS today
(MinIO's community images were discontinued in 2025), Garage or AWS S3 later.

    k = key("data-dumper", dump_id, "dump.sql")      # → "data-dumper/<id>/dump.sql"
    put_bytes(k, data); get_bytes(k); delete(k)

Downloads for the browser should stream through the tool's API: the S3 endpoint is internal to the compose
network, so presigned URLs are only useful between services.
"""

from __future__ import annotations

import threading

from core.state.config import load, require

_lock = threading.Lock()
_client = None
_bucket_ready: set[str] = set()


def client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                cfg = load()
                endpoint = require(cfg.s3_endpoint, "TOOLBOX_S3_ENDPOINT")  # clear error before importing boto3
                import boto3
                from botocore.config import Config

                _client = boto3.client(
                    "s3", endpoint_url=endpoint,
                    aws_access_key_id=require(cfg.s3_access_key, "TOOLBOX_S3_ACCESS_KEY"),
                    aws_secret_access_key=require(cfg.s3_secret_key, "TOOLBOX_S3_SECRET_KEY"),
                    region_name=cfg.s3_region,
                    config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                  retries={"max_attempts": 3, "mode": "standard"},
                                  connect_timeout=5, read_timeout=60))
    return _client


def bucket() -> str:
    return load().s3_bucket


def ensure_bucket(name: str | None = None) -> str:
    name = name or bucket()
    if name in _bucket_ready:
        return name
    from botocore.exceptions import ClientError

    c = client()
    try:
        c.head_bucket(Bucket=name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
            raise
        c.create_bucket(Bucket=name)
    _bucket_ready.add(name)
    return name


def key(tool: str, *parts: str) -> str:
    """Object key namespaced by tool. Rejects empty parts, '..' and leading slashes."""
    segs = [tool, *parts]
    for s in segs:
        if not s or any(piece in ("", ".", "..") for piece in s.split("/")):
            raise ValueError(f"invalid key part {s!r}")
    return "/".join(segs)


def put_bytes(k: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client().put_object(Bucket=ensure_bucket(), Key=k, Body=data, ContentType=content_type)


def get_bytes(k: str) -> bytes | None:
    from botocore.exceptions import ClientError

    try:
        return client().get_object(Bucket=ensure_bucket(), Key=k)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def exists(k: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        client().head_object(Bucket=ensure_bucket(), Key=k)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def delete(k: str) -> None:
    client().delete_object(Bucket=ensure_bucket(), Key=k)


def list_keys(prefix: str) -> list[str]:
    out, token = [], None
    while True:
        kw = {"Bucket": ensure_bucket(), "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = client().list_objects_v2(**kw)
        out += [o["Key"] for o in resp.get("Contents", [])]
        if not resp.get("IsTruncated"):
            return out
        token = resp.get("NextContinuationToken")


def health() -> dict:
    name = ensure_bucket()
    client().head_bucket(Bucket=name)
    return {"endpoint": load().s3_endpoint, "bucket": name}
