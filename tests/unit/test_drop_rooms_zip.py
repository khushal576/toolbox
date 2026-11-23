"""Drop Rooms (roadmap DR2): the browser's folder-to-ZIP builder (ui/zip.js, run by node), checked by Python's own zipfile, and then by the
server's own safety check (store.check_zip)."""

import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _store():
    spec = importlib.util.spec_from_file_location("drop_rooms_store_zip", REPO / "drop-rooms" / "store.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_zip_the_browser_builds_is_a_valid_safe_zip(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(REPO / "tests" / "unit" / "drop_rooms_zip_cases.js"), str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.startswith("OK"), r.stdout + r.stderr
    z = zipfile.ZipFile(tmp_path / "folder.zip")
    assert z.testzip() is None                                                     # every CRC matches
    names = z.namelist()
    assert names == ["My Folder/readme.txt", "My Folder/sub/ünïcode — файл.txt", "My Folder/sub/empty.txt", "My Folder/data.bin",
                     "My Folder/dup.txt", "My Folder/dup (2).txt", "escape.txt", "abs/evil.txt"], names
    assert z.read("My Folder/readme.txt") == b"hello zip\n" and z.read("My Folder/sub/ünïcode — файл.txt") == b"unicode name ok"
    assert z.read("My Folder/sub/empty.txt") == b"" and z.read("My Folder/data.bin") == (tmp_path / "bin.expected").read_bytes()
    assert z.read("My Folder/dup.txt") == b"first" and z.read("My Folder/dup (2).txt") == b"second"
    assert all(i.compress_type == zipfile.ZIP_STORED and i.flag_bits & 0x800 for i in z.infolist())
    with open(tmp_path / "folder.zip", "rb") as f:                                 # and the server accepts it
        assert _store().check_zip(f) == 8


def test_the_server_refuses_zips_that_could_write_outside_the_folder(tmp_path):
    store = _store()

    def make(names):
        p = tmp_path / "x.zip"
        with zipfile.ZipFile(p, "w") as z:
            for n in names:
                z.writestr(n, b"x")
        return open(p, "rb")

    for bad in (["../evil.txt"], ["a/../../evil"], ["/abs/evil"], ["C:/evil"], ["a\\..\\..\\evil"], ["ok.txt", "x/../../y"]):
        with make(bad) as f, pytest.raises(store.BadRequest, match="unsafe"):
            store.check_zip(f)
    with make(["a.txt", "dir/b.txt", "dir/"]) as f:
        assert store.check_zip(f) == 2                                              # directories are not counted as files
    (tmp_path / "junk").write_bytes(b"not a zip at all")
    with open(tmp_path / "junk", "rb") as f, pytest.raises(store.BadRequest, match="valid folder"):
        store.check_zip(f)
    with make([f"f{i}.txt" for i in range(store.MAX_ZIP_ENTRIES + 1)]) as f, pytest.raises(store.BadRequest, match="too many"):
        store.check_zip(f)
