"""Per-mod shared cache and bounded background task system."""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class SharedCache:
    """Thread-safe namespaced cache shared by every editor for one open mod."""

    def __init__(self):
        self._values: dict[tuple[str, object], object] = {}
        self._lock = threading.RLock()

    def get(self, namespace: str, key: object, loader: Callable[[], T]) -> T:
        cache_key = (namespace, key)
        with self._lock:
            if cache_key in self._values:
                return self._values[cache_key]  # type: ignore[return-value]
        value = loader()
        with self._lock:
            existing = self._values.setdefault(cache_key, value)
        return existing  # type: ignore[return-value]

    def invalidate(self, namespace: str, key: object | None = None) -> None:
        with self._lock:
            if key is not None:
                self._values.pop((namespace, key), None)
                return
            for cache_key in [k for k in self._values if k[0] == namespace]:
                self._values.pop(cache_key, None)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


@dataclass
class TaskContext:
    cancel_event: threading.Event
    _progress: Callable[[float, str], None]

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def report(self, progress: float, message: str = "") -> None:
        self._progress(max(0.0, min(1.0, float(progress))), message)


@dataclass
class TaskInfo(Generic[T]):
    id: str
    name: str
    future: Future[T]
    cancel_event: threading.Event
    created_at: float = field(default_factory=time.time)
    progress: float = 0.0
    message: str = ""
    completed_at: float | None = None

    def cancel(self) -> None:
        self.cancel_event.set()
        self.future.cancel()


class TaskManager:
    """Bounded executor with cancellation, progress and Tk-safe delivery."""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="anka-task")
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.RLock()
        self._closed = False

    def submit(self, name: str, work: Callable[[TaskContext], T]) -> TaskInfo[T]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Task manager is closed")
        task_id = uuid.uuid4().hex
        cancel_event = threading.Event()

        def progress(value: float, message: str) -> None:
            with self._lock:
                info = self._tasks.get(task_id)
                if info is not None:
                    info.progress, info.message = value, message

        future = self._executor.submit(
            work, TaskContext(cancel_event, progress))
        info = TaskInfo(task_id, name, future, cancel_event)
        with self._lock:
            self._tasks[task_id] = info
        future.add_done_callback(lambda _f: self._forget_later(task_id))
        # A tiny task can finish before it is inserted into `_tasks`, in which
        # case the callback above observed nothing.
        if future.done():
            self._forget_later(task_id)
        return info

    def submit_tk(self, widget, name: str, work: Callable[[], T],
                  done: Callable[[T], None],
                  failed: Callable[[Exception], None] | None = None) -> TaskInfo[T]:
        info = self.submit(name, lambda _ctx: work())

        def poll() -> None:
            try:
                if not widget.winfo_exists():
                    info.cancel()
                    return
            except Exception:
                info.cancel()
                return
            if not info.future.done():
                widget.after(25, poll)
                return
            if info.future.cancelled() or info.cancel_event.is_set():
                return
            try:
                done(info.future.result())
            except Exception as exc:  # noqa: BLE001
                if failed is not None:
                    failed(exc)

        widget.after(25, poll)
        return info

    def snapshot(self) -> list[TaskInfo]:
        with self._lock:
            cutoff = time.time() - 2.0
            for task_id in [
                task_id for task_id, info in self._tasks.items()
                if info.completed_at is not None and info.completed_at < cutoff
            ]:
                self._tasks.pop(task_id, None)
            return list(self._tasks.values())

    def cancel_all(self) -> None:
        for task in self.snapshot():
            task.cancel()

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.cancel_all()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _forget_later(self, task_id: str) -> None:
        # Keep completed tasks briefly enough for a UI status panel to observe
        # completion, then discard them when the next snapshot is requested.
        with self._lock:
            info = self._tasks.get(task_id)
            if info is not None:
                info.progress = 1.0
                info.completed_at = time.time()


@dataclass
class ModRuntime:
    cache: SharedCache = field(default_factory=SharedCache)
    tasks: TaskManager = field(default_factory=TaskManager)
