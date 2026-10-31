"""
Try the SharePoint Lists page without a tenant: the real tool + an in-memory Vault + the fake Graph (tests/unit/fake_graph.py).

  docker run --rm -p 9000:9000 -e TOOLBOX_SP_DEV=1 -v $PWD/sharepoint-lab:/app/sharepoint_lab:ro \
      -v $PWD/tests/unit:/app/devtests:ro -w /app toolbox-rt-data python /app/devtests/sp_dev_server.py
  → http://localhost:9000/   (two seeded connections: an app-secret one with 3 sites, and a device-code one you can sign in to)
"""
import sys

sys.path.insert(0, "/app/devtests")
import uvicorn  # noqa: E402

import fake_graph  # noqa: E402
from sharepoint_lab import service  # noqa: E402
from sharepoint_lab.server import app  # noqa: E402


class MemVault:
    class SecretNotFound(Exception):
        pass

    class ScopeError(PermissionError):
        pass

    def __init__(self):
        self.rows, self.n = {}, 0

    def list_secrets(self, kind):
        return [{"id": i, "name": n, "kind": k} for i, (n, k, _) in self.rows.items() if k == kind]

    def get_secret(self, sid):
        if sid not in self.rows:
            raise self.SecretNotFound(sid)
        return dict(self.rows[sid][2])

    def save_secret(self, name, kind, data):
        self.n += 1
        sid = f"s{self.n}"
        self.rows[sid] = (name, kind, dict(data))
        return sid

    def update_secret(self, sid, data):
        n, k, _ = self.rows[sid]
        self.rows[sid] = (n, k, dict(data))


BASE = "http://127.0.0.1:9000/fake"
fg = fake_graph.FakeGraph(n_tasks=60, page=25)
fg.public_base = BASE + "/v1.0"
service._VAULT = MemVault()
dev = {"authority_base": BASE, "graph_base": BASE}
common = {"tenant_id": fake_graph.TENANT, "client_id": fake_graph.CLIENT, "cloud": "global", **dev}
service.vault().save_secret("Contoso (app secret)", "sharepoint_connection", {**common, "auth": "client_secret", "client_secret": fake_graph.GOOD_SECRET, "read_only": False,
    "sites": ["https://contoso.sharepoint.com/sites/Team", "https://contoso.sharepoint.com/sites/Ops", "https://contoso.sharepoint.com/sites/Missing"]})
service.vault().save_secret("Contoso (me, read-only)", "sharepoint_connection", {**common, "auth": "device_code", "read_only": True, "refresh_token": "",
    "sites": ["https://contoso.sharepoint.com/sites/Team"]})
app.mount("/fake", fake_graph.make_asgi(fg, prefix="/fake"))
uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")
