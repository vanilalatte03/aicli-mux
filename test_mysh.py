import json
import os
import shutil
import subprocess
import tempfile
import unittest
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
