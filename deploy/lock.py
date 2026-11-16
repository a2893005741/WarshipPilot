"""One installation process at a time, shared with the running GUI."""
from contextlib import contextmanager
from pathlib import Path
import msvcrt


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def instance_lock(root):
    path = Path(root) / 'log' / 'instance.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise AlreadyRunning('本目录的后台或安装器已经运行') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
