import json
import os
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


if __name__ == "__main__":
    unittest.main()
