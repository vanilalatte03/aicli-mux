# mysh

`mysh.py`는 Python 3.8+ 표준 라이브러리만 사용하는 단일 파일 미니 커스텀 셸입니다.

## 실행

```powershell
python mysh.py
```

외부 패키지 설치는 필요 없습니다.

## 명령어

- `help` - 등록된 명령어와 설명 출력
- `cd <경로>` - 디렉터리 이동, 인자가 없으면 홈으로 이동
- `pwd` - 현재 경로 출력
- `ls` - 현재 폴더 목록 출력, 폴더는 `/`로 표시
- `echo <텍스트>` - 입력한 텍스트 출력
- `history` - 이번 세션 명령어 기록 출력
- `clear` - 화면 지우기
- `theme <green|blue|magenta|mono>` - 프롬프트 색상 변경
- `alias 이름=명령` - 별칭 추가
- `unalias <이름>` - 별칭 삭제
- `exit`, `quit` - 셸 종료

등록되지 않은 명령어는 실제 OS 셸 명령으로 실행을 시도합니다.

## 새 명령어 추가

`mysh.py`의 내장 명령어 섹션에서 아래처럼 함수 하나를 추가하면 됩니다.

```python
@command("hello", "인사를 출력합니다.")
def cmd_hello(ctx, args, raw_args):
    print("hello from mysh")
```
