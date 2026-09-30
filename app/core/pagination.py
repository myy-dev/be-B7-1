from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


def clamp(page: int, size: int, max_size: int = 100) -> tuple[int, int]:
    return max(page, 1), max(min(size, max_size), 1)


def make_page[T](items: list[T], total: int, page: int, size: int) -> Page[T]:
    page, size = clamp(page, size)
    return Page(items=items, total=total, page=page, size=size)
