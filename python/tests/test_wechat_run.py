import os
import shutil
import subprocess
import sys
import threading
import unittest
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechat_whale_core.conversation_batch import collect_batch
from wechat_whale_core.wechat_run import GroupLoop, arguments, core_call, session_lock


class FakeAdapter:
    chat_id = 'demo@chatroom'
    self_id = 'demo-bot'
    self_name = 'Demo Bot'

    def __init__(self):
        self.rows = []
        self.sent = []
        self.confirm = True
        self.reads = []

    def latest_sequence(self):
        return 20

    def add(self, seq, body, *, sender='demo-member', mentions=(), local_id=None, chat=None):
        self.rows.append({'username': chat or self.chat_id, 'sort_seq': seq,
                          'local_id': seq if local_id is None else local_id, 'type': '文本',
                          'sender_username': sender, 'content': body, 'mentions': list(mentions)})

    def read_after(self, since, limit):
        self.reads.append(since)
        return sorted((row for row in self.rows if row['sort_seq'] > since),
                      key=lambda row: row['sort_seq'])[:limit]

    def project(self, row):
        return {'id': str(row['local_id']), 'senderId': row['sender_username'],
                'mentions': row['mentions'], 'text': row['content'],
                'time': 1700000000 + row['sort_seq'], 'self': row['sender_username'] == self.self_id}

    def send_text(self, text):
        self.sent.append(text)
        return self.confirm


class GroupLoopTests(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which('node')
        self.assertIsNotNone(self.node, 'Node is required for the integration checks')
        self.adapter = FakeAdapter()
        self.prompts = []
        self.reports = []
        self.stop = threading.Event()

    def complete(self, prompt):
        self.prompts.append(prompt)
        return 'Demo reply'

    def loop(self, **options):
        return GroupLoop(self.adapter, partial(core_call, self.node), options.pop('complete', self.complete),
                         collector=partial(collect_batch, quiet_seconds=0), report=self.reports.append,
                         stop=self.stop, **options)

    def test_start_boundary_and_preview_of_a_complete_batch(self):
        loop = self.loop(owner_id='demo-member')
        self.adapter.add(20, 'old message', mentions=['demo-bot'])
        self.adapter.add(21, 'directed question', mentions=['demo-bot'])
        self.adapter.add(22, 'extra detail')
        self.assertTrue(loop.step())
        self.assertFalse(loop.step())
        self.assertEqual(len(self.prompts), 1)
        self.assertNotIn('old message', self.prompts[0])
        self.assertIn('extra detail', self.prompts[0])
        self.assertIn('"speakerIsOwner":true', self.prompts[0])
        self.assertNotIn('demo-member', self.prompts[0])
        self.assertTrue(self.reports[0].endswith('Demo reply'))
        self.assertEqual(self.adapter.sent, [])

    def test_own_messages_and_messages_for_others_do_not_call_model(self):
        loop = self.loop(send=True)
        self.adapter.add(21, 'own message', sender='demo-bot', mentions=['demo-bot'])
        self.adapter.add(22, 'for another member', mentions=['demo-other'])
        self.assertTrue(loop.step())
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.adapter.sent, [])

    def test_send_once_only_for_confirmed_target(self):
        loop = self.loop(send=True)
        self.adapter.add(21, 'ping', mentions=['demo-bot'])
        self.assertTrue(loop.step())
        self.assertFalse(loop.step())
        self.assertEqual(self.adapter.sent, ['Demo reply'])

    def test_drops_reply_when_new_message_arrives(self):
        def with_new_message(prompt):
            self.adapter.add(22, 'new message')
            return self.complete(prompt)

        loop = self.loop(send=True, complete=with_new_message)
        self.adapter.add(21, 'ping', mentions=['demo-bot'])
        self.assertTrue(loop.step())
        self.assertEqual(self.adapter.sent, [])

    def test_suppressed_reply_and_model_failure_never_send(self):
        for complete in (lambda prompt: '[不回]', self.failing_model):
            with self.subTest(complete=complete):
                self.adapter.rows.clear()
                loop = self.loop(send=True, complete=complete)
                self.adapter.add(21, 'ping', mentions=['demo-bot'])
                self.assertTrue(loop.step())
                self.assertEqual(self.adapter.sent, [])

    @staticmethod
    def failing_model(prompt):
        raise RuntimeError('mock transport failure')

    def test_uncertain_send_stops_without_retry(self):
        loop = self.loop(send=True)
        self.adapter.add(21, 'ping', mentions=['demo-bot'])
        self.adapter.confirm = False
        with self.assertRaises(RuntimeError):
            loop.step()
        self.assertTrue(self.stop.is_set())
        self.assertFalse(loop.step())
        self.assertEqual(self.adapter.sent, ['Demo reply'])

    def test_other_chat_stops_before_model(self):
        loop = self.loop(send=True)
        self.adapter.add(21, 'ping', mentions=['demo-bot'], chat='other@chatroom')
        with self.assertRaises(RuntimeError):
            loop.step()
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.adapter.sent, [])

    def test_modes(self):
        args = arguments(['--group', 'Demo'])
        self.assertFalse(args.send)
        self.assertFalse(args.check)
        self.assertFalse(args.check_send)
        self.assertTrue(arguments(['--group', 'Demo', '--check-send']).check_send)

    def test_help_is_utf8_with_legacy_terminal_encoding(self):
        python_root = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONIOENCODING': 'cp1252'}
        result = subprocess.run([sys.executable, '-B', '-m', 'wechat_whale_core.wechat_run', '--help'],
                                cwd=python_root, env=env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertIn('大肥鱼微信群聊', result.stdout.decode('utf-8'))
        self.assertIn(b'--check-send', result.stdout)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows named mutex')
    def test_instance_lock(self):
        with session_lock():
            with self.assertRaises(RuntimeError):
                with session_lock():
                    self.fail('second instance acquired the same lock')
        with session_lock():
            pass
