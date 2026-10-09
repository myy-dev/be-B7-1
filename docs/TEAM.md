# 팀 작업과 협업 기록

아래는 현재 브랜치에 포함된 Git 기록에서 확인한 작업 요약입니다. 작성자 계정은 실명이나 공식 담당 배정을 의미하지 않습니다. 공식 팀원 이름·담당 범위는 팀 확인 후 보완합니다.

## 작성자별 작업 요약

| Git 작성자 | 확인한 작업 | 커밋 증빙 |
| --- | --- | --- |
| `andy1398` | 회원가입, 비밀번호 검증, 로그인·JWT, 토큰 폐기 로그아웃 | [e7c6f4c](https://github.com/myy-dev/be-B7-1/commit/e7c6f4c), [193d5ff](https://github.com/myy-dev/be-B7-1/commit/193d5ff), [a40a359](https://github.com/myy-dev/be-B7-1/commit/a40a359), [2c9bcf5](https://github.com/myy-dev/be-B7-1/commit/2c9bcf5) |
| `ted111712` | AI·채팅 모델·저장·호출·테스트, 논리 삭제, DB URL 설정 | [2a5cb56](https://github.com/myy-dev/be-B7-1/commit/2a5cb56), [09bf723](https://github.com/myy-dev/be-B7-1/commit/09bf723), [6a3d378](https://github.com/myy-dev/be-B7-1/commit/6a3d378), [036fa35](https://github.com/myy-dev/be-B7-1/commit/036fa35), [0f434ab](https://github.com/myy-dev/be-B7-1/commit/0f434ab) |
| `servercat` | 관리자 조회 API·실제 DB 연결, 관리자 JWT·권한 검사, 오류·CORS 정리 | [27788b8](https://github.com/myy-dev/be-B7-1/commit/27788b8), [eea3522](https://github.com/myy-dev/be-B7-1/commit/eea3522), [ee88b28](https://github.com/myy-dev/be-B7-1/commit/ee88b28) |
| `Servercat`, `Hidsquid97`, `Codyssey_4Week` | Git 병합 커밋에서 PR 통합 확인 | 아래 PR 표 참고 |

대소문자가 다른 작성자 이름은 Git에 기록된 그대로 표기했습니다. 동일인 여부는 확인하지 않았습니다. 프론트엔드 역할은 이 저장소 기록만으로 판단하지 않습니다.

## PR 증빙

| PR | 병합 기록에서 확인한 브랜치·내용 |
| --- | --- |
| [#2](https://github.com/myy-dev/be-B7-1/pull/2) | `feat/admin-repositories` |
| [#3](https://github.com/myy-dev/be-B7-1/pull/3) | `feat/signup` |
| [#4](https://github.com/myy-dev/be-B7-1/pull/4), [#7](https://github.com/myy-dev/be-B7-1/pull/7) | `feat/ai` |
| [#5](https://github.com/myy-dev/be-B7-1/pull/5) | `feat/login` |
| [#8](https://github.com/myy-dev/be-B7-1/pull/8) | `feat/admin-db` |
| [#9](https://github.com/myy-dev/be-B7-1/pull/9) | `feat/logout` |
| [#10](https://github.com/myy-dev/be-B7-1/pull/10) | `refactor/code-cleanup` |

PR 번호와 브랜치는 로컬 병합 커밋 메시지 기준입니다. 온라인 리뷰·승인 내역은 별도 확인이 필요합니다.

## 브랜치·커밋 운영 제안

기록에는 `main`과 기능별 `feat/...` 브랜치를 PR로 병합한 흐름이 있습니다. 다음은 이를 바탕으로 한 운영 제안이며, 브랜치 보호·필수 승인 설정이 적용되어 있다는 의미는 아닙니다.

1. 최신 `main`에서 기능별 `feat/<기능>`, 수정 `fix/<내용>`, 문서 `docs/<내용>` 브랜치를 만듭니다.
2. 변경 범위를 작게 나누고 `feat:`, `fix:`, `docs:`, `refactor:`, `test:` 등의 커밋 메시지로 목적을 기록합니다.
3. PR에 변경 이유, API·DB 영향, 검증 명령과 결과를 작성하고 관련 커밋·이슈를 연결합니다.
4. 리뷰 후 `main`에 병합합니다. DB·API 계약 변경은 관련 문서와 함께 갱신합니다.

이번 문서 작업은 로컬 `main`에서 만든 `docs/readme` 브랜치입니다. 아직 PR·커밋 증빙은 생성되지 않았습니다.

```bash
git log main --format='%h %an %s'
git log main --merges --oneline
```
