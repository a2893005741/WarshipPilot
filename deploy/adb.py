"""Check ADB without changing any emulator connection or server."""
import subprocess
from module.config.config import Config


def check(root):
    executable = Config(root).executable('Adb')
    subprocess.run([executable, 'version'], check=True, capture_output=True, timeout=15,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
