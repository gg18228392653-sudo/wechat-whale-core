import io
import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import HTTPHandler, HTTPSHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechat_whale_core.chat_model import _MAX_RESPONSE, complete_chat

BASE = "https://fixture.invalid/v1/"
MODEL = "fixture-model"
KEY = "fixture-key-not-a-credential"
PROMPT = "\u5408\u6210\u95ee\u9898"
TEXT = " \u5408\u6210\u56de\u590d "


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = self.code = status
        self.msg = "fixture response"
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.read_sizes = []

    def info(self):
        return self.headers

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


def completion(reason="stop", **message):
    return {"choices": [{"finish_reason": reason, "message": {
        "role": "assistant", "content": TEXT, **message,
    }}]}


def response_json(payload):
    return Response(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class ChatModelTests(unittest.TestCase):
    def setUp(self):
        https = patch.object(HTTPSHandler, "https_open", autospec=True)
        http = patch.object(HTTPHandler, "http_open", autospec=True)
        self.https = https.start()
        self.http = http.start()
        self.addCleanup(https.stop)
        self.addCleanup(http.stop)
        self.https.side_effect = self.http.side_effect = AssertionError("Unexpected transport request")

    def test_single_post_with_default_timeout_and_no_tools(self):
        response = response_json(completion(tool_calls=[], reasoning_content="fixture reasoning"))
        self.https.side_effect = None
        self.https.return_value = response
        self.assertEqual(complete_chat(BASE, MODEL, KEY, PROMPT), TEXT)
        self.https.assert_called_once()
        self.http.assert_not_called()
        request = self.https.call_args.args[1]
        self.assertEqual(request.full_url, "https://fixture.invalid/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.timeout, 30)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {KEY}")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {
            "model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "stream": False,
        })
        self.assertTrue(response.closed)
        self.assertEqual(response.read_sizes, [_MAX_RESPONSE + 1])

    def test_only_explicit_loopback_addresses_allow_plain_http(self):
        self.http.side_effect = [response_json(completion()) for _ in range(3)]
        for base in ("http://127.0.0.1:8000/v1", "http://[::1]/v1", "http://localhost/v1"):
            with self.subTest(base=base):
                self.assertEqual(complete_chat(base, MODEL, KEY, PROMPT, 1.5), TEXT)
                self.assertEqual(self.http.call_args.args[1].full_url, base + "/chat/completions")
                self.assertEqual(self.http.call_args.args[1].timeout, 1.5)
        self.assertEqual(self.http.call_count, 3)
        self.https.assert_not_called()

    def test_invalid_parameters_stop_before_transport(self):
        invalid_urls = (
            "http://fixture.invalid/v1", "http://10.0.0.1/v1", "http://localhost.fixture.invalid/v1",
            "http://2130706433/v1", "http://127.1/v1", "https://", "https://fixture.invalid/\nx",
            "https://fixture-user:fixture-password@fixture.invalid/v1", "https://@fixture.invalid/v1",
            "https://fixture.invalid/v1?auth=fixture-private", "https://fixture.invalid/v1?",
            "https://fixture.invalid/v1#", "https://fixture.invalid/\\x", "https://fixture.invalid:99999/v1",
            "https://[::1]fixture.invalid/v1", "file:///fixture", b"https://fixture.invalid/",
        )
        cases = [(url, MODEL, KEY, PROMPT, 3) for url in invalid_urls] + [
            (BASE, "", KEY, PROMPT, 3), (BASE, MODEL, "", PROMPT, 3),
            (BASE, MODEL, "fixture-key\r\nX: fixture", PROMPT, 3),
            (BASE, MODEL, KEY, " ", 3), (BASE, MODEL, KEY, [PROMPT], 3),
            (BASE, MODEL, KEY, "\ud800", 3), (BASE, MODEL, KEY, PROMPT, False),
            (BASE, MODEL, KEY, PROMPT, float("inf")), (BASE, MODEL, KEY, PROMPT, 0),
        ]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError, "^Invalid chat completion parameters$") as caught:
                    complete_chat(*args)
                self.assertIsNone(caught.exception.__context__)
        self.https.assert_not_called()
        self.http.assert_not_called()

    def test_redirects_do_not_send_a_second_request_or_read_the_body(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.https.reset_mock()
                response = Response(b"fixture-private-body", status, {"Location": "https://other.invalid/fixture"})
                self.https.side_effect = None
                self.https.return_value = response
                self.assert_generic_failure()
                self.https.assert_called_once()
                self.http.assert_not_called()
                self.assertTrue(response.closed)
                self.assertEqual(response.read_sizes, [])

    def assert_generic_failure(self):
        with self.assertRaisesRegex(RuntimeError, "^Chat completion failed$") as caught:
            complete_chat(BASE, MODEL, KEY, PROMPT)
        self.assertIsNone(caught.exception.__context__)

    def test_transport_and_http_errors_are_generic_without_retries(self):
        self.https.side_effect = URLError("fixture-raw-error containing " + KEY)
        self.assert_generic_failure()
        self.https.assert_called_once()

        self.https.reset_mock()
        response = Response(b"fixture-private-body", 429)
        self.https.side_effect = None
        self.https.return_value = response
        self.assert_generic_failure()
        self.https.assert_called_once()
        self.assertTrue(response.closed)
        self.assertEqual(response.read_sizes, [])

    def test_rejects_non_text_malformed_or_unsafe_results(self):
        responses = [response_json(payload) for payload in (
            [], {"choices": []}, {"choices": [1]}, {"choices": [{}]},
            {"choices": completion()["choices"] * 2}, {"error": {}, **completion()},
            completion("content_filter"), completion("length"), completion("tool_calls"),
            completion(None), completion(role="tool"), completion(content=None),
            completion(content=[{"type": "text", "text": TEXT}]), completion(content=" "),
            completion(tool_calls=[{"type": "function"}]), completion(function_call={}),
            completion(refusal="fixture refusal"), completion(audio={}),
        )] + [Response(raw) for raw in (
            b"{", b"\xff", b'{"choices":NaN}', b'{"choices":[],"choices":[]}',
            b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"\\ud800"}}]}',
        )]
        self.https.side_effect = None
        for response in responses:
            with self.subTest(response=response.getvalue()):
                self.https.reset_mock()
                self.https.return_value = response
                self.assert_generic_failure()
                self.https.assert_called_once()
                self.assertTrue(response.closed)

    def test_response_body_byte_limit(self):
        baseline = response_json(completion()).getvalue()
        fits = baseline.ljust(_MAX_RESPONSE)
        self.https.side_effect = [Response(fits), Response(fits + b" ")]
        self.assertEqual(complete_chat(BASE, MODEL, KEY, PROMPT), TEXT)
        self.assert_generic_failure()
        self.assertEqual(self.https.call_count, 2)


if __name__ == "__main__":
    unittest.main()
