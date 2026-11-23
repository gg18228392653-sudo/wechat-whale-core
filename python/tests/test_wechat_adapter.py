import sqlite3
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from wechat_whale_core import wechat_adapter as module


GROUP = "Example group"
CHAT = "314@chatroom"
SELF = "wxid_demo_bot"
OTHER = "wxid_demo_member"


def message(seq=1, *, sender=OTHER, content="Example text", kind="文本", **fields):
    return {"sort_seq": seq, "local_id": seq, "shard": "fixture", "sender_username": sender,
            "content": content, "type": kind, "create_time": 1700000000, **fields}


class FakeRuntime:
    def __init__(self):
        self.db = Mock()
        self.gui = Mock()
        self.backend = Mock()
        self.backend.database.return_value = self.db
        self.backend.sender.return_value = self.gui
        self.db.get_self_info.return_value = {"username": SELF, "nick_name": "Example bot"}
        self.db.get_groups.return_value = [{"username": CHAT, "name": GROUP}]
        self.db.search_contact.return_value = [{"username": CHAT, "nick_name": GROUP}]
        self.db.get_messages.return_value = []
        self.db.get_new_messages.return_value = []
        self.gui.send_msg.return_value = SimpleNamespace(is_success=True)

    def adapter(self, group=GROUP):
        with patch.object(module, "_load_backend", return_value=self.backend):
            return module.WeChatAdapter(group)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.db = self.runtime.db
        self.gui = self.runtime.gui

    def test_portable_import_and_early_input_validation(self):
        with patch.object(module.sys, "platform", "linux"), patch.object(module, "version") as version:
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                module.WeChatAdapter(GROUP)
            with self.assertRaises(ValueError):
                module.WeChatAdapter(" " + GROUP)
            version.assert_not_called()

    def test_exact_group_and_account_bound_reads(self):
        self.db.get_groups.return_value += [{"name": GROUP + " extra", "username": "999@chatroom"}]
        adapter = self.runtime.adapter()
        self.assertEqual((adapter.self_id, adapter.self_name, adapter.chat_id), (SELF, "Example bot", CHAT))
        self.assertEqual(adapter.latest_sequence(), 0)
        self.db.get_messages.return_value = [message(12)]
        self.assertEqual(adapter.latest_sequence(), 12)
        self.db.get_messages.assert_called_with(CHAT, limit=1)
        original = [message(9), message(7, kind="系统消息")]
        self.db.get_new_messages.return_value = original
        self.assertEqual(adapter.read_after(6, 2), [{**row, "username": CHAT} for row in reversed(original)])
        self.db.get_new_messages.assert_called_once_with(CHAT, since_seq=6, limit=2)
        self.assertNotIn("username", original[0])
        self.runtime.backend.sender.assert_not_called()

    def test_no_fuzzy_match_or_duplicate_group(self):
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            self.runtime.adapter("Example")
        self.db.get_groups.return_value += [{"name": GROUP, "username": "999@chatroom"}]
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            self.runtime.adapter()
        self.db.get_messages.assert_not_called()
        self.gui.send_msg.assert_not_called()

    def test_contact_collisions_and_truncated_search(self):
        for key in ("nick_name", "remark", "username"):
            with self.subTest(key=key):
                self.db.search_contact.return_value = [{"username": OTHER, key: GROUP}]
                with self.assertRaisesRegex(RuntimeError, "contact results"):
                    self.runtime.adapter()
        self.db.search_contact.return_value = [{"username": f"demo_{i}"} for i in range(50)]
        with self.assertRaisesRegex(RuntimeError, "contact results"):
            self.runtime.adapter()

    def test_rebinding_is_refused_before_operations(self):
        adapter = self.runtime.adapter()
        self.db.get_groups.return_value = [{"username": "999@chatroom", "name": GROUP}]
        self.db.search_contact.return_value = [{"username": "999@chatroom", "nick_name": GROUP}]
        with self.assertRaisesRegex(RuntimeError, "group changed"):
            adapter.latest_sequence()
        self.assertFalse(adapter.send_text("Example reply"))
        with self.assertRaisesRegex(RuntimeError, "standalone chat window"):
            adapter.check_send_ready()
        self.db.get_self_info.return_value = {"username": "wxid_other_account"}
        with self.assertRaisesRegex(RuntimeError, "account changed"):
            adapter.read_after(0, 1)
        self.db.get_messages.assert_not_called()
        self.db.get_new_messages.assert_not_called()
        self.gui.send_msg.assert_not_called()

    def test_read_rejects_other_chat_and_invalid_sequence(self):
        adapter = self.runtime.adapter()
        self.db.get_new_messages.return_value = [message(2, username="9@chatroom")]
        with self.assertRaises(RuntimeError):
            adapter.read_after(0, 1)
        self.db.get_new_messages.return_value = [message(2)]
        with self.assertRaises(RuntimeError):
            adapter.read_after(2, 1)
        with self.assertRaises(ValueError):
            adapter.read_after(0, True)

    def test_project_exact_mentions_sender_and_history_self(self):
        adapter = self.runtime.adapter()
        row = message(username=CHAT, content=f"{OTHER}:\nExample text", mentions=[OTHER, SELF, SELF, 3])
        self.assertEqual(adapter.project(row), {"id": "local:fixture:1", "senderId": OTHER,
                         "text": "Example text", "mentions": [OTHER, SELF], "self": False,
                         "time": 1700000000})
        own = adapter.project(message(username=CHAT, sender=SELF, sender_id=4, content="Self text"))
        self.assertTrue(own["self"])
        self.assertEqual(own["senderId"], SELF)
        for invalid in (message(username="9@chatroom"), message(username=CHAT, kind="系统消息"),
                        message(username=CHAT, sender="2", sender_id=2, content=f"{SELF}:\ntext"),
                        message(username=CHAT, sender="", senderId=SELF)):
            self.assertIsNone(adapter.project(invalid))

    def test_vocative_excludes_other_mentions_and_ambiguous_markup(self):
        adapter = self.runtime.adapter()
        positive = message(username=CHAT, content="大肥鱼，在吗？")
        self.assertEqual(adapter.project(positive)["mentions"], [SELF])
        for text in ("大肥鱼助手，你好", "你问大肥鱼吧", "@大肥鱼助手 你好", "@大肥鱼 你好",
                     "大肥鱼，@另一个人 你好", "大肥鱼，<atuserlist>person</atuserlist>"):
            with self.subTest(text=text):
                self.assertEqual(adapter.project(message(username=CHAT, content=text))["mentions"], [])
        self.assertEqual(adapter.project({**positive, "mentions": [OTHER]})["mentions"], [OTHER])
        self.assertEqual(adapter.project({**positive, "sender_username": SELF})["mentions"], [])
        self.db.get_groups.return_value[0]["members"] = [{"username": OTHER, "nick_name": "大肥鱼"}]
        self.assertEqual(self.runtime.adapter().project(positive)["mentions"], [])

    def test_quote_and_media_projection_never_uses_xml_identity(self):
        adapter = self.runtime.adapter()
        xml = (f"<msg><appmsg><type>57</type><title>Example reply</title><refermsg>"
               f"<fromusr>{SELF}</fromusr><content>Quoted text</content></refermsg></appmsg>"
               f"<msgsource><atuserlist>{SELF}</atuserlist></msgsource></msg>")
        result = adapter.project(message(username=CHAT, kind="文件/链接/卡片", content=xml))
        self.assertEqual((result["text"], result["quote"], result["mentions"]),
                         ("Example reply", {"text": "Quoted text"}, []))
        structured = adapter.project(message(username=CHAT, kind="引用消息", content="Example reply",
                                             quote={"senderId": SELF, "text": "Quoted text"}))
        self.assertEqual(structured["quote"], {"senderId": SELF, "text": "Quoted text"})
        for kind, expected in (("图片", "image"), ("动画表情", "sticker"), ("文件/链接/卡片", "file")):
            with self.subTest(kind=kind):
                media = adapter.project(message(username=CHAT, kind=kind, content="<img source='private'/>"))
                self.assertEqual((media["text"], media["media"]), ("", [{"kind": expected}]))
        self.assertIsNone(adapter.project(message(username=CHAT, kind="引用", content="<!DOCTYPE msg><msg/>")))

    def test_send_once_only_after_verification_and_fresh_exact_self_row(self):
        adapter = self.runtime.adapter()
        adapter.check_send_ready()
        self.gui.send_msg.assert_not_called()
        before = message(7, sender=SELF, content="Example reply")
        equal_seq = message(7, sender=SELF, sender_id=5, local_id=8, content="Example reply")
        self.db.get_messages.side_effect = [[before], [before, equal_seq]]
        self.assertTrue(adapter.send_text("Example reply"))
        self.runtime.backend.sender.assert_called_with(GROUP, CHAT, SELF)
        self.gui.send_msg.assert_called_once_with("Example reply", who=CHAT, verify=True)

    def test_false_confirmation_wrong_chat_sender_or_stale_row(self):
        before = message(7, sender=SELF, content="Example reply")
        success = SimpleNamespace(is_success=True)
        cases = (
            (SimpleNamespace(is_success=False), [message(8, sender=SELF, content="Example reply")]),
            ({"status": "success"}, [message(8, sender=SELF, content="Example reply")]),
            (success, [before]),
            (success, [message(8, sender=OTHER, sender_id=2, content="Example reply")]),
            (success, [message(8, sender=SELF, content="Example reply extra")]),
            (success, [message(8, sender=SELF, content="Example reply", username="9@chatroom")]),
        )
        for response, rows in cases:
            with self.subTest(response=response, rows=rows):
                fake = FakeRuntime()
                fake.db.get_messages.side_effect = [[before], rows]
                fake.gui.send_msg.return_value = response
                self.assertFalse(fake.adapter().send_text("Example reply"))
                fake.gui.send_msg.assert_called_once_with("Example reply", who=CHAT, verify=True)

    def test_send_failure_does_not_retry(self):
        adapter = self.runtime.adapter()
        self.gui.send_msg.side_effect = OSError("unknown outcome")
        self.assertFalse(adapter.send_text("Example reply"))
        self.gui.send_msg.assert_called_once_with("Example reply", who=CHAT, verify=True)
        self.gui.send_msg.reset_mock()
        self.runtime.backend.sender.side_effect = RuntimeError("window invalid")
        self.assertFalse(adapter.send_text("Example reply"))
        self.gui.send_msg.assert_not_called()


class ContactAdapterTests(unittest.TestCase):
    CONTACT = "wxid_demo_contact"
    NICK = "Example nickname"
    REMARK = "Example remark"

    def setUp(self):
        self.runtime = FakeRuntime()
        self.db = self.runtime.db
        self.contacts = [(self.CONTACT, self.NICK, self.REMARK, 1, 0)]
        self.db._contact_conn.side_effect = self.contact_connection

    def contact_connection(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE contact (username TEXT COLLATE NOCASE, "
                     "nick_name TEXT COLLATE NOCASE, remark TEXT COLLATE NOCASE, local_type, verify_flag)")
        conn.executemany("INSERT INTO contact VALUES (?, ?, ?, ?, ?)", self.contacts)
        return conn

    def adapter(self, selector=None):
        with patch.object(module, "_load_backend", return_value=self.runtime.backend):
            return module.WeChatAdapter(contact=self.REMARK if selector is None else selector)

    def test_contact_selectors_are_exact(self):
        with patch.object(module, "_load_backend") as backend:
            for args, kwargs in (((GROUP,), {"contact": self.REMARK}), ((), {"contact": " "}),
                                 ((), {"contact": 123}), ((), {})):
                with self.assertRaises(ValueError):
                    module.WeChatAdapter(*args, **kwargs)
            backend.assert_not_called()
        for selector in (self.REMARK, self.NICK, self.CONTACT):
            with self.subTest(selector=selector):
                adapter = self.adapter(selector)
                self.assertEqual((adapter.chat_id, adapter.self_id), (self.CONTACT, SELF))
                self.assertEqual(adapter.latest_sequence(), 0)
                self.db.get_messages.assert_called_with(self.CONTACT, limit=1)
                self.db.get_new_messages.return_value = [message(2, sender=self.CONTACT)]
                self.assertEqual(adapter.read_after(1, 2)[0]["username"], self.CONTACT)
                adapter.check_send_ready()
                self.runtime.backend.sender.assert_called_with(self.REMARK, self.CONTACT, SELF)
        for selector in ("Example", self.NICK.lower(), "%", "example_alias"):
            with self.assertRaisesRegex(RuntimeError, "exactly one verified person"):
                self.adapter(selector)
        self.db.search_contact.assert_not_called()
        self.db.get_groups.assert_not_called()

    def test_collisions_and_non_people_are_rejected(self):
        original = self.contacts[0]
        for selector, collision in ((self.REMARK, (OTHER, self.REMARK, None, 1, 0)),
                                    (self.CONTACT, (OTHER, "Other", self.CONTACT, 1, 0)),
                                    (self.NICK, (CHAT, self.NICK, None, 2, 0)), (self.NICK, original)):
            with self.subTest(selector=selector, collision=collision):
                self.contacts[:] = [original, collision]
                with self.assertRaisesRegex(RuntimeError, "exactly one verified person"):
                    self.adapter(selector)
        for username, local_type, flag in (("filehelper", 1, 0), ("weixin", 1, 0), ("gh_demo", 3, 0),
                                           ("biz_demo", 3, 0), ("demo@openim", 1, 0), (CHAT, 2, 0),
                                           (SELF, 1, 0), ("123", 1, 0), (self.CONTACT, 0, 0),
                                           (self.CONTACT, 3, 8), (self.CONTACT, 1, None)):
            self.contacts[:] = [(username, self.NICK, self.REMARK, local_type, flag)]
            with self.subTest(username=username, local_type=local_type, flag=flag):
                with self.assertRaisesRegex(RuntimeError, "exactly one verified person"):
                    self.adapter()
        self.db._contact_conn.side_effect = sqlite3.OperationalError("unavailable schema")
        with self.assertRaisesRegex(RuntimeError, "exactly one verified person"):
            self.adapter()
        self.db.get_messages.assert_not_called()
        self.runtime.backend.sender.assert_not_called()

    def test_contact_and_account_are_pinned(self):
        adapter = self.adapter()
        self.contacts[:] = [(OTHER, self.NICK, self.REMARK, 1, 0)]
        with self.assertRaisesRegex(RuntimeError, "contact changed"):
            adapter.latest_sequence()
        self.assertFalse(adapter.send_text("Example reply"))
        self.db.get_self_info.return_value = {"username": "wxid_other_account"}
        with self.assertRaisesRegex(RuntimeError, "account changed"):
            adapter.read_after(0, 1)
        with self.assertRaisesRegex(RuntimeError, "standalone chat window"):
            adapter.check_send_ready()
        self.db.get_messages.assert_not_called()
        self.db.get_new_messages.assert_not_called()
        self.runtime.backend.sender.assert_not_called()

    def test_projection_and_confirmation_use_real_participant_ids(self):
        adapter = self.adapter(self.CONTACT)
        raw = message(username=self.CONTACT, sender=self.CONTACT, sender_id=2, content="大肥鱼，你好")
        self.assertEqual(adapter.project(raw), {"id": "local:fixture:1", "senderId": self.CONTACT,
                         "text": "大肥鱼，你好", "mentions": [], "self": False, "time": 1700000000})
        self.assertEqual(adapter.project({**raw, "mentions": [SELF]})["mentions"], [])
        self.assertTrue(adapter.project({**raw, "sender_username": SELF, "sender_id": 5})["self"])
        for sender in (OTHER, "2", "", "filehelper", CHAT):
            self.assertIsNone(adapter.project({**raw, "sender_username": sender, "senderId": SELF}))
        for sender, chat, expected in ((SELF, self.CONTACT, True), (self.CONTACT, self.CONTACT, False),
                                       (SELF, OTHER, False)):
            self.db.get_messages.side_effect = [[], [message(username=chat, sender=sender, content="Example reply")]]
            self.assertIs(adapter.send_text("Example reply"), expected)
            self.runtime.backend.sender.assert_called_with(self.REMARK, self.CONTACT, SELF)
            self.runtime.gui.send_msg.assert_called_with("Example reply", who=self.CONTACT, verify=True)


class WindowsBindingTests(unittest.TestCase):
    def test_standalone_class_pid_title_and_native_id_are_all_required(self):
        self.check_standalone_binding(GROUP, CHAT)

    def test_private_standalone_has_no_other_window_or_search_fallback(self):
        self.check_standalone_binding(ContactAdapterTests.REMARK, ContactAdapterTests.CONTACT, private=True)

    def check_standalone_binding(self, title, chat, *, private=False):
        def node(hwnd, kind, title, aid=""):
            return SimpleNamespace(NativeWindowHandle=hwnd, ClassName=f"mmui::{kind}",
                                   Name=title, AutomationId=aid)

        main = node(1, "MainWindow", "Client")
        exact = node(2, "ChatSingleWindow", title, "ChatSingleWindow" + chat)
        wrong_id = node(3, "ChatSingleWindow", title, "ChatSingleWindow" + OTHER)
        wrong_pid = node(4, "ChatSingleWindow", title, "ChatSingleWindow" + chat)
        wrong_title = node(5, "ChatSingleWindow", title + " suffix", "ChatSingleWindow" + chat)
        history = node(6, "SearchMsgUniqueChatWindow", title, "ChatSingleWindow" + chat)
        nodes = [wrong_id, wrong_pid, wrong_title, history]
        runtime = FakeRuntime()
        if private:
            fixture = ContactAdapterTests()
            fixture.setUp()
            runtime = fixture.runtime
        actions = []
        field = SimpleNamespace(value="Example reply", ready_value="", foreground=2)
        activations = []

        class GUI:
            def __init__(self, hwnd):
                self.main_hwnd, self.pid = hwnd, pid(hwnd)[1]
                self.calibrate_layout()

            def calibrate_layout(self):
                raise AssertionError("calibration")

            def _get_db(self):
                return runtime.db

            def send_msg(self, text, who, verify):
                driver = self._get_uia()
                if not driver:
                    return SimpleNamespace(is_success=False)
                if driver.open_chat(OTHER) or not driver.open_chat(who):
                    raise AssertionError("unverified chat route")
                mark = self._send_watermark(who)
                if not driver.ensure_window():
                    return SimpleNamespace(is_success=False)
                driver._paste_into(SimpleNamespace(value=field.ready_value), text)
                driver._paste_landed(field, text)
                actions.append((self.main_hwnd, who, verify))
                return SimpleNamespace(is_success=self._verify_sent(text, who, after=mark))

        class UIA:
            def __init__(self, hwnd):
                self.hwnd = hwnd

            def _find_main(self):
                return next((item for item in nodes if item.NativeWindowHandle == self.hwnd), None)

            def ensure_window(self, *, wake, timeout):
                if wake:
                    raise AssertionError("wake")
                activations.append(self.hwnd)
                self._win = self._find_main()
                return self._win is not None

            def _chat_input(self, root):
                return SimpleNamespace(value=field.ready_value)

            @staticmethod
            def _read_edit_value(ctrl):
                return ctrl.value

            @staticmethod
            def _paste_into(ctrl, text, clear=True):
                if clear:
                    raise AssertionError("draft clearance attempted")

        def pid(hwnd):
            return 0, 99 if hwnd == 4 else 88

        def fake_module(name, **attrs):
            result = ModuleType(name)
            result.__dict__.update(attrs)
            return result

        modules = {
            "wechatauto": fake_module("wechatauto", WeChatGUI=GUI, WxParam=SimpleNamespace(ENABLE_FILE_LOGGER=True)),
            "wechatauto.ui.main": fake_module("wechatauto.ui.main", find_wechat_windows=lambda name: (
                [main] if name == "mmui::MainWindow" else nodes)),
            "wechatauto.uia_driver": fake_module("wechatauto.uia_driver", WeChatUIA=UIA),
            "wechatauto.utils.win32": fake_module("wechatauto.utils.win32", GetPathByHwnd=lambda _: "weixin.exe"),
            "win32gui": fake_module("win32gui", IsWindowVisible=lambda _: True,
                                    GetForegroundWindow=lambda: field.foreground),
            "win32process": fake_module("win32process", GetWindowThreadProcessId=pid),
        }
        with patch.dict(sys.modules, modules), patch.object(sys, "platform", "win32"), \
                patch.object(module, "version", return_value="1.2.9"), patch.object(module.logging, "getLogger"):
            adapter = module.WeChatAdapter(contact=chat) if private else module.WeChatAdapter(title)
            with self.assertRaisesRegex(RuntimeError, "standalone chat window"):
                adapter.check_send_ready()
            self.assertFalse(adapter.send_text("Example reply"))
            self.assertEqual(actions, [])
            nodes.append(exact)
            for unreadable_or_draft in (None, "Unsent draft"):
                field.ready_value = unreadable_or_draft
                with self.assertRaisesRegex(RuntimeError, "standalone chat window"):
                    adapter.check_send_ready()
                self.assertFalse(adapter.send_text("Example reply"))
                self.assertEqual(field.ready_value, unreadable_or_draft)
                self.assertEqual(actions, [])
            field.ready_value = ""
            adapter.check_send_ready()
            self.assertEqual(activations, [])
            for unconfirmed in (None, "Example reply extra"):
                field.value = unconfirmed
                self.assertFalse(adapter.send_text("Example reply"))
                self.assertEqual(actions, [])
            field.value, field.foreground = "Example reply", 3
            self.assertFalse(adapter.send_text("Example reply"))
            self.assertEqual(actions, [])
            field.foreground = 2
            landed = message(sender=SELF, sender_id=4, content="Example reply")
            runtime.db.get_messages.side_effect = [[], [], [landed], [landed]]
            self.assertTrue(adapter.send_text("Example reply"))
            self.assertEqual(actions, [(2, chat, True)])
            nodes.append(node(7, "ChatSingleWindow", title, "ChatSingleWindow" + chat))
            with self.assertRaisesRegex(RuntimeError, "standalone chat window"):
                adapter.check_send_ready()


if __name__ == "__main__":
    unittest.main()
