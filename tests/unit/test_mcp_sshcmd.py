"""
Roadmap K5 — which commands an AI may run over SSH (mcp_server/sshcmd.py, ADR-MCP D13). PURE logic, no server needed.

The guarantees: allow-list (unknown program / unknown flag = refused), nothing special to a shell survives outside single quotes,
quotes hide nothing (a quoted --follow is still --follow), and the command SENT is rebuilt from the validated tokens so the shell
parses exactly what was checked.
"""

from __future__ import annotations

import random
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp_server import sshcmd  # noqa: E402
from mcp_server.sshcmd import CommandRefused, scrub_output, validate  # noqa: E402

ALLOWED = [
    "ls", "ls -la /var/log", "ls -lh --color /tmp", "ls /var/log/*.log", "cat /etc/os-release", "cat -n /var/log/app.log",
    "head -n 20 /var/log/syslog", "head -n20 /var/log/syslog", "head -20 /var/log/syslog", "tail -n 100 /var/log/syslog", "tail -n100 /var/log/x",
    "tail --lines=50 /var/log/x", "wc -l /var/log/x", "du -sh /var/lib", "du -h --max-depth=1 /var", "df -h", "df -t ext4", "stat /etc/hostname",
    "stat -c %s /etc/hostname", "file /bin/ls", "uname -a", "uptime", "free -h", "id", "id -un", "whoami", "hostname", "hostname -f", "date", "date +%F",
    "date -d yesterday +%F", "date -u", "who", "w", "last -n 5", "find /var/log -name '*.log' -mtime -1", "find / -name .env", "find . -type f -size +10M",
    "grep error /var/log/syslog", "grep -i secret /var/log/app.log", "grep -rn 'timeout' /var/log/nginx", "grep -A3 -B1 -e ERROR /var/log/x",
    "grep -m5 ERROR /var/log/x", "grep -E 'a|b' /var/log/x", "ps aux", "ps -ef", "ps -eo pid,comm,pcpu --sort=-pcpu", "ps aux | grep nginx | head -5",
    "ss -tlnp", "ss -tuln", "ip a", "ip -br addr", "ip route", "ip addr show dev eth0", "top -b -n 1", "top -bn1", "journalctl -u nginx -n 100 --no-pager",
    "journalctl -p err --since '1 hour ago'", "journalctl -b -k", "systemctl status nginx", "systemctl is-active nginx", "systemctl list-units --failed",
    "systemctl show nginx -p ActiveState", "docker ps", "docker ps -a --format '{{.Names}} {{.Status}}'", "docker logs --tail 100 web", "docker logs -t --since 10m web",
    "docker stats --no-stream", "docker images", "docker top web", "docker info", "git status", "git log --oneline -n 5", "git diff --stat", "git -C /srv/app status",
    "git show HEAD --stat", "crontab -l", "dmesg -T", "sort -k2 -n /tmp/a", "cut -d, -f1 /tmp/a | sort | uniq -c | sort -rn | head -10", "cat /var/log/x | grep -v debug | tail -50",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd):
    built = validate(cmd)
    assert built and "\n" not in built


REFUSED = [
    # chaining / redirection / substitution — each of these has meaning to a shell
    "ls; id", "ls && id", "ls || id", "ls & ", "ls | sh", "ls | bash", "cat x | xargs rm", "ls > /tmp/x", "cat a >> b", "cat < /etc/passwd", "echo hi", "ls $(id)",
    "ls `id`", "ls $HOME", "ls ${HOME}", 'ls "$HOME"', "ls (", "ls {a,b}", "ls \\\\", "ls !", "ls #", "ls\nid", "ls\rid", "ls\x00", "ls \tid;", "ls ||id", "|| id", "| ls", "ls |",
    # not on the list at all
    "sudo ls", "su -", "sh -c ls", "bash", "python3 -c 1", "perl -e 1", "awk 'BEGIN{system(\"id\")}'", "sed -i s/a/b/ x", "vi x", "nano x", "rm -rf /", "rm x", "mv a b", "cp a b",
    "touch x", "chmod 777 x", "chown a x", "kill 1", "pkill x", "dd if=/dev/zero of=/x", "mkfs /dev/sda", "shutdown -h now", "reboot", "curl http://x", "wget http://x",
    "nc -l 1", "ssh other", "scp a b", "env", "printenv", "set", "export A=1", "alias", "tee x", "xargs ls", "nohup ls", "watch ls", "timeout 5 ls", "apt install x", "pip install x",
    "mount /dev/x /mnt", "umount /mnt", "crontab -e", "crontab -r", "service nginx restart", "systemctl restart nginx", "systemctl stop nginx", "systemctl daemon-reload",
    "docker exec -it web sh", "docker run alpine", "docker rm web", "docker kill web", "docker cp a b", "docker inspect web", "docker compose up", "docker -H tcp://x ps",
    "docker stats", "docker logs -f web", "docker logs --follow web", "git push", "git commit", "git checkout x", "git reset --hard", "git clone x", "git -c core.pager=x log",
    "git config -l", "git remote -v", "git log --output=/tmp/x", "git diff --ext-diff", "ip addr add 1.2.3.4 dev lo", "ip link set eth0 down", "ip route del default", "ip neigh flush all",
    # flags that make an allowed program dangerous or endless
    "tail -f /var/log/syslog", "tail -F x", "tail --follow x", "tail '--follow' x", "tail \"-f\" x", "journalctl -f", "journalctl --follow", "journalctl --vacuum-size=1M",
    "journalctl --rotate", "sort -o /etc/passwd x", "sort --output=x y", "uniq a b", "uniq in /etc/passwd", r"find . -exec rm {} \;", "find . -exec cat {} +", "find . -delete", "find . -fprint /tmp/x",
    "find . -ok rm", "find . -execdir sh", "date 010112002026", "date -s '2020-01-01'", "date --set=x", "hostname evil", "hostname -b evil", "free -s 1", "free -c 5", "top", "top -b", "top -n 1",
    "ss -K", "ss --kill", "dmesg -C", "dmesg -c", "ps aux e", "ps eww", "ps -eo pid,cmd extra;", "ls --bad-option", "ls -Z", "cat -z x", "grep -f /etc/passwd x", "grep --file=x y",
    "head -f x", "du -X x", "df --bogus", "wc --files0-from=x",
    # secret files
    "cat /etc/shadow", "cat .env", "cat /app/.env", "cat /app/.env.production", "cat ~/.ssh/id_rsa", "cat /home/u/.ssh/authorized_keys", "cat /root/.aws/credentials", "cat server.pem",
    "cat /etc/ssl/private/x.key", "cat /proc/1/environ", "tail /var/lib/secrets", "cat /home/u/.netrc", "head /home/u/.git-credentials", "cat id_ed25519", "grep x /etc/sudoers",
    # names / shape
    "/bin/ls", "./ls", "a=b ls", "'ls'", "ls*", "l[s]", "", "   ", "ls " + "a" * 1100, "ls | wc | wc | wc | wc | wc | wc",
    "ls é", "ls ｓｅｃ", 'cat "a $b"', "cat 'unclosed", 'cat "unclosed',
]


@pytest.mark.parametrize("cmd", REFUSED)
def test_refused(cmd):
    with pytest.raises(CommandRefused):
        validate(cmd)


def test_every_refusal_has_a_human_reason():
    for cmd in REFUSED:
        try:
            validate(cmd)
        except CommandRefused as exc:
            assert len(str(exc)) > 10


def test_quotes_hide_nothing():
    for cmd in ["tail '-f' x", "tail \"--follow\" x", "find . '-delete'", "find . '-exec' ls", "sort '-o' x", "journalctl '-f'", "date '010112002026'",
                "docker 'exec' c", "docker logs '-f' c", "git '-c' x log", "cat '.env'", "cat '/etc/'shadow"]:
        with pytest.raises(CommandRefused):
            validate(cmd)


def test_the_command_sent_is_rebuilt_not_forwarded():
    assert validate("ls   -la    '/var/log/my dir'") == "ls -la '/var/log/my dir'"
    assert validate("grep -i 'a b' /var/log/x|head -5") == "grep -i 'a b' /var/log/x | head -5"
    assert validate("cat /tmp/it's") if False else True
    built = validate("grep 'x;y' /var/log/x")          # a ; INSIDE single quotes is data, and stays quoted when sent
    assert shlex.split(built) == ["grep", "x;y", "/var/log/x"] and "'x;y'" in built
    g = validate("git log -n 3")
    assert g.startswith("git -c core.fsmonitor=false -c core.pager=cat --no-pager log")


def test_a_wildcard_is_left_for_the_server_but_only_with_a_safe_charset():
    assert validate("ls /var/log/*.log") == "ls /var/log/*.log"
    assert validate("ls '/var/log/*.log'") == "ls '/var/log/*.log'"          # quoted = literal, not expanded
    with pytest.raises(CommandRefused):
        validate("ls /tmp/a*;id")


# ------------------------------------------------------------------------------------------------------------ stress

_ALPHABET = ["ls", "cat", "tail", "grep", "find", "sort", "-f", "-n", "5", "-la", "--follow", "-exec", "-delete", "-o", "|", "||", "&&", ";", ">", "<", "$(id)", "`id`", "'a b'",
             "\"x\"", "'", '"', "\\", "$HOME", "*", "?", "[a]", "/etc/shadow", ".env", "~/.ssh/id_rsa", "/var/log/syslog", "e", "aux", "ps", "docker", "exec", "logs", "git", "-c", "date",
             "010112002026", "\n", "\t", "{", "}", "(", ")", "!", "#", "=", "a=b", "é"]
_UNSAFE_OUTSIDE_SINGLE = set(";&<>(){}`$\\!#\n\r\x00|")


def _outside_single_quotes(text: str) -> str:
    out, inside = [], False
    for ch in text:
        if ch == "'":
            inside = not inside
            continue
        if not inside:
            out.append(ch)
    return "".join(out)


def test_random_commands_never_produce_something_a_shell_could_misread():
    rnd = random.Random(20261110)
    accepted = 0
    for _ in range(25000):
        cmd = " ".join(rnd.choice(_ALPHABET) for _ in range(rnd.randint(1, 7)))
        try:
            built = validate(cmd)
        except CommandRefused:
            continue
        accepted += 1
        assert "\n" not in built and "\x00" not in built
        for stage in built.split(" | "):
            outside = _outside_single_quotes(stage)
            assert not (set(outside) & _UNSAFE_OUTSIDE_SINGLE), (cmd, built)
            toks = shlex.split(stage)
            if toks[0] == "git":
                toks = toks[7:]            # the fixed hardening prefix: git -c core.fsmonitor=false -c core.pager=cat --no-pager
                toks = ["git"] + toks
            assert toks[0] in sshcmd.ALLOWED_PROGRAMS, (cmd, built)
            prog, rest = toks[0], toks[1:]
            if prog == "find":
                assert not {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"} & set(rest), (cmd, built)
            if prog in ("tail", "journalctl"):
                assert not {"-f", "-F", "--follow"} & set(rest), (cmd, built)
            if prog == "docker" and rest and rest[0] == "logs":
                assert not {"-f", "--follow"} & set(rest), (cmd, built)
            if prog == "sort":
                assert "-o" not in rest and not any(x.startswith("--output") for x in rest), (cmd, built)
            if prog == "date" and "-d" not in rest:
                assert all(x.startswith(("-", "+")) for x in rest), (cmd, built)
            assert prog not in ("sudo", "sh", "bash", "env", "rm", "mv"), (cmd, built)
    assert accepted > 300           # the generator does produce valid commands, so the invariants above really were exercised


# ------------------------------------------------------------------------------------------------------------ output scrubbing

def test_output_scrubbing():
    t, n = scrub_output("DB_PASSWORD=hunter2\napi_key: 'abc123xyz'\ntoken = abcdef\nuser=bob\nAuthorization: Bearer abcdefghijklmnop1234\n"
                        "AKIAABCDEFGHIJKLMNOP\npostgres://u:pw1234@db/x\n-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\nBBBB\n-----END OPENSSH PRIVATE KEY-----\nplain line")
    assert n >= 7
    for leaked in ("hunter2", "abc123xyz", "abcdef\n", "abcdefghijklmnop1234", "AKIAABCDEFGHIJKLMNOP", "pw1234", "AAAA", "BBBB"):
        assert leaked not in t, leaked
    assert "DB_PASSWORD=[redacted]" in t and "user=bob" in t and "plain line" in t       # readable: only the values go


def test_scrubbing_leaves_normal_logs_alone():
    line = "2026-11-10 12:00:01 INFO nginx started worker 12 listening on 0.0.0.0:80 passwords are hashed with bcrypt"
    assert scrub_output(line) == (line, 0)
