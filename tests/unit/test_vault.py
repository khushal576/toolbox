"""core.vault after roadmap B7: key sources + fingerprint, scoped access, backup/restore with re-encryption.
Runs against the SQLite backend in a temp folder (the Postgres/S3 path is verified live — see the B7 handoff)."""

import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytest.importorskip("cryptography")
from cryptography.fernet import Fernet  # noqa: E402

from core import vault  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402


@pytest.fixture
def v(tmp_path, monkeypatch):
    """A fresh, isolated vault (SQLite + local blobs) keyed by TOOLBOX_VAULT_KEY."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", key)
    monkeypatch.delenv("TOOLBOX_VAULT_KEY_FILE", raising=False)
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    data = tmp_path / "vault"
    monkeypatch.setattr(vault, "DATA_DIR", data)
    monkeypatch.setattr(vault, "DB_PATH", data / "vault.db")
    monkeypatch.setattr(vault, "KEY_PATH", data / "vault.key")
    monkeypatch.setattr(vault, "BLOBS_DIR", data / "blobs")
    store = SqlStore("vault", sqlite_path=data / "vault.db", ddl=vault._SCHEMA, backend="sqlite")
    monkeypatch.setattr(vault, "STORE", store)
    monkeypatch.setattr(vault, "_connect", store.connect)
    monkeypatch.setattr(vault, "BLOBS", FileCache("vault", data / "blobs"))
    vault.invalidate_key_cache()
    vault._scope_cache.clear()
    yield vault
    vault.invalidate_key_cache()


def test_round_trip_and_key_from_env(v):
    sid = v.save_secret("db", "postgres_connection", {"password": "pw"})
    assert v.get_secret(sid) == {"password": "pw"}
    assert v.key_info()["source"] == "env TOOLBOX_VAULT_KEY" and not v.key_info()["on_data_volume"]
    assert not v.KEY_PATH.exists()  # nothing written to the data volume when the env provides the key
    assert v.list_secrets("postgres_connection")[0]["name"] == "db"


def test_wrong_key_fails_loudly(v, monkeypatch):
    v.save_secret("db", "postgres_connection", {"password": "pw"})
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", Fernet.generate_key().decode())
    v.invalidate_key_cache()
    with pytest.raises(v.VaultKeyMismatch, match="TOOLBOX_VAULT_KEY"):
        v.list_secrets()


def test_first_fingerprint_refuses_a_key_that_cannot_read_existing_secrets(v, monkeypatch):
    v.save_secret("db", "postgres_connection", {"x": 1})
    with v._connect() as con:  # a database migrated from before B7 has no fingerprint yet
        con.execute("DELETE FROM _vault_meta")
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", Fernet.generate_key().decode())
    v.invalidate_key_cache()
    with pytest.raises(v.VaultKeyMismatch, match="cannot decrypt"):
        v.get_secret_by_name("db")


def test_legacy_key_file_is_used_when_no_env(v, monkeypatch):
    monkeypatch.delenv("TOOLBOX_VAULT_KEY")
    v.DATA_DIR.mkdir(parents=True)
    v.KEY_PATH.write_bytes(Fernet.generate_key())
    v.invalidate_key_cache()
    assert v.key_info()["on_data_volume"] and "warning" in v.health()


def test_datasets_stream_through_blobs(v, tmp_path):
    src = tmp_path / "d.csv"
    src.write_text("a,b\n1,2\n")
    sid = v.save_dataset("ds", "duckdb_result", {"format": "csv"}, src)
    out = v.load_dataset_file(sid)
    assert out.read_text() == "a,b\n1,2\n" and out.suffix == ".csv"
    out.unlink()
    v.delete_secret(sid)
    assert not list(v.BLOBS_DIR.glob(f"{sid}*"))


# ---- scopes ----------------------------------------------------------------------------------------------------

def test_scoped_access_follows_the_manifest(v, tmp_path):
    db_id = v.save_secret("db", "postgres_connection", {"password": "pw"})
    ssh_id = v.save_secret("srv", "ssh_server", {"host": "h"})
    syncer = v.scoped("data-syncer")  # manifest: vault: {read: [postgres_connection]}
    assert syncer.get_secret(db_id) == {"password": "pw"}
    with pytest.raises(v.ScopeError):
        syncer.get_secret(ssh_id)  # a database tool can never be coaxed into reading an SSH login
    with pytest.raises(v.ScopeError):
        syncer.list_secrets("ssh_server")
    with pytest.raises(v.ScopeError):
        syncer.save_secret("x", "postgres_connection", {})
    ssh = v.scoped("ssh-sftp")  # read + write ssh_server
    ssh.update_secret(ssh_id, {"host": "h", "host_key": "pinned"})
    with pytest.raises(v.ScopeError):
        ssh.update_secret(db_id, {})
    src = tmp_path / "d.csv"
    src.write_text("a\n1\n")
    with pytest.raises(v.ScopeError):
        v.scoped("df-studio").save_dataset("d", "k", {"format": "csv"}, src)  # datasets: read
    ds = v.scoped("duck-lab").save_dataset("d", "duckdb_result", {"format": "csv"}, src)  # datasets: write
    v.scoped("df-studio").load_dataset_file(ds).unlink()
    with pytest.raises(v.ScopeError):
        v.scoped("data-syncer").load_dataset_file(ds)
    with pytest.raises(v.ScopeError):
        v.scoped("encode-decode").list_secrets("postgres_connection")  # no `vault:` → no access


def test_plugin_tokens(v):
    t = v.plugin_token("data-syncer")
    assert v.verify_token("data-syncer", t) and not v.verify_token("ssh-sftp", t) and not v.verify_token("", "")


# ---- backup / restore ------------------------------------------------------------------------------------------

def test_backup_restore_same_key(v, tmp_path):
    sid = v.save_secret("db", "postgres_connection", {"password": "pw"})
    src = tmp_path / "d.csv"
    src.write_text("x\n1\n")
    did = v.save_dataset("ds", "duckdb_result", {"format": "csv"}, src)
    zp = tmp_path / "b.zip"
    v.export_backup(zp)
    v.clear_all()
    assert v.import_backup(zp) == {"secrets": 2, "datasets": 1, "re_encrypted": 0}
    assert v.get_secret(sid) == {"password": "pw"} and v.load_dataset_file(did).read_text() == "x\n1\n"


def test_restore_re_encrypts_a_backup_made_with_another_key(v, tmp_path):
    """A pre-B7 (format 1) backup: vault.db + its own vault.key + blobs/, from a different vault."""
    key = Fernet.generate_key()
    old = Fernet(key)
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as con:
        con.executescript(vault._SCHEMA)
        con.execute("INSERT INTO secrets VALUES ('s1','db','postgres_connection','t','t',?,NULL)",
                    (old.encrypt(b'{"password": "old"}'),))
        con.execute("INSERT INTO secrets VALUES ('d1','ds','duckdb_result','t','t',?,'d1.blob')",
                    (old.encrypt(b'{"format": "csv"}'),))
    blob = tmp_path / "d1.blob"
    token = old.encrypt(b"a,b\n3,4\n")
    blob.write_bytes(len(token).to_bytes(4, "big") + token)
    zp = tmp_path / "old.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.write(db, "vault.db")
        zf.writestr("vault.key", key)
        zf.write(blob, "blobs/d1.blob")
    v.save_secret("will be replaced", "x", {})
    assert v.import_backup(zp) == {"secrets": 2, "datasets": 1, "re_encrypted": 1}
    assert [s["name"] for s in v.list_secrets()] == ["db", "ds"]
    assert v.get_secret("s1") == {"password": "old"}  # readable with THIS vault's key now
    assert v.load_dataset_file("d1").read_text() == "a,b\n3,4\n"


def test_restore_refuses_a_damaged_backup_before_replacing_anything(v, tmp_path):
    keep = v.save_secret("keep", "x", {"a": 1})
    zp = tmp_path / "bad.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("vault.key", Fernet.generate_key())
        zf.writestr("vault.json", json.dumps({"format": 2, "secrets": [
            {"id": "z", "name": "z", "kind": "x", "created_at": "t", "updated_at": "t",
             "ciphertext": "bm90LWEtdG9rZW4=", "blob_path": None}]}))
    with pytest.raises(ValueError, match="can't be decrypted"):
        v.import_backup(zp)
    assert v.get_secret(keep) == {"a": 1}
