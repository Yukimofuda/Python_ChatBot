from __future__ import annotations

import json

import pytest

from src.chatbot.storage import JsonPluginStorage


def test_storage_get_set_delete_and_list(tmp_path):
    store = JsonPluginStorage("sign", data_dir=tmp_path)

    assert store.get("users", {}) == {}

    store.set("users", {"10001": {"points": 12}})
    store.set("enabled", True)

    assert store.get("users") == {"10001": {"points": 12}}
    assert store.list() == ["enabled", "users"]
    assert store.delete("enabled") is True
    assert store.delete("missing") is False
    assert store.list() == ["users"]


def test_storage_writes_atomically_to_plugin_path(tmp_path):
    store = JsonPluginStorage("points", data_dir=tmp_path)

    store.write({"score": 42})

    assert store.path == tmp_path / "plugins" / "points.json"
    assert json.loads(store.path.read_text(encoding="utf-8")) == {"score": 42}


def test_storage_update_persists_changes(tmp_path):
    store = JsonPluginStorage("todo", default={"items": []}, data_dir=tmp_path)

    data = store.update(lambda state: state["items"].append({"id": 1, "done": False}))

    assert data == {"items": [{"id": 1, "done": False}]}
    assert store.read() == {"items": [{"id": 1, "done": False}]}


def test_storage_rejects_path_components(tmp_path):
    with pytest.raises(ValueError):
        JsonPluginStorage("../bad", data_dir=tmp_path)


def test_storage_rejects_corrupted_json(tmp_path):
    store = JsonPluginStorage("quote", data_dir=tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupted"):
        store.read()

    backups = list(store.path.parent.glob("quote.corrupt-*.json"))
    assert len(backups) == 1


def test_storage_has_key(tmp_path):
    store = JsonPluginStorage("persona", data_dir=tmp_path)

    store.set("enabled", True)

    assert store.has("enabled") is True
    assert store.has("missing") is False
