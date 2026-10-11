# 개발 환경 시작하기

uv로 Python·패키지를 관리하고 FastAPI 개발 서버를 실행합니다. 편집기와 코드 검사는 VS Code·Ruff를 사용합니다.

## 1. uv 설치

Git·VS Code 설치 후 운영체제에 맞게 실행합니다.

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

터미널을 다시 열고 확인합니다.

```bash
uv --version
```

## 2. 클론 및 패키지 설치

```bash
git clone https://github.com/myy-dev/be-B7-1.git
cd be-B7-1
uv python install 3.12
uv sync --locked
```

이후 명령은 `pyproject.toml`이 있는 저장소 루트에서 실행합니다.
패키지 변경을 받은 뒤에도 위 동기화 명령을 실행합니다.

## 3. VS Code 설정

VS Code에서 `be-B7-1`을 열고 다음 확장을 설치합니다.

| 확장 | 확장 ID |
| --- | --- |
| Python (Microsoft) | `ms-python.python` |
| Ruff (Astral Software) | `charliermarsh.ruff` |

명령 팔레트에서 **Python: Select Interpreter** → `.venv`를 선택합니다. **Preferences: Open Workspace Settings (JSON)**에 아래 설정을 추가하거나 기존 설정과 병합합니다.

```json
{
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  }
}
```

`.vscode/settings.json`은 Git에서 제외되므로 각자 설정합니다.

## 로컬 실행

설치·패키지 동기화를 마친 뒤 저장소 루트에서 실행합니다.

```bash
cp .env.example .env
openssl rand -hex 32
```

`.env`에 `OPENAI_API_KEY`, 사용할 `OPENAI_MODEL`, 생성한 `JWT_SECRET_KEY`, 로컬 DB 주소 `DATABASE_URL=sqlite+aiosqlite:///./app.db`를 설정합니다. 실제 비밀값은 Git에 올리지 않습니다. 전체 환경 변수와 비밀값 없는 예시는 [환경 변수](OPERATIONS.md#환경-변수)를 참고합니다.

```bash
uv run fastapi dev app/main.py
```

| 확인 | 주소 / 방법 |
| --- | --- |
| 서버·DB 정상 여부 | http://127.0.0.1:8000/health → `{"status":"ok"}` |
| API 문서와 요청 실행 | http://127.0.0.1:8000/docs → API 선택 → Try it out → Execute |
| API 문서 읽기 (ReDoc) | http://127.0.0.1:8000/redoc → 요청·응답 구조 확인 |
| 서버 종료 | 터미널에서 `Ctrl+C` |

`/docs`·`/redoc`은 같은 `/openapi.json`을 보여줍니다. 기본 SQLite DB는 저장소 루트의 `app.db`이며 별도 설치가 필요 없습니다.

가입·로그인 → Authorize → 채팅방 생성·질문의 실행 순서는 [사용자 API 확인](DATABASE.md#사용자-api로-확인), 테스트·권한·실패 점검은 [운영 검증](OPERATIONS.md#운영-검증)을 따릅니다. 운영 API는 [배포 Swagger](https://be-b7-1-development.up.railway.app/docs)에서 확인합니다.

## API 설명 관리

API 변경 시 `app/api/v1/endpoints/`의 설명·`responses`와 `app/schemas/`의 필드 설명·제한·예시를 갱신합니다. 서버를 다시 실행하면 Swagger에 반영됩니다.

## 자주 쓰는 uv 명령어

| 명령어 | 용도 |
| --- | --- |
| `uv add 패키지명` | 패키지 추가 |
| `uv add --dev 패키지명` | 개발용 패키지 추가 |
| `uv remove 패키지명` | 패키지 제거 |

패키지 변경 시 `pyproject.toml`·`uv.lock`을 함께 커밋합니다.
