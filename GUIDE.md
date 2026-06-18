# mysh 활용 설명서 (자세한 버전)

이 문서는 `mysh`를 실제로 어떻게 쓰는지 처음부터 끝까지 따라 할 수 있게 정리한 매뉴얼입니다. README가 "무엇이 있는지"라면, 이 문서는 "어떻게, 왜, 어떤 순서로 쓰는지"입니다.

---

## 1. mysh가 뭔가 — 3층 멘탈 모델

mysh는 Codex / Claude Code와 함께 쓰는 **개인용 AI 작업 셸**입니다. 세 개의 층으로 생각하면 쉽습니다.

1. **평범한 셸** — `cd`, `ls`, `pwd`, `echo` 등 기본 명령. 등록되지 않은 명령은 실제 OS 셸로 넘어갑니다.
2. **AI 작업 보조 (`ai ...`)** — AI 도구 실행을 기록하고, 작업(task)으로 묶고, 붙여넣기용 컨텍스트를 뽑아주는 층. mysh의 핵심 가치.
3. **안전장치** — 위험한 명령(`rm -rf`, `git reset --hard` 등)을 실행 직전에 막아주는 과속방지턱.

모든 상태(세션·작업·설정·정책·입력 히스토리)는 프로젝트 폴더 안의 **`.mysh/`** 디렉터리에 JSON으로 저장됩니다. 즉 **프로젝트마다 독립적**입니다.

> 한 줄 요약: "AI 도구를 띄우고, 작업 단위로 추적하고, 위험한 실수를 막아주는, 프로젝트 전용 셸."

---

## 2. 설치 & 실행

### 기본 실행 (의존성 0)
```bash
python mysh.py
```
표준 라이브러리만으로 바로 실행됩니다. `input()`/readline 기반 입력과 plain 텍스트 출력으로 동작합니다.

### 향상된 실행 (선택)
```bash
python -m pip install -r requirements.txt
python mysh.py
```
- `rich` 설치 시: `ai doctor`, `ai sessions`, `ai show` 등이 표/패널로 예쁘게 출력됩니다.
- `prompt_toolkit` 설치 시: 영속 입력 히스토리, 명령어 자동완성, 멀티라인 입력(일반 Enter=실행, Esc+Enter=줄바꿈)을 씁니다.
- 둘 다 없어도 기본 모드로 자동 동작합니다.

---

## 3. 첫 5분 — 그대로 따라 하기

작업하려는 프로젝트 폴더에서 mysh를 실행한 뒤:

```text
ai doctor                      # 환경(파이썬/codex/claude/git) 점검
ai task new "로그인 버그 수정"   # 작업 시작 (지금부터의 AI 세션이 여기 묶임)
ai context --mode debug        # 현재 상황을 AI에 붙여넣을 텍스트로 출력
codex "로그인 실패 원인 찾아줘"   # Codex 실행 (세션 자동 기록 + 작업에 연결)
ai sessions                    # 방금 실행한 세션 확인
ai task done <id> --next "테스트 추가"   # 작업 마무리 + 다음 액션 메모
```

이 흐름이 mysh의 전형적인 사용 루프입니다. 아래에서 각 명령을 자세히 봅니다.

---

## 4. 명령어 레퍼런스

### 4.1 기본 셸 명령

| 명령 | 동작 | 예시 |
|------|------|------|
| `help` | 등록된 명령어·별칭 목록 | `help` |
| `cd [경로]` | 디렉터리 이동(없으면 홈) | `cd src`, `cd ..`, `cd` |
| `pwd` | 현재 경로 | `pwd` |
| `ls [경로]` | 폴더 목록(`[D]`/`[F]` 표시) | `ls`, `ls src` |
| `echo <텍스트>` | 텍스트 출력 | `echo hello` |
| `history` | 이번 세션 입력 기록 | `history` |
| `clear` | 화면 지우기 | `clear` |
| `theme <이름>` | 프롬프트 색상 변경(저장됨) | `theme blue` |
| `alias 이름=명령` | 별칭 추가(저장됨) | `alias gs=git status` |
| `unalias <이름>` | 별칭 삭제 | `unalias gs` |
| `!<명령>` | 내장/별칭/안전확인 우회하고 OS 셸로 직접 | `!git status` |
| `exit` / `quit` | 종료 | `exit` |

색상 테마는 `green`, `blue`, `magenta`, `mono`(무색) 중 선택. `theme`/`alias` 변경은 `.mysh/config.json`에 즉시 저장돼 다음 실행에도 유지됩니다.

> 등록되지 않은 명령(예: `git`, `python`, `npm`)은 자동으로 OS 셸에서 실행됩니다. 따로 외울 필요 없이 평소처럼 쓰면 됩니다.

### 4.2 `ai doctor` — 환경 점검

```text
ai doctor
```
Python 버전, `codex`/`claude` CLI 설치 여부와 버전, 현재 폴더의 Git 상태(branch, 변경 파일 수)를 한눈에 보여줍니다. 새 환경에서 "왜 codex가 안 되지?" 같은 삽질을 줄여줍니다.

### 4.3 `ai context` — 붙여넣기용 컨텍스트 추출 (핵심 기능)

현재 작업 상황을 **AI에 그대로 붙여넣기 좋은 plain 텍스트**로 뽑아줍니다. 웹 AI에 상황을 설명하거나, codex/claude에 배경을 줄 때 유용합니다.

```text
ai context                          # 기본 팩 (개요)
ai context --mode debug             # 디버깅용
ai context --mode review            # 코드 리뷰용
ai context --mode handoff           # 인수인계용
ai context --mode ship              # 배포 직전 점검용
ai context --mode debug --max-lines 80   # 출력 길이 제한
```

> ⚠️ 문법 주의: 모드는 **`--mode debug`** 형태입니다. `ai context debug`처럼 위치 인자로 쓰면 오류가 납니다.

모드별 초점:
- **default** — 작업 디렉터리, README 요약, 파일 트리, Git 요약 등 전반적 개요.
- **debug** — 변경 파일과 Git diff, 테스트 힌트 등 "지금 뭐가 깨졌나" 중심.
- **review** — staged + 작업 트리 diff, 최근 커밋, 테스트 상태 등 "이 변경 검토" 중심.
- **handoff** — README·구조 요약 + 최근 AI 세션/현재 작업 요약 등 "남에게 넘기기" 중심.
- **ship** — 변경 요약 + 검증/테스트 상태 + 미커밋·untracked 미리보기 등 "배포 직전 확인" 중심.

`--max-lines N`으로 출력이 너무 길어지지 않게 잘라낼 수 있습니다(긴 diff를 AI에 붙일 때 유용). active task가 있으면 출력 상단에 현재 작업 정보가 함께 붙습니다.

### 4.4 `ai task` — 작업 단위 추적

세션을 "작업(task)"으로 묶습니다. 작업이 active인 동안 실행한 codex/claude 세션이 자동으로 그 작업에 연결됩니다.

```text
ai task new "<목표>"          # 새 작업 시작 + active로 지정 (Git baseline 자동 스냅샷)
ai task list                  # 작업 목록 (상태/세션 수/목표)
ai task current               # 현재 active 작업 상세
ai task show <id>             # 특정 작업 상세 (연결 세션, 변경 파일 등)
ai task use <id>              # active 작업 전환
ai task done <id> [--next "<다음 액션>"]   # 작업 완료 + 변경 파일 최종 캡처
```

동작 포인트:
- **목표(goal)만 필수**입니다. 다음 액션·테스트 결과는 선택.
- 작업 시작 시 현재 Git 상태(HEAD·branch·변경 목록)를 `git_baseline`으로 저장하고, `done` 시점에 baseline 대비 **변경 파일을 자동 산출**합니다.
- id는 앞부분만 입력해도 매칭됩니다(예: 전체가 `7adb388...`이면 `ai task show 7adb`).
- Git이 아닌 폴더에서도 오류 없이 동작(변경 파일 추적만 생략).

### 4.5 `ai start` / `codex` / `claude` — AI 도구 실행 (세션 기록)

AI 도구를 실행하면서 세션을 자동 기록합니다. 두 가지 방법이 있습니다.

```text
# 방법 A: 명시적
ai start codex [--title "제목"] [--profile "프로필"] [프롬프트...]
ai start claude [--title "제목"] [--profile "프로필"] [프롬프트...]
ai start            # 도구 생략 시 기본 도구(default_ai_tool) 사용

# 방법 B: 평소처럼 (wrapper)
codex "버그 찾아줘"
claude
```

동작 포인트:
- **Codex**: `--cd <현재 폴더>`를 자동으로 붙입니다(이미 `--cd`/`-C`를 줬으면 중복하지 않음).
- **Claude**: 현재 폴더에서 실행하고, 넘긴 인자는 그대로 전달합니다.
- codex/claude의 자체 플래그(예: `--resume`, `--continue`)는 **그대로 위임**됩니다. 즉 실제 "대화 이어가기"는 도구 자체 기능으로 하면 됩니다.
- 실행 전 세션을 기록하고, 종료 후 exit code와 종료 시각을 갱신합니다.
- **프롬프트 본문은 저장하지 않습니다.** 도구·플래그·유무만 기록(민감정보 보호).
- 위험/권한 우회 옵션(`--dangerously-*` 등)은 절대 자동으로 붙이지 않습니다.

### 4.6 `ai sessions` / `ai show` / `ai rerun` — 세션 조회·재실행

```text
ai sessions                       # 저장된 세션 목록
ai sessions --tool codex          # 도구별 필터
ai sessions --tool claude --failed   # 실패(exit code != 0)한 claude 세션만
ai show <session-id>              # 세션 상세 (tool, cwd, command, 시각, exit code)
ai show <session-id> --json       # JSON으로 출력 (스크립트 연동용)
ai rerun <session-id>             # 같은 도구/폴더/플래그로 다시 실행 (새 세션으로 기록)
```

> `ai rerun`은 "같은 실행을 다시 띄우기"입니다. AI와의 대화 스레드를 잇는 게 아니라, 같은 커맨드를 재실행합니다. 대화 재개가 필요하면 `codex --resume` 같은 도구 자체 기능을 쓰세요.

### 4.7 `ai config` — 영속 설정

```text
ai config           # 현재 설정 출력
ai config reset     # 기본값으로 초기화
```
`.mysh/config.json`에 저장되는 항목:
- `theme` — 기본 프롬프트 색상
- `aliases` — 별칭 목록
- `active_profile` — 기본 프로필(없으면 비움)
- `default_ai_tool` — `ai start`에서 도구 생략 시 쓸 기본 도구(`codex` 또는 `claude`)

`theme`/`alias` 명령으로 바꾸면 자동 저장됩니다.

### 4.8 `ai policy` — 위험 명령 정책

```text
ai policy           # 현재 적용 중인 정책(규칙 목록) 출력
ai policy init      # 기본 정책을 .mysh/policy.json 파일로 기록 (이후 직접 편집)
```
자세한 동작은 아래 7장(안전장치)에서 설명합니다.

---

## 5. 실전 워크플로 예시

### 5.1 버그 디버깅
```text
ai task new "결제 실패 버그"
ai context --mode debug --max-lines 100     # 출력을 복사
claude                                       # Claude에 붙여넣고 원인 분석
# ... 수정 ...
!python -m pytest -k payment                 # 안전확인 없이 바로 테스트
ai task done <id> --next "엣지케이스 테스트 추가"
```

### 5.2 코드 리뷰 인수인계
```text
ai context --mode handoff                    # 작업/구조/최근 세션 요약을 동료나 AI에 전달
ai context --mode review                     # 변경 diff + 최근 커밋 중심으로 리뷰 요청
```

### 5.3 배포 직전 점검
```text
ai context --mode ship                        # 변경 요약 + 검증 상태 + 미커밋 미리보기
ai sessions --failed                          # 최근 실패한 작업이 남아있는지 확인
```

---

## 6. `.mysh/` 저장소 — 무엇이 어디에

프로젝트 루트의 `.mysh/` 안에 모든 상태가 JSON으로 저장됩니다(Git 저장소면 `.gitignore`에 자동 추가되어 커밋되지 않습니다).

| 파일 | 내용 |
|------|------|
| `sessions.json` | AI 세션 기록 (도구, cwd, 플래그, exit code, 시각) |
| `tasks.json` | 작업 목록과 현재 active 작업 |
| `config.json` | theme, aliases, default_ai_tool, profile |
| `policy.json` | 위험 명령 정책(있을 때만; 없으면 내장 기본값) |
| `history.txt` | prompt_toolkit 입력 히스토리 |

JSON이 손상되면 자동으로 `.bak` 백업을 만든 뒤 안전한 기본값으로 복구합니다.

> **단일 사용자 가정**: 저장소는 한 명이 쓰는 것을 전제로 합니다. 여러 터미널/에이전트가 같은 `.mysh/`에 동시에 쓰는 상황은 지원하지 않습니다.

---

## 7. 안전장치 — 어떻게 막고, 어떻게 우회하나

등록되지 않은 명령이 OS 셸로 넘어가기 직전에 정책을 검사합니다. 입력은 `;`, `&&`, `||`, `|` 단위로 쪼개 **세그먼트별로** 검사합니다.

세 가지 판정:
- **allow / 매칭 없음** → 그냥 실행.
- **ask** → 확인 프롬프트(`[y/N]`, 기본 N). 동의해야 실행.
- **deny** → 실행 차단. `.mysh/policy.json`을 직접 수정해야만 풀립니다.

기본 정책(요약):
- **ask**: 재귀적 `rm -r`, `del`, `Remove-Item`, `git reset --hard`, `git clean`, `pip install`, 글로벌 `npm install -g`, `curl|wget ... | sh/bash`, `iwr/irm ... | iex`.
- **deny**: `DROP TABLE/DATABASE`, `mkfs`, `> /dev/...`, fork bomb(`:(){`).

우회와 한계:
- **`!<명령>`** 은 **ask를 건너뜁니다**(고급 사용자용 명시적 의도). 단 **deny는 그래도 차단**됩니다.
- **비대화형 입력**(파이프 등 확인을 받을 수 없는 상황)에서는 ask·deny **둘 다 차단**합니다. 확인 없이 자동 실행하지 않습니다.
- 정책을 바꾸려면 `ai policy init`으로 파일을 만든 뒤 `.mysh/policy.json`의 규칙(`match`/`action`/`reason`)을 편집하세요.

> ⚠️ 이 안전장치는 **"진짜 보안"이 아니라 명백한 실수를 막는 과속방지턱**입니다. 정규식 기반이라 모든 위험을 잡지 못하고 우회도 가능합니다. 맹신하지 마세요.

---

## 8. 팁 & 자주 막히는 점

- **`ai context debug`가 오류 남** → 모드는 `--mode` 플래그입니다: `ai context --mode debug`.
- **긴 diff가 AI 입력 한도를 넘음** → `--max-lines`로 줄이세요.
- **위험하지 않은데 자꾸 확인을 물어봄** → `!` 접두사로 한 번 우회하거나, `.mysh/policy.json`에서 해당 규칙을 `allow`로 바꾸세요.
- **codex/claude가 "없음"으로 나옴** → `ai doctor`로 설치/PATH 확인. mysh는 도구를 대신 설치해주지 않습니다.
- **세션이 작업에 안 묶임** → 세션 실행 *전에* `ai task new`로 active 작업이 있어야 자동 연결됩니다.
- **설정이 초기화됨/꼬임** → `ai config reset` 또는 `.mysh/`의 해당 JSON 삭제 후 재실행(기본값으로 다시 생성).

---

## 9. 직접 확장하기

새 명령어는 `mysh.py`의 내장 명령어 섹션에 함수 하나만 추가하면 됩니다.

```python
@command("hello", "인사를 출력합니다.")
def cmd_hello(ctx, args, raw_args):
    print("hello from mysh")
```

- `args`: 공백 기준으로 나눈 인자 목록
- `raw_args`: 명령어 뒤 원문 문자열
- `ctx`: 셸 상태(세션 저장소, 작업 저장소, 설정, 테마 등)에 접근

추가 후 `python -m py_compile mysh.py`로 문법 확인, 가능하면 `test_mysh.py`에 테스트를 더하세요.
