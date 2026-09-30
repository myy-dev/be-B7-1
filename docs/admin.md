# 관리자 파트

관리자 화면에서 쓰는 조회 기능이다. 회원 정보, 대화 기록, 시스템 로그를 관리자가 본다.

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/admin/users` | 회원 목록 |
| GET | `/admin/users/{id}` | 회원 상세 |
| GET | `/admin/logs` | 대화 기록 |
| GET | `/admin/sessions` | 세션 목록 |
| GET | `/admin/sessions/{id}` | 세션별 대화 |
| GET | `/admin/system-logs` | 시스템 이벤트 로그 |

`items`, `total`, `page`, `size` 형태로 돌려준다. 오류는 `{"error": {"code", "message"}}`로 통일한다.

## 파일

```
app/api/v1/admin.py              라우터
app/api/v1/admin_deps.py         의존성(인증 자리, 저장소 연결)
app/services/admin_service.py    조회 로직
app/schemas/admin.py             응답 형식
app/repositories/admin_repositories.py  저장소 인터페이스
app/repositories/admin_mock.py          임시 데이터
app/repositories/admin_system_log.py    시스템 로그 파일 조회
tests/test_admin_api.py          테스트
```

## 현재 상태

| 기능 | 상태 |
| --- | --- |
| 관리자 라우터·서비스·응답 형식 | 구현 |
| 시스템 로그 조회 | 구현 (이벤트·레벨·기간 필터, 최신순) |
| 회원 조회 | 임시 데이터 (회원 스키마 대기) |
| 대화 기록·세션 조회 | 임시 데이터 (채팅 스키마 대기) |
| 관리자 인증 | 통과 (회원 담당 JWT 대기) |

- 회원, 대화 기록, 세션은 저장소 스키마가 정해지지 않아 `admin_mock.py`로 돌아간다. 스키마가 나오면 이 파일만 실제 조회로 바꾸면 되고, 서비스와 라우터는 그대로 둔다.
- 관리자 인증은 회원 담당이 JWT를 정하기 전까지 검사 없이 통과시킨다(`admin_deps.py`의 `require_admin`).
- 시스템 로그는 백엔드 각자 JSONL 파일로 남기고, 조회는 여기서 맡는다. `event`, `level`, `start`, `end`로 걸러 최신순으로 준다. 이벤트 이름과 필드가 팀에서 정해지면 `admin_system_log.py`에서 맞춘다.

## 환경 변수

`SYSTEM_LOG_PATH` — 시스템 로그 파일 경로. 안 넣으면 `logs/system.jsonl`.