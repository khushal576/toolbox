"""Run the learn-english tool alone on 127.0.0.1:8765 with a THROWAWAY SQLite progress store (never the owner's).

    python3 learn-english/tools/run_private.py        # then open http://127.0.0.1:8765/ (Ctrl+C to stop)

Use it for every click-through test: preset progress with
    curl -X PUT -H 'X-Speak-English: 1' -H 'Content-Type: application/json' -d '{"state":{"passed":{"1":true}}}' http://127.0.0.1:8765/progress
The data disappears when it stops. Never test against the live Toolbox: that is the owner's real progress.
"""
import importlib.util, os, sys, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO)); os.environ.pop("TOOLBOX_DATABASE_URL", None)
from core.state.sqlstore import SqlStore
spec = importlib.util.spec_from_file_location("le_srv", REPO / "learn-english" / "server.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.STORE = SqlStore("learn_english", sqlite_path=Path(tempfile.mkdtemp()) / "p.db", ddl=m._SCHEMA)
import uvicorn
uvicorn.run(m.app, host="127.0.0.1", port=8765, log_level="warning")
