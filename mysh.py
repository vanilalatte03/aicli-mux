# 새 명령어 추가: 아래의 @command("이름", "설명") 데코레이터를 붙인 함수를 만든다.
# 함수 시그니처는 func(ctx, args, raw_args) 형태를 사용한다.
# args는 공백 기준으로 나눈 인자 목록이고, raw_args는 명령어 뒤 원문 문자열이다.
# 파일 아래쪽의 "내장 명령어" 섹션 예시를 복사해서 고치면 된다.

"""Python 표준 라이브러리만 사용하는 작은 대화형 커스텀 셸."""

from __future__ import annotations

import ctypes
import datetime as _dt
import os
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


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


def color(text: str, ansi_code: str) -> str:
    """색상 코드가 비어 있으면 원문 그대로 반환한다."""
    if not ansi_code:
        return text
    return f"{ansi_code}{text}{Ansi.RESET}"


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


def command(name: str, description: str) -> Callable[[CommandHandler], CommandHandler]:
    """내장 명령어를 등록하는 데코레이터."""

    def decorator(func: CommandHandler) -> CommandHandler:
        COMMANDS[name] = Command(name=name, description=description, handler=func)
        return func

    return decorator


# -----------------------------------------------------------------------------
# 셸 상태와 유틸리티
# -----------------------------------------------------------------------------


@dataclass
class ShellContext:
    history: List[str] = field(default_factory=list)
    aliases: Dict[str, str] = field(
        default_factory=lambda: {
            "h": "help",
            "ll": "ls",
            "q": "quit",
        }
    )
    theme: str = "green"
    running: bool = True
    readline_available: bool = False


class ShellExit(Exception):
    """exit/quit 명령이 셸 루프를 빠져나가도록 알려주는 예외."""


def parse_args(raw_args: str) -> List[str]:
    """따옴표를 이해하는 간단한 인자 파서."""
    if not raw_args.strip():
        return []
    return shlex.split(raw_args, posix=(os.name != "nt"))


def split_command_line(line: str) -> tuple[str, str]:
    """입력 한 줄을 명령어 이름과 나머지 원문 인자로 나눈다."""
    stripped = line.strip()
    if not stripped:
        return "", ""

    parts = stripped.split(maxsplit=1)
    name = parts[0]
    raw_args = parts[1] if len(parts) > 1 else ""
    return name, raw_args


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


def run_external_command(line: str) -> None:
    """등록되지 않은 명령은 실제 OS 셸에 넘겨 실행을 시도한다."""
    if not line.strip():
        print_error("실행할 외부 명령을 입력하세요.")
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
        run_external_command(line[1:].lstrip())
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
# readline 지원: 위/아래 히스토리와 Tab 자동완성
# -----------------------------------------------------------------------------


def setup_readline(ctx: ShellContext) -> None:
    """readline이 있는 환경이면 히스토리 탐색과 명령어 자동완성을 켠다."""
    try:
        import readline  # type: ignore
    except ImportError:
        ctx.readline_available = False
        return

    ctx.readline_available = True

    def completer(text: str, state: int) -> Optional[str]:
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


# -----------------------------------------------------------------------------
# AI 보조 명령 유틸리티
# -----------------------------------------------------------------------------


def run_tool(args: List[str], timeout: float = 5.0) -> Optional[subprocess.CompletedProcess[str]]:
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
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    """stdout/stderr에서 사람이 읽을 첫 줄을 고른다."""
    output = (result.stdout or result.stderr).strip()
    if not output:
        return "(출력 없음)"
    return output.splitlines()[0].strip()


def git_result(args: List[str], timeout: float = 5.0) -> Optional[subprocess.CompletedProcess[str]]:
    """Git 명령을 실행한다. Git이 없거나 실패하면 호출자가 상태를 판단한다."""
    return run_tool(["git", *args], timeout=timeout)


def is_git_repository() -> bool:
    result = git_result(["rev-parse", "--is-inside-work-tree"])
    return bool(result and result.returncode == 0 and result.stdout.strip() == "true")


def current_git_branch() -> str:
    branch = git_result(["branch", "--show-current"])
    if branch and branch.returncode == 0 and branch.stdout.strip():
        return branch.stdout.strip()

    commit = git_result(["rev-parse", "--short", "HEAD"])
    if commit and commit.returncode == 0 and commit.stdout.strip():
        return f"detached HEAD ({commit.stdout.strip()})"

    return "(알 수 없음)"


def changed_git_files() -> List[str]:
    status = git_result(["status", "--porcelain"])
    if not status or status.returncode != 0:
        return []
    return [line for line in status.stdout.splitlines() if line.strip()]


def recent_git_commits(limit: int = 3) -> List[str]:
    result = git_result(["log", "--oneline", f"-{limit}"])
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


def print_status_table(rows: List[tuple[str, str, str]]) -> None:
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


def print_ai_context() -> None:
    root = Path.cwd().resolve()
    print("=== AI Context ===")
    print(f"CWD: {root}")

    readme = find_readme(root)
    if readme:
        print()
        print(f"=== README: {readme.name} (first 40 lines) ===")
        for line in read_text_preview(readme, max_lines=40):
            print(line)

    print()
    print("=== File Tree (depth 2, max 100 items) ===")
    for line in file_tree_lines(root, max_depth=2, max_items=100):
        print(line)

    if is_git_repository():
        print()
        print("=== Git Summary ===")
        print(f"Branch: {current_git_branch()}")

        commits = recent_git_commits(limit=3)
        print("Recent commits:")
        if commits:
            for commit in commits:
                print(f"  {commit}")
        else:
            print("  (none)")

        changes = changed_git_files()
        print("Changed files:")
        if changes:
            for change in changes:
                print(f"  {change}")
        else:
            print("  (none)")


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


@command("ai", "AI 작업 보조 명령입니다. 예: ai doctor, ai context")
def cmd_ai(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    if not args:
        print("사용법: ai doctor | ai context")
        return

    subcommand = args[0].lower()
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
        print_ai_context()
        return

    print_error(f"알 수 없는 ai 하위 명령입니다: {subcommand}")
    print("사용법: ai doctor | ai context")


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
    print(f"테마를 '{next_theme}'로 바꿨습니다.")


@command("alias", "명령어 별칭을 관리합니다. 예: alias gs=git status")
def cmd_alias(ctx: ShellContext, args: List[str], raw_args: str) -> None:
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
    print(f"{name} -> {value}")


@command("unalias", "등록된 별칭을 삭제합니다. 예: unalias gs")
def cmd_unalias(ctx: ShellContext, args: List[str], raw_args: str) -> None:
    if not args:
        print_error("삭제할 별칭 이름을 입력하세요.")
        return

    name = args[0]
    if name not in ctx.aliases:
        print_error(f"등록된 별칭이 아닙니다: {name}")
        return

    del ctx.aliases[name]
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
    if not ctx.readline_available:
        print(color("참고: 이 환경에서는 readline 히스토리/Tab 자동완성이 비활성화되었습니다.", Ansi.DIM))


def main() -> int:
    enable_ansi_on_windows()

    ctx = ShellContext()
    setup_readline(ctx)
    print_welcome(ctx)

    while ctx.running:
        try:
            line = input(make_prompt(ctx))
        except KeyboardInterrupt:
            print("^C")
            continue
        except EOFError:
            print()
            break

        line = line.strip()
        if not line:
            continue

        ctx.history.append(line)
        if ctx.readline_available:
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
