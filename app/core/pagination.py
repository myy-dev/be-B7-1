"""페이지 응답 형식.

목록 API가 공통으로 쓰는 형태다. 잘라내기는 각 저장소가 맡고(파일 저장소는
파일을, mock은 전체 목록을), 여기서는 값 보정과 응답 조립만 한다. 즉 make_page는
items를 자르지 않으므로, 저장소가 이미 페이지 크기만큼 돌려준 것을 그대로 싣는다.
"""

from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


def clamp(page: int, size: int, max_size: int = 100) -> tuple[int, int]:
    return max(page, 1), max(min(size, max_size), 1)


def slice_page[T](rows: list[T], page: int, size: int) -> tuple[list[T], int]:
    """목록을 페이지 크기로 잘라 (자른 목록, 전체 수)로 돌려준다.

    자르기는 저장소가 맡으므로 mock·파일 저장소가 이 함수를 함께 쓴다.
    """
    page, size = clamp(page, size)
    begin = (page - 1) * size
    return rows[begin : begin + size], len(rows)


def make_page[T](items: list[T], total: int, page: int, size: int) -> Page[T]:
    page, size = clamp(page, size)
    return Page(items=items, total=total, page=page, size=size)
