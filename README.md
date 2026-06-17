# mysh

`mysh.py`는 Python 3.8+ 표준 라이브러리만 사용하는 단일 파일 미니 커스텀 셸입니다.

## 실행

### 기본 실행(의존성 0)

외부 패키지 설치 없이 바로 실행할 수 있습니다. 이 경로에서는 Python 표준 라이브러리만 사용하며, 기존 `input()`/`readline` 기반 입력과 plain 텍스트 출력으로 동작합니다.

```powershell
python mysh.py
```

Windows에서는 시작 시 콘솔 코드 페이지와 Python 표준 입출력을 UTF-8로 맞춰 한글과 이모지가 깨질 가능성을 줄입니다.

### 향상된 실행(선택 의존성)

Rich 테이블/패널 출력과 prompt_toolkit 입력 루프를 쓰려면 선택 의존성을 설치합니다.

```powershell
python -m pip install -r requirements.txt
python mysh.py
```

`rich`가 있으면 `ai doctor`, `ai sessions`, `ai show`가 Rich 테이블·패널로 출력됩니다. `prompt_toolkit`이 있으면 영속 히스토리, 명령어/별칭/`ai` 하위 명령 자동완성, 멀티라인 입력을 사용합니다. 일반 Enter는 실행이고, `Esc+Enter`는 줄바꿈입니다. 둘 중 하나가 없거나 둘 다 없어도 셸은 기본 실행 경로로 자동 fallback합니다.

## 명령어

| 명령 | 설명 |
|------|------|
| `help` | 등록된 명령어와 설명 출력 |
| `cd <경로>` | 디렉터리 이동, 인자가 없으면 홈으로 이동 |
| `pwd` | 현재 경로 출력 |
| `ls` | 현재 폴더 목록 출력, 폴더는 `/`로 표시 |
| `echo <텍스트>` | 입력한 텍스트 출력 |
| `history` | 이번 세션 명령어 기록 출력 |
| `clear` | 화면 지우기 |
| `theme <green\|blue\|magenta\|mono>` | 프롬프트 색상 변경 |
| `alias 이름=명령` | 별칭 추가 |
| `unalias <이름>` | 별칭 삭제 |
| `ai doctor` | Python, Git, Codex, Claude 상태 확인 |
| `ai context [--mode debug\|review\|handoff] [--max-lines N]` | 기본/디버그/리뷰/인수인계용 plain-text 컨텍스트 팩 출력 |
| `ai sessions` | `.mysh/sessions.json`에 저장된 AI 세션 목록 출력 |
| `ai show <session-id>` | 저장된 AI 세션 상세 정보 출력 |
| `ai start codex [--title T] [--profile P] [prompt...]` | 세션을 기록하고 Codex 실행 |
| `ai start claude [--title T] [--profile P] [prompt...]` | 세션을 기록하고 Claude 실행 |
| `codex ...`, `claude ...` | 세션을 먼저 기록한 뒤 실제 CLI에 위임 |
| `exit`, `quit` | 셸 종료 |

등록되지 않은 명령어는 실제 OS 셸 명령으로 실행을 시도합니다.

AI 세션 기록은 프로젝트 루트의 `.mysh/sessions.json`에 저장됩니다. 프롬프트 본문은 저장하지 않고 유무와 길이만 기록합니다.

## 새 명령어 추가

`mysh.py`의 내장 명령어 섹션에서 아래처럼 함수 하나를 추가하면 됩니다.

```python
@command("hello", "인사를 출력합니다.")
def cmd_hello(ctx, args, raw_args):
    print("hello from mysh")
```
