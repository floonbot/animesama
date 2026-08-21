import contextlib
import contextvars
from collections.abc import Iterator

_task_id: contextvars.ContextVar[str] = contextvars.ContextVar("task_id", default="")


def get_task_id() -> str:
    return _task_id.get()


def set_task_id(value: str) -> contextvars.Token[str]:
    return _task_id.set(value or "")


def reset_task_id(token: contextvars.Token[str]) -> None:
    _task_id.reset(token)


@contextlib.contextmanager
def task_context(value: str) -> Iterator[None]:
    token = _task_id.set(value or "")
    try:
        yield
    finally:
        _task_id.reset(token)
