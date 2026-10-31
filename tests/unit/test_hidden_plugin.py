"""Roadmap L6: manifest `hidden: true` — the Data Lake's page moved into Vault → Vault Data, its API stays mounted."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import discover  # noqa: E402


def test_data_lake_is_hidden_but_still_mounted():
    reg = discover(REPO)
    by = {m.name: m for m in reg.ordered()}
    assert by["data-lake"].hidden and by["data-lake"].kind == "python" and by["data-lake"].runtime == "data"
    assert "Data Lake" not in by["data-lake"].title and "Lake" not in by["data-lake"].description
    assert not by["vault"].hidden and not by["duck-lab"].hidden


def test_hidden_defaults_to_false():
    reg = discover(REPO)
    assert sum(1 for m in reg.ordered() if m.hidden) == 1      # only data-lake so far
