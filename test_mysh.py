import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import mysh


class AiSessionStoreTests(unittest.TestCase):
    def make_session(self) -> mysh.AiSession:
        return mysh.AiSession(
            id="abc123",
            title="test session",
            tool="codex",
            cwd="C:\\WorkSpace\\custom-tm",
            command="codex --cd <value> [prompt=yes, chars=6, args=1]",
            profile="default",
            created_at="2026-06-17T10:00:00+09:00",
            updated_at="2026-06-17T10:01:00+09:00",
            exit_code=0,
            args=["--model", "gpt-5"],
        )

    def test_session_json_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = mysh.AiSessionStore(Path(tmp))
            session = self.make_session()

            store.add(session)
            loaded = store.load()

            self.assertEqual(1, len(loaded))
            self.assertEqual(session.to_dict(), loaded[0].to_dict())

    def test_corrupt_json_is_backed_up_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_dir = root / ".mysh"
            store_dir.mkdir()
            store_path = store_dir / "sessions.json"
            store_path.write_text("{broken json", encoding="utf-8")

            store = mysh.AiSessionStore(root)
            loaded = store.load()

            self.assertEqual([], loaded)
            self.assertTrue((store_dir / "sessions.json.bak").exists())
            with store_path.open("r", encoding="utf-8") as file:
                self.assertEqual({"sessions": []}, json.load(file))

    def test_gitignore_gets_mysh_when_store_dir_is_created_in_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")

            store = mysh.AiSessionStore(root)
            store.save([])

            gitignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".mysh/", gitignore.splitlines())


class ShellConfigStoreTests(unittest.TestCase):
    def test_config_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mysh.ShellContext(project_root=root)
            ctx.theme = "blue"
            ctx.aliases = {"gs": "git status"}
            ctx.active_profile = "work"
            ctx.default_ai_tool = "claude"
            ctx.save_config()

            loaded = mysh.ShellContext(project_root=root)

            self.assertEqual("blue", loaded.theme)
            self.assertEqual({"gs": "git status"}, loaded.aliases)
            self.assertEqual("work", loaded.active_profile)
            self.assertEqual("claude", loaded.default_ai_tool)

    def test_corrupt_config_json_is_backed_up_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_dir = root / ".mysh"
            store_dir.mkdir()
            config_path = store_dir / "config.json"
            config_path.write_text("{broken json", encoding="utf-8")

            ctx = mysh.ShellContext(project_root=root)

            self.assertEqual("green", ctx.theme)
            self.assertEqual(mysh.default_aliases(), ctx.aliases)
            self.assertTrue((store_dir / "config.json.bak").exists())
            with config_path.open("r", encoding="utf-8") as file:
                self.assertEqual(mysh.default_shell_config(), json.load(file))

    def test_ai_config_reset_restores_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mysh.ShellContext(project_root=root)
            ctx.theme = "magenta"
            ctx.aliases = {"gs": "git status"}
            ctx.active_profile = "work"
            ctx.default_ai_tool = "claude"
            ctx.save_config()

            output = StringIO()
            with redirect_stdout(output):
                mysh.cmd_ai(ctx, [], "config reset")

            self.assertIn("초기화", output.getvalue())
            self.assertEqual("green", ctx.theme)
            self.assertEqual(mysh.default_aliases(), ctx.aliases)
            self.assertIsNone(ctx.active_profile)
            self.assertEqual("codex", ctx.default_ai_tool)


class AiCommandBuilderTests(unittest.TestCase):
    def test_codex_command_adds_default_cd(self) -> None:
        cwd = Path("C:/WorkSpace/custom-tm")

        command = mysh.build_codex_command(["--help"], cwd)

        self.assertEqual(["codex", "--cd", str(cwd), "--help"], command)

    def test_codex_command_does_not_duplicate_existing_cd(self) -> None:
        cwd = Path("C:/WorkSpace/custom-tm")

        command = mysh.build_codex_command(["-C", "D:/repo", "--help"], cwd)

        self.assertEqual(["codex", "-C", "D:/repo", "--help"], command)

    def test_claude_command_preserves_user_args(self) -> None:
        cwd = Path("C:/WorkSpace/custom-tm")

        command = mysh.build_claude_command(["--help"], cwd)

        self.assertEqual(["claude", "--help"], command)

    @unittest.skipUnless(os.name == "nt", "Windows shim resolution is platform-specific")
    def test_windows_resolver_prefers_cmd_over_extensionless_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tool").write_text("", encoding="utf-8")
            (root / "tool.cmd").write_text("@echo off\n", encoding="utf-8")
            (root / "tool.ps1").write_text("", encoding="utf-8")

            with mock.patch.dict(os.environ, {"PATH": str(root)}):
                resolved = mysh.resolve_executable_for_subprocess("tool")

            self.assertEqual(str(root / "tool.cmd"), resolved)

    def test_command_summary_does_not_store_prompt_body(self) -> None:
        summary = mysh.summarize_ai_command("claude", ["write", "secret", "plan"])

        self.assertIn("prompt=yes", summary)
        self.assertIn("chars=17", summary)
        self.assertNotIn("secret", summary)
        self.assertNotIn("plan", summary)

    def test_claude_print_flag_does_not_consume_prompt_in_summary(self) -> None:
        summary = mysh.summarize_ai_command("claude", ["-p", "hello"])

        self.assertIn("-p", summary)
        self.assertIn("prompt=yes", summary)
        self.assertIn("chars=5", summary)
        self.assertNotIn("hello", summary)

    def test_rerunnable_args_keep_flags_but_drop_prompt_and_dangerous_options(self) -> None:
        args = mysh.extract_rerunnable_ai_args(
            "codex",
            ["--model", "gpt-5", "--dangerously-bypass-approvals-and-sandbox", "write", "secret"],
        )

        self.assertEqual(["--model", "gpt-5"], args)

    def test_rerunnable_args_drop_resume_and_continue_flags(self) -> None:
        args = mysh.extract_rerunnable_ai_args(
            "claude",
            ["--continue", "--resume", "old-session", "-r", "another-session", "--model", "sonnet", "prompt"],
        )

        self.assertEqual(["--model", "sonnet"], args)

    def test_rerunnable_args_drop_dangerous_value_options(self) -> None:
        args = mysh.extract_rerunnable_ai_args(
            "codex",
            [
                "-c",
                "approval_policy=never",
                "-c",
                'model="gpt-5"',
                "--sandbox",
                "danger-full-access",
                "--model",
                "gpt-5",
                "prompt",
            ],
        )

        self.assertEqual(["-c", 'model="gpt-5"', "--model", "gpt-5"], args)

    def test_rerunnable_args_drop_claude_permission_bypass_value(self) -> None:
        args = mysh.extract_rerunnable_ai_args(
            "claude",
            ["--permission-mode", "bypassPermissions", "--model", "sonnet", "prompt"],
        )

        self.assertEqual(["--model", "sonnet"], args)


class InputCompletionTests(unittest.TestCase):
    def test_normalize_input_line_removes_leading_bom(self) -> None:
        self.assertEqual("ai doctor", mysh.normalize_input_line("\ufeffai doctor\n"))

    def test_completion_candidates_include_commands_aliases_and_ai_subcommands(self) -> None:
        ctx = mysh.ShellContext()
        ctx.aliases["gs"] = "git status"

        candidates = mysh.command_completion_candidates(ctx)

        self.assertIn("help", candidates)
        self.assertIn("gs", candidates)
        self.assertIn("ai doctor", candidates)
        self.assertIn("ai start codex", candidates)


class AiSessionCommandTests(unittest.TestCase):
    def make_session(self, session_id: str, tool: str, exit_code, cwd: Path) -> mysh.AiSession:
        return mysh.AiSession(
            id=session_id,
            title=f"{tool} session",
            tool=tool,
            cwd=str(cwd),
            command=f"{tool} --model <value> [prompt=no, chars=0, args=0]",
            profile="default",
            created_at="2026-06-17T10:00:00+09:00",
            updated_at=f"2026-06-17T10:0{session_id[-1]}:00+09:00",
            exit_code=exit_code,
            args=["--model", "gpt-5"],
        )

    def test_sessions_filter_by_tool_and_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = [
                self.make_session("codex-ok-1", "codex", 0, root),
                self.make_session("codex-fail-2", "codex", 1, root),
                self.make_session("claude-fail-3", "claude", 2, root),
                self.make_session("claude-open-4", "claude", None, root),
            ]

            filtered = mysh.filter_ai_sessions(sessions, tool="codex", failed_only=True)

            self.assertEqual(["codex-fail-2"], [session.id for session in filtered])

    def test_show_json_outputs_valid_session_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session("codex-json-1", "codex", 0, Path(tmp))
            output = StringIO()

            with redirect_stdout(output):
                mysh.print_ai_session_json(session)

            data = json.loads(output.getvalue())
            self.assertEqual("codex-json-1", data["id"])
            self.assertEqual("codex", data["tool"])
            self.assertEqual(["--model", "gpt-5"], data["args"])

    def test_ai_rerun_reconstructs_command_from_stored_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mysh.ShellContext(project_root=root)
            session = self.make_session("abc123", "codex", 1, root)
            session.args = ["--model", "gpt-5", "--dangerously-bypass-approvals-and-sandbox", "ignored prompt"]
            ctx.session_store.add(session)
            completed = subprocess.CompletedProcess(["codex"], 0)

            with mock.patch("mysh.refresh_project_context", lambda _ctx: None), mock.patch(
                "mysh.resolve_executable_for_subprocess", return_value="codex"
            ), mock.patch("mysh.subprocess.run", return_value=completed) as run_mock:
                exit_code = mysh.rerun_ai_session(ctx, "abc123")

            self.assertEqual(0, exit_code)
            run_mock.assert_called_once_with(
                ["codex", "--cd", str(root.resolve()), "--model", "gpt-5"],
                cwd=str(root.resolve()),
            )
            sessions = ctx.session_store.load()
            self.assertEqual(2, len(sessions))
            rerun = sessions[-1]
            self.assertEqual("rerun: codex session", rerun.title)
            self.assertEqual(0, rerun.exit_code)
            self.assertEqual(["--model", "gpt-5"], rerun.args)


class AiContextTests(unittest.TestCase):
    def write_readme(self, root: Path, line_count: int = 3) -> None:
        lines = ["# Demo", "", *[f"line {index}" for index in range(line_count)]]
        (root / "README.md").write_text("\n".join(lines), encoding="utf-8")

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_context_modes_return_text_in_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            self.write_readme(root)
            (root / "mysh.py").write_text("print('hi')\n", encoding="utf-8")
            store = mysh.AiSessionStore(root)

            for mode in ("default", "debug", "review", "handoff"):
                with self.subTest(mode=mode):
                    output = mysh.build_ai_context(root, mode=mode, session_store=store)

                    self.assertIn("## AI Context", output)
                    self.assertIn(f"Mode: {mode}", output)

    def test_context_max_lines_limits_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_readme(root, line_count=50)

            output = mysh.build_ai_context(root, mode="default", max_lines=5)

            self.assertLessEqual(len(output.splitlines()), 5)
            self.assertIn("(생략됨:", output)

    def test_context_in_non_git_directory_is_graceful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_readme(root)

            output = mysh.build_ai_context(root, mode="debug", max_lines=50)

            self.assertIn("## AI Context", output)
            self.assertIn("## Test Command Hints", output)
            self.assertNotIn("## Git Diff", output)

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_review_context_includes_untracked_file_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            self.write_readme(root)
            untracked = root / "new_notes.txt"
            untracked.write_text("new context\nsecond line\n", encoding="utf-8")

            output = mysh.build_ai_context(root, mode="review", max_lines=80)

            self.assertIn("# untracked files", output)
            self.assertIn("?? new_notes.txt", output)
            self.assertIn("new context", output)

    @unittest.skipUnless(shutil.which("git") and hasattr(os, "symlink"), "git and symlink support are required")
    def test_review_context_does_not_preview_untracked_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "repo"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            self.write_readme(root)
            outside = parent / "secret.txt"
            outside.write_text("outside secret\n", encoding="utf-8")
            link = root / "notes.txt"
            try:
                os.symlink(outside, link)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            output = mysh.build_ai_context(root, mode="review", max_lines=80)

            self.assertIn("?? notes.txt", output)
            self.assertNotIn("outside secret", output)
            self.assertNotIn("--- notes.txt (untracked preview", output)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support is required")
    def test_todo_scan_does_not_follow_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "repo"
            root.mkdir()
            outside = parent / "secret.txt"
            outside.write_text("TODO outside secret\n", encoding="utf-8")
            link = root / "todo.txt"
            try:
                os.symlink(outside, link)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            lines = mysh.todo_scan_lines(root)

            self.assertEqual(["(TODO/FIXME 없음)"], lines)

    def test_unknown_context_mode_lists_available_modes(self) -> None:
        with self.assertRaises(ValueError) as raised:
            mysh.parse_ai_context_options(["--mode", "unknown"])

        message = str(raised.exception)
        self.assertIn("사용 가능", message)
        self.assertIn("debug", message)
        self.assertIn("review", message)
        self.assertIn("handoff", message)


if __name__ == "__main__":
    unittest.main()
