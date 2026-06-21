from loomloop import Blackboard


def test_set_get_and_version():
    bb = Blackboard()
    assert bb.version == 0
    v = bb.set("k", 1, who="a")
    assert v == 1
    assert bb.get("k") == 1
    assert "k" in bb


def test_atomic_update():
    bb = Blackboard()
    bb.set("count", 0)
    bb.update("count", lambda c: c + 1)
    bb.update("count", lambda c: c + 1)
    assert bb.get("count") == 2


def test_history_since():
    bb = Blackboard()
    bb.set("a", 1, who="x")
    mark = bb.version
    bb.set("b", 2, who="y")
    recent = list(bb.history(since=mark))
    assert len(recent) == 1
    assert recent[0][1:3] == ("y", "b")
