"""Install public immutable Python code independently of checkout permissions."""
from pathlib import Path
import os
import shutil
import stat
import sys


def install_package(source: Path, destination: Path) -> None:
    if os.geteuid() != 0:
        raise PermissionError('package installation requires root')
    # Check the complete source before copying; never follow links into private data.
    entries = [source, *source.rglob('*')]
    for entry in entries:
        mode = entry.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('package contains a link or special file')
    for entry in entries:
        relative = entry.relative_to(source)
        if '__pycache__' in relative.parts or entry.suffix == '.pyc':
            continue
        target = destination / relative
        if target.is_symlink():
            raise ValueError('package destination contains a symbolic link')
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            os.chown(target, 0, 0)
            target.chmod(0o755)
        else:
            if target.exists() and (not target.is_file() or target.stat().st_nlink != 1):
                raise ValueError('package destination is not a private regular file')
            shutil.copyfile(entry, target)
            os.chown(target, 0, 0)
            target.chmod(0o644)


if __name__ == '__main__':
    install_package(Path(sys.argv[1]), Path(sys.argv[2]))
