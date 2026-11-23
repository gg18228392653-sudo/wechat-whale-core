# Agent Tasks

## Windows WeChat

- Run on the same Windows x64 desktop as the user's signed-in WeChat 4.x. Required: Git, Node.js 20+, 64-bit Python 3.12 with `venv` and `pip`, and access to a Python package index.
- From the checkout root, run `py -3.12 scripts/setup.py --wechat`, or `python scripts/setup.py --wechat` with the required Python on PATH. Installation stays in `.venv`.
- Obtain the chat type and exact target from the user. For groups use `--group "exact group name"`. For private chats use `--contact "exact contact remark or nickname"`. The launcher accepts one target per run. For an ambiguous contact name, ask for a unique remark or the stable account ID.

| Mode | Group | Private |
| --- | --- | --- |
| Read-only check | `.\.venv\Scripts\wechat-whale.exe --group "exact group name" --check` | `.\.venv\Scripts\wechat-whale.exe --contact "exact contact" --check` |
| Reply preview | `.\.venv\Scripts\wechat-whale.exe --group "exact group name"` | `.\.venv\Scripts\wechat-whale.exe --contact "exact contact"` |
| Window check | `.\.venv\Scripts\wechat-whale.exe --group "exact group name" --check-send` | `.\.venv\Scripts\wechat-whale.exe --contact "exact contact" --check-send` |
| Live replies | `.\.venv\Scripts\wechat-whale.exe --group "exact group name" --send` | `.\.venv\Scripts\wechat-whale.exe --contact "exact contact" --send` |

- An installation request ends after setup and the requested read-only check. Both check modes exit without a model key or a sent message. Report the selected chat type, the command's exit code, and any error. On a failed check, stop before preview or sending.
- Preview and live replies pass the selected conversation and recent context to the configured model. Start these modes with the user's authorization for model use. The user enters the API key in the local no-echo prompt or sets `WHALE_API_KEY` locally. Never request or print a key in Agent chat. Use `--base-url` and `--model` for the user's chosen OpenAI-compatible service.
- For a group preview, have a group member send a new text starting with `大肥鱼，`. For a private preview, an incoming message from that contact is enough. Messages sent by the logged-in account cannot trigger a reply. Each run starts at the current message position.
- Stop the preview with `Ctrl+C`. For live replies the user opens the exact target in a standalone WeChat window, leaves its input empty, and authorizes sending. Run the window check before starting live replies. Report failed checks without switching targets. Stop the current run before starting another chat.

## Core and Tests

- On Linux, macOS, or Windows, run `python scripts/setup.py` with Python 3.10+ and Node.js 20+. Exit code `0` and `Installation and verification passed` identify a passing run.
- Example: `node examples/group-chat.mjs`. Tests: `npm test` (`npm.cmd test` on Windows if PowerShell blocks `npm.ps1`) and `.venv/bin/python -B -m unittest discover -s python/tests` or, on Windows, `.venv\Scripts\python.exe -B -m unittest discover -s python/tests`.
- Keep real messages, IDs, credentials, and private configurations out of committed files and tests.
- [Windows commands and adapter interface](README.md).
