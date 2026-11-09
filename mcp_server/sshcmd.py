"""
mcp_server/sshcmd.py — which commands the AI may run over SSH (ADR D13, roadmap K5). PURE: text in, decision out; it runs nothing.

Two ideas make this safe, and both are tested hard (tests/unit/test_mcp_sshcmd.py, plus a real OpenSSH server):

  1. ALLOW-LIST, not deny-list. A command must be one of the known read-only programs; every flag must be on THAT program's list
     (a flag that is not listed — even a harmless one — is refused); the few programs that need sub-commands (docker, git, systemctl,
     ip) have their sub-commands listed too.
  2. WE BUILD THE COMMAND THE SHELL SEES. The text is tokenised by our own tokenizer (not by guessing what a shell would do). Anything
     that has a special meaning to a shell outside single quotes — ; & | (except a plain pipe) < > ( ) { } ` $ \\ ! # newline — is refused.
     What is sent to the server is REBUILT from the validated tokens (shlex.quote), so the server's shell parses exactly what we
     checked. A parser difference between "what we validated" and "what the shell ran" is the classic hole; this closes it.

Pipes are allowed only between allow-listed programs and only INTO grep / head / tail / wc / sort / uniq / cut. No redirects, no sudo, no
shells, no editors, no network tools, no env / printenv (they print secrets). Reading obvious secret files (keys, .env, shadow …) is refused
as a best effort; output is also scrubbed for the secrets Toolbox knows (safety.REDACTOR).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Optional

MAX_LENGTH = 1000
MAX_STAGES = 6
PIPE_TARGETS = {"grep", "head", "tail", "wc", "sort", "uniq", "cut"}


class CommandRefused(ValueError):
    """Why a command was not allowed (a sentence for the AI and the owner)."""


# ---- tokenizer -------------------------------------------------------------------------------------------------------------

@dataclass
class Tok:
    text: str
    quoted: bool = False     # any part came from quotes (then it is never glob-expanded: it is rebuilt with shlex.quote)
    glob: bool = False       # unquoted * ? [ ] — kept raw so the remote shell expands it (read-only), charset-checked

_SHELL_META = set(";&<>(){}`$\\!#\n\r\x00")
_GLOB_CHARS = set("*?[]")
_SAFE_RAW = re.compile(r"^[A-Za-z0-9_./*?\[\]@%+=:,~-]+$")


def tokenize(command: str) -> list[list[Tok]]:
    """Split into pipeline stages of tokens, or raise CommandRefused. Single-line, printable text only."""
    if not isinstance(command, str) or not command.strip():
        raise CommandRefused("The command is empty.")
    if len(command) > MAX_LENGTH:
        raise CommandRefused(f"The command is longer than {MAX_LENGTH} characters.")
    if any(ord(c) < 32 and c != "\t" for c in command):
        raise CommandRefused("Control characters (including newlines) are not allowed; send one single-line command.")
    stages: list[list[Tok]] = [[]]
    cur: Optional[Tok] = None
    i, n = 0, len(command)

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            stages[-1].append(cur)
            cur = None

    while i < n:
        c = command[i]
        if c in " \t":
            flush()
        elif c == "|":
            if i + 1 < n and command[i + 1] == "|":
                raise CommandRefused("'||' is not allowed. Run one command, or a plain pipe '|' between allowed commands.")
            flush()
            if not stages[-1]:
                raise CommandRefused("A pipe needs a command on its left.")
            stages.append([])
        elif c == "'":
            j = command.find("'", i + 1)
            if j < 0:
                raise CommandRefused("Unclosed single quote.")
            cur = cur or Tok("")
            cur.text += command[i + 1:j]
            cur.quoted = True
            i = j
        elif c == '"':
            j = i + 1
            buf = ""
            while j < n and command[j] != '"':
                if command[j] in "$`\\!":
                    raise CommandRefused("Inside double quotes, $ ` \\ ! are special to a shell; use single quotes instead.")
                buf += command[j]
                j += 1
            if j >= n:
                raise CommandRefused("Unclosed double quote.")
            cur = cur or Tok("")
            cur.text += buf
            cur.quoted = True
            i = j
        elif c in _SHELL_META:
            raise CommandRefused(f"'{c if c.isprintable() else '?'}' has a special meaning to the shell and is not allowed "
                                 "(no ; & > < ( ) { } ` $ \\ ! # — one command, or a plain pipe).")
        else:
            if ord(c) > 126:
                raise CommandRefused("Only plain ASCII is allowed outside quotes.")
            cur = cur or Tok("")
            cur.text += c
            if c in _GLOB_CHARS:
                cur.glob = True
        i += 1
    flush()
    if not stages[-1]:
        raise CommandRefused("A pipe needs a command on its right.")
    if len(stages) > MAX_STAGES:
        raise CommandRefused(f"At most {MAX_STAGES} commands in a pipe.")
    return stages


# ---- secret-file paths (best effort) ------------------------------------------------------------------------------------------

_SECRET_PATH = re.compile(
    r"(^|/)(shadow|gshadow|sudoers(\.d)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|authorized_keys|\.ssh|\.gnupg|\.aws|\.azure|\.kube|\.docker|"
    r"\.netrc|\.pgpass|\.git-credentials|\.npmrc|\.pypirc|\.env(\..*)?|secrets?(\..*)?|credentials?(\..*)?|master\.key|"
    r"[^/]*\.(pem|key|p12|pfx|jks|kdbx|keystore|ovpn))(/|$)|^/proc/[^/]+/(environ|mem|maps)$|^/proc/kcore$|^/etc/(ssl/private|ssh/ssh_host_)", re.I)


def _check_path(text: str) -> None:
    if _SECRET_PATH.search(text) or ".." in text.split("/") and _SECRET_PATH.search(text.replace("..", "")):
        raise CommandRefused(f"'{text}' looks like a secret file (keys, passwords, .env …). Ask the owner if you really need it.")


# ---- the allow-list ----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Spec:
    short: str = ""                  # allowed single-letter flags (may be bundled: -la)
    long: frozenset = frozenset()    # allowed --long-flags (with or without =value)
    numeric: bool = False            # -20 style flags (head/tail)
    max_pos: Optional[int] = None    # max positional arguments (values of flags do not count)
    val: str = ""                    # letters that TAKE a value (-n20, -n 20, -d,): the rest of the word / the next word is that value
    pattern_first: bool = False      # grep: the first positional is a PATTERN (not a path) unless -e is used


def S(short: str = "", long: str = "", numeric: bool = False, max_pos: Optional[int] = None, val: str = "",
      pattern_first: bool = False) -> Spec:
    return Spec(short, frozenset(long.split()), numeric, max_pos, val, pattern_first)


SPECS: dict[str, Spec] = {
    "ls": S("1aAbcCdfFghHiklLmnNopqrRsStTuUvxX", "all almost-all human-readable long recursive reverse size classify directory time sort color group-directories-first"),
    "cat": S("AbeEnstTuv", "number show-all show-ends show-tabs squeeze-blank number-nonblank"),
    "head": S("cnqv", "lines bytes quiet verbose", numeric=True, val="cn"),
    "tail": S("cnqv", "lines bytes quiet verbose", numeric=True, val="cn"),  # no -f / -F / --follow: they never end
    "wc": S("clmLw", "lines bytes chars words max-line-length"),
    "du": S("abcdhHkmsSx", "all apparent-size bytes total human-readable summarize max-depth one-file-system", val="d"),
    "df": S("aBhHiklPTt", "all human-readable inodes local print-type type", val="t"),
    "stat": S("cfLt", "format file-system dereference terse", val="c"),
    "file": S("bikLNnsz", "brief mime mime-type mime-encoding dereference"),
    "uname": S("asnrvmpio", "all kernel-name nodename kernel-release kernel-version machine processor operating-system"),
    "uptime": S("ps", "pretty since"),
    "free": S("bkmghltw", "human total wide bytes kilo mega giga"),       # no -s / -c: they repeat forever
    "id": S("gGnruZ", "group groups name real user"),
    "whoami": S(max_pos=0),
    "hostname": S("fisI", "fqdn ip-address short all-ip-addresses", max_pos=0),   # a positional would SET the hostname
    "date": S("Rud", "utc universal rfc-3339 iso-8601 date", max_pos=1, val="d"),
    "who": S("abHlmpqrTtu"), "w": S("hsfiu"), "last": S("0123456789adFinRwx", numeric=True),
    "sort": S("bdfghiMnrRuVzkt", "ignore-leading-blanks dictionary-order ignore-case numeric-sort reverse unique version-sort key field-separator", val="kt"),   # no -o (writes a file)
    "uniq": S("cdiuzDfsw", "count repeated ignore-case unique", max_pos=1, val="fsw"),    # a 2nd positional is an OUTPUT file
    "cut": S("bcdfnswz", "bytes characters delimiter fields complement only-delimited", val="bcdf"),
    "grep": S("AaBbCcEeFGHhIiLlmnoPqrRsTUuVvwxyZz", "after-context before-context context count extended-regexp fixed-strings ignore-case invert-match "
              "line-number only-matching recursive word-regexp files-with-matches files-without-match max-count no-messages quiet regexp include "
              "exclude exclude-dir with-filename no-filename text color null binary-files", val="ABCme", pattern_first=True),
    "ps": S("aAefFlmuwxjhHNoOprsTUZ", "forest no-headers sort"),            # positional tokens are handled specially (BSD options)
    "ss": S("tuxnlpaeoi46s", "tcp udp unix numeric listening processes all summary"),          # no -K (kills sockets)
    "dmesg": S("HkTx", "human kernel ctime"),                              # no -C / -c (clears the buffer)
}

FIND_OK = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-type", "-size", "-mtime", "-atime", "-ctime", "-mmin", "-amin", "-cmin",
           "-newer", "-user", "-group", "-perm", "-maxdepth", "-mindepth", "-xdev", "-depth", "-print", "-print0", "-empty", "-readable",
           "-writable", "-executable", "-o", "-a", "-not", "-true", "-false", "-nouser", "-nogroup", "-links", "-inum", "-samefile"}

SYSTEMCTL_VERBS = {"status", "is-active", "is-enabled", "is-failed", "list-units", "list-unit-files", "list-timers", "list-sockets", "show", "cat"}
SYSTEMCTL_FLAGS = {"--no-pager", "-l", "--full", "--failed", "--all", "-a", "--no-legend", "-q", "--quiet", "--plain", "-t", "--type", "--state", "-n", "--lines", "-p", "--property", "--value"}
JOURNAL_FLAGS = {"-u", "--unit", "-n", "--lines", "-p", "--priority", "--since", "--until", "-S", "-U", "-b", "--boot", "-k", "--dmesg", "--no-pager", "-o", "--output",
                 "-r", "--reverse", "--no-hostname", "-x", "-e", "-g", "--grep", "-t", "--identifier", "-q", "--quiet", "--utc", "-a", "--all", "--case-sensitive"}
IP_OBJECTS = {"a", "addr", "address", "route", "r", "link", "l", "neigh", "neighbor", "n", "rule"}
IP_FLAGS = {"-4", "-6", "-br", "-brief", "-s", "-stats", "-c", "-d", "-details", "-o", "-oneline", "-j", "-json", "-h", "-human"}
DOCKER_VERBS = {"ps": {"-a", "-q", "--no-trunc", "--format", "-f", "--filter", "-n", "-l", "-s", "--size", "--all", "--quiet"},
                "logs": {"--tail", "-n", "--since", "--until", "-t", "--timestamps", "--details"},      # no -f / --follow
                "stats": {"--no-stream", "--no-trunc", "--format", "-a", "--all"},
                "images": {"-a", "-q", "--format", "--digests", "--filter", "-f", "--no-trunc", "--all", "--quiet"},
                "top": set(), "version": {"--format", "-f"}, "info": {"--format", "-f"}, "port": set()}
GIT_VERBS = {"status": {"-s", "--short", "-b", "--branch", "--porcelain", "--ignored"},
             "log": {"--oneline", "--stat", "-n", "-p", "--since", "--until", "--author", "--grep", "--name-only", "--name-status", "--graph", "--decorate", "--all", "--no-pager", "--format", "--pretty", "-i", "--max-count"},
             "diff": {"--stat", "--name-only", "--name-status", "--cached", "--staged", "-p", "--no-pager", "--shortstat", "-w", "--numstat", "-U"},
             "show": {"--stat", "-s", "--name-only", "--name-status", "--no-pager", "--format", "--pretty", "-p"}}
CRONTAB_FLAGS = {"-l"}
ALLOWED_PROGRAMS = sorted(set(SPECS) | {"find", "systemctl", "journalctl", "ip", "docker", "git", "top", "crontab"})

_NUM = re.compile(r"^-\d+$")
_VALUE = re.compile(r"^[\w@%+=:,./~*?\[\]{}\- ]*$")


def _flag_name(t: str) -> str:
    return t.split("=", 1)[0]


def _check_with_spec(name: str, spec: Spec, args: list[Tok]) -> None:
    """Judge every word by its TEXT (a quoted '--follow' reaches the program as --follow, so quotes hide nothing)."""
    pos = 0
    expect_value = False
    pattern_pending = spec.pattern_first
    for a in args:
        t = a.text
        if expect_value:                       # the value of the previous flag (-n 20, -d ,): never a path, never counted
            expect_value = False
            if not _VALUE.match(t):
                raise CommandRefused(f"The value '{t}' for {name} has characters that are not allowed.")
            continue
        if t == "--":
            continue
        if t.startswith("--") and len(t) > 2:
            if _flag_name(t)[2:] not in spec.long:
                raise CommandRefused(f"'{t}' is not an allowed option for {name}.")
            if _flag_name(t) == "--regexp":
                pattern_pending = False
            continue
        if t.startswith("-") and len(t) > 1:
            if spec.numeric and _NUM.match(t):
                continue
            body = t[1:]
            for idx, ch in enumerate(body):
                if ch not in spec.short:
                    raise CommandRefused(f"'-{ch}' is not an allowed option for {name}.")
                if ch == "e" and spec.pattern_first:
                    pattern_pending = False
                if ch in spec.val:
                    rest = body[idx + 1:]
                    if rest:
                        if not _VALUE.match(rest):
                            raise CommandRefused(f"The value '{rest}' for {name} has characters that are not allowed.")
                    else:
                        expect_value = True
                    break
            continue
        pos += 1
        if pattern_pending:                    # grep PATTERN: searching for the word "secret" is fine; reading a secret FILE is not
            pattern_pending = False
            continue
        _check_path(t)
    if spec.max_pos is not None and pos > spec.max_pos:
        raise CommandRefused(f"{name} takes at most {spec.max_pos} argument(s) here (an extra one could make it write).")
    if name == "date":
        has_d = any(a.text == "-d" or a.text.startswith("--date") or (a.text.startswith("-") and not a.text.startswith("--") and "d" in a.text[1:]) for a in args)
        for a in args:
            if not a.text.startswith("-") and not a.text.startswith("+") and not has_d:
                raise CommandRefused("date accepts only a +FORMAT (a bare number would SET the system clock).")


def _check_flags_set(name: str, args: list[Tok], allowed: set[str], first_positional_is_verb: bool = False) -> list[Tok]:
    """For programs with an explicit flag set: every '-…' word must be listed; returns the positionals."""
    rest = []
    for a in args:
        if a.text.startswith("-") and len(a.text) > 1:
            if _flag_name(a.text) not in allowed and not _NUM.match(a.text):
                raise CommandRefused(f"'{a.text}' is not an allowed option for {name}.")
        else:
            _check_path(a.text)
            rest.append(a)
    return rest


def check_stage(stage: list[Tok], piped: bool) -> None:
    name = stage[0].text
    args = stage[1:]
    if stage[0].quoted or stage[0].glob or "/" in name or "=" in name:
        raise CommandRefused("Start with a plain command name (no paths, quotes, wildcards or VAR=value).")
    if piped and name not in PIPE_TARGETS:
        raise CommandRefused(f"After a pipe only {', '.join(sorted(PIPE_TARGETS))} are allowed (got '{name}').")
    if name in SPECS and name not in ("ps",):
        _check_with_spec(name, SPECS[name], args)
        return
    if name == "ps":
        i = 0
        while i < len(args):
            t = args[i]
            if t.text.startswith("-") and not t.text.startswith("--") and len(t.text) > 1 and t.text[-1] in "oO":
                _check_with_spec("ps", SPECS["ps"], [t])               # e.g. -o  or  -eo : the NEXT word is the output format
                if i + 1 >= len(args) or not re.fullmatch(r"[A-Za-z0-9_,%=:+-]+", args[i + 1].text):
                    raise CommandRefused("After -o give an output format of letters, digits and , % = : + - (for example pid,comm,pcpu).")
                i += 2
                continue
            if t.text.startswith("-"):
                _check_with_spec("ps", SPECS["ps"], [t])
            elif not re.fullmatch(r"[auxfw]+", t.text):   # BSD-style options: 'e' would print every process's environment — refused
                raise CommandRefused("ps accepts aux-style options made of a u x f w only (not 'e', which prints environments).")
            i += 1
        return
    if name == "find":
        i = 0
        while i < len(args) and not args[i].text.startswith("-"):
            _check_path(args[i].text)               # the places searched
            i += 1
        for t in args[i:]:                           # expression: tests must be listed; their VALUES (-name .env) only list paths
            if t.text.startswith("-") and len(t.text) > 1 and not _NUM.match(t.text) and t.text not in FIND_OK:
                raise CommandRefused(f"find: '{t.text}' is not allowed (no -exec, -delete, -fprint …).")
        return
    if name == "top":
        if [t.text for t in args] not in (["-b", "-n", "1"], ["-bn1"], ["-n", "1", "-b"]):
            raise CommandRefused("top is only allowed as: top -b -n 1")
        return
    if name == "crontab":
        if [t.text for t in args] != ["-l"]:
            raise CommandRefused("crontab is only allowed as: crontab -l")
        return
    if name == "systemctl":
        rest = _check_flags_set("systemctl", args, SYSTEMCTL_FLAGS)
        if not rest or rest[0].text not in SYSTEMCTL_VERBS:
            raise CommandRefused(f"systemctl is only allowed with: {', '.join(sorted(SYSTEMCTL_VERBS))}.")
        return
    if name == "journalctl":
        _check_flags_set("journalctl", args, JOURNAL_FLAGS)      # no -f / --follow / --vacuum-* / --rotate …
        return
    if name == "ip":
        rest = _check_flags_set("ip", args, IP_FLAGS)
        ok = bool(rest) and rest[0].text in IP_OBJECTS and all(t.text in ("show", "list", "ls") for t in rest[1:2]) and len(rest) <= 4
        if len(rest) == 4 and rest[2].text != "dev":
            ok = False
        if not ok:
            raise CommandRefused("ip is only allowed to show: ip [-br] addr|route|link|neigh [show [dev IFACE]].")
        return
    if name == "docker":
        if not args or args[0].text.startswith("-"):
            raise CommandRefused("docker needs a sub-command: ps, logs, stats --no-stream, images, top, version, info, port.")
        verb = args[0].text
        if verb not in DOCKER_VERBS:
            raise CommandRefused(f"docker {verb} is not allowed. Allowed: {', '.join(sorted(DOCKER_VERBS))} (no exec / inspect / run / rm / cp).")
        _check_flags_set(f"docker {verb}", args[1:], DOCKER_VERBS[verb])
        if verb == "stats" and "--no-stream" not in [t.text for t in args]:
            raise CommandRefused("docker stats must include --no-stream (it never ends otherwise).")
        for t in args[1:]:
            if t.text in ("-f", "--follow") and verb == "logs":
                raise CommandRefused("docker logs -f never ends; use --tail N.")
        return
    if name == "git":
        a = list(args)
        if len(a) >= 2 and a[0].text == "-C":
            _check_path(a[1].text)
            a = a[2:]
        if not a or a[0].text not in GIT_VERBS:
            raise CommandRefused(f"git is only allowed with: {', '.join(sorted(GIT_VERBS))} (no -c, no config).")
        _check_flags_set(f"git {a[0].text}", a[1:], GIT_VERBS[a[0].text])
        return
    raise CommandRefused(f"'{name}' is not on the allow-list. Allowed programs: {', '.join(ALLOWED_PROGRAMS)}.")


def rebuild(stage: list[Tok]) -> str:
    out = []
    for t in stage:
        if t.glob and not t.quoted:
            if not _SAFE_RAW.match(t.text):
                raise CommandRefused("A wildcard word may contain only letters, digits and _ . / * ? [ ] @ % + = : , ~ -")
            out.append(t.text)               # left for the remote shell to expand (read-only)
        else:
            out.append(shlex.quote(t.text))  # everything else is passed literally: nothing in it can mean anything to a shell
    return " ".join(out)


def validate(command: str) -> str:
    """The exact command to send to the server (rebuilt from validated tokens), or raise CommandRefused."""
    stages = tokenize(command)
    for i, st in enumerate(stages):
        check_stage(st, piped=i > 0)
    built = []
    for st in stages:
        text = rebuild(st)
        if st[0].text == "git":   # a repository's own config can run programs (core.fsmonitor on `git status`): switch that off
            text = text.replace("git", "git -c core.fsmonitor=false -c core.pager=cat --no-pager", 1)
        elif st[0].text in ("journalctl", "systemctl") and "--no-pager" not in text:
            text += " --no-pager"     # the command runs on a pseudo-terminal (see ssh_run.py): a pager would wait for a key press
        built.append(text)
    return " | ".join(built)


# ---- output scrubbing (best effort; the Redactor in safety.py ALSO removes every secret Toolbox itself knows) ------------------

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S)
_KV = re.compile(r"(?i)\b([A-Za-z0-9_.-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)[A-Za-z0-9_.-]*)(\s*[=:]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;\"']+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}")
_AWS = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
_URLPW = re.compile(r"(\w+://[^:/\s@]+:)([^@/\s]+)(@)")


def scrub_output(text: str) -> tuple[str, int]:
    """(text with likely secrets replaced by [redacted], how many replacements). Keeps the KEY of key=value so logs stay readable."""
    n = 0

    def sub(rx, repl, t):
        nonlocal n
        t, k = rx.subn(repl, t)
        n += k
        return t

    text = sub(_PEM, "[redacted private key]", text)
    text = sub(_KV, lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    text = sub(_BEARER, lambda m: f"{m.group(1)} [redacted]", text)
    text = sub(_AWS, "[redacted]", text)
    text = sub(_URLPW, lambda m: f"{m.group(1)}[redacted]{m.group(3)}", text)
    return text, n

