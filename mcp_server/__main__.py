"""python -m mcp_server            → the MCP server on stdio (what Claude starts)
   python -m mcp_server recent [N] → the owner's view of the audit log (last N calls, default 30)
   python -m mcp_server tools      → print the tool list (no Toolbox services needed)
   OWNER commands (asked on the terminal, never reachable through MCP — roadmap K4):
   python -m mcp_server status | kill | resume | set-pin | grants [--all] | revoke <id> | grant <kind> <target> --actions a,b [--minutes N] [--rows N]"""
import json
import sys


def _owner_command(cmd: str, argv: list[str]) -> int:
    """The owner's CLI (roadmap K4). NOT reachable through MCP. PIN is asked on the terminal (never on the command line)."""
    import argparse
    import getpass

    from . import control

    def pin(prompt: str = "PIN: ") -> str:
        return getpass.getpass(prompt)

    try:
        if cmd == "status":
            print(json.dumps(control.status(), indent=2))
        elif cmd == "grants":
            for g in control.list_grants(active_only="--all" not in argv):
                print(f"{g['id']}  {'ACTIVE' if g['active'] else 'ended '}  {g['target_kind']}:{g['target']}  {','.join(g['actions'])}  "
                      f"{g['seconds_left'] // 60} min left  rows<={g['row_limit'] or 'any'}  {g['note'] or ''}")
        elif cmd == "kill":
            print(f"AI access STOPPED; {control.kill('stopped from the CLI')} grant(s) revoked.")
        elif cmd == "revoke":
            if argv and argv[0] == "all":
                print(f"{control.kill('revoked all from the CLI') and 'revoked'} (this also stops AI access; use `resume` to allow reading again)")
            else:
                print("revoked" if argv and control.revoke(argv[0]) else "nothing to revoke")
        elif cmd == "resume":
            control.resume(pin())
            print("AI access resumed (read-only until you create a grant).")
        elif cmd == "set-pin":
            old = pin("Current PIN (leave empty if none yet): ") if control.pin_is_set() else None
            new = pin("New PIN: ")
            if new != pin("Repeat new PIN: "):
                print("The two PINs differ.", file=sys.stderr)
                return 1
            control.set_pin(new, old)
            print("PIN saved.")
        elif cmd == "grant":
            ap = argparse.ArgumentParser(prog="python -m mcp_server grant")
            ap.add_argument("kind", choices=control.TARGET_KINDS)
            ap.add_argument("target")
            ap.add_argument("--actions", required=True, help="comma separated, e.g. append_rows,create_table")
            ap.add_argument("--minutes", type=int, default=control.DEFAULT_MINUTES)
            ap.add_argument("--rows", type=int)
            ap.add_argument("--note", default="")
            ap.add_argument("--prod-ok", action="store_true", help="confirm that the target may be prod / unlabelled")
            a = ap.parse_args(argv)
            from . import access

            env = access.target_environment(a.kind, a.target)   # the REAL label from the Vault; unknown = protected
            g = control.create_grant(a.kind, a.target, [x.strip() for x in a.actions.split(",") if x.strip()], minutes=a.minutes, pin=pin(),
                                     row_limit=a.rows, note=a.note, via="cli", environment=env, confirm_prod=a.prod_ok)
            print(f"grant {g['id']} created: {g['target_kind']}:{g['target']} {','.join(g['actions'])} for {a.minutes} min")
    except control.ControlError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "serve":
        from .protocol import serve

        serve()
        return 0
    if cmd == "recent":
        from . import audit

        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        for r in reversed(audit.recent(n)):
            print(f"{r['ts']}  {r['session']}  {r['outcome']:<8} {r['tool']:<22} {r.get('connection') or '-':<18} "
                  f"{r.get('environment') or '-':<9} rows={r.get('rows')} {r.get('duration_ms')}ms  {(r.get('detail') or '')[:80]}")
        return 0
    if cmd in ("status", "grants", "grant", "revoke", "kill", "resume", "set-pin"):
        return _owner_command(cmd, sys.argv[2:])
    if cmd == "tools":
        from .protocol import _tool_listing

        print(json.dumps(_tool_listing(), indent=2))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
