"""Notebook tool: workspace/file/zip safety and pip-spec parsing (run anywhere), plus real kernel runs that need
jupyter_client + ipykernel — run those inside the notebook runtime:
    docker cp tests toolbox-rt-notebook-1:/tmp/tests && docker exec -w /app toolbox-rt-notebook-1 python -m pytest /tmp/tests/unit/test_notebook.py -q
"""

import asyncio
import importlib
import importlib.machinery
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    """The repo folder is `notebook-lab/`; the image copies it as package `notebook_lab` — recreate that here."""
    try:
        return importlib.import_module("notebook_lab.workspaces"), importlib.import_module("notebook_lab.kernels")
    except ImportError:
        spec = importlib.machinery.ModuleSpec("notebook_lab", None, is_package=True)
        spec.submodule_search_locations = [str(REPO / "notebook-lab")]
        sys.modules["notebook_lab"] = importlib.util.module_from_spec(spec)
        return importlib.import_module("notebook_lab.workspaces"), importlib.import_module("notebook_lab.kernels")


workspaces, kernels = _load()
WorkspaceError = workspaces.WorkspaceError


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "DATA_DIR", tmp_path)
    workspaces.create("w1")
    return "w1"


# ---- names + paths ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "..", ".hidden", "a/b", "a b", "x" * 80, "-x"])
def test_workspace_names_are_restricted(ws, bad):
    with pytest.raises(WorkspaceError):
        workspaces.create(bad)


def test_duplicate_workspace_is_refused(ws):
    with pytest.raises(WorkspaceError) as e:
        workspaces.create(ws)
    assert e.value.status == 409


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "/etc/passwd", ".venv/bin/python", ".home/x", ".kernels/python3/kernel.json", ".tmp/a"])
def test_paths_cannot_escape_or_touch_the_environment(ws, rel):
    with pytest.raises(WorkspaceError):
        workspaces.safe(ws, rel)


def test_symlink_leaving_the_workspace_is_refused(ws, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    (tmp_path / "ws" / ws / "link").symlink_to(outside)
    with pytest.raises(WorkspaceError) as e:
        workspaces.read_text(ws, "link")
    assert e.value.status == 403


def test_listing_hides_the_environment_folders(ws, tmp_path):
    root = tmp_path / "ws" / ws
    for n in (".venv", ".home", ".kernels", ".tmp"):
        (root / n).mkdir()
    (root / "data.csv").write_text("a\n1\n")
    (root / "sub").mkdir()
    names = [e["name"] for e in workspaces.listing(ws)["entries"]]
    assert names == ["sub", "data.csv"]          # folders first, no dot-folders


def test_rename_never_overwrites_and_delete_is_recursive(ws):
    workspaces.write_text(ws, "a.txt", "1")
    workspaces.write_text(ws, "b.txt", "2")
    with pytest.raises(WorkspaceError):
        workspaces.rename(ws, "a.txt", "b.txt")
    assert workspaces.read_text(ws, "b.txt")["content"] == "2"
    workspaces.write_text(ws, "d/x/y.txt", "z")
    workspaces.remove(ws, "d")
    assert [e["name"] for e in workspaces.listing(ws)["entries"]] == ["a.txt", "b.txt"]


def test_binary_and_huge_files_are_not_opened_in_the_editor(ws, tmp_path):
    (tmp_path / "ws" / ws / "x.bin").write_bytes(b"\x00\x01\x02")
    with pytest.raises(WorkspaceError) as e:
        workspaces.read_text(ws, "x.bin")
    assert e.value.status == 415


def test_streamed_upload_is_atomic_and_size_limited(ws, monkeypatch):
    async def chunks(*parts):
        for p in parts:
            yield p

    assert asyncio.run(workspaces.save_upload(ws, "in/data.csv", chunks(b"ab", b"cd"))) == 4
    assert workspaces.read_text(ws, "in/data.csv")["content"] == "abcd"
    monkeypatch.setattr(workspaces, "MAX_UPLOAD_BYTES", 3)
    with pytest.raises(WorkspaceError) as e:
        asyncio.run(workspaces.save_upload(ws, "big.bin", chunks(b"abcd")))
    assert e.value.status == 413
    assert not [p for p in (workspaces.existing(ws)).iterdir() if p.name == "big.bin" or p.name.startswith(".part-")]


# ---- zip ----------------------------------------------------------------------------------------------------------

def _zip(tmp_path, members):
    p = tmp_path / "ws" / "w1" / "p.zip"
    with zipfile.ZipFile(p, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return p


def test_zip_extracts_a_project_tree(ws, tmp_path):
    _zip(tmp_path, {"proj/main.py": "print(1)", "proj/data/a.csv": "a\n1", "proj/empty/": ""})
    r = workspaces.extract_zip(ws, "p.zip", "", delete_zip=True)
    assert r == {"files": 2, "skipped": 0}
    assert workspaces.read_text(ws, "proj/data/a.csv")["content"] == "a\n1"
    assert (tmp_path / "ws" / ws / "proj" / "empty").is_dir() and not (tmp_path / "ws" / ws / "p.zip").exists()


def test_zip_slip_absolute_reserved_and_symlink_members_are_skipped(ws, tmp_path):
    p = tmp_path / "ws" / ws / "evil.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../../escaped.txt", "x")
        z.writestr("/abs.txt", "x")
        z.writestr(".venv/bin/python", "#!evil")
        z.writestr("C:/win.txt", "x")
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (0o120777) << 16
        z.writestr(link, "/etc/passwd")
        z.writestr("ok.txt", "fine")
    r = workspaces.extract_zip(ws, "evil.zip", "")
    assert r == {"files": 1, "skipped": 5}
    assert sorted(e["name"] for e in workspaces.listing(ws)["entries"]) == ["evil.zip", "ok.txt"]
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path / "ws" / ws / ".venv").exists()


def test_zip_limits_and_invalid_archives(ws, tmp_path, monkeypatch):
    (tmp_path / "ws" / ws / "bad.zip").write_text("not a zip")
    with pytest.raises(WorkspaceError):
        workspaces.extract_zip(ws, "bad.zip", "")
    _zip(tmp_path, {"a": "x" * 100})
    monkeypatch.setattr(workspaces, "MAX_ZIP_BYTES", 50)
    with pytest.raises(WorkspaceError) as e:
        workspaces.extract_zip(ws, "p.zip", "")
    assert e.value.status == 413


def test_download_zip_roundtrip_leaves_out_the_environment(ws, tmp_path):
    root = tmp_path / "ws" / ws
    workspaces.write_text(ws, "src/a.py", "print(1)")
    workspaces.write_text(ws, "b.csv", "x")
    (root / ".venv").mkdir()
    (root / ".venv" / "huge").write_text("x")
    z, name = workspaces.make_zip(ws, "")
    assert name == "w1.zip"
    with zipfile.ZipFile(z) as zf:
        assert sorted(zf.namelist()) == ["b.csv", "src/a.py"]
    z2, name2 = workspaces.make_zip(ws, "src")
    assert name2 == "src.zip" and zipfile.ZipFile(z2).namelist() == ["a.py"]


# ---- environment + pip --------------------------------------------------------------------------------------------

def test_kernel_env_carries_nothing_from_the_server(ws, monkeypatch):
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", "secret")
    monkeypatch.setenv("TOOLBOX_REDIS_URL", "redis://redis")
    env = workspaces.kernel_env(ws)
    assert not [k for k in env if k.startswith("TOOLBOX")] and "secret" not in "".join(env.values())
    assert env["HOME"].endswith(".home") and env["PATH"].startswith(str(workspaces.venv_dir(ws) / "bin"))


@pytest.mark.parametrize("spec,expected", [
    ("tensorflow", ["tensorflow"]),
    ("scikit-learn==1.5.2 pandas>=2.0,<3", ["scikit-learn==1.5.2", "pandas>=2.0,<3"]),
    ("torch --upgrade", ["torch", "--upgrade"]),
    ("-r requirements.txt", ["-r", "requirements.txt"]),
    ("uvicorn[standard]", ["uvicorn[standard]"]),
])
def test_pip_args_accept_normal_specs(spec, expected):
    assert workspaces.pip_args(spec) == expected


@pytest.mark.parametrize("spec", ["", "   ", "--index-url http://evil", "x; rm -rf /", "$(id)", "-r /etc/passwd", "-r ../x", "git+https://x/y"])
def test_pip_args_reject_flags_and_junk(spec):
    with pytest.raises(WorkspaceError):
        workspaces.pip_args(spec)


# ---- output shaping (no kernel needed) ----------------------------------------------------------------------------

def test_stream_chunks_merge_and_are_capped(monkeypatch):
    monkeypatch.setattr(kernels, "MAX_STREAM_CHARS", 10)
    ex = kernels.Execution("c1", "code", None)
    ex.stream("stdout", "abc")
    ex.stream("stdout", "def")
    ex.stream("stderr", "E")
    assert [(o["name"], o["text"]) for o in ex.outputs] == [("stdout", "abcdef"), ("stderr", "E")]
    ex.stream("stdout", "x" * 50)
    ex.stream("stdout", "more")
    assert "truncated" in ex.outputs[-1]["text"] and sum(len(o["text"]) for o in ex.outputs[:-1]) == 10


def test_poll_view_omits_the_body_when_unchanged():
    ex = kernels.Execution("c1", "code", None)
    ex.stream("stdout", "hi")
    assert "outputs" in ex.view(None) and "outputs" in ex.view(ex.version - 1)
    assert "outputs" not in ex.view(ex.version)


def test_display_update_replaces_in_place():
    ex = kernels.Execution("c1", "code", None)
    ex.add({"output_type": "display_data", "data": {"text/plain": "1"}, "metadata": {}}, "d1")
    ex.update_display("d1", {"output_type": "display_data", "data": {"text/plain": "2"}, "metadata": {}})
    assert len(ex.outputs) == 1 and ex.outputs[0]["data"]["text/plain"] == "2"


# ---- a real kernel (needs jupyter_client + ipykernel: the notebook runtime) --------------------------------------

jc = pytest.importorskip("jupyter_client", reason="runs in the rt-notebook container")


def _run(coro):
    return asyncio.run(coro)


async def _cell(s, code, cid="c"):
    ex = await s.submit(code, cid)
    while ex.status in ("queued", "running"):
        await asyncio.sleep(0.1)
    return ex


def test_real_kernel_runs_cells_keeps_state_and_writes_files(ws):
    async def go():
        s = kernels.session(ws)
        await s.start()
        assert s.state == "idle", s.message
        try:
            e1 = await _cell(s, "import pandas as pd\ndf = pd.DataFrame({'a': [1, 2]})\ndf.to_csv('out.csv', index=False)\nprint('hi')")
            e2 = await _cell(s, "len(df)")
            e3 = await _cell(s, "1/0")
            return e1, e2, e3
        finally:
            await s.stop()
            kernels.forget(ws)

    e1, e2, e3 = _run(go())
    assert e1.status == "ok" and e1.outputs[0]["text"] == "hi\n"
    assert e2.outputs[0]["data"]["text/plain"] == "2"          # state survived between cells
    assert e3.status == "error" and e3.outputs[0]["ename"] == "ZeroDivisionError"
    assert "out.csv" in [e["name"] for e in workspaces.listing(ws)["entries"]]


def test_real_kernel_cannot_see_server_environment(ws, monkeypatch):
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", "super-secret")

    async def go():
        s = kernels.session(ws)
        await s.start()
        try:
            return await _cell(s, "import os\nprint([k for k in os.environ if k.startswith('TOOLBOX')])\nimport sys\nprint(sys.prefix)")
        finally:
            await s.stop()
            kernels.forget(ws)

    ex = _run(go())
    assert ex.outputs[0]["text"].splitlines()[0] == "[]" and ".venv" in ex.outputs[0]["text"]


def test_run_all_batch_stops_at_the_first_error(ws):
    async def go():
        s = kernels.session(ws)
        await s.start()
        try:
            a = await s.submit("1/0", "a", "b1")
            b = await s.submit("print('never')", "b", "b1")
            while a.status in ("queued", "running"):
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)
            return a, b
        finally:
            await s.stop()
            kernels.forget(ws)

    a, b = _run(go())
    assert a.status == "error" and b.status == "aborted"
