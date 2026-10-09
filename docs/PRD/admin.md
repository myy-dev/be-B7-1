# 관리자 파트

관리자 화면에서 쓰는 조회 기능이다. 회원 정보, 대화 기록, 시스템 로그를 관리자가 본다.

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/v1/admin/users` | 회원 목록 |
| GET | `/api/v1/admin/users/{id}` | 회원 상세 |
| PATCH | `/api/v1/admin/users/{id}/role` | 역할 변경 (`{"role": "admin"|"user"}`) |
| GET | `/api/v1/admin/logs` | 대화 기록 |
| GET | `/api/v1/admin/sessions` | 세션 목록 |
| GET | `/api/v1/admin/sessions/{chat_id}` | 세션별 대화 (chat_id=uuid) |
| GET | `/api/v1/admin/system-logs` | 시스템 이벤트 로그 |

`items`, `total`, `page`, `size` 형태로 돌려준다. 오류는 프론트가 한 가지 모양으로 처리하도록 `{"error": {"code", "message", "request_id"}}`로 통일한다(request_id는 현재 요청 식별자).

대화 기록·세션은 채팅 파트가 정한 식별자·기록 스키마를 따른다. 세션은 `chat_id`(uuid), 기록은 `request_id`(uuid)·`chat_id`·`question`·`answer`·`status`(pending/completed/failed)·`error_code`·`created_at`·`finished_at`을 쓴다.

## 파일

```
app/api/v1/admin.py              라우터
app/api/v1/admin_deps.py         의존성(인증 자리, 저장소 연결)
app/services/admin_service.py    조회 로직
app/schemas/admin.py             응답 형식
app/repositories/admin_repositories.py  저장소 인터페이스
app/repositories/admin_db.py             실제 DB 조회·역할 변경
app/repositories/admin_system_log.py    시스템 로그 파일 조회
scripts/seed_admin.py            초기 관리자 시드 (서버 안 1회 실행)
```

## 현재 상태

| 기능 | 상태 |
| --- | --- |
| 관리자 라우터·서비스·응답 형식 | 구현 |
| 시스템 로그 조회 | 구현 (이벤트·레벨·기간 필터, 최신순) |
| 회원 조회 | 구현 (`users` 실제 조회) |
| 역할 변경 | 구현 (`PATCH /admin/users/{id}/role`, 본인 강등 403) |
| 초기 관리자 시드 | 구현 (`scripts/seed_admin.py`, 멱등) |
| 대화 기록·세션 조회 | 구현 (`chats`·`chat_logs` 실제 조회) |
| 관리자 인증 | JWT+DB role 실보호 (`require_admin`, 로그아웃 폐기 토큰 거절) |
| 오류 응답 | 구현 (`code`·`message`·`request_id`) |

- 회원·대화 기록·세션은 `admin_db.py`에서 실제 DB(`users`·`chats`·`chat_logs`)를 읽는다. 세션 `title`은 DB에 컬럼이 없어 첫 질문으로 채운다.

- 시스템 로그는 백엔드 각자 JSONL 파일로 남기고, 조회는 여기서 맡는다. `event`, `level`, `start`, `end`로 걸러 최신순으로 준다. 형식은 조회를 맡은 어드민이 제시했고 [system-logs.md](system-logs.md)에 있다.

## 초기 관리자 만들기

서버 안에서 1회 실행한다. 로컬에서 돌리면 로컬 DB에만 생기므로 운영 DB에는 닿지 않는다.

### CLI로 실행

```bash
railway ssh -- SEED_ADMIN_PASSWORD='초기비번' python scripts/seed_admin.py --username admin
```

### 대시보드로 실행 (CLI 없이)

서비스 → Shell 탭을 열고 같은 명령을 입력한다. `SEED_ADMIN_PASSWORD`를 Variables에 미리
등록해 두면 비밀번호 입력 없이 실행된다.

```bash
python scripts/seed_admin.py --username admin
```

실행 후 Variables에서 `SEED_ADMIN_PASSWORD`를 삭제한다. 이미 admin이 있으면 종료되므로
다시 실행해도 안전하다(멱등).

## 환경 변수

`SYSTEM_LOG_PATH` — 시스템 로그 파일 경로. 공용 `Settings.system_log_path`로 관리한다(기본 `logs/system.jsonl`).