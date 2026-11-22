# Agent Tasks

## Windows WeChat

- Run on the same Windows x64 desktop as the user's signed-in WeChat 4.x. Required: Git, Node.js 20+, 64-bit Python 3.12 with `venv` and `pip`, and access to a Python package index.
- From the checkout root, run `py -3.12 scripts/setup.py --wechat`, or `python scripts/setup.py --wechat` with the required Python on PATH. Installation stays in `.venv`.
- Use the exact group name supplied by the user. Run `.\.venv\Scripts\wechat-whale.exe --group "exact group name" --check` for a read-only check. Report the actual exit code and any failure. The check does not require a model key.
- Run without a mode flag only when the user authorizes model use. Preview mode sends the selected group's eligible messages and recent context to the configured model, and displays replies in the terminal without posting to WeChat. The user supplies the API key locally through the no-echo prompt or `WHALE_API_KEY`. Never ask for the key in chat or print it. Use `--base-url` and `--model` when the user specifies another OpenAI-compatible service.
- Sending requires explicit authorization, a visible standalone window for the specified group, and a successful `--check-send`. Only then run the launcher with `--send`. Do not send test messages without explicit authorization. The user signs in and opens the group window themselves.

## Core and Tests

- On Linux, macOS, or Windows, run `python scripts/setup.py` with Python 3.10+ and Node.js 20+. Exit code `0` and `Installation and verification passed` identify a passing run.
- Example: `node examples/group-chat.mjs`. Tests: `node --test` and `.venv/bin/python -B -m unittest discover -s python/tests` or, on Windows, `.venv\Scripts\python.exe -B -m unittest discover -s python/tests`.
- Keep real messages, IDs, credentials, and private configurations out of committed files and tests.
- [Windows commands and adapter interface](README.md).
