# mysh

Codex / Claude Code 작업에 특화된 단일 파일 미니 셸. Python 3.8+ 표준 라이브러리만으로 바로 실행되며, 원하면 `rich`·`prompt_toolkit`으로 업그레이드할 수 있습니다.

> 📖 **자세한 사용법·워크플로·예시는 [GUIDE.md](GUIDE.md)를 참고하세요.** 이 README는 빠른 시작과 명령어 요약입니다.

## 빠른 시작

```bash
python mysh.py
```

설치 없이 바로 실행됩니다. `help`로 명령어 목록을, `exit`로 종료합니다.

### 향상된 모드 (선택)

```bash
python -m pip install -r requirements.txt
python mysh.py
```

- `rich` → `ai doctor`·`ai sessions`·`ai show`가 표/패널로 출력
- `prompt_toolkit` → 영속 히스토리, 자동완성, 멀티라인 입력 (Enter 실행 / Esc+Enter 줄바꿈)

패키지가 없으면 자동으로 기본 모드로 동작합니다.

## 명령어 요약

### 기본

| 명령 | 설명 |
|------|------|
| `help` | 명령어 목록 |
| `cd [경로]` | 디렉터리 이동 (없으면 홈) |
| `pwd` / `ls` / `echo` / `history` / `clear` | 기본 셸 동작 |
| `theme <green\|blue\|magenta\|mono>` | 프롬프트 색상 변경 (저장됨) |
| `alias 이름=명령` / `unalias 이름` | 별칭 추가 / 삭제 (저장됨) |
| `!<명령>` | 내장/별칭과 정책의 ask 확인을 우회하고 OS 셸에 직접 전달 |
| `exit` / `quit` | 종료 |

### AI

| 명령 | 설명 |
|------|------|
| `ai doctor` | Python·Git·Codex·Claude 환경 점검 |
| `ai context [--mode debug\|review\|handoff\|ship] [--max-lines N]` | 붙여넣기용 컨텍스트 팩 출력 |
| `ai task new\|list\|show\|current\|use\|done` | AI 세션을 작업 단위로 묶고 Git 변경 추적 |
| `ai start [codex\|claude] [--title T] [--profile P] [prompt...]` | 세션 기록 후 AI 도구 실행 |
| `codex ...` / `claude ...` | 세션을 먼저 기록한 뒤 실제 CLI에 위임 |
| `ai sessions [--tool ...] [--failed]` / `ai show <id> [--json]` / `ai rerun <id>` | 세션 조회·필터·재실행 |
| `ai config` / `ai config reset` | 프로젝트 설정(theme, alias, 기본 tool/profile) 출력 / 초기화 |
| `ai policy` / `ai policy init` | 외부 명령 정책 출력 / 기본 정책 파일 생성 |

> 명령별 상세 동작, 모드별 차이, 실전 워크플로는 [GUIDE.md](GUIDE.md)에 있습니다.

## 저장소와 안전장치 (요약)

- 모든 상태는 프로젝트 루트의 `.mysh/`에 JSON으로 저장됩니다 (`sessions.json`, `tasks.json`, `config.json`, `policy.json`). Git 저장소면 `.gitignore`에 자동 추가됩니다. **단일 사용자 가정**이며 동시 사용은 지원하지 않습니다. AI 세션은 **프롬프트 본문을 저장하지 않습니다.**
- 등록되지 않은 명령은 OS 셸로 실행되며, 직전에 정책(`ask`/`deny`)을 검사합니다. `!`는 `ask`만 건너뛰고 `deny`는 차단됩니다. 이 정책은 **실수 방지용 과속방지턱일 뿐 보안 경계가 아닙니다.** 자세한 규칙·커스터마이징은 [GUIDE.md](GUIDE.md) 7장 참고.

## 새 명령어 추가

`mysh.py`의 내장 명령어 섹션에 함수 하나만 추가하면 됩니다.

```python
@command("hello", "인사를 출력합니다.")
def cmd_hello(ctx, args, raw_args):
    print("hello from mysh")
```
