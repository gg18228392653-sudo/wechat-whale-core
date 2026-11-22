import copy
import itertools
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechat_whale_core import BatchStopped, BatchTruncated, collect_batch, row_identity, row_sort_key

GROUP = "fixture@chatroom"
DIRECT = "fixture-direct"


def message(seq, *, chat=GROUP, local_id=None, sender="actor-a", kind="\u6587\u672c", **extra):
    return {
        "username": chat,
        "sort_seq": seq,
        "local_id": seq if local_id is None else local_id,
        "sender_username": sender,
        "type": kind,
        "create_time": 0,
        "content": f"fixture-{seq}",
        **extra,
    }


class Reader:
    def __init__(self, rows=()):
        self.rows = [(0, row) for row in rows]
        self.now = 0.0
        self.calls = []
        self.sleeps = []
        self.on_sleep = None

    def add(self, at, row):
        self.rows.append((at, row))

    def read_after(self, since, limit):
        self.calls.append((since, limit))
        rows = [row for at, row in self.rows if at <= self.now and int(row["sort_seq"]) > since]
        return reversed(sorted(rows, key=row_sort_key)[:limit])

    def sleep(self, delay):
        if delay <= 0:
            raise AssertionError("collector busy-polls")
        self.sleeps.append(delay)
        self.now += delay
        if self.on_sleep:
            self.on_sleep()

    def collect(self, first, **kwargs):
        return collect_batch(first, self.read_after, sleep=self.sleep, monotonic=lambda: self.now, **kwargs)


class ConversationBatchTests(unittest.TestCase):
    def test_mixed_media_quotes_and_senders_preserve_original_rows(self):
        rows = [message(1), message(2, kind="\u56fe\u7247", sender="actor-b"),
                message(3, kind="\u52a8\u753b\u8868\u60c5", sender="actor-c"),
                message(4, kind="\u6587\u4ef6/\u94fe\u63a5/\u5361\u7247", quote={"id": 3}),
                message(5, kind="\u5f15\u7528\u6d88\u606f", is_self=True)]
        before = copy.deepcopy(rows)
        reader = Reader(rows)
        result = reader.collect(rows[0])
        self.assertEqual(rows, before)
        self.assertEqual(result, rows)
        self.assertTrue(all(a is b for a, b in zip(result, rows)))
        self.assertEqual(reader.now, 10.0)

    def test_group_quiet_window_resets_on_each_new_row(self):
        first = message(1)
        reader = Reader([first])
        reader.add(7, message(2))
        reader.add(15, message(3))
        self.assertEqual([row["sort_seq"] for row in reader.collect(first)], [1, 2, 3])
        self.assertEqual(reader.now, 25.0)

    def test_continuous_traffic_hits_group_or_direct_deadline(self):
        for chat, deadline in ((GROUP, 45.0), (DIRECT, 30.0)):
            with self.subTest(chat=chat):
                first = message(1, chat=chat)
                reader = Reader([first])
                for seq in range(2, 13):
                    reader.add((seq - 1) * 6, message(seq, chat=chat))
                result = reader.collect(first)
                self.assertEqual(reader.now, deadline)
                self.assertEqual(len(result), 1 + int(deadline // 6))

    def test_direct_filter_and_explicit_group_override(self):
        first = message(1, chat=DIRECT)
        second = message(2, chat=DIRECT, sender="actor-b")
        for options, quiet in (({}, 8.0), ({"is_group": True}, 10.0)):
            with self.subTest(options=options):
                reader = Reader([first, second, message(3)])
                self.assertEqual(reader.collect(first, **options), [first, second])
                self.assertEqual(reader.now, quiet)

    def test_row_cap_leaves_next_rows_for_next_batch(self):
        rows = [message(seq) for seq in range(1, 81)]
        first = Reader(rows)
        self.assertEqual(first.collect(rows[0]), rows[:30])
        self.assertEqual(first.calls, [(0, 64)])
        self.assertEqual(Reader(rows).collect(rows[30]), rows[30:60])

    def test_equal_sequence_late_rows_and_replays_using_numeric_id_order(self):
        first = message(9, local_id=11, create_time=1)
        earlier = message(9, local_id=2, create_time=1)
        later = message(9, local_id=1, create_time=2)
        reader = Reader([first, copy.deepcopy(first)])
        reader.add(3, earlier)
        reader.add(4, later)
        self.assertEqual(reader.collect(first), [earlier, first, later])
        self.assertTrue(all(call == (8, 64) for call in reader.calls))
        self.assertEqual(reader.now, 14.0)

    def test_identity_falls_back_to_server_then_message_fields(self):
        first = message(1, local_id="", msg_svr_id="server-1")
        replay = message(1, local_id="", server_id="server-1")
        self.assertEqual(row_identity(first), row_identity(replay))
        self.assertNotEqual(row_identity(first), row_identity({**replay, "shard": "second"}))
        fallback = message(1, local_id="")
        self.assertNotEqual(row_identity(fallback), row_identity({**fallback, "content": "other"}))

    def test_filtered_rows_paginate_and_do_not_reset_quiet_window(self):
        first = message(1)
        last = message(67)
        rows = [first, *[message(seq, kind="other") for seq in range(2, 66)],
                message(66, sender="blocked"), last]
        reader = Reader(rows)
        reader.add(9, message(68, sender="blocked"))
        reader.add(9.5, message(69, kind=[]))
        self.assertEqual(reader.collect(first, is_allowed=lambda row: row["sender_username"] != "blocked"), [first, last])
        self.assertEqual(reader.calls[:2], [(0, 64), (63, 64)])
        self.assertEqual(reader.now, 10.0)

    def test_duplicate_only_pages_sleep(self):
        first = message(1)
        reader = Reader([first])
        self.assertEqual(reader.collect(first), [first])
        self.assertEqual(len(reader.sleeps), 40)
        self.assertEqual(len(reader.calls), 41)

    def test_unpageable_shared_sequence_reports_truncation(self):
        first = message(4, local_id=1)
        reader = Reader([first, *[message(4, local_id=i, kind="other") for i in range(2, 66)]])
        with self.assertRaises(BatchTruncated) as caught:
            reader.collect(first)
        self.assertEqual((caught.exception.sequence, caught.exception.limit), (4, 64))
        self.assertEqual(reader.sleeps, [])

    def test_stop_before_read_or_during_sleep(self):
        first = message(1)
        reader = Reader([first])
        event = threading.Event()
        event.set()
        with self.assertRaises(BatchStopped):
            reader.collect(first, stop=event)
        self.assertEqual(reader.calls, [])
        event.clear()
        reader.on_sleep = event.set
        with self.assertRaises(BatchStopped):
            reader.collect(first, stop=event.is_set)
        self.assertEqual(len(reader.calls), 1)

    def test_stop_during_read_or_filter(self):
        event = threading.Event()

        def read_after(since, limit):
            event.set()
            return [message(2)]

        def is_allowed(row):
            event.set()
            return True

        with self.assertRaises(BatchStopped):
            collect_batch(message(1), read_after, stop=event)
        event.clear()
        with self.assertRaises(BatchStopped):
            collect_batch(message(1), read_after, stop=event, is_allowed=is_allowed, max_rows=1)

    def test_reader_failure_propagates(self):
        def unavailable(since, limit):
            raise RuntimeError("fixture reader unavailable")

        with self.assertRaisesRegex(RuntimeError, "fixture reader unavailable"):
            collect_batch(message(1), unavailable)

    def test_timing_and_reader_limits(self):
        first = message(1)
        for options in ({"max_rows": 31}, {"max_rows": True}, {"max_seconds": -1},
                        {"quiet_seconds": float("nan")}, {"poll_seconds": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                Reader([first]).collect(first, **options)
        with self.assertRaisesRegex(ValueError, "more than 64"):
            collect_batch(first, lambda since, limit: itertools.repeat(first))
        with self.assertRaisesRegex(TypeError, "message mappings"):
            collect_batch(first, lambda since, limit: [None])


if __name__ == "__main__":
    unittest.main()
