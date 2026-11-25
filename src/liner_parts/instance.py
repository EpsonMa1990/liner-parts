import os
from pathlib import Path


class InstanceLock:
    """Prevent two desktop processes from resetting or editing the same task queue."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.file = (root / "instance.lock").open("a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("此数据目录已在另一窗口中打开，请返回已打开的 Agamaship取件表制作工作台。") from None

    def close(self):
        if self.file.closed:
            return
        if os.name == "nt":
            import msvcrt

            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()
