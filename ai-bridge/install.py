#!/usr/bin/env python3
"""
ai-bridge/install.py — set up / remove / check the AI helper bridge on this computer (roadmap H1).

    python3 ai-bridge/install.py install [--write-env] [--no-systemd] [--dry-run]
    python3 ai-bridge/install.py status
    python3 ai-bridge/install.py uninstall [--purge]

install: finds `claude` and `docker`, writes ~/.config/toolbox-helper/{config.json,token,mcp.json} (token 0600), writes a systemd USER unit
(toolbox-helper.service, restarts on failure, starts at login) and starts it. --write-env appends TOOLBOX_HELPER_URL / TOOLBOX_HELPER_TOKEN to
the repo's .env (a backup is made first; nothing else in .env is touched). The Claude login is never copied anywhere.
Safe to run again: it keeps the existing token.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONF_DIR = Path("~/.config/toolbox-helper").expanduser()
UNIT_DIR = Path("~/.config/systemd/user").expanduser()
UNIT = "toolbox-helper.service"
PORT = 8787


def find(name: str) -> str:
    p = shutil.which(name)
    if p:
        return str(Path(p))
    for cand in sorted((Path.home() / ".nvm/versions/node").glob(f"*/bin/{name}"), reverse=True) if name == "claude" else []:
        return str(cand)
    raise SystemExit(f"Could not find '{name}' on this computer. Install it first.")


def mcp_config(docker: str) -> dict:
    return {"mcpServers": {"toolbox": {"command": docker, "args": ["compose", "-f", str(REPO / "docker-compose.yml"), "run", "--rm", "-T", "--no-deps", "worker", "python", "-m", "mcp_server"]}}}


def unit_text(python: str, conf_dir: Path) -> str:
    return f"""[Unit]
Description=Toolbox AI helper bridge (local only)
After=network.target

[Service]
ExecStart={python} {HERE / 'bridge.py'} --config {conf_dir / 'config.json'}
Restart=on-failure
RestartSec=3
# the bridge only starts the owner's own `claude`; it needs no extra rights
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""


def build(conf_dir: Path, claude: str, docker: str, python: str) -> dict:
    token_file = conf_dir / "token"
    cfg = {"claude_bin": claude, "work_dir": str(conf_dir / "workdir"), "mcp_config": str(conf_dir / "mcp.json"), "token_file": str(token_file),
           "port": PORT, "bind": ["127.0.0.1"], "bind_docker_bridge": True, "timeout_s": 240}
    return {"config": cfg, "mcp": mcp_config(docker), "unit": unit_text(python, conf_dir)}


def write_private(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def write_env(env_path: Path, token: str) -> str:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    keep = [l for l in lines if not l.startswith(("TOOLBOX_HELPER_URL=", "TOOLBOX_HELPER_TOKEN="))]
    if env_path.exists():
        backup = env_path.with_name(f".env.bak-helper-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(env_path, backup)
        backup.chmod(0o600)
    keep += [f"TOOLBOX_HELPER_URL=http://host.docker.internal:{PORT}", f"TOOLBOX_HELPER_TOKEN={token}"]
    env_path.write_text("\n".join(keep) + "\n")
    env_path.chmod(0o600)
    return str(env_path)


def systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def install(a) -> None:
    claude, docker, python = find("claude"), find("docker"), sys.executable or "/usr/bin/python3"
    plan = build(CONF_DIR, claude, docker, python)
    token_file = CONF_DIR / "token"
    token = token_file.read_text().strip() if token_file.exists() and len(token_file.read_text().strip()) >= 24 else secrets.token_urlsafe(32)
    if a.dry_run:
        print(json.dumps(plan["config"], indent=2)); print(plan["unit"]); return
    write_private(token_file, token + "\n")
    write_private(CONF_DIR / "config.json", json.dumps(plan["config"], indent=2) + "\n")
    write_private(CONF_DIR / "mcp.json", json.dumps(plan["mcp"], indent=2) + "\n")
    (CONF_DIR / "workdir").mkdir(exist_ok=True)
    print(f"Settings written to {CONF_DIR} (token file is private).")
    if a.write_env:
        print("Added the helper address and token to", write_env(REPO / ".env", token), "(backup kept). Now run: docker compose up -d --no-deps toolbox")
    if a.no_systemd:
        print("Skipped the background service (--no-systemd). Start by hand: python3", HERE / "bridge.py"); return
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (UNIT_DIR / UNIT).write_text(plan["unit"])
    for cmd in (("daemon-reload",), ("enable", UNIT), ("restart", UNIT)):
        r = systemctl(*cmd)
        if r.returncode:
            raise SystemExit(f"systemctl {' '.join(cmd)} failed: {r.stderr.strip()}")
    print("The helper service is installed and running; it starts again at every login.")
    print("If your computer has a firewall (ufw), Toolbox's container must be allowed to reach the helper — once, with admin rights:")
    print("    sudo ufw allow from 172.16.0.0/12 to any port 8787 proto tcp   # Docker's private networks only, not your Wi-Fi/LAN")
    print("To also start it at boot, before you log in (optional): loginctl enable-linger", Path.home().name)


def status(_a) -> None:
    r = systemctl("is-active", UNIT); e = systemctl("is-enabled", UNIT)
    print("service:", r.stdout.strip() or "unknown", "| starts at login:", e.stdout.strip() or "unknown")
    print("settings:", "present" if (CONF_DIR / "config.json").exists() else "missing", "| token:", "present" if (CONF_DIR / "token").exists() else "missing")


def uninstall(a) -> None:
    for cmd in (("disable", "--now", UNIT),):
        systemctl(*cmd)
    (UNIT_DIR / UNIT).unlink(missing_ok=True)
    systemctl("daemon-reload")
    if a.purge:
        shutil.rmtree(CONF_DIR, ignore_errors=True)
    print("Helper service removed." + (" Settings and token deleted." if a.purge else " Settings kept (use --purge to delete them)."))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install"); i.add_argument("--write-env", action="store_true"); i.add_argument("--no-systemd", action="store_true"); i.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    u = sub.add_parser("uninstall"); u.add_argument("--purge", action="store_true")
    a = ap.parse_args()
    {"install": install, "status": status, "uninstall": uninstall}[a.cmd](a)


if __name__ == "__main__":
    main()
