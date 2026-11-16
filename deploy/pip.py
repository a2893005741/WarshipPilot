"""Synchronize locked runtime dependencies only when the environment is stale."""
import hashlib
from pathlib import Path
import subprocess

from module.config.config import Config
from module.logger import atomic_text


def sync(root, force=False):
    root = Path(root)
    config = Config(root)
    digest = hashlib.sha256((root / 'uv.lock').read_bytes() +
                            (root / 'pyproject.toml').read_bytes()).hexdigest()
    marker = root / '.venv' / '.warship-lock'
    if not force and marker.exists() and marker.read_text(encoding='utf-8') == digest:
        return False
    uv = config.executable('Python', 'Uv')
    if not Path(uv).is_file():
        raise RuntimeError('找不到 .venv/uv.exe，不能同步依赖')
    subprocess.run([uv, 'sync', '--frozen', '--no-dev', '--python',
                    config.executable('Python'), '--project', str(root)], check=True, cwd=root,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    # uv may regenerate Windows redirectors after a dependency synchronization.
    portable = root / '.venv' / 'python'
    if (portable / 'python.exe').exists():
        import shutil
        for name in ('python.exe', 'pythonw.exe'):
            destination = root / '.venv' / 'Scripts' / name
            # Running executables cannot be replaced on Windows. uv normally
            # keeps them; only restore a redirector when its bytes differ.
            if destination.read_bytes() != (portable / name).read_bytes():
                shutil.copy2(portable / name, destination)
    atomic_text(marker, digest)
    return True
