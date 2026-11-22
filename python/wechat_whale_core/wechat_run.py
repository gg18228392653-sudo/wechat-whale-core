from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
from getpass import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable

from .conversation_batch import SUPPORTED_TYPES, BatchStopped, collect_batch, row_identity, row_sort_key

READER_LIMIT = 64
POLL_SECONDS = 0.5
KEY_ENV = 'WHALE_API_KEY'
REQUEST_LIMIT = 512 * 1024


def checkout_root() -> Path:
    for root in (Path(__file__).resolve().parents[2], Path(sys.prefix).resolve().parent):
        if (root / 'src' / 'adapter-cli.mjs').is_file() and (root / 'scripts' / 'setup.py').is_file():
            return root
    raise RuntimeError('未找到项目源码；从完整仓库运行安装脚本后使用项目内的启动器')


def core_call(node: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if len(encoded) > REQUEST_LIMIT:
        raise RuntimeError('群聊请求超过大小限制')
    env = dict(os.environ)
    env.pop(KEY_ENV, None)
    env.pop('NODE_OPTIONS', None)
    root = checkout_root()
    try:
        result = subprocess.run(
            [node, str(root / 'src' / 'adapter-cli.mjs'), operation],
            input=encoded, capture_output=True, timeout=10, check=True, cwd=root, env=env,
        )
        value = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise RuntimeError('群聊核心执行失败') from exc
    if not isinstance(value, dict):
        raise RuntimeError('群聊核心返回了无效数据')
    return value


class GroupLoop:
    def __init__(self, adapter: Any, core: Callable, complete: Callable, *, send: bool = False,
                 owner_id: str = '', stop: threading.Event | None = None,
                 collector: Callable = collect_batch, report: Callable[[str], None] = print):
        self.adapter = adapter
        self.core = core
        self.complete = complete
        self.send = send
        self.owner_id = owner_id
        self.stop = stop if stop is not None else threading.Event()
        self.collector = collector
        self.report = report
        self.cursor = adapter.latest_sequence()
        self.initial_cursor = self.cursor
        self.cursor_ids: set[tuple] = set()
        self.history: deque[dict] = deque(maxlen=20)

    def _read(self, since: int, limit: int) -> list[dict]:
        rows = self.adapter.read_after(max(0, since), limit)
        if any(row.get('username') != self.adapter.chat_id for row in rows):
            raise RuntimeError('适配器返回了其他会话的消息，已停止')
        return rows

    def _unseen(self, row: dict) -> bool:
        seq = row_sort_key(row)[0]
        return seq > self.initial_cursor and (
            seq > self.cursor or seq == self.cursor and row_identity(row) not in self.cursor_ids
        )

    def _advance(self, rows: list[dict]) -> None:
        for row in rows:
            seq = row_sort_key(row)[0]
            if seq > self.cursor:
                self.cursor = seq
                self.cursor_ids.clear()
            if seq == self.cursor:
                self.cursor_ids.add(row_identity(row))

    def step(self) -> bool:
        page = self._read(max(self.initial_cursor, self.cursor - 1), READER_LIMIT)
        rows = sorted((row for row in page if self._unseen(row)), key=row_sort_key)
        if len(page) == READER_LIMIT and row_sort_key(page[-1])[0] <= self.cursor:
            raise RuntimeError('同一消息水位无法安全分页，已停止')
        if not rows or self.stop.is_set():
            return False

        for first in rows:
            try:
                projected = self.adapter.project(first)
            except ValueError:
                projected = None
            if projected and not projected.get('self') and first.get('type') in SUPPORTED_TYPES:
                break
            self._advance([first])
            if projected:
                self.history.append(projected)
        else:
            return True

        batch = self.collector(first, self._read, stop=self.stop, is_allowed=self._unseen)
        self._advance(batch)
        current = [item for row in batch if (item := self.adapter.project(row)) is not None]
        input_data = {'selfId': self.adapter.self_id, 'selfName': self.adapter.self_name,
                      'aliases': ['大肥鱼'], 'messages': current, 'historyRecords': list(self.history)}
        self.history.extend(current)
        if self.stop.is_set():
            return True
        decision = self.core('prepare', {'input': input_data, 'adapter': {'ownerAccountId': self.owner_id}})
        if decision.get('shouldReply') is not True:
            return True
        prompt = decision.get('prompt')
        if not isinstance(prompt, str) or not prompt:
            raise RuntimeError('群聊核心未返回有效提示')
        try:
            output = self.complete(prompt)
        except RuntimeError:
            self.report('模型请求失败，本批未发送')
            return True
        reply = self.core('reply', {'message': output}).get('reply')
        if not isinstance(reply, str) or not reply.strip() or self.stop.is_set():
            return True
        if not self.send:
            self.report(f'预览：{reply}')
            return True
        if any(self._unseen(row) for row in self._read(max(self.initial_cursor, self.cursor - 1), READER_LIMIT)):
            self.report('群里有新消息，本批旧回复不发送')
            return True
        if self.stop.is_set():
            return True
        if self.adapter.send_text(reply) is not True:
            self.report('发送未确认，已停止；本条不重发')
            self.stop.set()
            raise RuntimeError('微信发送未确认')
        self.report('已发送，微信本地记录已确认')
        return True

    def run(self) -> None:
        while not self.stop.is_set():
            if not self.step():
                self.stop.wait(POLL_SECONDS)


@contextmanager
def session_lock():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, r'Local\WeChatWhaleRunner')
    error = ctypes.get_last_error()
    if not handle:
        raise RuntimeError('无法建立微信运行实例锁')
    try:
        if error == 183:
            raise RuntimeError('大肥鱼已在当前 Windows 会话运行；先停止已有实例')
        yield
    finally:
        kernel.CloseHandle(handle)


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='wechat-whale', description='大肥鱼微信群聊')
    parser.add_argument('--group', required=True, help='精确的微信群名')
    parser.add_argument('--base-url', default=os.getenv('WHALE_BASE_URL', 'https://api.deepseek.com'))
    parser.add_argument('--model', default=os.getenv('WHALE_MODEL', 'deepseek-flash'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='仅检查微信和群，不请求模型或发送')
    mode.add_argument('--check-send', action='store_true', help='仅检查目标群的发送窗口，不请求模型或发送')
    mode.add_argument('--send', action='store_true', help='允许发送；默认仅在终端预览')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8', errors='backslashreplace')
    args = arguments(argv)
    try:
        if os.name != 'nt':
            raise RuntimeError('微信收发只支持 Windows，核心库可在其他平台运行')
        from .wechat_adapter import WeChatAdapter

        with session_lock():
            adapter = WeChatAdapter(args.group)
            if args.check or args.check_send:
                adapter.latest_sequence()
                if args.check_send:
                    adapter.check_send_ready()
                    print('目标群及发送输入框已校验。未发送消息。')
                else:
                    print('目标群唯一且可读。未发送消息。')
                return 0
            checkout_root()
            node = shutil.which('node')
            if not node:
                raise RuntimeError('需要 Node.js 20+')
            if args.send:
                adapter.check_send_ready()
            from .chat_model import complete_chat

            key = os.environ.get(KEY_ENV, '').strip()
            if not key and sys.stdin.isatty():
                key = getpass('模型 API 密钥（不回显）: ').strip()
            if not key:
                raise RuntimeError(f'请在本机终端设置 {KEY_ENV}，或在交互终端输入密钥')
            loop = GroupLoop(
                adapter, lambda operation, payload: core_call(node, operation, payload),
                lambda prompt: complete_chat(args.base_url, args.model, key, prompt),
                send=args.send, owner_id=os.getenv('WHALE_OWNER_ID', ''),
                report=lambda text: print(text, flush=True),
            )
            print('监听已启动：' + ('实际发送' if args.send else '预览，不发送'), flush=True)
            loop.run()
    except (KeyboardInterrupt, BatchStopped):
        print('已停止')
    except ImportError:
        print('启动失败：先运行 scripts/setup.py --wechat 安装微信依赖', file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'启动或运行失败：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
