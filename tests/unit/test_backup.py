"""Ops session: core/state/backup.py streams the bucket into a tar and back (fake S3 here; live test in handoff)."""

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.state import backup  # noqa: E402


class FakeS3:
    def __init__(self, data):
        self.data = dict(data)

    # core.state.objects surface used by backup.py
    def client(self):
        return self

    def ensure_bucket(self):
        return "toolbox"

    def list_objects(self, prefix):
        return [{"key": k, "size": len(v), "last_modified": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                for k, v in sorted(self.data.items()) if k.startswith(prefix)]

    # boto3 client surface
    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.data[Key])}

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.data.pop(o["Key"], None)

    def upload_fileobj(self, f, bucket, key):
        assert f.seekable() is False  # the tar stream must be presented as non-seekable (it crashed before)
        self.data[key] = f.read()


@pytest.fixture
def s3(monkeypatch):
    import core.state as state_pkg

    def use(data):
        fake = FakeS3(data)
        monkeypatch.setattr(state_pkg, "objects", fake, raising=False)
        monkeypatch.setitem(sys.modules, "core.state.objects", fake)
        return fake
    return use


class OneWay(io.RawIOBase):
    """A pipe: readable, not seekable (like stdin in `restore.sh … < objects.tar`)."""

    def __init__(self, data):
        self._b = io.BytesIO(data)

    def readable(self):
        return True

    def readinto(self, b):
        chunk = self._b.read(len(b))
        b[:len(chunk)] = chunk
        return len(chunk)


def test_export_then_import_replaces_the_bucket_exactly(s3):
    src = s3({"datadiff/a/a.result.json.gz": b"\x1f\x8b result", "duck-lab/s/files/t.csv": b"a,b\n1,2\n" * 1000})
    buf = io.BytesIO()
    assert backup.objects_export(buf) == 2
    dst = s3({"stale/x/x.bin": b"old", "datadiff/a/a.result.json.gz": b"different"})
    removed, imported = backup.objects_import(OneWay(buf.getvalue()))
    assert (removed, imported) == (2, 2) and dst.data == src.data


def test_import_refuses_unsafe_names(s3):
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("../../etc/evil")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    s3({})
    with pytest.raises(ValueError, match="unsafe"):
        backup.objects_import(OneWay(buf.getvalue()))
