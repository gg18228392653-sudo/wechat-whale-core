from __future__ import annotations

import io
import logging
import re
import sys
from collections.abc import Mapping
from contextlib import redirect_stderr
from importlib.metadata import version
from pathlib import PureWindowsPath
from xml.etree import ElementTree


_MEDIA = {"图片": "image", "动画表情": "sticker", "文件/链接/卡片": "file",
          "语音": "audio", "视频": "video"}
_VOCATIVE = re.compile(r"^大肥鱼(?:$|[，。！？、,:：!?])")
_ID = re.compile(r"[A-Za-z0-9_@.\-]{1,128}\Z")
_WINDOW_ERROR = "The exact standalone group window is unavailable."
_CONFIRM_LIMIT = 64


def _identifier(value) -> str:
    return value if isinstance(value, str) and _ID.fullmatch(value) else ""


def _sender(value) -> str:
    username = _identifier(value)
    return username if username and not username.isdecimal() and "@" not in username else ""


def _body(row: Mapping, sender: str) -> str:
    text = row.get("content")
    if not isinstance(text, str):
        return ""
    for separator in (":\n", ":\r\n"):
        prefix = sender + separator
        if sender and text.startswith(prefix):
            return text[len(prefix):]
    return text


def _quote_xml(text: str) -> tuple[str, dict]:
    if not text.startswith("<msg>") or len(text) > 65536 or "<!" in text or "<?" in text:
        return "", {}
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return "", {}
    apps = root.findall("appmsg")
    if root.tag != "msg" or len(apps) != 1 or apps[0].findtext("type") != "57":
        return "", {}
    app = apps[0]
    title, refs = app.findall("title"), app.findall("refermsg")
    if len(title) != 1 or len(title[0]) or len(refs) != 1:
        return "", {}
    body = refs[0].findall("content")
    quoted = (body[0].text or "").strip() if len(body) == 1 and not len(body[0]) else ""
    return (title[0].text or "").strip(), {"text": quoted} if quoted else {}


def _seq(row: Mapping) -> int:
    n = row.get("sort_seq")
    if type(n) is not int or n < 0:
        raise ValueError("Invalid message sequence.")
    return n


def _row_key(row: Mapping) -> tuple[str, int] | None:
    shard, local_id = row.get("shard"), row.get("local_id")
    if isinstance(shard, str) and shard and type(local_id) is int and local_id > 0:
        return shard, local_id
    return None


def _watermark(rows: list[dict], chat_id: str) -> tuple[int, set, bool]:
    if len(rows) > _CONFIRM_LIMIT or any(row.get("username", chat_id) != chat_id for row in rows):
        raise RuntimeError("Message query returned an unexpected row.")
    sequences = [_seq(row) for row in rows]
    cutoff = max(sequences, default=-1)
    seen = {_row_key(row) for row in rows}
    allow_equal = (None not in seen and (len(rows) < _CONFIRM_LIMIT or min(sequences) < cutoff))
    return cutoff, seen, allow_equal


def _confirmed(rows: list[dict], mark: tuple[int, set, bool], chat_id: str, self_id: str, text: str) -> bool:
    cutoff, seen, allow_equal = mark
    if len(rows) > _CONFIRM_LIMIT:
        return False
    for row in rows:
        key = _row_key(row)
        if (row.get("username", chat_id) == chat_id and key is not None and key not in seen
                and (_seq(row) > cutoff or (allow_equal and _seq(row) == cutoff))
                and row.get("type") == "文本" and row.get("sender_username") == self_id
                and _body(row, self_id) == text):
            return True
    return False


class WeChatAdapter:
    def __init__(self, group: str):
        if not isinstance(group, str) or not group.strip() or group != group.strip():
            raise ValueError("An exact group name is required.")
        self._group = group
        self._backend = _load_backend()
        db = self._backend.database()
        info = db.get_self_info()
        self._self_id = _sender(info.get("username"))
        if not self._self_id:
            raise RuntimeError("The logged-in account could not be verified.")
        name = info.get("nick_name")
        self._self_name = name if isinstance(name, str) else ""
        self._chat_id = self._resolve_group(db)

    @property
    def self_id(self) -> str:
        return self._self_id

    @property
    def self_name(self) -> str:
        return self._self_name

    @property
    def chat_id(self) -> str:
        return self._chat_id

    def _resolve_group(self, db) -> str:
        groups = [row for row in db.get_groups() if row.get("name") == self._group]
        if len(groups) != 1:
            raise RuntimeError("The group name did not match exactly one group.")
        chat_id = _identifier(groups[0].get("username"))
        if not chat_id.endswith("@chatroom") or chat_id == self._group:
            raise RuntimeError("The exact group name could not be verified.")
        contacts = db.search_contact(self._group)
        if len(contacts) >= 50 or any(
            row.get("username") != chat_id
            and self._group in (row.get("nick_name"), row.get("remark"), row.get("username"))
            for row in contacts
        ):
            raise RuntimeError("The group name could not be distinguished from contact results.")
        self._vocative_clear = not any(
            member.get("username") != self._self_id
            and "大肥鱼" in (member.get("nick_name"), member.get("remark"))
            for member in groups[0].get("members", ())
        )
        return chat_id

    def _checked_database(self):
        db = self._backend.database()
        if db.get_self_info().get("username") != self.self_id:
            raise RuntimeError("The logged-in account changed.")
        if self._resolve_group(db) != self.chat_id:
            raise RuntimeError("The configured group changed.")
        return db

    def latest_sequence(self) -> int:
        rows = self._checked_database().get_messages(self.chat_id, limit=1)
        if not rows:
            return 0
        if rows[0].get("username", self.chat_id) != self.chat_id:
            raise RuntimeError("Message query returned an unexpected chat.")
        return _seq(rows[0])

    def read_after(self, since_seq: int, limit: int) -> list[dict]:
        if type(since_seq) is not int or type(limit) is not int or limit < 1:
            raise ValueError("Invalid message cursor or limit.")
        rows = self._checked_database().get_new_messages(self.chat_id, since_seq=since_seq, limit=limit)
        if len(rows) > limit:
            raise RuntimeError("Message query exceeded its limit.")
        result = []
        for row in rows:
            if row.get("username", self.chat_id) != self.chat_id or _seq(row) <= since_seq:
                raise RuntimeError("Message query returned an unexpected row.")
            result.append({**row, "username": self.chat_id})
        return sorted(result, key=_seq)

    def check_send_ready(self) -> None:
        try:
            self._checked_database()
            self._backend.sender(self._group, self.chat_id, self.self_id)
        except Exception:
            raise RuntimeError(_WINDOW_ERROR) from None

    def send_text(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip() or text != text.strip():
            return False
        try:
            db = self._checked_database()
            mark = _watermark(db.get_messages(self.chat_id, limit=_CONFIRM_LIMIT), self.chat_id)
            gui = self._backend.sender(self._group, self.chat_id, self.self_id)
            response = gui.send_msg(text, who=self.chat_id, verify=True)
            if getattr(response, "is_success", None) is not True:
                return False
            rows = self._checked_database().get_messages(self.chat_id, limit=_CONFIRM_LIMIT)
            return _confirmed(rows, mark, self.chat_id, self.self_id, text)
        except Exception:
            return False
        return False

    def project(self, row: Mapping) -> dict | None:
        if not isinstance(row, Mapping) or row.get("username") != self.chat_id:
            return None
        sender = _sender(row.get("sender_username"))
        kind = row.get("type")
        if not sender or not isinstance(kind, str):
            return None
        server_id = row.get("server_id")
        key = _row_key(row)
        if (type(server_id) is int and server_id > 0) or (
            isinstance(server_id, str) and server_id.isascii() and server_id.isdecimal()
            and server_id.strip("0")
        ):
            message_id = f"server:{server_id}"
        elif key is not None:
            message_id = f"local:{key[0]}:{key[1]}"
        else:
            return None
        text = _body(row, sender).strip()
        quote = {}
        media = []
        plain = kind == "文本"
        if kind in ("引用", "引用消息", "文件/链接/卡片"):
            raw_quote = row.get("quote")
            if isinstance(raw_quote, Mapping):
                quote_sender = _sender(raw_quote.get("senderId"))
                quote_text = raw_quote.get("text")
                if quote_sender:
                    quote["senderId"] = quote_sender
                if isinstance(quote_text, str) and quote_text.strip():
                    quote["text"] = quote_text.strip()
            elif text.startswith("<"):
                text, quote = _quote_xml(text)
            if not quote and kind in _MEDIA:
                text, media = "", [{"kind": _MEDIA[kind]}]
        elif kind in _MEDIA:
            text, media = "", [{"kind": _MEDIA[kind]}]
        elif not plain:
            return None
        elif text.startswith("<") or text == "[文本]":
            return None
        if not (text or quote or media):
            return None
        raw_mentions = row.get("mentions")
        mentions = []
        if isinstance(raw_mentions, (list, tuple)) and len(raw_mentions) <= 64:
            mentions = list(dict.fromkeys(name for value in raw_mentions if (name := _sender(value))))
        own = sender == self.self_id
        if (not own and plain and raw_mentions is None and self._vocative_clear and "@" not in text
                and "＠" not in text and "<" not in text and _VOCATIVE.match(text)):
            mentions = [self.self_id]
        result = {"id": message_id, "senderId": sender, "text": text, "mentions": mentions, "self": own}
        stamp = row.get("create_time")
        if type(stamp) is int and stamp > 0:
            result["time"] = stamp
        if quote:
            result["quote"] = quote
        if media:
            result["media"] = media
        return result


def _load_backend():
    if sys.platform != "win32":
        raise RuntimeError("Live WeChat is only available on Windows.")
    try:
        if version("wechatauto-replica") != "1.2.9":
            raise RuntimeError
        from wechatauto import WeChatGUI, WxParam
        from wechatauto.ui.main import find_wechat_windows
        from wechatauto.uia_driver import WeChatUIA
        from wechatauto.utils.win32 import GetPathByHwnd
        from win32gui import GetForegroundWindow, IsWindowVisible
        from win32process import GetWindowThreadProcessId
    except Exception:
        raise RuntimeError("Live WeChat requires wechatauto-replica 1.2.9.") from None

    WxParam.ENABLE_FILE_LOGGER = False
    logging.getLogger("wechatauto").disabled = True

    class BoundUIA(WeChatUIA):
        def __init__(self, hwnd, group, target):
            self.group, self.target = group, target
            super().__init__(hwnd=hwnd)

        def matches(self, node) -> bool:
            return (node is not None and node.ClassName == "mmui::ChatSingleWindow"
                    and int(node.NativeWindowHandle) == self.hwnd and node.Name == self.group
                    and node.AutomationId == "ChatSingleWindow" + self.target
                    and IsWindowVisible(self.hwnd))

        def input_is_empty(self):
            root = self._find_main()
            if not self.matches(root):
                return False
            field = self._chat_input(root)
            return field is not None and self._read_edit_value(field) == ""

        def _paste_into(self, ctrl, text, clear=True):
            if (not self.matches(self._find_main()) or GetForegroundWindow() != self.hwnd
                    or self._read_edit_value(ctrl) != ""):
                raise RuntimeError("The group input is not empty or could not be verified.")
            return super()._paste_into(ctrl, text, clear=False)

        def ensure_window(self, wake=False, timeout=None):
            return (self.matches(self._find_main())
                    and super().ensure_window(wake=False, timeout=timeout)
                    and self.matches(self._win))

        def _paste_landed(self, ctrl, text):
            actual = self._read_edit_value(ctrl)
            if (actual != text or not self.matches(self._find_main())
                    or GetForegroundWindow() != self.hwnd):
                raise RuntimeError("The group input could not be verified.")
            return True, actual, 1.0

    class BoundGUI(WeChatGUI):
        def __init__(self, hwnd, group=None, target=None, account=None):
            self.target, self.account = target, account
            self.driver = BoundUIA(hwnd, group, target) if target else None
            super().__init__(hwnd=hwnd)

        def calibrate_layout(self, save=False):
            return False

        def _get_uia(self, refresh=False):
            if self.driver and self.driver.ensure_window():
                return self.driver
            return None

        def _window_kind(self, uia):
            return "chat" if self.target else super()._window_kind(uia)

        def _checked_send_db(self, who):
            if not self.target or who != self.target:
                raise RuntimeError(_WINDOW_ERROR)
            db = self._get_db()
            if db.get_self_info().get("username") != self.account:
                raise RuntimeError(_WINDOW_ERROR)
            return db

        def _send_watermark(self, who):
            db = self._checked_send_db(who)
            return _watermark(db.get_messages(who, limit=_CONFIRM_LIMIT), who)

        def _verify_sent(self, text, who, mode="exact", after=None):
            if mode != "exact" or after is None:
                return False
            db = self._checked_send_db(who)
            return _confirmed(db.get_messages(who, limit=_CONFIRM_LIMIT), after, who, self.account, text)

        def _get_db(self):
            try:
                with redirect_stderr(io.StringIO()):
                    return super()._get_db()
            except Exception:
                raise RuntimeError("The window account could not be verified.") from None

    def visible_windows(kind):
        for node in find_wechat_windows(f"mmui::{kind}"):
            hwnd = int(node.NativeWindowHandle)
            if node.ClassName == f"mmui::{kind}" and IsWindowVisible(hwnd):
                yield node, hwnd

    class Backend:
        def __init__(self):
            self.main = None

        def database(self):
            try:
                main_handles = [hwnd for _, hwnd in visible_windows("MainWindow")
                                if PureWindowsPath(GetPathByHwnd(hwnd) or "").name.lower() == "weixin.exe"]
                if len(main_handles) != 1:
                    raise RuntimeError
                hwnd = main_handles[0]
                pid = GetWindowThreadProcessId(hwnd)[1]
                if not pid:
                    raise RuntimeError
                if self.main is None:
                    self.main = BoundGUI(hwnd)
                if self.main.main_hwnd != hwnd or self.main.pid != pid:
                    raise RuntimeError
                return self.main._get_db()
            except Exception:
                raise RuntimeError("The logged-in WeChat window could not be verified.") from None

        def sender(self, group, chat_id, account):
            main_db = self.database()
            if main_db.get_self_info().get("username") != account:
                raise RuntimeError(_WINDOW_ERROR)
            handles = [hwnd for node, hwnd in visible_windows("ChatSingleWindow")
                       if GetWindowThreadProcessId(hwnd)[1] == self.main.pid
                       and node.Name == group and node.AutomationId == "ChatSingleWindow" + chat_id]
            if len(handles) != 1:
                raise RuntimeError(_WINDOW_ERROR)
            gui = BoundGUI(handles[0], group, chat_id, account)
            if gui.pid != self.main.pid or not gui.driver.input_is_empty():
                raise RuntimeError(_WINDOW_ERROR)
            gui._checked_send_db(chat_id)
            return gui

    return Backend()
