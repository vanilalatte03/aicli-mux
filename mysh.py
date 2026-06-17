# 새 명령어 추가: 아래의 @command("이름", "설명") 데코레이터를 붙인 함수를 만든다.
# 함수 시그니처는 func(ctx, args, raw_args) 형태를 사용한다.
# args는 공백 기준으로 나눈 인자 목록이고, raw_args는 명령어 뒤 원문 문자열이다.
# 파일 아래쪽의 "내장 명령어" 섹션 예시를 복사해서 고치면 된다.

"""Python 표준 라이브러리만 사용하는 작은 대화형 커스텀 셸."""

from __future__ import annotations

import ctypes
import datetime as _dt
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from rich.console import Console as RichConsole
    from rich.markup import escape as rich_markup_escape
    from rich.panel import Panel as RichPanel
    from rich.table import Table as RichTable

    RICH = True
except ImportError:
    RichConsole = None  # type: ignore[assignment]
    RichPanel = None  # type: ignore[assignment]
    RichTable = None  # type: ignore[assignment]
    rich_markup_escape = None  # type: ignore[assignment]
    RICH = False

try:
    from prompt_toolkit import PromptSession as PromptToolkitSession
    from prompt_toolkit.completion import Completer as PromptCompleter
    from prompt_toolkit.completion import Completion as PromptCompletion
    from prompt_toolkit.formatted_text import ANSI as PromptANSI
    from prompt_toolkit.history import FileHistory as PromptFileHistory
    from prompt_toolkit.key_binding import KeyBindings as PromptKeyBindings
    from prompt_toolkit.patch_stdout import patch_stdout as prompt_patch_stdout

    PROMPT_TOOLKIT = True
except ImportError:
    PromptToolkitSession = None  # type: ignore[assignment]
    PromptCompleter = None  # type: ignore[assignment]
    PromptCompletion = None  # type: ignore[assignment]
    PromptANSI = None  # type: ignore[assignment]
    PromptFileHistory = None  # type: ignore[assignment]
    PromptKeyBindings = None  # type: ignore[assignment]
    prompt_patch_stdout = None  # type: ignore[assignment]
    PROMPT_TOOLKIT = False


# -----------------------------------------------------------------------------
# ANSI 색상과 프롬프트 테마
# -----------------------------------------------------------------------------


class Ansi:
    RESET = "\033[0m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"


STATUS_OK = "OK"
STATUS_WARN = "경고"
STATUS_NONE = "없음"

TREE_EXCLUDED_NAMES = {".git", "node_modules", "__pycache__", ".mysh"}
TEXT_PREVIEW_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".text",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
GIT_EMPTY_TREE_SHA1 = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
AI_CONTEXT_MODES = ("default", "debug", "review", "handoff", "ship")
AI_CONTEXT_DEFAULT_MAX_LINES = {
    "default": 200,
    "debug": 220,
    "review": 240,
    "handoff": 240,
    "ship": 240,
}
AI_CONTEXT_TEST_HINTS = (
    "python -m py_compile mysh.py",
    "python -m unittest test_mysh",
)
FAILURE_TRACE_KEYWORDS = (
    "traceback",
    "failed",
    "failure",
    "error",
    "exception",
    "assertionerror",
)
# 실수 방지용 과속방지턱이다. 정책 파일/정규식은 모든 위험 명령을 잡지 못하고
# 우회도 가능하므로, 보안 경계로 취급하지 않는다.
POLICY_ACTIONS = {"allow", "ask", "deny"}
DEFAULT_POLICY_RULES: List[Dict[str, str]] = [
    {
        "match": r"(?<![\w.-])rm(?:\.exe)?(?=[^\n;&|]*(?:\s-[A-Za-z]*r[A-Za-z]*\b|\s--recursive\b))",
        "action": "ask",
        "reason": "recursive rm can delete many files",
    },
    {"match": r"(?<![\w.-])del(?:\.exe)?(?![\w.-])", "action": "ask", "reason": "del removes files"},
    {"match": r"(?<![\w-])Remove-Item(?![\w-])", "action": "ask", "reason": "Remove-Item removes files"},
    {"match": r"\bgit\s+reset\b[^\n;&|]*--hard\b", "action": "ask", "reason": "git reset --hard discards work"},
    {
        "match": r"\bgit\s+clean\b(?![^\n;&|]*(?:\s--(?:dry-run|interactive|help)\b|\s-[A-Za-z]*[nih][A-Za-z]*\b))",
        "action": "ask",
        "reason": "git clean removes untracked files",
    },
    {"match": r"\bpip(?:3)?\s+install\b", "action": "ask", "reason": "pip install changes the Python environment"},
    {"match": r"\bnpm\s+install\b[^\n;&|]*\s-g\b|\bnpm\s+install\b[^\n;&|]*\s--global\b", "action": "ask", "reason": "global npm install changes the machine environment"},
    {"match": r"\b(?:curl|wget)\b[^\n;&|]*\|\s*(?:sh|bash)\b", "action": "ask", "reason": "downloaded shell script execution"},
    {"match": r"\b(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^\n;&|]*\|\s*(?:iex|Invoke-Expression)\b", "action": "ask", "reason": "downloaded PowerShell execution"},
    {"match": r"\bdrop\s+(?:table|database)\b", "action": "deny", "reason": "DROP TABLE/DATABASE is destructive"},
    {"match": r"(?<![\w.-])mkfs(?:\.[\w.-]+)?\b", "action": "deny", "reason": "mkfs formats filesystems"},
    {"match": r">\s*/dev/", "action": "deny", "reason": "writing to /dev devices can destroy data"},
    {"match": r":\s*\(\s*\)\s*\{", "action": "deny", "reason": "fork bomb pattern"},
]


THEMES = {
    "green": {
        "label": Ansi.BRIGHT_GREEN,
        "path": Ansi.CYAN,
        "time": Ansi.YELLOW,
        "symbol": Ansi.BRIGHT_GREEN,
    },
    "blue": {
        "label": Ansi.BRIGHT_BLUE,
        "path": Ansi.CYAN,
        "time": Ansi.WHITE,
        "symbol": Ansi.BRIGHT_BLUE,
    },
    "magenta": {
        "label": Ansi.BRIGHT_MAGENTA,
        "path": Ansi.BRIGHT_CYAN,
        "time": Ansi.YELLOW,
        "symbol": Ansi.BRIGHT_MAGENTA,
    },
    "mono": {
        "label": "",
        "path": "",
        "time": "",
        "symbol": "",
    },
}


def default_aliases() -> Dict[str, str]:
    return {
        "h": "help",
        "ll": "ls",
        "q": "quit",
    }


def color(text: str, ansi_code: str) -> str:
    """색상 코드가 비어 있으면 원문 그대로 반환한다."""
    if not ansi_code:
        return text
    return f"{ansi_code}{text}{Ansi.RESET}"


def configure_utf8_console() -> None:
    """Windows 콘솔에서 UTF-8 입출력을 우선 사용하도록 맞춘다."""
    if os.name != "nt":
        return

    os.system("chcp 65001 > nul 2>&1")
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def enable_ansi_on_windows() -> None:
    """Windows 콘솔에서 colorama 없이 ANSI 이스케이프 색상을 활성화한다."""
    if os.name != "nt":
        return

    # 최신 Windows 터미널/PowerShell에서는 이 호출만으로도 ANSI가 켜지는 경우가 많다.
    os.system("")

    # 구형 콘솔 호스트를 위해 Virtual Terminal Processing 플래그도 직접 켠다.
    kernel32 = ctypes.windll.kernel32
    stdout_handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)


# -----------------------------------------------------------------------------
# 명령어 레지스트리
# -----------------------------------------------------------------------------


CommandHandler = Callable[["ShellContext", List[str], str], None]


@dataclass
class Command:
    name: str
    description: str
    handler: CommandHandler


COMMANDS: Dict[str, Command] = {}

AI_SUBCOMMAND_COMPLETIONS = (
    "ai doctor",
    "ai context",
    "ai context --mode debug",
    "ai context --mode review",
    "ai context --mode handoff",
    "ai context --mode ship",
    "ai config",
    "ai config reset",
    "ai policy",
    "ai policy init",
    "ai rerun",
    "ai sessions",
    "ai sessions --tool codex",
    "ai sessions --failed",
    "ai show",
    "ai show --json",
    "ai start",
    "ai start codex",
    "ai start claude",
    "ai task",
    "ai task current",
    "ai task done",
    "ai task list",
    "ai task new",
    "ai task show",
    "ai task use",
)


def command(name: str, description: str) -> Callable[[CommandHandler], CommandHandler]:
    """내장 명령어를 등록하는 데코레이터."""

    def decorator(func: CommandHandler) -> CommandHandler:
        COMMANDS[name] = Command(name=name, description=description, handler=func)
        return func

    return decorator


# -----------------------------------------------------------------------------
# 셸 상태와 유틸리티
# -----------------------------------------------------------------------------


def now_iso() -> str:
    """사람이 읽기 쉬운 로컬 시간 ISO 문자열을 만든다."""
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def detect_project_root(start: Optional[Path] = None) -> Path:
    """Git 루트가 있으면 그곳을, 없으면 현재 폴더를 프로젝트 루트로 쓴다."""
    current = (start or Path.cwd()).resolve()
    git = shutil.which("git")
    if git:
        try:
            result = subprocess.run(
                [git, "-C", str(current), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            result = None
        if result and result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()

    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate.resolve()
    return current


def is_git_project(root: Path) -> bool:
    """주어진 루트가 Git 저장소인지 확인한다."""
    root = root.resolve()
    if (root / ".git").exists():
        return True

    git = shutil.which("git")
    if not git:
        return False
    try:
        result = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def gitignore_has_mysh(lines: List[str]) -> bool:
    """이미 .mysh가 무시되고 있는지 느슨하게 판단한다."""
    ignored_forms = {".mysh", ".mysh/", "/.mysh", "/.mysh/"}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ignored_forms:
            return True
    return False


def ensure_mysh_gitignore(project_root: Path) -> None:
    """Git 저장소라면 .mysh/가 .gitignore에 들어가도록 보장한다."""
    if not is_git_project(project_root):
        return

    gitignore = project_root / ".gitignore"
    try:
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            if gitignore_has_mysh(lines):
                return
            separator = "" if not content or content.endswith(("\n", "\r")) else "\n"
            gitignore.write_text(f"{content}{separator}.mysh/\n", encoding="utf-8")
        else:
            gitignore.write_text(".mysh/\n", encoding="utf-8")
    except OSError:
        # 세션 기록 자체는 계속 가능해야 하므로 .gitignore 갱신 실패는 조용히 넘긴다.
        return


@dataclass
class AiSession:
    id: str
    title: str
    tool: str
    cwd: str
    command: str
    profile: Optional[str]
    created_at: str
    updated_at: str
    exit_code: Optional[int]
    args: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "tool": self.tool,
            "cwd": self.cwd,
            "command": self.command,
            "args": list(self.args),
            "profile": self.profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AiSession":
        exit_code = data.get("exit_code")
        if not isinstance(exit_code, int):
            exit_code = None
        raw_args = data.get("args", [])
        args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            tool=str(data.get("tool", "")),
            cwd=str(data.get("cwd", "")),
            command=str(data.get("command", "")),
            profile=data.get("profile") if data.get("profile") is None else str(data.get("profile")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            exit_code=exit_code,
            args=args,
        )


class AiSessionStore:
    """프로젝트 루트 아래 .mysh/sessions.json을 관리한다."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.store_dir = self.project_root / ".mysh"
        self.path = self.store_dir / "sessions.json"
        self.backup_path = self.store_dir / "sessions.json.bak"

    def ensure_store_dir(self) -> None:
        existed = self.store_dir.exists()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if not existed:
            ensure_mysh_gitignore(self.project_root)

    def load(self) -> List[AiSession]:
        if not self.path.exists():
            return []

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            self.recover_corrupt_store()
            return []

        if isinstance(data, dict):
            raw_sessions = data.get("sessions", [])
        else:
            raw_sessions = data

        if not isinstance(raw_sessions, list):
            self.recover_corrupt_store()
            return []

        sessions: List[AiSession] = []
        for item in raw_sessions:
            if not isinstance(item, dict):
                continue
            session = AiSession.from_dict(item)
            if session.id:
                sessions.append(session)
        return sessions

    def save(self, sessions: List[AiSession]) -> None:
        self.ensure_store_dir()
        payload = {"sessions": [session.to_dict() for session in sessions]}
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)

    def add(self, session: AiSession) -> None:
        sessions = self.load()
        sessions.append(session)
        self.save(sessions)

    def update(self, session: AiSession) -> None:
        sessions = self.load()
        for index, current in enumerate(sessions):
            if current.id == session.id:
                sessions[index] = session
                self.save(sessions)
                return
        sessions.append(session)
        self.save(sessions)

    def get(self, session_id: str) -> Optional[AiSession]:
        sessions = self.load()
        for session in sessions:
            if session.id == session_id:
                return session

        matches = [session for session in sessions if session.id.startswith(session_id)]
        if len(matches) == 1:
            return matches[0]
        return None

    def recover_corrupt_store(self) -> None:
        self.ensure_store_dir()
        try:
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
        except OSError:
            pass
        self.save([])


@dataclass
class AiTask:
    id: str
    goal: str
    cwd: str
    status: str
    created_at: str
    updated_at: str
    session_ids: List[str] = field(default_factory=list)
    git_baseline: Optional[Dict[str, Any]] = None
    changed_files: Optional[List[str]] = None
    test_result: Optional[str] = None
    next_action: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "goal": self.goal,
            "cwd": self.cwd,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "session_ids": list(self.session_ids),
        }
        if self.git_baseline is not None:
            data["git_baseline"] = self.git_baseline
        if self.changed_files is not None:
            data["changed_files"] = list(self.changed_files)
        if self.test_result:
            data["test_result"] = self.test_result
        if self.next_action:
            data["next_action"] = self.next_action
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AiTask":
        raw_status = str(data.get("status", "active"))
        status = raw_status if raw_status in {"active", "done"} else "active"
        raw_session_ids = data.get("session_ids", [])
        session_ids = [str(item) for item in raw_session_ids] if isinstance(raw_session_ids, list) else []

        raw_baseline = data.get("git_baseline")
        git_baseline = raw_baseline if isinstance(raw_baseline, dict) else None

        raw_changed_files = data.get("changed_files")
        changed_files = [str(item) for item in raw_changed_files] if isinstance(raw_changed_files, list) else None

        test_result = data.get("test_result")
        next_action = data.get("next_action")
        return cls(
            id=str(data.get("id", "")),
            goal=str(data.get("goal", "")),
            cwd=str(data.get("cwd", "")),
            status=status,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            session_ids=session_ids,
            git_baseline=git_baseline,
            changed_files=changed_files,
            test_result=str(test_result) if test_result else None,
            next_action=str(next_action) if next_action else None,
        )


class AiTaskStore:
    """프로젝트 루트 아래 .mysh/tasks.json을 관리한다."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.store_dir = self.project_root / ".mysh"
        self.path = self.store_dir / "tasks.json"
        self.backup_path = self.store_dir / "tasks.json.bak"

    def ensure_store_dir(self) -> None:
        existed = self.store_dir.exists()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if not existed:
            ensure_mysh_gitignore(self.project_root)

    def load_state(self) -> tuple[List[AiTask], Optional[str]]:
        if not self.path.exists():
            return [], None

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            self.recover_corrupt_store()
            return [], None

        current_task_id: Optional[str] = None
        if isinstance(data, dict):
            raw_tasks = data.get("tasks", [])
            raw_current = data.get("current_task_id")
            if isinstance(raw_current, str) and raw_current:
                current_task_id = raw_current
        else:
            raw_tasks = data

        if not isinstance(raw_tasks, list):
            self.recover_corrupt_store()
            return [], None

        tasks: List[AiTask] = []
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            task = AiTask.from_dict(item)
            if task.id:
                tasks.append(task)
        return tasks, current_task_id

    def load(self) -> List[AiTask]:
        tasks, _current_task_id = self.load_state()
        return tasks

    def save_state(self, tasks: List[AiTask], current_task_id: Optional[str]) -> None:
        self.ensure_store_dir()
        payload: Dict[str, Any] = {"tasks": [task.to_dict() for task in tasks]}
        if current_task_id:
            payload["current_task_id"] = current_task_id
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)

    def add(self, task: AiTask, set_current: bool = True) -> None:
        tasks, current_task_id = self.load_state()
        tasks.append(task)
        self.save_state(tasks, task.id if set_current else current_task_id)

    def update(self, task: AiTask, current_task_id: Optional[str]) -> None:
        tasks, _previous_current = self.load_state()
        for index, current in enumerate(tasks):
            if current.id == task.id:
                tasks[index] = task
                self.save_state(tasks, current_task_id)
                return
        tasks.append(task)
        self.save_state(tasks, current_task_id)

    def get(self, task_id: str) -> Optional[AiTask]:
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                return task

        matches = [task for task in tasks if task.id.startswith(task_id)]
        if len(matches) == 1:
            return matches[0]
        return None

    def current(self) -> Optional[AiTask]:
        tasks, current_task_id = self.load_state()
        if not current_task_id:
            return None
        for task in tasks:
            if task.id == current_task_id and task.status == "active":
                return task
        return None

    def set_current(self, task_id: str) -> Optional[AiTask]:
        tasks, _current_task_id = self.load_state()
        matches = [task for task in tasks if task.id == task_id or task.id.startswith(task_id)]
        if len(matches) != 1 or matches[0].status != "active":
            return None
        self.save_state(tasks, matches[0].id)
        return matches[0]

    def add_session_to_current(self, session_id: str) -> Optional[AiTask]:
        tasks, current_task_id = self.load_state()
        if not current_task_id:
            return None
        for index, task in enumerate(tasks):
            if task.id == current_task_id and task.status == "active":
                if session_id not in task.session_ids:
                    task.session_ids.append(session_id)
                    task.updated_at = now_iso()
                    tasks[index] = task
                    self.save_state(tasks, current_task_id)
                return task
        return None

    def recover_corrupt_store(self) -> None:
        self.ensure_store_dir()
        try:
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
        except OSError:
            pass
        self.save_state([], None)


class CommandPolicyStore:
    """프로젝트 루트 아래 .mysh/policy.json을 관리한다."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.store_dir = self.project_root / ".mysh"
        self.path = self.store_dir / "policy.json"
        self.backup_path = self.store_dir / "policy.json.bak"

    def ensure_store_dir(self) -> None:
        existed = self.store_dir.exists()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if not existed:
            ensure_mysh_gitignore(self.project_root)

    def load(self) -> List[Dict[str, str]]:
        if not self.path.exists():
            return default_policy_rules()

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return self.recover_corrupt_store()

        raw_rules = data.get("rules") if isinstance(data, dict) else data
        if not isinstance(raw_rules, list):
            return [{"match": r"(?s).*", "action": "deny", "reason": "invalid policy rule"}]
        return normalize_policy_rules(raw_rules)

    def save(self, rules: List[Dict[str, str]]) -> None:
        self.ensure_store_dir()
        payload = {"rules": normalize_policy_rules(rules)}
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)

    def init_default(self) -> None:
        self.save(default_policy_rules())

    def recover_corrupt_store(self) -> List[Dict[str, str]]:
        self.ensure_store_dir()
        try:
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
        except OSError:
            pass
        return default_policy_rules()


def default_policy_rules() -> List[Dict[str, str]]:
    return [dict(rule) for rule in DEFAULT_POLICY_RULES]


def normalize_policy_rules(raw_rules: List[Any]) -> List[Dict[str, str]]:
    rules: List[Dict[str, str]] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            rules.append({"match": r"(?s).*", "action": "deny", "reason": "invalid policy rule"})
            continue
        raw_match = item.get("match")
        raw_action = item.get("action")
        raw_reason = item.get("reason", "")
        if (
            not isinstance(raw_match, str)
            or not isinstance(raw_action, str)
            or ("reason" in item and not isinstance(raw_reason, str))
        ):
            rules.append({"match": r"(?s).*", "action": "deny", "reason": "invalid policy rule"})
            continue
        match = raw_match.strip()
        action = raw_action.strip().lower()
        reason = raw_reason.strip()
        if not match or action not in POLICY_ACTIONS:
            rules.append({"match": r"(?s).*", "action": "deny", "reason": "invalid policy rule"})
            continue
        rules.append({"match": match, "action": action, "reason": reason or match})
    return rules or default_policy_rules()


def default_shell_config() -> Dict[str, Any]:
    return {
        "theme": "green",
        "aliases": default_aliases(),
        "active_profile": None,
        "default_ai_tool": "codex",
    }


class ShellConfigStore:
    """프로젝트 루트 아래 .mysh/config.json을 관리한다."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.store_dir = self.project_root / ".mysh"
        self.path = self.store_dir / "config.json"
        self.backup_path = self.store_dir / "config.json.bak"

    def ensure_store_dir(self) -> None:
        existed = self.store_dir.exists()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if not existed:
            ensure_mysh_gitignore(self.project_root)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return default_shell_config()

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return self.recover_corrupt_store()

        if not isinstance(data, dict):
            return self.recover_corrupt_store()
        return normalize_shell_config(data)

    def save(self, config: Dict[str, Any]) -> None:
        self.ensure_store_dir()
        payload = normalize_shell_config(config)
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)

    def reset(self) -> Dict[str, Any]:
        config = default_shell_config()
        self.save(config)
        return config

    def recover_corrupt_store(self) -> Dict[str, Any]:
        self.ensure_store_dir()
        try:
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
        except OSError:
            pass
        return self.reset()


def normalize_shell_config(data: Dict[str, Any]) -> Dict[str, Any]:
    defaults = default_shell_config()
    theme = data.get("theme")
    if not isinstance(theme, str) or theme not in THEMES:
        theme = defaults["theme"]

    raw_aliases = data.get("aliases")
    aliases: Dict[str, str] = {}
    if isinstance(raw_aliases, dict):
        for name, value in raw_aliases.items():
            name_text = str(name).strip()
            value_text = str(value).strip()
            if name_text and value_text and not any(char.isspace() for char in name_text):
                aliases[name_text] = value_text
    else:
        aliases = dict(defaults["aliases"])

    active_profile = data.get("active_profile")
    if active_profile is not None:
        active_profile = str(active_profile)

    default_ai_tool = data.get("default_ai_tool")
    if default_ai_tool not in {"codex", "claude"}:
        default_ai_tool = defaults["default_ai_tool"]

    return {
        "theme": theme,
        "aliases": aliases,
        "active_profile": active_profile,
        "default_ai_tool": default_ai_tool,
    }


@dataclass
class ShellContext:
    history: List[str] = field(default_factory=list)
    aliases: Dict[str, str] = field(default_factory=default_aliases)
    theme: str = "green"
    running: bool = True
    readline_available: bool = False
    input_backend: str = "input"
    project_root: Path = field(default_factory=lambda: detect_project_root(Path.cwd()))
    session_store: AiSessionStore = field(init=False)
    task_store: AiTaskStore = field(init=False)
    policy_store: CommandPolicyStore = field(init=False)
    config_store: ShellConfigStore = field(init=False)
    active_profile: Optional[str] = None
    default_ai_tool: str = "codex"

    def __post_init__(self) -> None:
        self.project_root = self.project_root.resolve()
        self.session_store = AiSessionStore(self.project_root)
        self.task_store = AiTaskStore(self.project_root)
        self.policy_store = CommandPolicyStore(self.project_root)
        self.config_store = ShellConfigStore(self.project_root)
        self.load_config()

    def apply_config(self, config: Dict[str, Any]) -> None:
        normalized = normalize_shell_config(config)
        self.theme = normalized["theme"]
        self.aliases = dict(normalized["aliases"])
        self.active_profile = normalized["active_profile"]
        self.default_ai_tool = normalized["default_ai_tool"]

    def current_config(self) -> Dict[str, Any]:
        return {
            "theme": self.theme,
            "aliases": dict(self.aliases),
            "active_profile": self.active_profile,
            "default_ai_tool": self.default_ai_tool,
        }

    def load_config(self) -> None:
        self.apply_config(self.config_store.load())

    def save_config(self) -> None:
        self.config_store.save(self.current_config())

    def reset_config(self) -> None:
        self.apply_config(self.config_store.reset())


class ShellExit(Exception):
    """exit/quit 명령이 셸 루프를 빠져나가도록 알려주는 예외."""


def parse_args(raw_args: str) -> List[str]:
    """따옴표를 이해하는 간단한 인자 파서."""
    if not raw_args.strip():
        return []
    return shlex.split(raw_args, posix=(os.name != "nt"))


def parse_process_args(raw_args: str) -> List[str]:
    """subprocess.run(list)에 넘길 인자를 OS 규칙대로 분해한다."""
    if not raw_args.strip():
        return []

    if os.name != "nt":
        return shlex.split(raw_args)

    argc = ctypes.c_int()
    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = command_line_to_argv(raw_args, ctypes.byref(argc))
    if not argv:
        raise ValueError("Windows 명령줄을 해석할 수 없습니다.")

    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def split_command_line(line: str) -> tuple[str, str]:
    """입력 한 줄을 명령어 이름과 나머지 원문 인자로 나눈다."""
    stripped = line.strip()
    if not stripped:
        return "", ""

    parts = stripped.split(maxsplit=1)
    name = parts[0]
    raw_args = parts[1] if len(parts) > 1 else ""
    return name, raw_args


def normalize_input_line(line: str) -> str:
    """PowerShell 파이프 등에서 첫 입력 앞에 붙을 수 있는 UTF-8 BOM을 제거한다."""
    return line.strip().lstrip("\ufeff")


def strip_outer_quotes(text: str) -> str:
    """경로 입력처럼 원문 인자를 그대로 쓰고 싶을 때 바깥 따옴표만 제거한다."""
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def compact_path(path: Optional[Path] = None) -> str:
    """홈 디렉터리 아래 경로는 ~로 줄여서 보여준다."""
    current = (path or Path.cwd()).resolve()
    home = Path.home().resolve()
    try:
        relative = current.relative_to(home)
    except ValueError:
        return str(current)

    if str(relative) == ".":
        return "~"
    return str(Path("~") / relative)


def make_prompt(ctx: ShellContext) -> str:
    """현재 경로와 시간을 포함한 두 줄 프롬프트를 만든다."""
    theme = THEMES.get(ctx.theme, THEMES["green"])
    now = _dt.datetime.now().strftime("%H:%M")
    label = color("[mysh]", theme["label"])
    path = color(compact_path(), theme["path"])
    clock = color(now, theme["time"])
    symbol = color("❯", theme["symbol"])
    return f"┌─{label} {path} {clock}\n└─{symbol} "


def print_error(message: str) -> None:
    """에러 메시지는 한곳에서 같은 형식으로 출력한다."""
    print(color(f"오류: {message}", Ansi.RED))


def print_warning(message: str) -> None:
    """경고 메시지는 한곳에서 같은 형식으로 출력한다."""
    print(color(f"경고: {message}", Ansi.YELLOW))


def refresh_project_context(ctx: ShellContext) -> None:
    """현재 cwd 기준 프로젝트 루트가 바뀌었으면 세션 저장소도 바꾼다."""
    project_root = detect_project_root(Path.cwd())
    if project_root != ctx.project_root:
        ctx.project_root = project_root
        ctx.session_store = AiSessionStore(project_root)
        ctx.task_store = AiTaskStore(project_root)
        ctx.policy_store = CommandPolicyStore(project_root)
        ctx.config_store = ShellConfigStore(project_root)
        ctx.load_config()


def expand_alias(ctx: ShellContext, line: str) -> str:
    """첫 단어가 별칭이면 실제 명령 문자열로 치환한다."""
    expanded = line
    seen = set()

    for _ in range(10):
        name, raw_args = split_command_line(expanded)
        if name not in ctx.aliases:
            return expanded
        if name in seen:
            raise ValueError(f"순환 별칭이 감지되었습니다: {name}")
        seen.add(name)
        replacement = ctx.aliases[name]
        expanded = replacement if not raw_args else f"{replacement} {raw_args}"

    raise ValueError("별칭 확장이 너무 깊습니다.")


@dataclass
class PolicyDecision:
    action: str
    reason: str = ""
    segment: str = ""
    match: str = ""


def split_command_segments(line: str, posix: Optional[bool] = None) -> List[str]:
    """정책 평가용으로 명령을 세그먼트로 나눈다.

    이 파서는 과속방지턱용이다. POSIX 입력은 shlex를 우선 쓰고, Windows/실패
    fallback은 따옴표만 고려해 ;, &&, ||, | 기준으로 단순 분리한다.
    """
    if posix is None:
        posix = os.name != "nt"

    if posix:
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            lexer.commenters = ""
            segments: List[str] = []
            current: List[str] = []
            for token in lexer:
                if token and all(char in ";&|" for char in token):
                    if current:
                        segments.append(" ".join(current).strip())
                        current = []
                    continue
                current.append(token)
            if current:
                segments.append(" ".join(current).strip())
            return [segment for segment in segments if segment]
        except ValueError:
            pass

    segments = []
    current_chars: List[str] = []
    quote: Optional[str] = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            current_chars.append(char)
            if char == quote:
                quote = None
            index += 1
            continue

        if char in {"'", '"'}:
            quote = char
            current_chars.append(char)
            index += 1
            continue

        two_chars = line[index : index + 2]
        if two_chars in {"&&", "||"}:
            segment = "".join(current_chars).strip()
            if segment:
                segments.append(segment)
            current_chars = []
            index += 2
            continue

        if char in {";", "|"}:
            segment = "".join(current_chars).strip()
            if segment:
                segments.append(segment)
            current_chars = []
            index += 1
            continue

        current_chars.append(char)
        index += 1

    segment = "".join(current_chars).strip()
    if segment:
        segments.append(segment)
    return segments


def match_policy_rule(segment: str, rules: List[Dict[str, str]]) -> PolicyDecision:
    """세그먼트에 매칭되는 정책 중 가장 강한 결정을 적용한다."""
    decisions: List[PolicyDecision] = []
    for rule in rules:
        pattern = rule.get("match", "")
        action = rule.get("action", "allow")
        try:
            matched = re.search(pattern, segment, re.IGNORECASE)
        except re.error:
            return PolicyDecision(
                action="deny",
                reason=f"invalid policy regex: {pattern}",
                segment=segment,
                match=pattern,
            )
        if matched:
            decisions.append(
                PolicyDecision(
                    action=action,
                    reason=rule.get("reason", pattern),
                    segment=segment,
                    match=pattern,
                )
            )

    for strongest in ("deny", "ask", "allow"):
        for decision in decisions:
            if decision.action == strongest:
                return decision
    return PolicyDecision(action="allow", segment=segment)


WRITE_COMMAND_NAMES = {
    "add-content",
    "copy",
    "copy-item",
    "cp",
    "del",
    "mkdir",
    "move",
    "move-item",
    "mv",
    "new-item",
    "out-file",
    "remove-item",
    "rm",
    "set-content",
    "tee",
    "tee-object",
    "touch",
}
DESTINATION_ONLY_WRITE_COMMANDS = {"copy", "copy-item", "cp"}
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
POSIX_ABSOLUTE_PATH_PATTERN = re.compile(r"^/(?!/)")


def policy_segment_tokens(segment: str) -> List[str]:
    try:
        return shlex.split(segment, posix=(os.name != "nt"))
    except ValueError:
        return segment.split()


def normalize_command_name(token: str) -> str:
    name = Path(token.strip("'\"")).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def clean_policy_path_token(token: str) -> str:
    return token.strip().strip("'\"")


def is_absolute_policy_path(token: str) -> bool:
    cleaned = clean_policy_path_token(token)
    if "://" in cleaned:
        return False
    return bool(WINDOWS_ABSOLUTE_PATH_PATTERN.search(cleaned) or POSIX_ABSOLUTE_PATH_PATTERN.search(cleaned))


def policy_path_outside_root(token: str, root: Path) -> bool:
    cleaned = clean_policy_path_token(token)
    if not is_absolute_policy_path(cleaned) or cleaned.startswith("/dev/"):
        return False
    try:
        resolved = Path(os.path.expandvars(os.path.expanduser(cleaned))).resolve()
    except (OSError, RuntimeError):
        return False
    return not path_is_under_root(resolved, root)


def redirection_target_tokens(segment: str) -> List[str]:
    targets: List[str] = []
    quote: Optional[str] = None
    index = 0
    while index < len(segment):
        char = segment[index]
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == ">":
            index += 2 if index + 1 < len(segment) and segment[index + 1] == ">" else 1
            while index < len(segment) and segment[index].isspace():
                index += 1
            if index >= len(segment):
                return targets
            if segment[index] in {"'", '"'}:
                quote = segment[index]
                index += 1
                start = index
                while index < len(segment) and segment[index] != quote:
                    index += 1
                targets.append(segment[start:index])
                if index < len(segment) and segment[index] == quote:
                    index += 1
                quote = None
                continue
            start = index
            while index < len(segment) and not segment[index].isspace():
                index += 1
            targets.append(segment[start:index])
            continue
        index += 1
    return targets


def option_values(tokens: List[str], options: set[str]) -> List[str]:
    values: List[str] = []
    index = 1
    while index < len(tokens):
        lowered = tokens[index].lower()
        for option in options:
            if lowered == option and index + 1 < len(tokens):
                values.append(tokens[index + 1])
                index += 2
                break
            if lowered.startswith(f"{option}="):
                values.append(tokens[index].split("=", 1)[1])
                index += 1
                break
            if lowered.startswith(f"{option}:"):
                values.append(tokens[index].split(":", 1)[1])
                index += 1
                break
        else:
            index += 1
    return values


def non_option_operands(tokens: List[str]) -> List[str]:
    operands: List[str] = []
    skip_next = False
    value_options = {
        "-credential",
        "-destination",
        "-encoding",
        "-filter",
        "-filepath",
        "-include",
        "-inputobject",
        "-itemtype",
        "-literalpath",
        "-name",
        "-path",
        "-stream",
        "-type",
        "-value",
    }
    for token in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        lowered = token.lower()
        if lowered in value_options:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        operands.append(token)
    return operands


def write_target_tokens(segment: str) -> List[str]:
    targets = redirection_target_tokens(segment)

    tokens = policy_segment_tokens(segment)
    if not tokens:
        return targets

    command_name = normalize_command_name(tokens[0])
    if command_name not in WRITE_COMMAND_NAMES:
        return targets

    if command_name in {"add-content", "set-content"}:
        command_targets = option_values(tokens, {"-path", "-literalpath"})
        if command_targets:
            return [*targets, *command_targets]
        operands = non_option_operands(tokens)
        return [*targets, *operands[:1]]

    if command_name in {"out-file", "tee", "tee-object"}:
        command_targets = option_values(tokens, {"-filepath", "-literalpath"})
        if command_targets:
            return [*targets, *command_targets]
        operands = non_option_operands(tokens)
        if command_name in {"tee", "tee-object"}:
            return [*targets, *operands]
        return [*targets, *operands[:1]]

    if command_name == "new-item":
        command_targets = option_values(tokens, {"-path", "-literalpath"})
        if command_targets:
            return [*targets, *command_targets]
        operands = non_option_operands(tokens)
        return [*targets, *operands[:1]]

    if command_name == "remove-item":
        command_targets = option_values(tokens, {"-path", "-literalpath"})
        if command_targets:
            return [*targets, *command_targets]

    if command_name in {"copy", "copy-item", "cp"}:
        command_targets = option_values(tokens, {"-destination"})
        if command_targets:
            return [*targets, *command_targets]

    if command_name in {"move", "move-item", "mv"}:
        command_targets = option_values(tokens, {"-path", "-literalpath", "-destination"})
        if command_targets:
            return [*targets, *command_targets]

    operands = non_option_operands(tokens)
    if not operands:
        return targets
    if command_name in DESTINATION_ONLY_WRITE_COMMANDS:
        return [*targets, operands[-1]]
    return [*targets, *operands]


def detect_outside_workspace_write(segment: str, root: Path) -> Optional[str]:
    """프로젝트 루트 밖 절대경로 쓰기 시도를 느슨하게 감지한다."""
    root = root.resolve()
    for candidate in write_target_tokens(segment):
        if policy_path_outside_root(candidate, root):
            return "workspace outside absolute path write"
    return None


def evaluate_command_policy(
    line: str,
    rules: Optional[List[Dict[str, str]]] = None,
    project_root: Optional[Path] = None,
) -> PolicyDecision:
    """외부 명령 전체에 적용될 최종 정책 결정을 계산한다."""
    normalized_rules = normalize_policy_rules(rules) if rules is not None else default_policy_rules()
    root = (project_root or detect_project_root(Path.cwd())).resolve()
    decisions: List[PolicyDecision] = []
    segments = split_command_segments(line)

    # 파이프를 포함한 정책은 세그먼트 분리 후 놓칠 수 있어 전체 줄도 함께 본다.
    for rule in normalized_rules:
        pattern = rule.get("match", "")
        if "|" not in pattern:
            continue
        try:
            matched = re.search(pattern, line, re.IGNORECASE)
        except re.error:
            decisions.append(
                PolicyDecision(
                    action="deny",
                    reason=f"invalid policy regex: {pattern}",
                    segment=line.strip(),
                    match=pattern,
                )
            )
            continue
        if matched:
            decisions.append(
                PolicyDecision(
                    action=rule.get("action", "allow"),
                    reason=rule.get("reason", pattern),
                    segment=line.strip(),
                    match=pattern,
                )
            )

    for segment in segments:
        decision = match_policy_rule(segment, normalized_rules)
        if decision.action != "allow":
            decisions.append(decision)
            continue
        outside_reason = detect_outside_workspace_write(segment, root)
        if outside_reason:
            decisions.append(PolicyDecision(action="ask", reason=outside_reason, segment=segment))

    for action in ("deny", "ask"):
        for decision in decisions:
            if decision.action == action:
                return decision
    return PolicyDecision(action="allow")


def detect_dangerous_command(line: str) -> Optional[str]:
    """호환용: 기본 정책에서 ask/deny가 필요한 명령 사유를 반환한다."""
    decision = evaluate_command_policy(line, default_policy_rules())
    if decision.action in {"ask", "deny"}:
        return decision.reason
    return None


def is_interactive_stdin() -> bool:
    """파이프/리다이렉션 입력에서는 확인 프롬프트를 받을 수 없다."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def confirm_policy_command(line: str, decision: PolicyDecision) -> bool:
    """정책상 확인이 필요한 명령 실행 전 y/N 확인을 받는다. 기본값은 N이다."""
    print_warning(f"정책상 확인이 필요한 외부 명령입니다: {decision.reason}")
    if decision.segment:
        print(f"segment: {decision.segment}")
    print(line)
    try:
        answer = input("계속 실행할까요? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def should_run_external_command(line: str, bypass_safety: bool = False) -> bool:
    """OS 셸로 넘기기 전 정책 기반 과속방지턱을 적용한다."""
    project_root = detect_project_root(Path.cwd())
    policy_store = CommandPolicyStore(project_root)
    decision = evaluate_command_policy(line, policy_store.load(), project_root)
    if decision.action == "allow":
        return True

    if decision.action == "deny":
        print_warning(f"정책상 차단된 외부 명령입니다: {decision.reason}")
        if decision.segment:
            print(f"segment: {decision.segment}")
        print("실행하려면 .mysh/policy.json 정책을 수정하세요.")
        return False

    if bypass_safety:
        return True

    if not is_interactive_stdin():
        print_warning(f"비대화형 입력에서는 확인할 수 없어 정책 확인 명령을 차단했습니다: {decision.reason}")
        return False

    if confirm_policy_command(line, decision):
        return True

    print_warning("외부 명령을 실행하지 않았습니다.")
    return False


def run_external_command(line: str, bypass_safety: bool = False) -> None:
    """등록되지 않은 명령은 실제 OS 셸에 넘겨 실행을 시도한다."""
    if not line.strip():
        print_error("실행할 외부 명령을 입력하세요.")
        return
    if not should_run_external_command(line, bypass_safety=bypass_safety):
        return

    try:
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if shell:
                result = subprocess.run(
                    [shell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", line]
                )
            else:
                result = subprocess.run(line, shell=True)
        else:
            result = subprocess.run(line, shell=True)
    except FileNotFoundError:
        print_error(f"명령을 찾을 수 없습니다: {line}")
        return
    except OSError as exc:
        print_error(f"명령 실행 중 문제가 발생했습니다: {exc}")
        return

    if result.returncode != 0:
        print_error(f"외부 명령이 종료 코드 {result.returncode}로 끝났습니다.")


def execute_line(ctx: ShellContext, line: str) -> None:
    """입력 한 줄을 내장 명령 또는 외부 명령으로 실행한다."""
    if line.startswith("!"):
        run_external_command(line[1:].lstrip(), bypass_safety=True)
        return

    try:
        line = expand_alias(ctx, line)
    except ValueError as exc:
        print_error(str(exc))
        return

    name, raw_args = split_command_line(line)
    if not name:
        return

    command_info = COMMANDS.get(name)
    if command_info is None:
        run_external_command(line)
        return

    try:
        args = parse_args(raw_args)
    except ValueError as exc:
        print_error(f"인자를 해석할 수 없습니다: {exc}")
        return

    command_info.handler(ctx, args, raw_args)


# -----------------------------------------------------------------------------
# 입력 지원: prompt_toolkit 우선, 없으면 readline/input fallback
# -----------------------------------------------------------------------------


def command_completion_candidates(ctx: ShellContext) -> List[str]:
    """등록 명령어, 별칭, 자주 쓰는 ai 하위 명령을 자동완성 후보로 만든다."""
    return sorted(set(COMMANDS) | set(ctx.aliases) | set(AI_SUBCOMMAND_COMPLETIONS))


class MyshPromptCompleter(PromptCompleter if PromptCompleter is not None else object):  # type: ignore[misc, valid-type]
    """prompt_toolkit용 동적 자동완성기."""

    def __init__(self, ctx: ShellContext):
        self.ctx = ctx

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        _ = complete_event
        if PromptCompletion is None:
            return

        raw_prefix = document.text_before_cursor
        prefix = raw_prefix.lstrip()
        lowered_prefix = prefix.lower()
        for candidate in command_completion_candidates(self.ctx):
            if candidate.lower().startswith(lowered_prefix):
                yield PromptCompletion(candidate, start_position=-len(prefix))


def prompt_history_path(ctx: ShellContext) -> Optional[Path]:
    """prompt_toolkit 영속 히스토리 파일 경로를 준비한다."""
    try:
        ctx.session_store.ensure_store_dir()
    except OSError:
        return None
    return ctx.session_store.store_dir / "history.txt"


def prompt_key_bindings() -> Optional[Any]:
    """Enter는 실행, Esc+Enter는 줄바꿈으로 쓰는 prompt_toolkit 키 설정."""
    if PromptKeyBindings is None:
        return None

    bindings = PromptKeyBindings()

    @bindings.add("enter")
    def _(event: Any) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    return bindings


def setup_prompt_toolkit(ctx: ShellContext) -> Optional[Any]:
    """prompt_toolkit이 있으면 히스토리/자동완성/멀티라인 입력 세션을 만든다."""
    if not PROMPT_TOOLKIT or PromptToolkitSession is None:
        return None
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    history = None
    if PromptFileHistory is not None:
        history_file = prompt_history_path(ctx)
        if history_file is not None:
            history = PromptFileHistory(str(history_file))

    try:
        session = PromptToolkitSession(
            completer=MyshPromptCompleter(ctx),
            complete_while_typing=False,
            enable_history_search=True,
            history=history,
            key_bindings=prompt_key_bindings(),
            multiline=True,
            prompt_continuation="... ",
        )
    except Exception:
        ctx.input_backend = "input"
        return None

    ctx.input_backend = "prompt_toolkit"
    return session


def setup_readline(ctx: ShellContext) -> None:
    """readline이 있는 환경이면 히스토리 탐색과 명령어 자동완성을 켠다."""
    try:
        import readline  # type: ignore
    except ImportError:
        ctx.readline_available = False
        return

    ctx.readline_available = True
    ctx.input_backend = "readline"

    def completer(text: str, state: int) -> Optional[str]:
        line_buffer = readline.get_line_buffer().lstrip()
        if line_buffer.startswith("ai "):
            options = sorted({item[len("ai ") :] for item in AI_SUBCOMMAND_COMPLETIONS})
        else:
            options = sorted(set(COMMANDS) | set(ctx.aliases))
        matches = [item for item in options if item.startswith(text)]
        if state < len(matches):
            return matches[state] + " "
        return None

    readline.set_completer(completer)

    doc = getattr(readline, "__doc__", "") or ""
    if "libedit" in doc:
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def add_readline_history(line: str) -> None:
    """readline 히스토리에 입력을 추가한다. readline이 없으면 조용히 넘어간다."""
    try:
        import readline  # type: ignore
    except ImportError:
        return
    readline.add_history(line)


def read_shell_line(ctx: ShellContext, prompt_session: Optional[Any]) -> str:
    """설정된 입력 백엔드에서 한 명령을 읽는다."""
    prompt_text = make_prompt(ctx)
    if prompt_session is None:
        return input(prompt_text)

    prompt_value: Any = PromptANSI(prompt_text) if PromptANSI is not None else prompt_text
    if prompt_patch_stdout is None:
        return prompt_session.prompt(prompt_value)

    with prompt_patch_stdout():
        return prompt_session.prompt(prompt_value)


# -----------------------------------------------------------------------------
# AI 보조 명령 유틸리티
# -----------------------------------------------------------------------------


def run_tool(
    args: List[str],
    timeout: float = 5.0,
    cwd: Optional[Path] = None,
) -> Optional[subprocess.CompletedProcess[str]]:
    """짧은 외부 도구 호출을 안전하게 실행하고 실패는 None으로 돌려준다."""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    """stdout/stderr에서 사람이 읽을 첫 줄을 고른다."""
    output = (result.stdout or result.stderr).strip()
    if not output:
        return "(출력 없음)"
    return output.splitlines()[0].strip()


def git_result(
    args: List[str],
    timeout: float = 5.0,
    cwd: Optional[Path] = None,
) -> Optional[subprocess.CompletedProcess[str]]:
    """Git 명령을 실행한다. Git이 없거나 실패하면 호출자가 상태를 판단한다."""
    return run_tool(["git", *args], timeout=timeout, cwd=cwd)


def is_git_repository(root: Optional[Path] = None) -> bool:
    result = git_result(["rev-parse", "--is-inside-work-tree"], cwd=root)
    return bool(result and result.returncode == 0 and result.stdout.strip() == "true")


def current_git_branch(root: Optional[Path] = None) -> str:
    branch = git_result(["branch", "--show-current"], cwd=root)
    if branch and branch.returncode == 0 and branch.stdout.strip():
        return branch.stdout.strip()

    commit = git_result(["rev-parse", "--short", "HEAD"], cwd=root)
    if commit and commit.returncode == 0 and commit.stdout.strip():
        return f"detached HEAD ({commit.stdout.strip()})"

    return "(알 수 없음)"


def changed_git_files(root: Optional[Path] = None) -> List[str]:
    status = git_result(["status", "--porcelain"], cwd=root)
    if not status or status.returncode != 0:
        return []
    return [line for line in status.stdout.splitlines() if line.strip()]


def current_git_head(root: Optional[Path] = None) -> Optional[str]:
    result = git_result(["rev-parse", "HEAD"], cwd=root)
    if not result or result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def git_baseline_snapshot(root: Path) -> Optional[Dict[str, Any]]:
    """작업 시작 시점의 Git HEAD와 status를 저장한다. Git이 아니면 None."""
    if not is_git_repository(root):
        return None
    return {
        "head": current_git_head(root),
        "branch": current_git_branch(root),
        "status": changed_git_files(root),
    }


def porcelain_status_paths(line: str) -> List[str]:
    if len(line) < 4:
        return []
    path_text = line[3:].strip()
    if not path_text:
        return []
    if " -> " in path_text:
        return [part.strip() for part in path_text.split(" -> ") if part.strip()]
    return [path_text]


def name_status_paths(line: str) -> List[str]:
    parts = [part.strip() for part in line.split("\t") if part.strip()]
    return parts[1:] if len(parts) > 1 else []


def baseline_tracked_dirty_paths(baseline: Optional[Dict[str, Any]]) -> set[str]:
    if not isinstance(baseline, dict):
        return set()
    raw_status = baseline.get("status", [])
    if not isinstance(raw_status, list):
        return set()

    paths = set()
    for item in raw_status:
        line = str(item)
        if line.startswith(("??", "!!")):
            continue
        paths.update(porcelain_status_paths(line))
    return paths


def changed_git_files_since_baseline(root: Path, baseline: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """baseline 이후 변경 요약을 산출한다. Git이 아니면 None."""
    if not is_git_repository(root):
        return None

    current_status = changed_git_files(root)
    baseline_status = baseline.get("status", []) if isinstance(baseline, dict) else []
    baseline_status_set = set(str(line) for line in baseline_status if str(line).strip())
    baseline_dirty_paths = baseline_tracked_dirty_paths(baseline)
    status_delta = [
        line
        for line in current_status
        if line not in baseline_status_set and not baseline_dirty_paths.intersection(porcelain_status_paths(line))
    ]

    diff_lines: List[str] = []
    head = baseline.get("head") if isinstance(baseline, dict) else None
    if isinstance(head, str) and head:
        raw_diff_lines = git_stdout_lines(root, ["diff", "--name-status", head, "--"], timeout=10.0)
        diff_lines = [
            line
            for line in raw_diff_lines
            if not baseline_dirty_paths.intersection(name_status_paths(line))
        ]
    elif current_git_head(root):
        raw_diff_lines = git_stdout_lines(root, ["diff", "--name-status", GIT_EMPTY_TREE_SHA1, "HEAD", "--"], timeout=10.0)
        diff_lines = [
            line
            for line in raw_diff_lines
            if not baseline_dirty_paths.intersection(name_status_paths(line))
        ]

    combined: List[str] = []
    seen = set()
    for line in [*diff_lines, *status_delta]:
        if not line.strip() or line in seen:
            continue
        combined.append(line)
        seen.add(line)
    return combined


def recent_git_commits(limit: int = 3, root: Optional[Path] = None) -> List[str]:
    result = git_result(["log", "--oneline", f"-{limit}"], cwd=root)
    if not result or result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def status_text(status: str) -> str:
    if status == STATUS_OK:
        return color(status, Ansi.GREEN)
    if status == STATUS_WARN:
        return color(status, Ansi.YELLOW)
    if status == STATUS_NONE:
        return color(status, Ansi.DIM)
    return status


def rich_console() -> Optional[Any]:
    if not RICH or RichConsole is None:
        return None
    return RichConsole()


def rich_escape(text: Any) -> str:
    value = str(text)
    if rich_markup_escape is None:
        return value
    return rich_markup_escape(value)


def rich_status_text(status: str) -> str:
    escaped = rich_escape(status)
    if status == STATUS_OK:
        return f"[green]{escaped}[/green]"
    if status == STATUS_WARN:
        return f"[yellow]{escaped}[/yellow]"
    if status == STATUS_NONE:
        return f"[dim]{escaped}[/dim]"
    return escaped


def print_status_table(rows: List[tuple[str, str, str]]) -> None:
    console = rich_console()
    if console is not None and RichTable is not None:
        table = RichTable(show_header=True, header_style="bold")
        table.add_column("항목", no_wrap=True)
        table.add_column("상태", no_wrap=True)
        table.add_column("세부")
        for name, status, detail in rows:
            table.add_row(rich_escape(name), rich_status_text(status), rich_escape(detail))
        console.print(table)
        return

    name_width = max([len("항목"), *(len(name) for name, _, _ in rows)])
    status_width = max([len("상태"), *(len(status) for _, status, _ in rows)])
    print(f"{'항목':<{name_width}}  {'상태':<{status_width}}  세부")
    print(f"{'-' * name_width}  {'-' * status_width}  {'-' * 40}")
    for name, status, detail in rows:
        print(f"{name:<{name_width}}  {status_text(status):<{status_width + len(status_text(status)) - len(status)}}  {detail}")


def cli_status(executable: str, label: str) -> tuple[str, str, str]:
    path = shutil.which(executable)
    if not path:
        return label, STATUS_NONE, f"PATH에서 {executable}을 찾지 못했습니다."

    version = run_tool([path, "--version"])
    if not version:
        return label, STATUS_WARN, f"{path} 발견, 버전 확인 실패"
    if version.returncode != 0:
        return label, STATUS_WARN, f"{path} 발견, 버전 확인 실패: {first_output_line(version)}"

    return label, STATUS_OK, f"{first_output_line(version)} ({path})"


def git_doctor_status() -> tuple[str, str, str]:
    if shutil.which("git") is None:
        return "Git 저장소", STATUS_NONE, "git 실행 파일을 찾지 못했습니다."
    if not is_git_repository():
        return "Git 저장소", STATUS_NONE, "현재 폴더는 Git 저장소가 아닙니다."

    branch = current_git_branch()
    changed_count = len(changed_git_files())
    return "Git 저장소", STATUS_OK, f"branch={branch}, 변경 파일 {changed_count}개"


def find_readme(root: Path) -> Optional[Path]:
    try:
        entries = [entry for entry in root.iterdir() if entry.is_file()]
    except OSError:
        return None

    preferred = ["readme.md", "readme.txt", "readme"]
    by_name = {entry.name.lower(): entry for entry in entries}
    for name in preferred:
        if name in by_name:
            return by_name[name]

    readmes = sorted((entry for entry in entries if entry.name.lower().startswith("readme")), key=lambda p: p.name.lower())
    return readmes[0] if readmes else None


def read_text_preview(path: Path, max_lines: int = 40) -> List[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            lines = []
            for index, line in enumerate(file):
                if index >= max_lines:
                    lines.append(f"... ({max_lines}줄 이후 생략)")
                    break
                lines.append(line.rstrip("\n"))
            return lines
    except OSError as exc:
        return [f"(README를 읽을 수 없습니다: {exc})"]


def safe_is_dir(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def file_tree_lines(root: Path, max_depth: int = 2, max_items: int = 100) -> List[str]:
    lines = ["."]
    count = 0
    truncated = False

    def walk(path: Path, depth: int, prefix: str) -> None:
        nonlocal count, truncated
        if depth > max_depth or count >= max_items:
            return

        try:
            entries = [entry for entry in os.scandir(path) if entry.name not in TREE_EXCLUDED_NAMES]
        except OSError as exc:
            lines.append(f"{prefix}(목록을 읽을 수 없습니다: {exc})")
            return

        entries.sort(key=lambda entry: (not safe_is_dir(entry), entry.name.lower()))
        for entry in entries:
            if count >= max_items:
                truncated = True
                return

            is_dir = safe_is_dir(entry)
            count += 1
            suffix = "/" if is_dir else ""
            lines.append(f"{prefix}{entry.name}{suffix}")

            if is_dir and depth < max_depth:
                walk(Path(entry.path), depth + 1, prefix + "  ")

    walk(root, 1, "  ")
    if truncated:
        lines.append(f"  ... (최대 {max_items}개 항목까지만 표시)")
    return lines


def section_lines(title: str, body: List[str]) -> List[str]:
    """복사·파싱하기 쉬운 Markdown 스타일 섹션을 만든다."""
    lines = [f"## {title}"]
    lines.extend(body or ["(없음)"])
    lines.append("")
    return lines


def limit_context_lines(lines: List[str], max_lines: int) -> List[str]:
    """전체 context 출력 줄 수를 제한하고 마지막 줄에 생략 수를 남긴다."""
    if len(lines) <= max_lines:
        return lines
    if max_lines <= 1:
        return [f"(생략됨: {len(lines)}줄)"]

    kept = max_lines - 1
    omitted = len(lines) - kept
    return [*lines[:kept], f"(생략됨: {omitted}줄)"]


def git_stdout_lines(root: Path, args: List[str], timeout: float = 10.0) -> List[str]:
    result = git_result(args, timeout=timeout, cwd=root)
    if not result or result.returncode != 0:
        return []
    return result.stdout.splitlines()


def git_diff_lines(root: Path, args: List[str]) -> List[str]:
    lines = git_stdout_lines(root, args, timeout=10.0)
    return lines or ["(diff 없음)"]


def untracked_git_files(root: Path) -> List[str]:
    return git_stdout_lines(root, ["ls-files", "--others", "--exclude-standard"], timeout=10.0)


def path_is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def untracked_file_preview_lines(root: Path, max_files: int = 10, max_preview_lines: int = 20) -> List[str]:
    paths = untracked_git_files(root)
    if not paths:
        return []

    root = root.resolve()
    lines = ["# untracked files"]
    for index, relative_text in enumerate(paths):
        if index >= max_files:
            lines.append(f"... ({len(paths) - max_files}개 untracked 파일 생략)")
            break

        lines.append(f"?? {relative_text}")
        path = root / relative_text
        try:
            if path.is_symlink():
                continue
            resolved = path.resolve()
            if not path_is_under_root(resolved, root):
                continue
            if not resolved.is_file() or resolved.stat().st_size > 200_000:
                continue
        except OSError:
            continue

        suffix = resolved.suffix.lower()
        if suffix and suffix not in TEXT_PREVIEW_SUFFIXES:
            continue

        lines.append(f"--- {relative_text} (untracked preview, first {max_preview_lines} lines) ---")
        lines.extend(read_text_preview(resolved, max_lines=max_preview_lines))
    return lines


def review_diff_lines(root: Path) -> List[str]:
    """스테이징+작업 트리 diff를 한 덩어리로 보여준다."""
    combined = git_stdout_lines(root, ["diff", "HEAD", "--"], timeout=10.0)
    untracked = untracked_file_preview_lines(root)
    if combined:
        return [*combined, *([] if not untracked else ["", *untracked])]

    cached = git_stdout_lines(root, ["diff", "--cached", "--"], timeout=10.0)
    working = git_stdout_lines(root, ["diff", "--"], timeout=10.0)
    lines: List[str] = []
    if cached:
        lines.extend(["# staged", *cached])
    if working:
        if lines:
            lines.append("")
        lines.extend(["# working tree", *working])
    if untracked:
        if lines:
            lines.append("")
        lines.extend(untracked)
    return lines or ["(diff 없음)"]


def test_command_hint_lines() -> List[str]:
    return [f"- {command}" for command in AI_CONTEXT_TEST_HINTS]


def iter_text_preview_files(root: Path, max_files: int = 250) -> List[Path]:
    """작은 텍스트 파일만 제한적으로 스캔한다."""
    root = root.resolve()
    files: List[Path] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in TREE_EXCLUDED_NAMES)
        for filename in sorted(filenames):
            if len(files) >= max_files:
                return files
            path = Path(current) / filename
            try:
                if path.is_symlink():
                    continue
                resolved = path.resolve()
                if not path_is_under_root(resolved, root):
                    continue
                if resolved.stat().st_size > 200_000:
                    continue
            except OSError:
                continue
            suffix = resolved.suffix.lower()
            if suffix and suffix not in TEXT_PREVIEW_SUFFIXES:
                continue
            files.append(resolved)
    return files


def scan_text_markers(root: Path, markers: List[str], max_matches: int = 20) -> List[str]:
    matches: List[str] = []
    lowered_markers = [marker.lower() for marker in markers]
    for path in iter_text_preview_files(root):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as file:
                for line_number, line in enumerate(file, start=1):
                    lowered = line.lower()
                    if any(marker in lowered for marker in lowered_markers):
                        try:
                            relative = path.relative_to(root)
                        except ValueError:
                            relative = path
                        snippet = line.strip()
                        if len(snippet) > 140:
                            snippet = snippet[:137] + "..."
                        matches.append(f"{relative}:{line_number}: {snippet}")
                        if len(matches) >= max_matches:
                            return matches
        except OSError:
            continue
    return matches


def failure_trace_lines(root: Path) -> List[str]:
    return scan_text_markers(root, list(FAILURE_TRACE_KEYWORDS), max_matches=20) or ["(최근 에러/실패 흔적 없음)"]


def todo_scan_lines(root: Path) -> List[str]:
    return scan_text_markers(root, ["TODO", "FIXME"], max_matches=20) or ["(TODO/FIXME 없음)"]


def ai_session_summary_lines(session_store: Optional[AiSessionStore]) -> List[str]:
    if session_store is None:
        return ["(세션 저장소 없음)"]

    sessions = session_store.load()
    if not sessions:
        return ["(저장된 AI 세션 없음)"]

    lines = []
    for session in sorted(sessions, key=lambda item: item.updated_at, reverse=True)[:5]:
        exit_code = "-" if session.exit_code is None else str(session.exit_code)
        title = shorten(session.title, 40)
        lines.append(f"- {session.id} {session.tool} exit={exit_code} updated={session.updated_at} title={title}")
    return lines


def task_changed_file_summary_lines(task: AiTask, max_files: int = 8) -> List[str]:
    changed_files = task_changed_files_for_display(task)
    if changed_files is None:
        return ["changed_files: -"]
    if not changed_files:
        return ["changed_files: (없음)"]

    lines = ["changed_files:"]
    for path in changed_files[:max_files]:
        lines.append(f"  {path}")
    if len(changed_files) > max_files:
        lines.append(f"  ... ({len(changed_files) - max_files}개 더 있음)")
    return lines


def task_linked_session_summary_lines(task: AiTask, session_store: Optional[AiSessionStore]) -> List[str]:
    if not task.session_ids:
        return ["  (연결된 세션 없음)"]
    if session_store is None:
        return [f"  - {session_id} (세션 저장소 없음)" for session_id in task.session_ids[-5:]]

    sessions_by_id = {session.id: session for session in session_store.load()}
    lines = []
    for session_id in task.session_ids[-5:]:
        session = sessions_by_id.get(session_id)
        if session is None:
            lines.append(f"  - {session_id} (메타데이터 없음)")
            continue
        exit_code = "-" if session.exit_code is None else str(session.exit_code)
        title = shorten(session.title, 40)
        lines.append(f"  - {session.id} {session.tool} exit={exit_code} updated={session.updated_at} title={title}")
    return lines


def active_task_context_lines(
    task_store: Optional[AiTaskStore],
    session_store: Optional[AiSessionStore],
    mode: str,
) -> List[str]:
    if task_store is None:
        return []
    task = task_store.current()
    if task is None:
        return []

    body = [
        f"id: {task.id}",
        f"goal: {task.goal}",
        f"status: {task.status}",
    ]
    body.extend(task_changed_file_summary_lines(task))
    if mode == "ship":
        body.append(f"test_result: {task.test_result or '-'}")
    if mode == "handoff":
        body.append(f"next_action: {task.next_action or '-'}")
        body.append("linked_sessions:")
        body.extend(task_linked_session_summary_lines(task, session_store))
    return section_lines("현재 작업", body)


def insert_context_after_header(lines: List[str], inserted: List[str]) -> List[str]:
    if not inserted:
        return lines
    try:
        insert_at = lines.index("") + 1
    except ValueError:
        insert_at = 0
    return [*lines[:insert_at], *inserted, *lines[insert_at:]]


def readme_section_lines(root: Path, max_lines: int, title: str = "README") -> List[str]:
    readme = find_readme(root)
    if not readme:
        return []
    body = [f"{readme.name} (first {max_lines} lines)", *read_text_preview(readme, max_lines=max_lines)]
    return section_lines(title, body)


def default_git_summary_lines(root: Path) -> List[str]:
    body = [f"Branch: {current_git_branch(root)}"]

    commits = recent_git_commits(limit=3, root=root)
    body.append("Recent commits:")
    body.extend([f"  {commit}" for commit in commits] or ["  (none)"])

    changes = changed_git_files(root)
    body.append("Changed files:")
    body.extend([f"  {change}" for change in changes] or ["  (none)"])
    return section_lines("Git Summary", body)


def build_default_context(root: Path, session_store: Optional[AiSessionStore]) -> List[str]:
    _ = session_store
    lines = section_lines("AI Context", [f"CWD: {root}", "Mode: default"])
    lines.extend(readme_section_lines(root, max_lines=40))
    lines.extend(section_lines("File Tree", file_tree_lines(root, max_depth=2, max_items=100)))
    if is_git_repository(root):
        lines.extend(default_git_summary_lines(root))
    return lines


def build_debug_context(root: Path, session_store: Optional[AiSessionStore]) -> List[str]:
    _ = session_store
    lines = section_lines("AI Context", [f"CWD: {root}", "Mode: debug"])
    if is_git_repository(root):
        changes = changed_git_files(root)
        lines.extend(section_lines("Changed Files", changes or ["(변경 파일 없음)"]))
        lines.extend(section_lines("Git Diff (working tree)", git_diff_lines(root, ["diff", "--"])))
    lines.extend(section_lines("Recent Error/Failure Traces", failure_trace_lines(root)))
    lines.extend(section_lines("Test Command Hints", test_command_hint_lines()))
    return lines


def build_review_context(root: Path, session_store: Optional[AiSessionStore]) -> List[str]:
    _ = session_store
    lines = section_lines("AI Context", [f"CWD: {root}", "Mode: review"])
    if is_git_repository(root):
        lines.extend(section_lines("Git Diff (staged + working tree)", review_diff_lines(root)))
        commits = recent_git_commits(limit=5, root=root)
        lines.extend(section_lines("Recent Commits", commits or ["(커밋 없음)"]))
    lines.extend(
        section_lines(
            "Test Status/Commands",
            ["Status: not run by ai context", *test_command_hint_lines()],
        )
    )
    return lines


def build_handoff_context(root: Path, session_store: Optional[AiSessionStore]) -> List[str]:
    lines = section_lines("AI Context", [f"CWD: {root}", "Mode: handoff"])
    lines.extend(readme_section_lines(root, max_lines=25, title="README Summary"))
    lines.extend(section_lines("Directory Structure", file_tree_lines(root, max_depth=3, max_items=150)))
    lines.extend(section_lines("Recent AI Sessions", ai_session_summary_lines(session_store)))
    lines.extend(section_lines("TODO/FIXME Scan", todo_scan_lines(root)))
    return lines


def ship_committed_change_lines(root: Path) -> tuple[Optional[str], List[str]]:
    for base_ref in ("main", "origin/main"):
        comparison = f"{base_ref}...HEAD"
        result = git_result(["diff", "--name-status", comparison, "--"], timeout=10.0, cwd=root)
        if result and result.returncode == 0:
            return comparison, result.stdout.splitlines()
    return None, []


def ship_change_summary_lines(root: Path) -> List[str]:
    if not is_git_repository(root):
        return ["Git repository: no"]

    comparison, committed_changes = ship_committed_change_lines(root)
    lines = [f"Branch: {current_git_branch(root)}"]
    lines.append(f"Committed changes ({comparison or 'base unavailable'}):")
    lines.extend([f"  {change}" for change in committed_changes] or ["  (none)"])

    uncommitted_changes = changed_git_files(root)
    lines.append("Uncommitted files:")
    lines.extend([f"  {change}" for change in uncommitted_changes] or ["  (none)"])

    diff_stat = git_stdout_lines(root, ["diff", "--stat", comparison, "--"], timeout=10.0) if comparison else []
    if diff_stat:
        lines.append("Diff stat:")
        lines.extend([f"  {line}" for line in diff_stat])
    return lines


def build_ship_context(root: Path, session_store: Optional[AiSessionStore]) -> List[str]:
    _ = session_store
    lines = section_lines("AI Context", [f"CWD: {root}", "Mode: ship"])
    lines.extend(section_lines("Ship Changes", ship_change_summary_lines(root)))
    lines.extend(
        section_lines(
            "Test Status/Commands",
            ["Status: see current task test_result if present", *test_command_hint_lines()],
        )
    )
    if is_git_repository(root):
        lines.extend(section_lines("Uncommitted/Untracked Preview", review_diff_lines(root)))
    return lines


def build_ai_context(
    root: Path,
    mode: str = "default",
    max_lines: Optional[int] = None,
    session_store: Optional[AiSessionStore] = None,
    task_store: Optional[AiTaskStore] = None,
) -> str:
    """AI에 붙여넣기 좋은 plain-text context pack을 만든다."""
    normalized_mode = mode.lower()
    if normalized_mode not in AI_CONTEXT_MODES:
        available = ", ".join(AI_CONTEXT_MODES)
        raise ValueError(f"알 수 없는 context mode입니다: {mode}. 사용 가능: {available}")

    root = root.resolve()
    builders = {
        "default": build_default_context,
        "debug": build_debug_context,
        "review": build_review_context,
        "handoff": build_handoff_context,
        "ship": build_ship_context,
    }
    lines = builders[normalized_mode](root, session_store)
    lines = insert_context_after_header(lines, active_task_context_lines(task_store, session_store, normalized_mode))
    limit = max_lines if max_lines is not None else AI_CONTEXT_DEFAULT_MAX_LINES[normalized_mode]
    return "\n".join(limit_context_lines(lines, limit)).rstrip() + "\n"


def parse_ai_context_options(args: List[str]) -> tuple[str, Optional[int]]:
    mode = "default"
    max_lines: Optional[int] = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--mode":
            if index + 1 >= len(args):
                raise ValueError("--mode에는 값이 필요합니다.")
            mode = args[index + 1].lower()
            index += 2
            continue
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1].lower()
            index += 1
            continue
        if arg == "--max-lines":
            if index + 1 >= len(args):
                raise ValueError("--max-lines에는 숫자 값이 필요합니다.")
            value = args[index + 1]
            index += 2
        elif arg.startswith("--max-lines="):
            value = arg.split("=", 1)[1]
            index += 1
        else:
            raise ValueError(f"알 수 없는 ai context 옵션입니다: {arg}")

        try:
            max_lines = int(value)
        except ValueError as exc:
            raise ValueError("--max-lines에는 정수를 입력하세요.") from exc
        if max_lines < 1:
            raise ValueError("--max-lines에는 1 이상의 정수를 입력하세요.")

    if mode not in AI_CONTEXT_MODES:
        available = ", ".join(AI_CONTEXT_MODES)
        raise ValueError(f"알 수 없는 context mode입니다: {mode}. 사용 가능: {available}")
    return mode, max_lines


def print_ai_context(ctx: ShellContext, mode: str = "default", max_lines: Optional[int] = None) -> None:
    refresh_project_context(ctx)
    print(
        build_ai_context(
            Path.cwd(),
            mode=mode,
            max_lines=max_lines,
            session_store=ctx.session_store,
            task_store=ctx.task_store,
        ),
        end="",
    )


# -----------------------------------------------------------------------------
# AI 세션과 wrapper 실행
# -----------------------------------------------------------------------------


CODEX_CD_FLAGS = {"--cd", "-C"}
LONG_FLAGS_WITH_VALUE = {
    "--add-dir",
    "--approval-policy",
    "--ask-for-approval",
    "--cd",
    "--config",
    "--cwd",
    "--model",
    "--output-format",
    "--permission-mode",
    "--profile",
    "--sandbox",
}
CODEX_SHORT_FLAGS_WITH_VALUE = {"-C", "-a", "-c", "-i", "-m", "-p", "-s"}
CLAUDE_SHORT_FLAGS_WITH_VALUE = {"-d", "-m", "-n", "-r", "-w"}
AI_RERUN_EXCLUDED_FLAGS = {
    "--continue",
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust",
    "--dangerously-skip-permissions",
    "--resume",
}
AI_RERUN_EXCLUDED_SHORT_FLAGS_WITH_VALUE = {"-r"}
AI_RERUN_DANGEROUS_VALUES = {
    "--approval-policy": {"never"},
    "--ask-for-approval": {"never"},
    "--permission-mode": {"bypasspermissions", "bypass-permissions"},
    "--sandbox": {"danger-full-access"},
    "-s": {"danger-full-access"},
}
AI_RERUN_CONFIG_FLAGS = {"--config", "-c"}
AI_RERUNNABLE_SUBCOMMANDS = {
    "codex": {"exec"},
    "claude": set(),
}
AI_TOOLS_WITH_PROFILE_FLAG = {"codex"}


def has_codex_cd_arg(args: List[str]) -> bool:
    """사용자가 Codex 작업 디렉터리를 이미 지정했는지 확인한다."""
    for arg in args:
        if arg == "--":
            return False
        if arg in CODEX_CD_FLAGS or arg.startswith("--cd="):
            return True
    return False


def build_codex_command(user_args: List[str], cwd: Path) -> List[str]:
    """Codex 실행 명령을 만든다. --cd/-C가 없으면 현재 cwd를 넣는다."""
    command_args = ["codex"]
    if not has_codex_cd_arg(user_args):
        command_args.extend(["--cd", str(cwd)])
    command_args.extend(user_args)
    return command_args


def build_claude_command(user_args: List[str], cwd: Optional[Path] = None) -> List[str]:
    """Claude 실행 명령을 만든다. cwd는 호출자가 subprocess.run(cwd=...)로 보장한다."""
    _ = cwd
    return ["claude", *user_args]


def build_ai_command(tool: str, user_args: List[str], cwd: Path) -> List[str]:
    if tool == "codex":
        return build_codex_command(user_args, cwd)
    if tool == "claude":
        return build_claude_command(user_args, cwd)
    raise ValueError(f"지원하지 않는 AI 도구입니다: {tool}")


def resolve_executable_for_subprocess(executable: str) -> str:
    """Windows에서 shell=False로 실행 가능한 shim을 우선 선택한다."""
    if os.name != "nt":
        return executable

    runnable_extensions = [".exe", ".cmd", ".bat", ".com"]
    executable_path = Path(executable)
    has_directory = executable_path.parent != Path(".")

    if has_directory:
        if executable_path.suffix.lower() in {"", ".ps1"}:
            base = executable_path.with_suffix("") if executable_path.suffix else executable_path
            for extension in runnable_extensions:
                candidate = base.with_suffix(extension)
                if candidate.exists():
                    return str(candidate)
        return executable

    for path_entry in os.environ.get("PATH", "").split(os.pathsep):
        if not path_entry:
            continue
        directory = Path(path_entry)
        for extension in runnable_extensions:
            candidate = directory / f"{executable}{extension}"
            if candidate.exists():
                return str(candidate)

    found = shutil.which(executable)
    if not found:
        return executable

    found_path = Path(found)
    if found_path.suffix.lower() in {"", ".ps1"}:
        base = found_path.with_suffix("") if found_path.suffix else found_path
        for extension in runnable_extensions:
            candidate = base.with_suffix(extension)
            if candidate.exists():
                return str(candidate)
    return found


def extract_long_option_value(args: List[str], name: str) -> Optional[str]:
    """--name value 또는 --name=value 형태에서 값을 찾는다."""
    for index, arg in enumerate(args):
        if arg == "--":
            return None
        if arg == name and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return None


def with_default_ai_profile(tool: str, args: List[str], profile: Optional[str]) -> List[str]:
    """활성 profile이 있으면 실제 도구 인자에도 기본값으로 주입한다."""
    if tool not in AI_TOOLS_WITH_PROFILE_FLAG:
        return list(args)
    if not profile or extract_long_option_value(args, "--profile") is not None:
        return list(args)
    return ["--profile", profile, *args]


def short_flags_with_value(tool: str) -> set[str]:
    if tool == "codex":
        return CODEX_SHORT_FLAGS_WITH_VALUE
    if tool == "claude":
        return CLAUDE_SHORT_FLAGS_WITH_VALUE
    return set()


def normalized_option_value(value: str) -> str:
    return value.strip().strip("\"'").lower()


def is_dangerous_rerun_option(name: str, value: str) -> bool:
    normalized = normalized_option_value(value)
    dangerous_values = AI_RERUN_DANGEROUS_VALUES.get(name)
    if dangerous_values and normalized in dangerous_values:
        return True

    if name in AI_RERUN_CONFIG_FLAGS:
        compact = normalized.replace(" ", "").replace("_", "-")
        return any(
            pattern in compact
            for pattern in (
                "approval-policy=never",
                "ask-for-approval=never",
                "sandbox-mode=danger-full-access",
                "sandbox=danger-full-access",
                "sandbox-permissions=danger-full-access",
                "permission-mode=bypasspermissions",
                "permission-mode=bypass-permissions",
            )
        )

    return False


def is_rerunnable_ai_subcommand(tool: str, arg: str) -> bool:
    return arg in AI_RERUNNABLE_SUBCOMMANDS.get(tool, set())


def extract_rerunnable_ai_args(tool: str, args: List[str]) -> List[str]:
    """프롬프트 본문 없이 재실행 가능한 옵션/플래그만 보존한다."""
    rerunnable: List[str] = []
    value_short_flags = short_flags_with_value(tool)
    subcommand_seen = False
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--":
            break

        if arg.startswith("--") and arg != "--":
            name, separator, _value = arg.partition("=")
            if name in AI_RERUN_EXCLUDED_FLAGS:
                if not separator and index + 1 < len(args) and not args[index + 1].startswith("-"):
                    index += 2
                    continue
                index += 1
                continue
            if separator:
                if is_dangerous_rerun_option(name, _value):
                    index += 1
                    continue
                rerunnable.append(arg)
                index += 1
                continue
            if name in LONG_FLAGS_WITH_VALUE and index + 1 < len(args):
                if is_dangerous_rerun_option(name, args[index + 1]):
                    index += 2
                    continue
                rerunnable.extend([arg, args[index + 1]])
                index += 2
                continue
            rerunnable.append(arg)
            index += 1
            continue

        if arg.startswith("-") and arg != "-":
            if arg in AI_RERUN_EXCLUDED_SHORT_FLAGS_WITH_VALUE:
                index += 2 if index + 1 < len(args) else 1
                continue
            if arg in value_short_flags and index + 1 < len(args):
                if is_dangerous_rerun_option(arg, args[index + 1]):
                    index += 2
                    continue
                rerunnable.extend([arg, args[index + 1]])
                index += 2
                continue
            rerunnable.append(arg)
            index += 1
            continue

        if not subcommand_seen and is_rerunnable_ai_subcommand(tool, arg):
            rerunnable.append(arg)
            subcommand_seen = True
            index += 1
            continue

        break

    return rerunnable


def summarize_ai_command(tool: str, args: List[str]) -> str:
    """프롬프트 본문을 제외한 안전한 명령 요약을 만든다."""
    parts = [tool]
    prompt_tokens: List[str] = []
    value_short_flags = short_flags_with_value(tool)
    subcommand_seen = False
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--":
            prompt_tokens.extend(args[index + 1 :])
            break

        if arg.startswith("--") and arg != "--":
            name, separator, _value = arg.partition("=")
            if separator:
                parts.append(f"{name}=<value>")
                index += 1
                continue
            if name in LONG_FLAGS_WITH_VALUE and index + 1 < len(args):
                parts.append(f"{name} <value>")
                index += 2
                continue
            parts.append(name)
            index += 1
            continue

        if arg.startswith("-") and arg != "-":
            if arg in value_short_flags and index + 1 < len(args):
                parts.append(f"{arg} <value>")
                index += 2
                continue
            parts.append(arg)
            index += 1
            continue

        if not prompt_tokens and not subcommand_seen and is_rerunnable_ai_subcommand(tool, arg):
            parts.append(arg)
            subcommand_seen = True
            index += 1
            continue

        prompt_tokens.append(arg)
        index += 1

    prompt_text = " ".join(prompt_tokens)
    prompt_note = f"prompt={'yes' if prompt_tokens else 'no'}, chars={len(prompt_text)}, args={len(prompt_tokens)}"
    return f"{' '.join(parts)} [{prompt_note}]"


def default_session_title(tool: str) -> str:
    return f"{tool} session"


def create_ai_session(
    tool: str,
    cwd: Path,
    command_args: List[str],
    title: Optional[str],
    profile: Optional[str],
    user_args: Optional[List[str]] = None,
) -> AiSession:
    timestamp = now_iso()
    return AiSession(
        id=uuid.uuid4().hex[:12],
        title=title or default_session_title(tool),
        tool=tool,
        cwd=str(cwd),
        command=summarize_ai_command(tool, command_args[1:]),
        profile=profile,
        created_at=timestamp,
        updated_at=timestamp,
        exit_code=None,
        args=extract_rerunnable_ai_args(tool, user_args if user_args is not None else command_args[1:]),
    )


def parse_ai_start_options(args: List[str]) -> tuple[Optional[str], Optional[str], List[str]]:
    """ai start 전용 옵션을 떼고 실제 도구에 넘길 인자를 반환한다."""
    title: Optional[str] = None
    profile: Optional[str] = None
    passthrough: List[str] = []
    index = 0
    option_mode = True

    while index < len(args):
        arg = args[index]
        if option_mode and arg == "--":
            passthrough.extend(args[index + 1 :])
            break
        if option_mode and arg == "--title":
            if index + 1 >= len(args):
                raise ValueError("--title에는 값이 필요합니다.")
            title = args[index + 1]
            index += 2
            continue
        if option_mode and arg.startswith("--title="):
            title = arg.split("=", 1)[1]
            index += 1
            continue
        if option_mode and arg == "--profile":
            if index + 1 >= len(args):
                raise ValueError("--profile에는 값이 필요합니다.")
            profile = args[index + 1]
            index += 2
            continue
        if option_mode and arg.startswith("--profile="):
            profile = arg.split("=", 1)[1]
            index += 1
            continue

        option_mode = False
        passthrough.append(arg)
        index += 1

    return title, profile, passthrough


def run_ai_tool_session(
    ctx: ShellContext,
    tool: str,
    user_args: List[str],
    title: Optional[str] = None,
    profile: Optional[str] = None,
    cwd_override: Optional[Path] = None,
) -> int:
    """세션을 기록하고 TTY를 상속한 채 실제 Codex/Claude CLI를 실행한다."""
    refresh_project_context(ctx)
    cwd = (cwd_override or Path.cwd()).resolve()
    explicit_profile = profile or extract_long_option_value(user_args, "--profile")
    session_profile = explicit_profile or ctx.active_profile
    if explicit_profile:
        ctx.active_profile = explicit_profile
        ctx.save_config()

    effective_user_args = with_default_ai_profile(tool, user_args, session_profile)
    command_args = build_ai_command(tool, effective_user_args, cwd)
    session = create_ai_session(tool, cwd, command_args, title, session_profile, user_args=effective_user_args)
    ctx.session_store.add(session)
    ctx.task_store.add_session_to_current(session.id)
    process_args = [resolve_executable_for_subprocess(command_args[0]), *command_args[1:]]

    exit_code: Optional[int] = None
    error_already_reported = False
    try:
        result = subprocess.run(process_args, cwd=str(cwd))
        exit_code = result.returncode
    except FileNotFoundError:
        exit_code = 127
        error_already_reported = True
        print_error(f"{tool} 실행 파일을 PATH에서 찾지 못했습니다.")
    except OSError as exc:
        exit_code = 1
        error_already_reported = True
        print_error(f"{tool} 실행 중 문제가 발생했습니다: {exc}")
    except KeyboardInterrupt:
        exit_code = 130
        raise
    finally:
        if exit_code is not None:
            session.exit_code = exit_code
            session.updated_at = now_iso()
            ctx.session_store.update(session)

    if exit_code and not error_already_reported:
        print_error(f"{tool}가 종료 코드 {exit_code}로 끝났습니다.")
    return exit_code or 0


def shorten(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3] + "..."


def format_text_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return lines


def print_ai_sessions(sessions: List[AiSession]) -> None:
    if not sessions:
        print("(저장된 AI 세션 없음)")
        return

    console = rich_console()
    if console is not None and RichTable is not None:
        table = RichTable(title="AI Sessions", show_header=True, header_style="bold")
        table.add_column("id", no_wrap=True)
        table.add_column("tool", no_wrap=True)
        table.add_column("title")
        table.add_column("cwd")
        table.add_column("updated_at", no_wrap=True)
        table.add_column("exit", no_wrap=True)
        for session in sorted(sessions, key=lambda item: item.updated_at, reverse=True):
            table.add_row(
                rich_escape(session.id),
                rich_escape(session.tool),
                rich_escape(shorten(session.title, 28)),
                rich_escape(shorten(session.cwd, 36)),
                rich_escape(session.updated_at),
                rich_escape("-" if session.exit_code is None else session.exit_code),
            )
        console.print(table)
        return

    rows = []
    for session in sorted(sessions, key=lambda item: item.updated_at, reverse=True):
        rows.append(
            [
                session.id,
                session.tool,
                shorten(session.title, 28),
                shorten(session.cwd, 36),
                session.updated_at,
                "-" if session.exit_code is None else str(session.exit_code),
            ]
        )

    for line in format_text_table(["id", "tool", "title", "cwd", "updated_at", "exit"], rows):
        print(line)


def create_ai_task(cwd: Path, goal: str) -> AiTask:
    timestamp = now_iso()
    return AiTask(
        id=uuid.uuid4().hex[:12],
        goal=goal,
        cwd=str(cwd.resolve()),
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
        session_ids=[],
        git_baseline=git_baseline_snapshot(cwd),
        changed_files=None,
    )


def task_changed_files_for_display(task: AiTask) -> Optional[List[str]]:
    if task.status == "done":
        return task.changed_files
    return changed_git_files_since_baseline(Path(task.cwd), task.git_baseline)


def print_ai_tasks(tasks: List[AiTask], current_task_id: Optional[str]) -> None:
    if not tasks:
        print("(저장된 작업 없음)")
        return

    console = rich_console()
    if console is not None and RichTable is not None:
        table = RichTable(title="AI Tasks", show_header=True, header_style="bold")
        table.add_column("id", no_wrap=True)
        table.add_column("status", no_wrap=True)
        table.add_column("sessions", justify="right")
        table.add_column("updated_at", no_wrap=True)
        table.add_column("goal")
        for task in sorted(tasks, key=lambda item: item.updated_at, reverse=True):
            marker = "*" if task.id == current_task_id else ""
            table.add_row(
                rich_escape(f"{marker}{task.id}"),
                rich_escape(task.status),
                rich_escape(len(task.session_ids)),
                rich_escape(task.updated_at),
                rich_escape(shorten(task.goal, 60)),
            )
        console.print(table)
        return

    rows = []
    for task in sorted(tasks, key=lambda item: item.updated_at, reverse=True):
        rows.append(
            [
                f"{'*' if task.id == current_task_id else ''}{task.id}",
                task.status,
                str(len(task.session_ids)),
                task.updated_at,
                shorten(task.goal, 60),
            ]
        )

    for line in format_text_table(["id", "status", "sessions", "updated_at", "goal"], rows):
        print(line)


def print_ai_task_detail(task: AiTask) -> None:
    changed_files = task_changed_files_for_display(task)
    baseline = task.git_baseline or {}
    print(f"id: {task.id}")
    print(f"goal: {task.goal}")
    print(f"cwd: {task.cwd}")
    print(f"status: {task.status}")
    print(f"created_at: {task.created_at}")
    print(f"updated_at: {task.updated_at}")
    print(f"sessions: {', '.join(task.session_ids) if task.session_ids else '-'}")
    if task.git_baseline is not None:
        print(f"git_baseline.head: {baseline.get('head') or '-'}")
        print(f"git_baseline.branch: {baseline.get('branch') or '-'}")
        baseline_status = baseline.get("status", [])
        print("git_baseline.status:")
        for line in baseline_status or ["(clean)"]:
            print(f"  {line}")
    else:
        print("git_baseline: -")
    print("changed_files:")
    if changed_files is None:
        print("  -")
    else:
        for line in changed_files or ["(없음)"]:
            print(f"  {line}")
    print(f"test_result: {task.test_result or '-'}")
    print(f"next_action: {task.next_action or '-'}")


def print_ai_policy(ctx: ShellContext) -> None:
    refresh_project_context(ctx)
    rules = ctx.policy_store.load()
    source = str(ctx.policy_store.path) if ctx.policy_store.path.exists() else "built-in default"
    print("AI Policy")
    print(f"source: {source}")
    for index, rule in enumerate(rules, start=1):
        print(f"{index}. {rule['action'].upper()} {rule['match']}")
        print(f"   reason: {rule['reason']}")


def handle_ai_policy_command(ctx: ShellContext, args: List[str]) -> None:
    refresh_project_context(ctx)
    usage = "사용법: ai policy | ai policy init"
    if not args:
        print_ai_policy(ctx)
        return

    action = args[0].lower()
    if action == "init":
        if len(args) > 1:
            print_error(f"알 수 없는 ai policy init 옵션입니다: {' '.join(args[1:])}")
            print(usage)
            return
        if ctx.policy_store.path.exists():
            if not is_interactive_stdin():
                print_warning("비대화형 입력에서는 기존 policy.json 덮어쓰기를 확인할 수 없어 중단했습니다.")
                return
            try:
                answer = input(f"{ctx.policy_store.path}를 기본 정책으로 덮어쓸까요? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in {"y", "yes"}:
                print("policy init을 취소했습니다.")
                return
        ctx.policy_store.init_default()
        print(f"기본 정책을 기록했습니다: {ctx.policy_store.path}")
        return

    print_error(f"알 수 없는 ai policy 명령입니다: {action}")
    print(usage)


def parse_task_done_options(args: List[str]) -> tuple[str, Optional[str]]:
    if not args:
        raise ValueError("종료할 task id를 입력하세요.")
    task_id = args[0]
    next_action: Optional[str] = None
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--next":
            if index + 1 >= len(args):
                raise ValueError("--next에는 값이 필요합니다.")
            next_action = args[index + 1]
            index += 2
            continue
        if arg.startswith("--next="):
            next_action = arg.split("=", 1)[1]
            index += 1
            continue
        raise ValueError(f"알 수 없는 ai task done 옵션입니다: {arg}")
    return task_id, next_action


def handle_ai_task_command(ctx: ShellContext, args: List[str]) -> None:
    refresh_project_context(ctx)
    usage = (
        "사용법: ai task new <goal> | ai task list | ai task show <id> | "
        "ai task done <id> [--next N] | ai task current | ai task use <id>"
    )
    if not args:
        print(usage)
        return

    action = args[0].lower()
    if action == "new":
        goal = " ".join(args[1:]).strip()
        if not goal:
            print_error("task goal을 입력하세요.")
            print("사용법: ai task new <goal>")
            return
        task = create_ai_task(Path.cwd(), goal)
        ctx.task_store.add(task, set_current=True)
        print(f"active task를 만들었습니다: {task.id}")
        return

    if action == "list":
        tasks, current_task_id = ctx.task_store.load_state()
        print_ai_tasks(tasks, current_task_id)
        return

    if action == "show":
        if len(args) < 2:
            print_error("task id를 입력하세요.")
            print("사용법: ai task show <id>")
            return
        task = ctx.task_store.get(args[1])
        if not task:
            print_error(f"task를 찾을 수 없습니다: {args[1]}")
            return
        print_ai_task_detail(task)
        return

    if action == "current":
        task = ctx.task_store.current()
        if not task:
            print("(현재 active task 없음)")
            return
        print_ai_task_detail(task)
        return

    if action == "use":
        if len(args) < 2:
            print_error("전환할 task id를 입력하세요.")
            print("사용법: ai task use <id>")
            return
        task = ctx.task_store.set_current(args[1])
        if not task:
            print_error(f"active task를 찾을 수 없습니다: {args[1]}")
            return
        print(f"current task: {task.id} {task.goal}")
        return

    if action == "done":
        try:
            task_id, next_action = parse_task_done_options(args[1:])
        except ValueError as exc:
            print_error(str(exc))
            print("사용법: ai task done <id> [--next N]")
            return
        tasks, current_task_id = ctx.task_store.load_state()
        matches = [task for task in tasks if task.id == task_id or task.id.startswith(task_id)]
        if len(matches) != 1:
            print_error(f"task를 찾을 수 없습니다: {task_id}")
            return
        task = matches[0]
        task.status = "done"
        task.updated_at = now_iso()
        task.changed_files = changed_git_files_since_baseline(Path(task.cwd), task.git_baseline)
        if next_action:
            task.next_action = next_action
        next_current_task_id = None if current_task_id == task.id else current_task_id
        ctx.task_store.update(task, next_current_task_id)
        print(f"task를 완료했습니다: {task.id}")
        return

    print_error(f"알 수 없는 ai task 명령입니다: {action}")
    print(usage)


def filter_ai_sessions(
    sessions: List[AiSession],
    tool: Optional[str] = None,
    failed_only: bool = False,
) -> List[AiSession]:
    filtered = sessions
    if tool is not None:
        filtered = [session for session in filtered if session.tool == tool]
    if failed_only:
        filtered = [session for session in filtered if session.exit_code not in (None, 0)]
    return filtered


def parse_ai_sessions_options(args: List[str]) -> tuple[Optional[str], bool]:
    tool: Optional[str] = None
    failed_only = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--failed":
            failed_only = True
            index += 1
            continue
        if arg == "--tool":
            if index + 1 >= len(args):
                raise ValueError("--tool에는 값이 필요합니다.")
            tool = args[index + 1].lower()
            index += 2
            continue
        if arg.startswith("--tool="):
            tool = arg.split("=", 1)[1].lower()
            index += 1
            continue
        raise ValueError(f"알 수 없는 ai sessions 옵션입니다: {arg}")

    if tool is not None and tool not in {"codex", "claude"}:
        raise ValueError(f"지원하지 않는 AI 도구입니다: {tool}. 사용 가능: codex, claude")
    return tool, failed_only


def print_ai_session_json(session: AiSession) -> None:
    print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))


def print_ai_config(ctx: ShellContext) -> None:
    config = ctx.current_config()
    print("AI Config")
    print(f"theme: {config['theme']}")
    print(f"default_ai_tool: {config['default_ai_tool']}")
    print(f"active_profile: {config['active_profile'] or '-'}")
    print("aliases:")
    aliases = config["aliases"]
    if aliases:
        for name in sorted(aliases):
            print(f"  {name} -> {aliases[name]}")
    else:
        print("  (none)")


def print_ai_session_detail(session: AiSession) -> None:
    console = rich_console()
    if console is not None and RichPanel is not None:
        lines = [
            f"[bold]id[/bold]: {rich_escape(session.id)}",
            f"[bold]title[/bold]: {rich_escape(session.title)}",
            f"[bold]tool[/bold]: {rich_escape(session.tool)}",
            f"[bold]cwd[/bold]: {rich_escape(session.cwd)}",
            f"[bold]command[/bold]: {rich_escape(session.command)}",
            f"[bold]args[/bold]: {rich_escape(' '.join(session.args) if session.args else '-')}",
            f"[bold]profile[/bold]: {rich_escape(session.profile or '-')}",
            f"[bold]created_at[/bold]: {rich_escape(session.created_at)}",
            f"[bold]updated_at[/bold]: {rich_escape(session.updated_at)}",
            f"[bold]exit_code[/bold]: {rich_escape('-' if session.exit_code is None else session.exit_code)}",
        ]
        console.print(RichPanel("\n".join(lines), title="AI Session"))
        return

    print(f"id: {session.id}")
    print(f"title: {session.title}")
    print(f"tool: {session.tool}")
    print(f"cwd: {session.cwd}")
    print(f"command: {session.command}")
    print(f"args: {' '.join(session.args) if session.args else '-'}")
    print(f"profile: {session.profile or '-'}")
    print(f"created_at: {session.created_at}")
    print(f"updated_at: {session.updated_at}")
    print(f"exit_code: {'-' if session.exit_code is None else session.exit_code}")


def rerun_ai_session(ctx: ShellContext, session_id: str) -> int:
    refresh_project_context(ctx)
    session = ctx.session_store.get(session_id)
    if not session:
        print_error(f"세션을 찾을 수 없습니다: {session_id}")
        return 1
    if session.tool not in {"codex", "claude"}:
        print_error(f"재실행을 지원하지 않는 AI 도구입니다: {session.tool}")
        return 1

    cwd = Path(session.cwd)
    if not cwd.exists() or not cwd.is_dir():
        print_error(f"세션 cwd를 찾을 수 없습니다: {session.cwd}")
        return 1

    args = extract_rerunnable_ai_args(session.tool, session.args)
    title = f"rerun: {session.title}"
    return run_ai_tool_session(ctx, session.tool, args, title=title, profile=session.profile, cwd_override=cwd)


# -----------------------------------------------------------------------------
# 내장 명령어
# -----------------------------------------------------------------------------


@command("help", "등록된 명령어 목록과 설명을 출력합니다.")
def cmd_help(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    print("내장 명령어:")
    width = max(len(name) for name in COMMANDS)
    for name in sorted(COMMANDS):
        info = COMMANDS[name]
        print(f"  {name:<{width}}  {info.description}")

    if ctx.aliases:
        print("\n별칭:")
        for name in sorted(ctx.aliases):
            print(f"  {name} -> {ctx.aliases[name]}")

    print("\n안전장치:")
    print("  미등록 외부 명령은 .mysh/policy.json 정책으로 allow/ask/deny 평가를 받습니다.")
    print("  !<명령>은 ask 확인만 우회하며, deny 정책은 정책 파일 수정 없이는 차단됩니다.")


@command("ai", "AI 작업 보조 명령입니다. 예: ai doctor, ai policy, ai task, ai sessions, ai start codex")
def cmd_ai(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    try:
        parsed_args = parse_process_args(raw_args)
    except ValueError as exc:
        print_error(f"인자를 해석할 수 없습니다: {exc}")
        return

    if not parsed_args:
        print("사용법: ai doctor | ai context | ai policy | ai task | ai sessions [--tool codex|claude] [--failed] | ai show <session-id> [--json] | ai rerun <session-id> | ai start [codex|claude] [옵션] [prompt...]")
        return

    subcommand = parsed_args[0].lower()
    if subcommand == "doctor":
        rows = [
            ("Python", STATUS_OK, sys.version.replace("\n", " ")),
            cli_status("codex", "Codex CLI"),
            cli_status("claude", "Claude CLI"),
            git_doctor_status(),
        ]
        print("AI Doctor")
        print_status_table(rows)
        return

    if subcommand == "context":
        try:
            mode, max_lines = parse_ai_context_options(parsed_args[1:])
        except ValueError as exc:
            print_error(str(exc))
            print(f"사용 가능 모드: {', '.join(AI_CONTEXT_MODES)}")
            print("사용법: ai context [--mode debug|review|handoff|ship] [--max-lines N]")
            return
        print_ai_context(ctx, mode=mode, max_lines=max_lines)
        return

    if subcommand == "task":
        handle_ai_task_command(ctx, parsed_args[1:])
        return

    if subcommand == "policy":
        handle_ai_policy_command(ctx, parsed_args[1:])
        return

    if subcommand == "config":
        refresh_project_context(ctx)
        if len(parsed_args) == 1:
            print_ai_config(ctx)
            return
        if len(parsed_args) == 2 and parsed_args[1].lower() == "reset":
            ctx.reset_config()
            print("AI config를 기본값으로 초기화했습니다.")
            return
        print_error(f"알 수 없는 ai config 옵션입니다: {' '.join(parsed_args[1:])}")
        print("사용법: ai config | ai config reset")
        return

    if subcommand == "sessions":
        refresh_project_context(ctx)
        try:
            tool, failed_only = parse_ai_sessions_options(parsed_args[1:])
        except ValueError as exc:
            print_error(str(exc))
            print("사용법: ai sessions [--tool codex|claude] [--failed]")
            return
        print_ai_sessions(filter_ai_sessions(ctx.session_store.load(), tool=tool, failed_only=failed_only))
        return

    if subcommand == "show":
        if len(parsed_args) < 2:
            print_error("세션 id를 입력하세요.")
            print("사용법: ai show <session-id> [--json]")
            return
        show_json = False
        for option in parsed_args[2:]:
            if option == "--json":
                show_json = True
                continue
            print_error(f"알 수 없는 ai show 옵션입니다: {option}")
            print("사용법: ai show <session-id> [--json]")
            return
        refresh_project_context(ctx)
        session = ctx.session_store.get(parsed_args[1])
        if not session:
            print_error(f"세션을 찾을 수 없습니다: {parsed_args[1]}")
            return
        if show_json:
            print_ai_session_json(session)
            return
        print_ai_session_detail(session)
        return

    if subcommand == "rerun":
        if len(parsed_args) < 2:
            print_error("재실행할 세션 id를 입력하세요.")
            print("사용법: ai rerun <session-id>")
            return
        if len(parsed_args) > 2:
            print_error(f"알 수 없는 ai rerun 옵션입니다: {' '.join(parsed_args[2:])}")
            print("사용법: ai rerun <session-id>")
            return
        rerun_ai_session(ctx, parsed_args[1])
        return

    if subcommand == "start":
        start_args = parsed_args[1:]
        if not start_args or start_args[0].startswith("-"):
            tool = ctx.default_ai_tool
            tool_args = start_args
        else:
            tool = start_args[0].lower()
            tool_args = start_args[1:]
        if tool not in {"codex", "claude"}:
            print_error(f"지원하지 않는 AI 도구입니다: {tool}")
            print("사용 가능: codex, claude")
            return

        try:
            title, profile, passthrough_args = parse_ai_start_options(tool_args)
        except ValueError as exc:
            print_error(str(exc))
            return
        run_ai_tool_session(ctx, tool, passthrough_args, title=title, profile=profile)
        return

    print_error(f"알 수 없는 ai 하위 명령입니다: {subcommand}")
    print("사용법: ai doctor | ai context | ai policy | ai task | ai sessions [--tool codex|claude] [--failed] | ai show <session-id> [--json] | ai rerun <session-id> | ai start [codex|claude] [옵션] [prompt...]")


@command("codex", "Codex CLI를 세션으로 기록한 뒤 실행합니다.")
def cmd_codex(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    try:
        user_args = parse_process_args(raw_args)
    except ValueError as exc:
        print_error(f"인자를 해석할 수 없습니다: {exc}")
        return
    run_ai_tool_session(ctx, "codex", user_args)


@command("claude", "Claude CLI를 세션으로 기록한 뒤 실행합니다.")
def cmd_claude(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    try:
        user_args = parse_process_args(raw_args)
    except ValueError as exc:
        print_error(f"인자를 해석할 수 없습니다: {exc}")
        return
    run_ai_tool_session(ctx, "claude", user_args)


@command("cd", "디렉터리를 이동합니다. 인자가 없으면 홈으로 이동합니다.")
def cmd_cd(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    target_text = strip_outer_quotes(raw_args) if raw_args.strip() else str(Path.home())
    target = Path(os.path.expandvars(os.path.expanduser(target_text))).resolve()

    if not target.exists():
        print_error(f"경로가 없습니다: {target}")
        return
    if not target.is_dir():
        print_error(f"디렉터리가 아닙니다: {target}")
        return

    os.chdir(target)
    refresh_project_context(ctx)


@command("pwd", "현재 작업 디렉터리를 출력합니다.")
def cmd_pwd(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    print(Path.cwd())


@command("ls", "현재 폴더 목록을 출력합니다. 폴더는 /로 표시합니다.")
def cmd_ls(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    target_text = strip_outer_quotes(raw_args) if raw_args.strip() else "."
    target = Path(os.path.expandvars(os.path.expanduser(target_text))).resolve()

    if not target.exists():
        print_error(f"경로가 없습니다: {target}")
        return
    if target.is_file():
        print(target.name)
        return

    try:
        entries = list(os.scandir(target))
    except OSError as exc:
        print_error(f"목록을 읽을 수 없습니다: {exc}")
        return

    entries.sort(key=lambda item: (not item.is_dir(), item.name.lower()))
    for entry in entries:
        if entry.is_dir():
            print(f"{color('[D]', Ansi.BLUE)} {entry.name}/")
        else:
            print(f"{color('[F]', Ansi.DIM)} {entry.name}")


@command("echo", "입력한 텍스트를 그대로 출력합니다.")
def cmd_echo(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    print(raw_args)


@command("history", "이번 세션에서 입력한 명령어 기록을 출력합니다.")
def cmd_history(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    if not ctx.history:
        print("(기록 없음)")
        return

    for index, item in enumerate(ctx.history, start=1):
        print(f"{index:>4}  {item}")


@command("clear", "화면을 지웁니다.")
def cmd_clear(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    os.system("cls" if os.name == "nt" else "clear")


@command("theme", "프롬프트 색상 테마를 바꿉니다. 예: theme blue")
def cmd_theme(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    refresh_project_context(ctx)
    if not args:
        names = ", ".join(sorted(THEMES))
        print(f"현재 테마: {ctx.theme}")
        print(f"사용 가능: {names}")
        return

    next_theme = args[0].lower()
    if next_theme not in THEMES:
        print_error(f"알 수 없는 테마입니다: {next_theme}")
        print(f"사용 가능: {', '.join(sorted(THEMES))}")
        return

    ctx.theme = next_theme
    ctx.save_config()
    print(f"테마를 '{next_theme}'로 바꿨습니다.")


@command("alias", "명령어 별칭을 관리합니다. 예: alias gs=git status")
def cmd_alias(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    refresh_project_context(ctx)
    text = raw_args.strip()
    if not text:
        if not ctx.aliases:
            print("(별칭 없음)")
            return
        for name in sorted(ctx.aliases):
            print(f"{name} -> {ctx.aliases[name]}")
        return

    if "=" in text:
        name, value = text.split("=", 1)
    else:
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            print_error("사용법: alias 이름=명령 또는 alias 이름 명령")
            return
        name, value = parts

    name = name.strip()
    value = value.strip()
    if not name or not value:
        print_error("별칭 이름과 명령을 모두 입력하세요.")
        return
    if any(char.isspace() for char in name):
        print_error("별칭 이름에는 공백을 넣을 수 없습니다.")
        return

    ctx.aliases[name] = value
    ctx.save_config()
    print(f"{name} -> {value}")


@command("unalias", "등록된 별칭을 삭제합니다. 예: unalias gs")
def cmd_unalias(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    refresh_project_context(ctx)
    if not args:
        print_error("삭제할 별칭 이름을 입력하세요.")
        return

    name = args[0]
    if name not in ctx.aliases:
        print_error(f"등록된 별칭이 아닙니다: {name}")
        return

    del ctx.aliases[name]
    ctx.save_config()
    print(f"별칭을 삭제했습니다: {name}")


@command("quit", "셸을 종료합니다.")
@command("exit", "셸을 종료합니다.")
def cmd_exit(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    raise ShellExit()


# -----------------------------------------------------------------------------
# 메인 루프
# -----------------------------------------------------------------------------


def print_welcome(ctx: ShellContext) -> None:
    print(color("mysh에 오신 것을 환영합니다.", Ansi.BRIGHT_GREEN))
    print("help를 입력하면 명령어 목록을 볼 수 있습니다. exit 또는 quit로 종료합니다.")
    if ctx.input_backend == "prompt_toolkit":
        print(color("prompt_toolkit 입력 모드: 영속 히스토리, Tab 자동완성, 멀티라인을 사용합니다.", Ansi.DIM))
    elif not ctx.readline_available:
        print(color("참고: 이 환경에서는 readline 히스토리/Tab 자동완성이 비활성화되었습니다.", Ansi.DIM))


def main() -> int:
    configure_utf8_console()
    enable_ansi_on_windows()

    ctx = ShellContext()
    prompt_session = setup_prompt_toolkit(ctx)
    if prompt_session is None:
        setup_readline(ctx)
    print_welcome(ctx)

    while ctx.running:
        try:
            line = read_shell_line(ctx, prompt_session)
        except KeyboardInterrupt:
            print("^C")
            continue
        except EOFError:
            print()
            break

        line = normalize_input_line(line)
        if not line:
            continue

        ctx.history.append(line)
        if ctx.input_backend == "readline":
            add_readline_history(line)

        try:
            execute_line(ctx, line)
        except ShellExit:
            break
        except KeyboardInterrupt:
            print("^C")
        except Exception as exc:  # 초보자가 확장하다 실수해도 셸이 바로 죽지 않게 보호한다.
            print_error(f"예상하지 못한 문제가 발생했습니다: {exc}")

    print("mysh를 종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
