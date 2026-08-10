import json

from hills import state


def entry(value: float) -> dict:
    return {"passed": True, "metrics": [{"name": "m", "value": value, "direction": "min"}]}


def test_chain_links_entries():
    state.append("demo", "tree1", entry(1.0))
    state.append("demo", "tree1", entry(0.5))
    records = state.read("demo", "tree1")
    assert [r["seq"] for r in records] == [1, 2]
    assert records[1]["prev"] == records[0]["chain"]
    assert all(record["_chain_ok"] for record in records)


def test_editing_a_line_breaks_the_chain():
    state.append("demo", "tree1", entry(1.0))
    state.append("demo", "tree1", entry(0.5))
    path = state.attempts_path("demo", "tree1")
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["metrics"][0]["value"] = 0.0
    path.write_text("\n".join([json.dumps(tampered, sort_keys=True), lines[1]]) + "\n")

    records = state.read("demo", "tree1")
    assert records[0]["_chain_ok"] is False
    assert records[1]["_chain_ok"] is True, "the edit is flagged where it happened, not everywhere"


def test_deleting_a_line_breaks_the_chain():
    for value in (1.0, 0.5, 0.25):
        state.append("demo", "tree1", entry(value))
    path = state.attempts_path("demo", "tree1")
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")

    records = state.read("demo", "tree1")
    assert records[0]["_chain_ok"] is True
    assert records[1]["_chain_ok"] is False


def test_history_is_keyed_by_tree_hash():
    state.append("demo", "tree1", entry(1.0))
    state.append("demo", "tree2", entry(0.5))
    assert len(state.read("demo", "tree1")) == 1
    assert len(state.read("demo", "tree2")) == 1
    assert state.known_tree_hashes("demo") == ["tree1", "tree2"]


def test_dirty_runs_are_logged_apart_from_official_history():
    state.append("demo", None, entry(0.1))
    assert state.read("demo", "tree1") == []
    assert len(state.read("demo", None)) == 1
    assert "demo@current" in str(state.attempts_path("demo", None))
