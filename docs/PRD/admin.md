# 관리자 기능

관리자는 회원·세션·대화 기록·시스템 로그를 조회하고 회원 역할을 변경합니다.

## API와 접근 제어

경로·필터·페이지 형식·응답 필드·오류는 [Swagger](https://be-b7-1-development.up.railway.app/docs)의 `admin` 항목에서 확인합니다. JWT 인증 후 DB 역할이 `admin`인지 검사하며 로그아웃으로 폐기된 토큰도 거절합니다.

- 회원 목록·상세에 `role`을 반환합니다. 회원·대화·세션은 실제 `users`·`chats`·`chat_logs`를 조회합니다.
- 세션 `title`은 별도 DB 컬럼 없이 첫 질문으로 구성합니다. 저장 구조는 [DB](../DATABASE.md), 응답 필드는 Swagger에서 확인합니다.
- 역할은 `admin`·`user`만 허용합니다. 본인 강등은 `403 CANNOT_DEMOTE_SELF`, 잘못된 역할은 `422 INVALID_ROLE`, 없는 회원은 `404 USER_NOT_FOUND`입니다.
- 시스템 로그는 JSONL 파일에서 이벤트·레벨·기간으로 필터링해 최신순으로 조회합니다. [로그 계약](system-logs.md)을 따릅니다.

## 구현 파일

| 파일 | 역할 |
| --- | --- |
| `app/api/v1/endpoints/admin.py` | 라우터 |
| `app/api/v1/admin_deps.py` | 인증·저장소 의존성 연결 |
| `app/services/admin_service.py` | 관리자 처리 로직 |
| `app/schemas/admin.py` | 요청·응답 형식 |
| `app/repositories/admin_repositories.py` | 저장소 인터페이스 |
| `app/repositories/admin_db.py` | 실제 DB 조회·역할 변경 |
| `app/repositories/admin_system_log.py` | 시스템 로그 파일 조회 |
| `scripts/seed_admin.py` | 초기 관리자 생성 |

배포 후 권한·조회 동작은 [운영 검증](../OPERATIONS.md#운영-검증)으로 확인합니다.

## 초기 관리자와 설정

배포 서비스 안에서 같은 DB를 사용하는 시드 스크립트를 실행합니다. 이미 관리자 역할의 회원이 있으면 추가 생성 없이 종료합니다. 로컬 실행은 운영 DB에 영향을 주지 않습니다. 접속·비밀번호 입력·실행·확인은 [초기 관리자 생성](../OPERATIONS.md#초기-관리자-생성)을 따릅니다.

`SYSTEM_LOG_PATH`는 공용 `Settings.system_log_path`로 관리합니다. 기본값과 Railway 볼륨 경로는 [운영 환경 변수](../OPERATIONS.md#환경-변수)에 있습니다.
