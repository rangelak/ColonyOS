"""Tests for the hooks module — HookRunner, HookContext, HookResult."""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from colonyos.config import ColonyConfig, HookConfig, CONFIG_DIR, CONFIG_FILE, load_config
from colonyos.hooks import HookContext, HookResult, HookRunner, _build_hook_env


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Provide a temporary directory as repo_root."""
    return tmp_path


@pytest.fixture
def context(repo_root: Path) -> HookContext:
    return HookContext(
        run_id="test-run-123",
        phase="implement",
        branch="colonyos/test-branch",
        repo_root=repo_root,
        status="running",
    )


def _make_config(*hooks_tuples: tuple[str, list[HookConfig]]) -> ColonyConfig:
    """Create a ColonyConfig with the given hooks."""
    return ColonyConfig(hooks=dict(hooks_tuples))


class TestHookContext:
    def test_fields(self, context: HookContext) -> None:
        assert context.run_id == "test-run-123"
        assert context.phase == "implement"
        assert context.branch == "colonyos/test-branch"
        assert context.status == "running"


class TestBuildHookEnv:
    def test_colonyos_vars_set(self, context: HookContext) -> None:
        env = _build_hook_env(context)
        assert env["COLONYOS_RUN_ID"] == "test-run-123"
        assert env["COLONYOS_PHASE"] == "implement"
        assert env["COLONYOS_BRANCH"] == "colonyos/test-branch"
        assert env["COLONYOS_REPO_ROOT"] == str(context.repo_root)
        assert env["COLONYOS_STATUS"] == "running"

    def test_inherits_path(self, context: HookContext) -> None:
        env = _build_hook_env(context)
        assert "PATH" in env

    def test_scrubs_anthropic_api_key(self, context: HookContext) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-secret"
        try:
            env = _build_hook_env(context)
            assert "ANTHROPIC_API_KEY" not in env
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_scrubs_github_token(self, context: HookContext) -> None:
        os.environ["GITHUB_TOKEN"] = "ghp_secret"
        try:
            env = _build_hook_env(context)
            assert "GITHUB_TOKEN" not in env
        finally:
            del os.environ["GITHUB_TOKEN"]

    def test_scrubs_slack_bot_token(self, context: HookContext) -> None:
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-secret"
        try:
            env = _build_hook_env(context)
            assert "SLACK_BOT_TOKEN" not in env
        finally:
            del os.environ["SLACK_BOT_TOKEN"]

    def test_scrubs_secret_pattern(self, context: HookContext) -> None:
        os.environ["MY_SECRET"] = "something"
        os.environ["DB_PASSWORD"] = "dbpass"
        os.environ["AUTH_TOKEN"] = "tok"
        os.environ["API_KEY"] = "key123"
        os.environ["MY_CREDENTIAL"] = "cred"
        try:
            env = _build_hook_env(context)
            assert "MY_SECRET" not in env
            assert "DB_PASSWORD" not in env
            assert "AUTH_TOKEN" not in env
            assert "API_KEY" not in env
            assert "MY_CREDENTIAL" not in env
        finally:
            for k in ["MY_SECRET", "DB_PASSWORD", "AUTH_TOKEN", "API_KEY", "MY_CREDENTIAL"]:
                os.environ.pop(k, None)

    def test_preserves_safe_vars(self, context: HookContext) -> None:
        os.environ["MY_SAFE_VAR"] = "hello"
        try:
            env = _build_hook_env(context)
            assert env.get("MY_SAFE_VAR") == "hello"
        finally:
            del os.environ["MY_SAFE_VAR"]


class TestHookRunnerSuccessfulExecution:
    def test_echo_command_succeeds(self, context: HookContext) -> None:
        config = _make_config(("post_implement", [HookConfig(command="echo hello")]))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].exit_code == 0
        assert "hello" in results[0].stdout
        assert results[0].timed_out is False

    def test_cwd_is_repo_root(self, context: HookContext) -> None:
        config = _make_config(("post_implement", [HookConfig(command="pwd")]))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert results[0].stdout.strip() == str(context.repo_root)

    def test_hooks_execute_in_order(self, context: HookContext) -> None:
        hooks = [
            HookConfig(command="echo first"),
            HookConfig(command="echo second"),
            HookConfig(command="echo third"),
        ]
        config = _make_config(("pre_plan", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_plan", context)
        assert len(results) == 3
        assert "first" in results[0].stdout
        assert "second" in results[1].stdout
        assert "third" in results[2].stdout


class TestHookRunnerBlocking:
    def test_blocking_failure_stops_remaining(self, context: HookContext) -> None:
        hooks = [
            HookConfig(command="exit 1", blocking=True),
            HookConfig(command="echo should-not-run"),
        ]
        config = _make_config(("pre_review", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_review", context)
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].exit_code == 1

    def test_non_blocking_failure_continues(self, context: HookContext) -> None:
        hooks = [
            HookConfig(command="exit 1", blocking=False),
            HookConfig(command="echo continued"),
        ]
        config = _make_config(("post_plan", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_plan", context)
        assert len(results) == 2
        assert results[0].success is False
        assert results[1].success is True
        assert "continued" in results[1].stdout


class TestHookRunnerTimeout:
    def test_timeout_treated_as_failure(self, context: HookContext) -> None:
        hooks = [HookConfig(command="sleep 10", timeout_seconds=1, blocking=True)]
        config = _make_config(("pre_deliver", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_deliver", context)
        assert len(results) == 1
        assert results[0].timed_out is True
        assert results[0].success is False

    def test_timeout_non_blocking_continues(self, context: HookContext) -> None:
        hooks = [
            HookConfig(command="sleep 10", timeout_seconds=1, blocking=False),
            HookConfig(command="echo after"),
        ]
        config = _make_config(("pre_deliver", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_deliver", context)
        assert len(results) == 2
        assert results[0].timed_out is True
        assert results[1].success is True


class TestHookRunnerInjectOutput:
    def test_inject_output_captures_stdout(self, context: HookContext) -> None:
        hooks = [HookConfig(command="echo injected-data", inject_output=True)]
        config = _make_config(("post_implement", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert results[0].injected_output is not None
        assert "injected-data" in results[0].injected_output

    def test_inject_output_sanitized(self, context: HookContext) -> None:
        # XML tags should be stripped by sanitize_hook_output
        hooks = [HookConfig(command="echo '<script>alert(1)</script>'", inject_output=True)]
        config = _make_config(("post_implement", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert results[0].injected_output is not None
        assert "<script>" not in results[0].injected_output

    def test_inject_output_truncated(self, context: HookContext, repo_root: Path) -> None:
        # Generate output larger than 8KB
        script = repo_root / "big_output.sh"
        script.write_text("#!/bin/bash\npython3 -c \"print('A' * 20000)\"")
        script.chmod(0o755)
        hooks = [HookConfig(command=f"bash {script}", inject_output=True)]
        config = _make_config(("post_implement", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert results[0].injected_output is not None
        assert "[truncated" in results[0].injected_output

    def test_no_inject_when_false(self, context: HookContext) -> None:
        hooks = [HookConfig(command="echo no-inject", inject_output=False)]
        config = _make_config(("post_implement", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert results[0].injected_output is None


class TestHookRunnerEnvironmentVars:
    def test_colonyos_env_vars_available(self, context: HookContext) -> None:
        hooks = [HookConfig(command="echo $COLONYOS_RUN_ID", inject_output=True)]
        config = _make_config(("pre_plan", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_plan", context)
        assert "test-run-123" in results[0].injected_output


class TestHookRunnerOnFailure:
    def test_on_failure_runs_best_effort(self, context: HookContext) -> None:
        hooks = [HookConfig(command="echo failure-hook", blocking=True)]
        config = _make_config(("on_failure", hooks))
        runner = HookRunner(config)
        results = runner.run_on_failure(context)
        assert len(results) == 1
        assert results[0].success is True

    def test_on_failure_swallows_errors(self, context: HookContext) -> None:
        hooks = [
            HookConfig(command="exit 1", blocking=True),
            HookConfig(command="echo still-runs"),
        ]
        config = _make_config(("on_failure", hooks))
        runner = HookRunner(config)
        # Should not raise, and should run all hooks best-effort
        results = runner.run_on_failure(context)
        assert len(results) == 2

    def test_on_failure_no_recursion(self, context: HookContext) -> None:
        """on_failure hooks should never trigger further on_failure."""
        hooks = [HookConfig(command="exit 1", blocking=True)]
        config = _make_config(("on_failure", hooks))
        runner = HookRunner(config)
        # Call run_on_failure twice — should not recurse or deadlock
        results1 = runner.run_on_failure(context)
        results2 = runner.run_on_failure(context)
        assert len(results1) == 1
        assert len(results2) == 1


class TestHookRunnerEdgeCases:
    def test_empty_config_returns_empty(self, context: HookContext) -> None:
        config = ColonyConfig()
        runner = HookRunner(config)
        results = runner.run_hooks("pre_plan", context)
        assert results == []

    def test_unknown_event_returns_empty(self, context: HookContext) -> None:
        config = _make_config(("pre_plan", [HookConfig(command="echo hi")]))
        runner = HookRunner(config)
        results = runner.run_hooks("nonexistent_event", context)
        assert results == []

    def test_result_fields_populated(self, context: HookContext) -> None:
        config = _make_config(("pre_plan", [HookConfig(command="echo test")]))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_plan", context)
        result = results[0]
        assert result.command == "echo test"
        assert result.exit_code == 0
        assert result.duration_ms >= 0
        assert result.timed_out is False
        assert result.success is True
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)


class TestHookRunnerShellAndEncoding:
    """Edge cases: shell pipes, non-UTF8 output, stderr-only output."""

    def test_shell_pipe_command(self, context: HookContext) -> None:
        hooks = [HookConfig(command="echo hello | tr a-z A-Z", inject_output=True)]
        config = _make_config(("post_implement", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        assert results[0].success is True
        assert "HELLO" in results[0].injected_output

    def test_non_utf8_output(self, context: HookContext) -> None:
        hooks = [HookConfig(command="printf '\\x80\\xff'", blocking=False)]
        config = _make_config(("post_implement", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_implement", context)
        # subprocess.run with text=True raises UnicodeDecodeError for non-UTF8
        # output; the engine's generic exception handler catches it and returns
        # exit_code=-1.  The important thing is it does not crash.
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].exit_code == -1

    def test_stderr_only_output(self, context: HookContext) -> None:
        hooks = [HookConfig(command="echo error-msg >&2")]
        config = _make_config(("pre_review", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_review", context)
        assert results[0].success is True
        assert results[0].stdout.strip() == ""
        assert "error-msg" in results[0].stderr

    def test_multiple_inject_output_concatenated(self, context: HookContext) -> None:
        hooks = [
            HookConfig(command="echo AAA", inject_output=True),
            HookConfig(command="echo BBB", inject_output=True),
            HookConfig(command="echo CCC", inject_output=True),
        ]
        config = _make_config(("post_plan", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("post_plan", context)
        injected = [r.injected_output for r in results if r.injected_output]
        assert len(injected) == 3
        # Verify order is preserved
        combined = "\n".join(injected)
        aaa_pos = combined.index("AAA")
        bbb_pos = combined.index("BBB")
        ccc_pos = combined.index("CCC")
        assert aaa_pos < bbb_pos < ccc_pos

    def test_timeout_with_1s_and_sleep_2(self, context: HookContext) -> None:
        hooks = [HookConfig(command="sleep 2", timeout_seconds=1, blocking=True)]
        config = _make_config(("pre_plan", hooks))
        runner = HookRunner(config)
        results = runner.run_hooks("pre_plan", context)
        assert len(results) == 1
        assert results[0].timed_out is True
        assert results[0].success is False
        assert results[0].duration_ms >= 900  # at least ~1s


class TestConfigToRunnerSmokeTest:
    """End-to-end smoke test: config.yaml → load_config → HookRunner → results."""

    def test_config_to_runner_roundtrip(self, tmp_path: Path) -> None:
        config_dir = tmp_path / CONFIG_DIR
        config_dir.mkdir()
        config_yaml = config_dir / CONFIG_FILE
        config_yaml.write_text(textwrap.dedent("""\
            hooks:
              pre_plan:
                - command: "echo plan-starting"
                  blocking: true
              post_implement:
                - command: "echo impl-done"
                  inject_output: true
                - command: "echo lint-check"
                  blocking: false
              on_failure:
                - command: "echo failure-notification"
        """))

        config = load_config(tmp_path)

        # Verify parsed hooks structure
        assert "pre_plan" in config.hooks
        assert "post_implement" in config.hooks
        assert "on_failure" in config.hooks
        assert len(config.hooks["pre_plan"]) == 1
        assert len(config.hooks["post_implement"]) == 2
        assert len(config.hooks["on_failure"]) == 1

        # Execute via HookRunner
        ctx = HookContext(
            run_id="smoke-test",
            phase="plan",
            branch="test-branch",
            repo_root=tmp_path,
        )
        runner = HookRunner(config)

        # pre_plan
        results = runner.run_hooks("pre_plan", ctx)
        assert len(results) == 1
        assert results[0].success is True
        assert "plan-starting" in results[0].stdout

        # post_implement — with inject_output
        results = runner.run_hooks("post_implement", ctx)
        assert len(results) == 2
        assert results[0].success is True
        assert results[0].injected_output is not None
        assert "impl-done" in results[0].injected_output
        assert results[1].success is True
        assert results[1].injected_output is None  # inject_output defaults False

        # on_failure — best-effort
        results = runner.run_on_failure(ctx)
        assert len(results) == 1
        assert results[0].success is True

        # Event with no hooks → empty
        results = runner.run_hooks("pre_review", ctx)
        assert results == []
