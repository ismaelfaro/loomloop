import asyncio
import os
import tempfile

import pytest

from loomloop import (
    FunctionLoop,
    Loom,
    OakBranchLoop,
    OakError,
    OakRepo,
    RecordingRunner,
    Step,
)


def run(coro):
    return asyncio.run(coro)


def subcommands(runner):
    """The list of `oak` subcommands issued (the arg right after the binary)."""
    return [c[1] for c in runner.calls]


# -- the adapter ---------------------------------------------------------

def test_available_reflects_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _b: None)
    assert OakRepo.available() is False
    monkeypatch.setattr("shutil.which", lambda _b: "/usr/bin/oak")
    assert OakRepo.available() is True


def test_missing_binary_raises_oak_error():
    # No runner injected -> real subprocess path, but the binary is absent.
    repo = OakRepo(bin="definitely-not-a-real-oak-binary")
    with pytest.raises(OakError):
        repo.status()


def test_branch_carries_description():
    runner = RecordingRunner()
    repo = OakRepo("/tmp", runner=runner)
    repo.branch("session/x", description="the work")
    assert runner.calls[-1] == ["oak", "branch", "session/x", "--description", "the work"]


def test_commit_funnels_paths_and_description():
    runner = RecordingRunner()
    repo = OakRepo("/tmp", runner=runner)
    repo.commit(paths=["a.txt", "b.txt"], description="msg")
    assert runner.calls[-1] == [
        "oak", "commit", "--description", "msg", "a.txt", "b.txt",
    ]


def test_merge_switches_into_target_first():
    runner = RecordingRunner()
    repo = OakRepo("/tmp", runner=runner)
    repo.merge("session/x", into="main")
    assert subcommands(runner) == ["switch", "merge"]
    assert runner.calls[0] == ["oak", "switch", "main"]
    assert runner.calls[1] == ["oak", "merge", "session/x"]


def test_nonzero_exit_raises():
    def failing(_args):
        from loomloop.oak import OakResult
        return OakResult(args=_args, returncode=2, stderr="boom")

    repo = OakRepo("/tmp", runner=failing)
    with pytest.raises(OakError) as exc:
        repo.push()
    assert "boom" in str(exc.value)


def test_current_branch_strips_output():
    runner = RecordingRunner(responses={"branch": "  main\n"})
    repo = OakRepo("/tmp", runner=runner)
    assert repo.current_branch() == "main"


# -- Loom integration ----------------------------------------------------

def test_branch_per_session_assigns_and_creates_branches():
    runner = RecordingRunner()
    repo = OakRepo("/tmp", runner=runner)
    loom = Loom(workspace=repo, branch_per_session=True, logger=lambda _l: None)

    seen = {}

    async def agent(ctx):
        seen["branch"] = ctx.branch
        seen["workspace"] = ctx.workspace
        return Step.done()

    loom.add(FunctionLoop("worker", agent))
    run(loom.run(max_ticks=3))

    assert seen["branch"] == "session/worker"
    assert seen["workspace"] is repo
    # the branch was created with a session description
    assert ["oak", "branch", "session/worker", "--description", "session: worker"] in runner.calls


def test_ctx_commit_targets_agent_branch():
    runner = RecordingRunner()
    repo = OakRepo("/tmp", runner=runner)
    loom = Loom(workspace=repo, branch_per_session=True, logger=lambda _l: None)

    async def agent(ctx):
        ctx.commit("did work", paths=["out.txt"])
        return Step.done()

    loom.add(FunctionLoop("worker", agent))
    run(loom.run(max_ticks=3))

    # switch to the agent's branch precedes the commit
    assert ["oak", "switch", "session/worker"] in runner.calls
    assert ["oak", "commit", "--description", "did work", "out.txt"] in runner.calls


def test_ctx_commit_without_workspace_raises():
    loom = Loom(logger=lambda _l: None)

    captured = {}

    async def agent(ctx):
        captured["workspace"] = ctx.workspace
        captured["branch"] = ctx.branch
        with pytest.raises(RuntimeError):
            ctx.commit("nope")
        return Step.done()

    loom.add(FunctionLoop("worker", agent))
    run(loom.run(max_ticks=3))
    assert captured["workspace"] is None
    assert captured["branch"] is None


def test_snapshot_writes_manifest_and_commits():
    root = tempfile.mkdtemp(prefix="oak-test-")
    runner = RecordingRunner()
    repo = OakRepo(root, runner=runner)
    loom = Loom(workspace=repo, snapshot=True, logger=lambda _l: None)

    async def agent(ctx):
        ctx.post("k", "v")
        return Step.done()

    loom.add(FunctionLoop("worker", agent))
    run(loom.run(max_ticks=3))

    manifest = os.path.join(root, "loomloop-run.json")
    assert os.path.exists(manifest)
    # the final commit references the run manifest
    commits = [c for c in runner.calls if c[1] == "commit"]
    assert any("loomloop-run.json" in c for c in commits)


# -- OakBranchLoop agent -------------------------------------------------

def test_oak_branch_loop_commits_each_message():
    root = tempfile.mkdtemp(prefix="oak-test-")
    runner = RecordingRunner()
    repo = OakRepo(root, runner=runner)
    loom = Loom(workspace=repo, branch_per_session=True, logger=lambda _l: None)

    async def source(ctx):
        if ctx.tick == 0:
            ctx.send("task", {"unit": "parser"}, to="builder")
            return Step.cont()
        return Step.done()

    loom.add(FunctionLoop("source", source))
    loom.add(OakBranchLoop("builder", listen="task", merge_into="main"))
    run(loom.run(max_ticks=10))

    # the payload was written and committed onto the builder's branch
    assert os.path.exists(os.path.join(root, "builder.json"))
    assert loom.blackboard.get("builder.commits") == 1
    # teardown merged the session branch back into main
    assert ["oak", "merge", "session/builder"] in runner.calls


def test_oak_branch_loop_without_workspace_is_noop():
    loom = Loom(logger=lambda _l: None)

    async def source(ctx):
        if ctx.tick == 0:
            ctx.send("task", 1, to="builder")
            return Step.cont()
        return Step.done()

    loom.add(FunctionLoop("source", source))
    loom.add(OakBranchLoop("builder", listen="task"))
    report = run(loom.run(max_ticks=10))
    # no workspace -> the agent drops messages without crashing the run
    assert report.errors == 0


# -- backwards compatibility --------------------------------------------

def test_loom_without_workspace_is_unchanged():
    loom = Loom(logger=lambda _l: None)
    assert loom.workspace is None

    async def agent(ctx):
        assert ctx.workspace is None
        assert ctx.branch is None
        ctx.post("ran", True)
        return Step.done()

    loom.add(FunctionLoop("worker", agent))
    run(loom.run(max_ticks=3))
    assert loom.blackboard.get("ran") is True
