from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping
from itertools import islice
from typing import Any

SUPPORTED_TYPES = frozenset(("文本", "图片", "动画表情", "文件/链接/卡片", "引用", "引用消息"))
READ_LIMIT = 64


class BatchStopped(RuntimeError):
    pass


class BatchTruncated(RuntimeError):
    def __init__(self, sequence: int, limit: int = READ_LIMIT):
        self.sequence = sequence
        self.limit = limit
        super().__init__(f"Cannot paginate a full page sharing sort_seq={sequence} with limit={limit}")


def _sequence(row: Mapping[str, Any]) -> int:
    try:
        value = int(row.get("sort_seq") or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid message sort_seq") from exc
    if value < 0:
        raise ValueError("Invalid message sort_seq")
    return value


def _number(value: Any) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _local_id(value: Any) -> tuple[int, Any]:
    text = str(value or "")
    try:
        return 0, int(text)
    except (TypeError, ValueError, OverflowError):
        return 1, text


def row_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return _sequence(row), _number(row.get("create_time")), _local_id(row.get("local_id"))


def row_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    prefix = str(row.get("username") or ""), str(row.get("shard") or "")
    local_id = str(row.get("local_id") or "")
    if local_id:
        return prefix + ("local", local_id)
    server_id = str(row.get("server_id") or row.get("msg_svr_id") or "")
    if server_id:
        return prefix + ("server", server_id)
    return prefix + (
        "row", _sequence(row), str(row.get("create_time") or ""),
        str(row.get("sender_username") or ""), str(row.get("type") or ""),
        str(row.get("content") or ""),
    )


def _stopped(stop: Any) -> bool:
    if stop is None:
        return False
    return bool(stop() if callable(stop) else stop.is_set())


def collect_batch(
    first: Mapping[str, Any],
    read_after: Callable[[int, int], Iterable[Mapping[str, Any]]],
    *,
    stop: Any = None,
    sleep: Callable[[float], Any] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    is_allowed: Callable[[Mapping[str, Any]], bool] | None = None,
    is_group: bool | None = None,
    quiet_seconds: float | None = None,
    max_seconds: float | None = None,
    max_rows: int = 30,
    poll_seconds: float = 0.25,
) -> list[Mapping[str, Any]]:
    if not isinstance(first, Mapping):
        raise TypeError("first must be a message mapping")
    chat = str(first.get("username") or "")
    if not chat:
        raise ValueError("first must have a username")
    group = chat.endswith("@chatroom") if is_group is None else bool(is_group)
    quiet = float((10.0 if group else 8.0) if quiet_seconds is None else quiet_seconds)
    budget = float((45.0 if group else 30.0) if max_seconds is None else max_seconds)
    poll = float(poll_seconds)
    if not all(math.isfinite(x) and x >= 0 for x in (quiet, budget)):
        raise ValueError("quiet_seconds and max_seconds must be finite and nonnegative")
    if not math.isfinite(poll) or poll <= 0:
        raise ValueError("poll_seconds must be finite and positive")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= 30:
        raise ValueError("max_rows must be an integer from 1 to 30")

    def check_stop() -> None:
        if _stopped(stop):
            raise BatchStopped("Batch collection stopped before acknowledgement")

    def include(row: Mapping[str, Any]) -> bool:
        kind = row.get("type")
        return (
            str(row.get("username") or "") == chat
            and isinstance(kind, str)
            and kind in SUPPORTED_TYPES
            and (is_allowed is None or bool(is_allowed(row)))
        )

    def finish() -> list[Mapping[str, Any]]:
        check_stop()
        return sorted(result, key=row_sort_key)

    check_stop()
    started = monotonic()
    last_new = started
    scan_seq = first_seq = _sequence(first)
    seen = {row_identity(first)}
    result = [first] if include(first) else []
    check_stop()
    if len(result) >= max_rows:
        return finish()

    while True:
        check_stop()
        page = list(islice(read_after(scan_seq - 1, READ_LIMIT), READ_LIMIT + 1))
        check_stop()
        if len(page) > READ_LIMIT:
            raise ValueError(f"read_after returned more than {READ_LIMIT} rows")
        if any(not isinstance(row, Mapping) for row in page):
            raise TypeError("read_after must return message mappings")
        ordered = sorted(page, key=row_sort_key)
        progressed = False
        for row in ordered:
            check_stop()
            sequence = _sequence(row)
            if sequence < first_seq:
                continue
            identity = row_identity(row)
            if identity in seen:
                continue
            seen.add(identity)
            scan_seq = max(scan_seq, sequence)
            progressed = True
            if include(row):
                result.append(row)
                last_new = monotonic()
                if len(result) >= max_rows:
                    return finish()

        if len(ordered) == READ_LIMIT and _sequence(ordered[0]) == _sequence(ordered[-1]):
            raise BatchTruncated(_sequence(ordered[-1]))
        now = monotonic()
        if now >= started + budget or now >= last_new + quiet:
            return finish()
        if len(ordered) == READ_LIMIT and progressed:
            continue
        delay = min(poll, started + budget - now, last_new + quiet - now)
        check_stop()
        sleep(max(0.0, delay))
        check_stop()
