"""
Helpers for scripts/backup.sh and scripts/restore.sh (Ops session). Run inside a one-off container of the
`worker` service (it has boto3, redis and the TOOLBOX_* settings):

    docker compose run --rm --no-deps -T worker python -m core.state.backup objects-export > objects.tar
    docker compose run --rm --no-deps -T worker python -m core.state.backup objects-import < objects.tar
    docker compose run --rm --no-deps -T worker python -m core.state.backup mark <file name> <bytes>
    docker compose run --rm --no-deps -T worker python -m core.state.backup last

objects-export streams every object of the S3 bucket into a tar on stdout (one member per key, never the whole
bucket in memory); objects-import REPLACES the bucket's content with a tar from stdin (objects not in the backup are
deleted, so the files match the restored database). `mark` records the last backup for the Status page
(Redis `toolbox:backup:last`).
"""

from __future__ import annotations

import json
import sys
import tarfile
import time

LAST_KEY = "toolbox:backup:last"


def objects_export(out) -> int:
    from core.state import objects

    client, bucket, n = objects.client(), objects.ensure_bucket(), 0
    with tarfile.open(fileobj=out, mode="w|") as tar:
        for o in objects.list_objects(""):
            info = tarfile.TarInfo(o["key"])
            info.size = int(o["size"])
            info.mtime = int(o["last_modified"].timestamp())
            body = client.get_object(Bucket=bucket, Key=o["key"])["Body"]
            tar.addfile(info, fileobj=body)
            n += 1
    return n


class _Unseekable:
    """A tar member read from a STREAM can't seek, but asking it crashes (tarfile's _Stream has no seekable()).
    boto3 asks; this answers "no", so it uses its streaming (non-seekable) upload."""

    def __init__(self, f):
        self._f = f

    def read(self, n: int = -1) -> bytes:
        return self._f.read(n)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def objects_import(inp) -> tuple[int, int]:
    from core.state import objects

    client, bucket = objects.client(), objects.ensure_bucket()
    old = [o["key"] for o in objects.list_objects("")]
    for i in range(0, len(old), 1000):
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in old[i:i + 1000]]})
    n = 0
    with tarfile.open(fileobj=inp, mode="r|") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if member.name.startswith("/") or ".." in member.name.split("/"):
                raise ValueError(f"unsafe name in backup: {member.name!r}")
            client.upload_fileobj(_Unseekable(tar.extractfile(member)), bucket, member.name)
            n += 1
    return len(old), n


def mark(name: str, size: int) -> None:
    from core.state import sessions

    sessions.client().set(LAST_KEY, json.dumps({"at": time.time(), "file": name, "bytes": size}))


def last() -> dict | None:
    from core.state import sessions

    raw = sessions.client().get(LAST_KEY)
    return json.loads(raw) if raw else None


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "objects-export":
        n = objects_export(sys.stdout.buffer)
        print(f"exported {n} object(s)", file=sys.stderr)
    elif cmd == "objects-import":
        removed, n = objects_import(sys.stdin.buffer)
        print(f"removed {removed} existing object(s), imported {n}", file=sys.stderr)
    elif cmd == "mark" and len(argv) == 4:
        mark(argv[2], int(argv[3]))
    elif cmd == "last":
        print(json.dumps(last()))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
