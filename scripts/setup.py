from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

INSTALLED_SMOKE = """
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from wechat_whale_core import collect_batch
from wechat_whale_core.media_normalize import normalize_media

row = {'username': 'demo', 'sort_seq': 1, 'local_id': 1, 'type': '\\u6587\\u672c'}
if collect_batch(row, lambda since, limit: [row], quiet_seconds=0) != [row]:
    raise RuntimeError('Unexpected batch result')

with TemporaryDirectory() as temp:
    root = Path(temp)
    source = root / 'demo.png'
    with Image.new('RGB', (8, 8), 'navy') as image:
        image.save(source)
    result = normalize_media(source, root / 'out')
    with Image.open(result['path']) as image:
        if image.format != 'PNG' or image.size != (8, 8):
            raise RuntimeError('Unexpected normalized image')
print('Installed Python smoke test passed')
"""


def run(*args: str | Path) -> None:
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def setup() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js 20 or newer is required on PATH')
    run(node, '-e', 'if (+process.versions.node.split(".")[0] < 20) { console.error("Node.js 20 or newer is required"); process.exit(1) }')

    venv = ROOT / '.venv'
    python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if venv.is_symlink() or venv.resolve() != venv:
        raise RuntimeError('The .venv path must not redirect to another directory')
    if not venv.exists():
        print('Creating .venv', flush=True)
        run(sys.executable, '-I', '-m', 'venv', venv)
    if not (venv / 'pyvenv.cfg').is_file() or not python.is_file():
        raise RuntimeError('The existing .venv is incomplete or is not a Python virtual environment')
    run(python, '-I', '-c', 'from pathlib import Path; import sys; '
        'sys.exit(0 if sys.version_info >= (3, 10) and Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve() '
        'and sys.prefix != sys.base_prefix else "Invalid project virtual environment")', venv)

    print('Installing Python package and Pillow', flush=True)
    with tempfile.TemporaryDirectory(prefix='install-', dir=venv) as staging:
        source = Path(staging)
        for name in ('pyproject.toml', 'LICENSE'):
            shutil.copyfile(ROOT / 'python' / name, source / name)
        shutil.copytree(ROOT / 'python' / 'wechat_whale_core', source / 'wechat_whale_core',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        run(python, '-I', '-m', 'pip', '--isolated', '--require-virtualenv', '--disable-pip-version-check',
            'install', '--no-cache-dir', source)

    print('Running verification', flush=True)
    run(python, '-I', '-B', '-c', INSTALLED_SMOKE)
    run(node, '--test')
    run(python, '-I', '-B', '-m', 'unittest', 'discover', '-s', 'python/tests')
    run(node, ROOT / 'examples' / 'group-chat.mjs')
    print('Installation and verification passed')


if __name__ == '__main__':
    try:
        setup()
    except subprocess.CalledProcessError as exc:
        command = subprocess.list2cmdline(exc.cmd) if os.name == 'nt' else shlex.join(exc.cmd)
        print(f'Setup failed (exit {exc.returncode}): {command}', file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as exc:
        print(f'Setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
