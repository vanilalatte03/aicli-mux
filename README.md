# mysh

Codex / Claude Code 작업에 특화된 단일 파일 미니 셸. Python 3.8+ 표준 라이브러리만으로 바로 실행되며, 원하면 `rich`·`prompt_toolkit`으로 업그레이드할 수 있습니다.

## 빠른 시작

```bash
python mysh.py
```

설치 없이 바로 실행됩니다. `help`로 명령어 목록을, `exit`로 종료합니다.

## 향상된 모드 (선택)

```bash
python -m pip install -r requirements.txt
python mysh.py
```

- `rich` → `ai doctor`·`ai sessions`·`ai show`가 표/패널로 출력
- `prompt_toolkit` → 영속 히스토리, 자동완성, 멀티라인 입력 (Enter 실행 / Esc+Enter 줄바꿈)

패키지가 없으면 자동으로 기본 모드로 동작합니다.

## 명령어

### 기본

| 명령 | 설명 |
|------|------|
| `help` | 명령어 목록 |
| `cd [경로]` | 디렉터리 이동 (없으면 홈) |
| `pwd` | 현재 경로 |
| `ls` | 폴더 목록 (폴더는 `/` 표시) |
| `echo <텍스트>` | 텍스트 출력 |
| `history` | 이번 세션 입력 기록 |
| `clear` | 화면 지우기 |
| `theme <green\|blue\|magenta\|mono>` | 프롬프트 색상 변경 |
| `alias 이름=명령` / `unalias 이름` | 별칭 추가 / 삭제 |
| `!<명령>` | 내장/별칭과 정책의 ask 확인을 우회하고 OS 셸에 직접 전달 |
| `exit` / `quit` | 종료 |

### AI

| 명령 | 설명 |
|------|------|
| `ai doctor` | Python·Git·Codex·Claude 환경 점검 |
| `ai context [--mode debug\|review\|handoff\|ship] [--max-lines N]` | 기본/디버그/리뷰/인수인계/출시용 plain-text 컨텍스트 팩 출력 |
| `ai config` / `ai config reset` | 프로젝트별 theme, alias, 기본 AI tool/profile 설정 출력 / 초기화 |
| `ai policy` / `ai policy init` | 적용 중인 외부 명령 정책 출력 / 기본 정책 파일 생성 |
| `ai task new <goal>` / `ai task list` / `ai task show <id>` | AI 세션을 작업 단위로 묶고 Git baseline/변경 파일을 추적 |
| `ai task current` / `ai task use <id>` / `ai task done <id> [--next N]` | 현재 작업 확인·전환·완료 처리 |
| `ai sessions [--tool codex\|claude] [--failed]` | 저장된 AI 세션 목록, 도구별/실패 세션 필터 |
| `ai show <id> [--json]` | 세션 상세 또는 스크립트용 JSON 메타데이터 |
| `ai rerun <id>` | 저장된 세션의 tool/cwd/플래그로 새 세션 재실행 |
| `ai start codex [--title T] [--profile P] [prompt...]` | 세션 기록 후 Codex 실행 |
| `ai start claude [--title T] [--profile P] [prompt...]` | 세션 기록 후 Claude 실행 |
| `codex ...` / `claude ...` | 세션을 먼저 기록한 뒤 실제 CLI에 위임 |

`ai context`는 active task가 있으면 출력 상단에 현재 작업(goal/변경 파일 요약)을 붙이고, `handoff`/`ship` 모드에서는 다음 액션·연결 세션·테스트 상태를 추가로 반영합니다.

등록되지 않은 명령은 OS 셸 명령으로 실행을 시도합니다. 실행 직전 `.mysh/policy.json` 정책이 있으면 그 파일을, 없으면 내장 기본 정책을 적용합니다. 정책 규칙은 `{ "match": "<정규식>", "action": "allow|ask|deny", "reason": "<설명>" }` 형태이며, `ai policy init`으로 기본 파일을 만들 수 있습니다. `ask`는 y/N 확인을 받고 비대화형 입력에서는 차단합니다. `deny`는 항상 차단되며, `!<명령>` escape hatch도 `ask`만 건너뛰고 `deny`는 건너뛰지 않습니다. 해제하려면 정책 파일을 수정해야 합니다.

정책 평가는 입력을 `;`, `&&`, `||`, `|` 기준의 세그먼트로 나눠 정규식과 대조합니다. POSIX 입력은 `shlex`, 그 외 환경은 따옴표만 고려하는 단순 분리를 사용하므로 셸 문법을 완전히 해석하지 않습니다. 이 정책은 실수 방지용 과속방지턱일 뿐이며, 모든 위험 명령을 잡거나 우회를 막는 보안 경계가 아닙니다.

AI 세션은 프로젝트 루트의 `.mysh/sessions.json`에 저장되며, **프롬프트 본문은 저장하지 않고** 유무·길이만 기록합니다. 작업 메타데이터는 `.mysh/tasks.json`, 정책은 `.mysh/policy.json`, 프로젝트 설정은 `.mysh/config.json`에 저장됩니다. JSON 저장소는 단일 사용자 사용을 가정하며 동시 사용은 지원하지 않습니다. `ai rerun`은 대화를 이어가지 않고 저장된 실행 옵션으로 새 세션을 시작합니다.

## 새 명령어 추가

`mysh.py`의 내장 명령어 섹션에 함수 하나만 추가하면 됩니다.

```python
@command("hello", "인사를 출력합니다.")
def cmd_hello(ctx, args, raw_args):
    print("hello from mysh")
```
