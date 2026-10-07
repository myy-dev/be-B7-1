# 개발 환경 시작하기

- **uv**: Python과 프로젝트 패키지 관리
- **FastAPI**: API 개발 프레임워크
- **Ruff**: 코드 검사와 자동 포맷

## 1. uv 설치

Git과 VS Code를 설치한 뒤, 운영체제에 맞게 실행합니다.

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

이후 명령은 모두 `pyproject.toml`이 있는 프로젝트 루트에서 실행합니다.

## 3. VS Code 설정

1. VS Code에서 `be-B7-1` 폴더를 엽니다.
2. 확장 메뉴에서 다음 확장을 설치합니다.

   | 확장 | 확장 ID |
   | --- | --- |
   | Python (Microsoft) | `ms-python.python` |
   | Ruff (Astral Software) | `charliermarsh.ruff` |

3. 명령 팔레트에서 **Python: Select Interpreter** → `.venv`를 선택합니다.
4. **Preferences: Open Workspace Settings (JSON)**에서 아래 설정을 추가합니다. 기존 설정이 있으면 병합합니다.

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

- `.vscode/settings.json`은 Git 제외 대상이므로 각자 설정

## 4. 환경변수 설정

프로젝트 루트에 `.env` 파일을 만들고 실제 키를 입력합니다.

```dotenv
OPENAI_API_KEY=발급받은_API_키
OPENAI_MODEL=GPT 모델
AI_TIMEOUT_SECONDS=30
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://www.quackquack-e.duckdns.org,https://b7-1-two.vercel.app
```

- OpenAI 기능 사용 시 필요하며, 현재 서버 실행 확인에는 키가 없어도 됩니다.
- 모델을 바꾸려면 `OPENAI_MODEL=사용할_모델_ID`를 추가합니다.
- `CORS_ORIGINS`는 브라우저가 허용할 프론트엔드 주소입니다. 쉼표로 여러 개를 적습니다. 기본값은 개발 서버(`http://localhost:5173`, `http://127.0.0.1:5173`)와 실제 배포 주소(`https://www.quackquack-e.duckdns.org`, `https://b7-1-two.vercel.app`)입니다.
- `.env`는 커밋하지 않습니다.

## 5. 서버 실행

```bash
uv run fastapi dev
```

| 확인 | 주소 / 방법 |
| --- | --- |
| 서버·DB 정상 여부 | http://127.0.0.1:8000/health → `{"status":"ok"}` |
| API 문서와 요청 실행 | http://127.0.0.1:8000/docs → API 선택 → Try it out → Execute |
| API 문서 읽기 (ReDoc) | http://127.0.0.1:8000/redoc → API별 요청·응답 구조를 읽기 좋은 형태로 확인 |
| 서버 종료 | 터미널에서 `Ctrl+C` |

SQLite는 별도 설치 없이 `app.db` 파일을 사용합니다.

## AI 채팅 MVP

- 채팅방 생성·목록·상세 조회와 `POST /api/v1/chats/{chat_id}/messages`를 제공합니다.
- 질문 전송 본문은 `{"question": "질문 내용"}`이며, 성공하면 저장된 질문·답변을 `201` 일반 JSON으로 반환합니다. 최근 완료 대화 5개를 다음 질문의 문맥에 사용합니다.
- `OPENAI_API_KEY`와 사용할 `OPENAI_MODEL`을 설정합니다. `AI_TIMEOUT_SECONDS`의 기본값은 30초이며 자동 재시도하지 않습니다.
- 실제 사용자 인증은 아직 미연결이므로 채팅 API는 현재 `401`을 반환합니다. 대화 흐름은 테스트에서 인증·AI 의존성을 교체하여 검증합니다.

## 자주 쓰는 uv 명령어

| 명령어 | 용도 |
| --- | --- |
| `uv sync --locked` | 클론·pull 후 패키지 설치 |
| `uv run fastapi dev` | 개발 서버 실행 |
| `uv add 패키지명` | 패키지 추가 |
| `uv add --dev 패키지명` | 개발용 패키지 추가 |
| `uv remove 패키지명` | 패키지 제거 |

패키지를 변경했다면 `pyproject.toml`과 `uv.lock`을 함께 커밋합니다.
