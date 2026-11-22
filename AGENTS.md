# Agent Tasks

## Install

- Required: Git, Node.js 20+, Python 3.10+ with `venv` and `pip`, and access to a Python package index for Pillow and build dependencies.
- Run `python scripts/setup.py` from the repository root. On Windows, `py -3 scripts/setup.py` is an alternative; on macOS and Linux, use `python3 scripts/setup.py`. The install runs inside `.venv` and does not install system runtimes.
- Success: exit code `0` and `Installation and verification passed`. The script checks the Python package installed in `.venv`, runs both test suites, and runs the group-chat example.
- On failure, report the failing command and its error. Do not report a successful installation after a partial run.

## Run

- Group-chat example: `node examples/group-chat.mjs`.
- Node tests: `node --test`.
- Python tests: `.venv/bin/python -B -m unittest discover -s python/tests` or, on Windows, `.venv\Scripts\python.exe -B -m unittest discover -s python/tests`.
- Adapter contract: [README](README.md#接入群聊).
- These commands are local. Keep actual WeChat messages, credentials, group bindings, and private persona cards out of the repository and test inputs. Installing this library does not authorize signing in to WeChat or sending messages.
