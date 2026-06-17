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


class AiTaskStoreTests(unittest.TestCase):
    def test_task_command_roundtrip_new_show_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mysh.ShellContext(project_root=root)
            original_cwd = Path.cwd()

            try:
                os.chdir(root)
                with mock.patch("mysh.refresh_project_context", lambda _ctx: None):
                    output = StringIO()
                    with redirect_stdout(output):
                        mysh.cmd_ai(ctx, [], 'task new "write retry docs"')

                    tasks, current_task_id = ctx.task_store.load_state()
                    self.assertEqual(1, len(tasks))
                    task = tasks[0]
                    self.assertEqual(task.id, current_task_id)
                    self.assertEqual("write retry docs", task.goal)
                    self.assertEqual("active", task.status)

                    show_output = StringIO()
                    with redirect_stdout(show_output):
                        mysh.cmd_ai(ctx, [], f"task show {task.id}")
                    self.assertIn("write retry docs", show_output.getvalue())

                    done_output = StringIO()
                    with redirect_stdout(done_output):
                        mysh.cmd_ai(ctx, [], f'task done {task.id} --next "open PR"')
            finally:
                os.chdir(original_cwd)

            done = ctx.task_store.get(task.id)
            self.assertIsNotNone(done)
            assert done is not None
            self.assertEqual("done", done.status)
            self.assertEqual("open PR", done.next_action)
            self.assertIsNone(ctx.task_store.current())

    def test_active_task_links_new_ai_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mysh.ShellContext(project_root=root)
            task = mysh.AiTask(
                id="task123",
                goal="run codex",
                cwd=str(root),
                status="active",
                created_at="2026-06-17T10:00:00+09:00",
                updated_at="2026-06-17T10:00:00+09:00",
            )
            ctx.task_store.add(task)
            completed = subprocess.CompletedProcess(["codex"], 0)

            with mock.patch("mysh.refresh_project_context", lambda _ctx: None), mock.patch(
                "mysh.resolve_executable_for_subprocess", return_value="codex"
            ), mock.patch("mysh.subprocess.run", return_value=completed):
                exit_code = mysh.run_ai_tool_session(ctx, "codex", ["--model", "gpt-5"], cwd_override=root)

            self.assertEqual(0, exit_code)
            sessions = ctx.session_store.load()
            linked = ctx.task_store.get("task123")
            self.assertIsNotNone(linked)
            assert linked is not None
            self.assertEqual([sessions[-1].id], linked.session_ids)

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_changed_files_are_captured_against_git_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, text=True, check=True)

            task = mysh.create_ai_task(root, "change files")
            tracked.write_text("changed\n", encoding="utf-8")
            (root / "new.txt").write_text("new\n", encoding="utf-8")

            changed = mysh.changed_git_files_since_baseline(root, task.git_baseline)

            self.assertIsNotNone(changed)
            assert changed is not None
            self.assertTrue(any("tracked.txt" in line for line in changed))
            self.assertTrue(any("new.txt" in line for line in changed))

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_changed_files_do_not_readd_preexisting_dirty_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, text=True, check=True)
            tracked.write_text("dirty before task\n", encoding="utf-8")

            task = mysh.create_ai_task(root, "start from dirty tree")
            (root / "new.txt").write_text("new after task\n", encoding="utf-8")

            changed = mysh.changed_git_files_since_baseline(root, task.git_baseline)

            self.assertIsNotNone(changed)
            assert changed is not None
            self.assertFalse(any("tracked.txt" in line for line in changed))
            self.assertTrue(any("new.txt" in line for line in changed))

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_changed_files_ignore_preexisting_dirty_file_when_index_status_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, text=True, check=True)
            tracked.write_text("dirty before task\n", encoding="utf-8")

            task = mysh.create_ai_task(root, "stage preexisting dirty file")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)

            changed = mysh.changed_git_files_since_baseline(root, task.git_baseline)

            self.assertIsNotNone(changed)
            assert changed is not None
            self.assertFalse(any("tracked.txt" in line for line in changed))

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_changed_files_include_first_commit_from_unborn_repo_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)

            task = mysh.create_ai_task(root, "first commit")
            (root / "first.txt").write_text("first\n", encoding="utf-8")
            subprocess.run(["git", "add", "first.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, text=True, check=True)

            changed = mysh.changed_git_files_since_baseline(root, task.git_baseline)

            self.assertIsNotNone(changed)
            assert changed is not None
            self.assertTrue(any("first.txt" in line for line in changed))

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_changed_files_filter_preexisting_staged_file_from_unborn_repo_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
            (root / "before.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "before.txt"], cwd=root, check=True)

            task = mysh.create_ai_task(root, "first commit with preexisting staged file")
            (root / "after.txt").write_text("after\n", encoding="utf-8")
            subprocess.run(["git", "add", "after.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, capture_output=True, text=True, check=True)

            changed = mysh.changed_git_files_since_baseline(root, task.git_baseline)

            self.assertIsNotNone(changed)
            assert changed is not None
            self.assertFalse(any("before.txt" in line for line in changed))
            self.assertTrue(any("after.txt" in line for line in changed))

    def test_task_git_fields_are_omitted_outside_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("mysh.is_git_repository", return_value=False):
                task = mysh.create_ai_task(root, "no git")
                changed = mysh.changed_git_files_since_baseline(root, task.git_baseline)

            self.assertIsNone(task.git_baseline)
            self.assertIsNone(changed)
            self.assertNotIn("git_baseline", task.to_dict())
            self.assertNotIn("changed_files", task.to_dict())


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

    def test_alias_save_refreshes_project_context_after_cd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            project_a = parent / "project-a"
            project_b = parent / "project-b"
            project_a.mkdir()
            project_b.mkdir()
            ctx = mysh.ShellContext(project_root=project_a)
            ctx.aliases = {}
            ctx.save_config()
            original_cwd = Path.cwd()

            try:
                os.chdir(project_b)
                output = StringIO()
                with redirect_stdout(output):
                    mysh.cmd_alias(ctx, [], "gs=git status")
            finally:
                os.chdir(original_cwd)

            with (project_b / ".mysh" / "config.json").open("r", encoding="utf-8") as file:
                project_b_config = json.load(file)
            with (project_a / ".mysh" / "config.json").open("r", encoding="utf-8") as file:
                project_a_config = json.load(file)

            self.assertEqual("git status", project_b_config["aliases"]["gs"])
            self.assertEqual({}, project_a_config["aliases"])


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


class ExternalCommandSafetyTests(unittest.TestCase):
    def test_policy_segment_split_handles_shell_operators(self) -> None:
        self.assertEqual(["a", "rm -rf b"], mysh.split_command_segments("a && rm -rf b", posix=False))
        self.assertEqual(["echo 'a && b'", "git status"], mysh.split_command_segments("echo 'a && b' | git status", posix=False))

    def test_policy_decision_allow_ask_and_deny(self) -> None:
        rules = [
            {"match": r"^safe\b", "action": "allow", "reason": "safe command"},
            {"match": r"^maybe\b", "action": "ask", "reason": "needs confirmation"},
            {"match": r"^never\b", "action": "deny", "reason": "blocked"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual("allow", mysh.evaluate_command_policy("safe run", rules, root).action)

            ask = mysh.evaluate_command_policy("maybe run", rules, root)
            self.assertEqual("ask", ask.action)
            self.assertEqual("needs confirmation", ask.reason)

            deny = mysh.evaluate_command_policy("safe run && never run", rules, root)
            self.assertEqual("deny", deny.action)
            self.assertEqual("blocked", deny.reason)

    def test_policy_deny_wins_over_earlier_ask_for_same_segment(self) -> None:
        rules = [
            {"match": r"drop", "action": "ask", "reason": "broad ask"},
            {"match": r"drop\s+table", "action": "deny", "reason": "drop table blocked"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            decision = mysh.evaluate_command_policy("drop table users", rules, Path(tmp))

        self.assertEqual("deny", decision.action)
        self.assertEqual("drop table blocked", decision.reason)

    def test_invalid_policy_regex_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mysh.CommandPolicyStore(root)
            store.save([{"match": "(", "action": "deny", "reason": "typo"}])

            decision = mysh.evaluate_command_policy("echo hello", store.load(), root)

        self.assertEqual("deny", decision.action)
        self.assertIn("invalid policy regex", decision.reason)

    def test_malformed_policy_rule_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mysh.CommandPolicyStore(root)
            store.save(
                [
                    {"match": r"^safe\b", "action": "allow", "reason": "safe"},
                    {"match": r"rm\s+-rf", "action": "typo", "reason": "bad action"},
                ]
            )

            decision = mysh.evaluate_command_policy("safe command", store.load(), root)

        self.assertEqual("deny", decision.action)
        self.assertEqual("invalid policy rule", decision.reason)

    def test_malformed_policy_match_type_and_container_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mysh.CommandPolicyStore(root)
            store.save(
                [
                    {"match": r"^safe\b", "action": "allow", "reason": "safe"},
                    {"match": [r"rm\s+-rf"], "action": "deny", "reason": "bad match"},
                ]
            )
            typed_decision = mysh.evaluate_command_policy("safe command", store.load(), root)

            store.path.write_text(json.dumps({"rules": {"match": r"^safe\b", "action": "allow"}}), encoding="utf-8")
            container_decision = mysh.evaluate_command_policy("safe command", store.load(), root)

        self.assertEqual("deny", typed_decision.action)
        self.assertEqual("invalid policy rule", typed_decision.reason)
        self.assertEqual("deny", container_decision.action)
        self.assertEqual("invalid policy rule", container_decision.reason)

    def test_policy_detects_outside_workspace_absolute_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            inside = root / "out.txt"
            outside = root.parent / "outside-policy-test.txt"

            inside_decision = mysh.evaluate_command_policy(f"echo hello > {inside}", [], root)
            outside_decision = mysh.evaluate_command_policy(f"echo hello > {outside}", [], root)

        self.assertEqual("allow", inside_decision.action)
        self.assertEqual("ask", outside_decision.action)
        self.assertIn("workspace outside", outside_decision.reason)

    def test_policy_outside_workspace_write_avoids_url_and_source_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root.parent / "source.txt"
            target = root / "dest.txt"
            outside_value = root.parent / "secret.txt"

            url_decision = mysh.evaluate_command_policy("curl https://example.com/file > out.txt", [], root)
            copy_decision = mysh.evaluate_command_policy(f"cp {source} {target}", [], root)
            value_decision = mysh.evaluate_command_policy(
                f"Set-Content -Path {target} -Value {outside_value}",
                [],
                root,
            )

        self.assertEqual("allow", url_decision.action)
        self.assertEqual("allow", copy_decision.action)
        self.assertEqual("allow", value_decision.action)

    def test_policy_outside_workspace_write_detects_powershell_path_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            outside = root.parent / "outside-policy-test.txt"

            decision = mysh.evaluate_command_policy(f"Set-Content -Path {outside} -Value ok", [], root)
            colon_path_decision = mysh.evaluate_command_policy(
                f"Set-Content -Path:{outside} -Value ok",
                [],
                root,
            )
            colon_literal_decision = mysh.evaluate_command_policy(
                f"Set-Content -LiteralPath:{outside} -Value ok",
                [],
                root,
            )
            colon_file_decision = mysh.evaluate_command_policy(
                f"Out-File -FilePath:{outside} -InputObject ok",
                [],
                root,
            )
            out_file_encoding_decision = mysh.evaluate_command_policy(
                f"Out-File -Encoding utf8 {outside}",
                [],
                root,
            )
            set_content_encoding_decision = mysh.evaluate_command_policy(
                f"Set-Content -Encoding utf8 {outside} -Value ok",
                [],
                root,
            )
            new_item_type_decision = mysh.evaluate_command_policy(
                f"New-Item -ItemType File {outside}",
                [],
                root,
            )
            tee_colon_file_decision = mysh.evaluate_command_policy(
                f"tee -FilePath:{outside}",
                [],
                root,
            )
            tee_object_file_decision = mysh.evaluate_command_policy(
                f"Tee-Object -FilePath {outside}",
                [],
                root,
            )
            tee_operand_decision = mysh.evaluate_command_policy(
                f"tee {outside}",
                [],
                root,
            )
            copy_decision = mysh.evaluate_command_policy(
                f"Copy-Item -Path {root / 'in.txt'} -Destination {outside}",
                [],
                root,
            )
            colon_destination_decision = mysh.evaluate_command_policy(
                f"Copy-Item -Path {root / 'in.txt'} -Destination:{outside}",
                [],
                root,
            )
            copy_with_log_decision = mysh.evaluate_command_policy(
                f"Copy-Item -Path {root / 'in.txt'} -Destination {outside} > {root / 'copy.log'}",
                [],
                root,
            )
            second_redirect_decision = mysh.evaluate_command_policy(
                f"Copy-Item -Path {root / 'in.txt'} -Destination {root / 'out.txt'} > {root / 'copy.log'} 2> {outside}",
                [],
                root,
            )
            move_decision = mysh.evaluate_command_policy(
                f"Move-Item -Path {root / 'in.txt'} -Destination {outside}",
                [],
                root,
            )

        self.assertEqual("ask", decision.action)
        self.assertIn("workspace outside", decision.reason)
        self.assertEqual("ask", colon_path_decision.action)
        self.assertIn("workspace outside", colon_path_decision.reason)
        self.assertEqual("ask", colon_literal_decision.action)
        self.assertIn("workspace outside", colon_literal_decision.reason)
        self.assertEqual("ask", colon_file_decision.action)
        self.assertIn("workspace outside", colon_file_decision.reason)
        self.assertEqual("ask", out_file_encoding_decision.action)
        self.assertIn("workspace outside", out_file_encoding_decision.reason)
        self.assertEqual("ask", set_content_encoding_decision.action)
        self.assertIn("workspace outside", set_content_encoding_decision.reason)
        self.assertEqual("ask", new_item_type_decision.action)
        self.assertIn("workspace outside", new_item_type_decision.reason)
        self.assertEqual("ask", tee_colon_file_decision.action)
        self.assertIn("workspace outside", tee_colon_file_decision.reason)
        self.assertEqual("ask", tee_object_file_decision.action)
        self.assertIn("workspace outside", tee_object_file_decision.reason)
        self.assertEqual("ask", tee_operand_decision.action)
        self.assertIn("workspace outside", tee_operand_decision.reason)
        self.assertEqual("ask", copy_decision.action)
        self.assertIn("workspace outside", copy_decision.reason)
        self.assertEqual("ask", colon_destination_decision.action)
        self.assertIn("workspace outside", colon_destination_decision.reason)
        self.assertEqual("ask", copy_with_log_decision.action)
        self.assertIn("workspace outside", copy_with_log_decision.reason)
        self.assertEqual("ask", second_redirect_decision.action)
        self.assertIn("workspace outside", second_redirect_decision.reason)
        self.assertEqual("ask", move_decision.action)
        self.assertIn("workspace outside", move_decision.reason)

    def test_dangerous_command_patterns_are_detected(self) -> None:
        dangerous = [
            "rm -rf build",
            "rm -r old",
            "rm -f -r build",
            "rm -f --recursive build",
            "DEL C:\\temp\\old.txt",
            "Remove-Item -Recurse C:\\temp\\old",
            "git reset --hard HEAD",
            "git clean -fdx",
            "DROP TABLE users",
            "drop database app",
            "mkfs.ext4 /dev/sdb1",
            "cat image.iso > /dev/sda",
            ":(){ :|:& };:",
        ]

        for command in dangerous:
            with self.subTest(command=command):
                self.assertIsNotNone(mysh.detect_dangerous_command(command))

    def test_safe_command_patterns_are_not_detected(self) -> None:
        safe = [
            "git status",
            "git reset --soft HEAD~1",
            "git cleanly formatted docs",
            "git clean -n",
            "git clean --dry-run",
            "git clean -nd",
            "git clean --help",
            "echo hello",
            "drop tablet notes",
            "model train",
        ]

        for command in safe:
            with self.subTest(command=command):
                self.assertIsNone(mysh.detect_dangerous_command(command))

    def test_bang_escape_hatch_skips_safety_confirmation(self) -> None:
        ctx = mysh.ShellContext()

        with mock.patch("mysh.run_external_command") as run_mock:
            mysh.execute_line(ctx, "!rm -rf build")

        run_mock.assert_called_once_with("rm -rf build", bypass_safety=True)

    def test_policy_bypass_skips_ask_but_not_deny(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = [{"match": r"rm\s+-rf", "action": "ask", "reason": "remove recursively"}]
            mysh.CommandPolicyStore(root).save(rules)
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with mock.patch("mysh.detect_project_root", return_value=root), mock.patch(
                    "mysh.subprocess.run"
                ) as run_mock:
                    run_mock.return_value.returncode = 0
                    mysh.run_external_command("rm -rf build", bypass_safety=True)
                run_mock.assert_called_once()

                mysh.CommandPolicyStore(root).save(
                    [{"match": r"rm\s+-rf", "action": "deny", "reason": "blocked"}]
                )
                output = StringIO()
                with mock.patch("mysh.detect_project_root", return_value=root), mock.patch(
                    "mysh.subprocess.run"
                ) as run_mock, redirect_stdout(output):
                    mysh.run_external_command("rm -rf build", bypass_safety=True)
                run_mock.assert_not_called()
            finally:
                os.chdir(old_cwd)

        self.assertIn("차단", output.getvalue())

    def test_noninteractive_dangerous_command_is_blocked(self) -> None:
        output = StringIO()

        with mock.patch("mysh.detect_project_root", return_value=Path.cwd()), mock.patch(
            "mysh.is_interactive_stdin", return_value=False
        ), mock.patch("mysh.subprocess.run") as run_mock, redirect_stdout(output):
            mysh.run_external_command("rm -rf build")

        run_mock.assert_not_called()
        self.assertIn("차단", output.getvalue())

    def test_noninteractive_ask_and_deny_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mysh.CommandPolicyStore(root).save(
                [
                    {"match": r"^ask-me\b", "action": "ask", "reason": "confirm"},
                    {"match": r"^deny-me\b", "action": "deny", "reason": "blocked"},
                ]
            )
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with mock.patch("mysh.detect_project_root", return_value=root), mock.patch(
                    "mysh.is_interactive_stdin", return_value=False
                ), mock.patch("mysh.subprocess.run") as run_mock:
                    mysh.run_external_command("ask-me")
                    mysh.run_external_command("deny-me")
                run_mock.assert_not_called()
            finally:
                os.chdir(old_cwd)

    def test_policy_store_corrupt_json_falls_back_to_defaults_and_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = mysh.CommandPolicyStore(Path(tmp))
            store.ensure_store_dir()
            store.path.write_text("{not json", encoding="utf-8")

            rules = store.load()

            self.assertEqual(mysh.default_policy_rules(), rules)
            self.assertTrue(store.backup_path.exists())


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

    def test_run_ai_tool_session_persists_profile_from_user_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mysh.ShellContext(project_root=root)
            completed = subprocess.CompletedProcess(["codex"], 0)

            with mock.patch("mysh.refresh_project_context", lambda _ctx: None), mock.patch(
                "mysh.resolve_executable_for_subprocess", return_value="codex"
            ), mock.patch("mysh.ensure_mysh_gitignore", lambda _root: None), mock.patch(
                "mysh.subprocess.run", return_value=completed
            ):
                exit_code = mysh.run_ai_tool_session(
                    ctx,
                    "codex",
                    ["--profile", "work", "--model", "gpt-5"],
                    cwd_override=root,
                )

            self.assertEqual(0, exit_code)
            loaded = mysh.ShellContext(project_root=root)
            self.assertEqual("work", loaded.active_profile)
            sessions = loaded.session_store.load()
            self.assertEqual("work", sessions[-1].profile)


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
