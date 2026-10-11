from typing import Protocol


class AIClient(Protocol):
    """AI 답변 생성과 자원 정리의 공통 계약을 정의한다."""

    async def generate_answer(
        self, question: str, history: list[tuple[str, str]]
    ) -> str:
        """대화 문맥과 현재 질문으로 완성된 답변을 생성한다.

        Args:
            question: 현재 사용자의 질문.
            history: 시간순으로 정렬한 이전 질문·답변 쌍.

        Returns:
            완성된 텍스트 답변.

        Raises:
            APIError: 타임아웃, 서버 설정 오류 또는 유효한 답변 생성 실패.
        """
        ...

    async def close(self) -> None:
        """클라이언트가 사용하는 비동기 자원을 정리한다."""
        ...
