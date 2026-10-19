"""Short immutable filenames, published atomically without replacing any file."""
import os
from pathlib import Path
import re
import tempfile


def _publish(source, target):
    # Windows rename fails if target exists; POSIX rename would replace it.
    if os.name == 'nt':
        os.rename(source, target)
    else:
        os.link(source, target)


def publish_bytes(contents: bytes, directory: Path, prefix: str, suffix='.parquet', *, reuse=True, validate_existing=None) -> Path:
    """Use date.ext, date.2.ext, ...; identical bytes reuse the same name.

    Expose a complete fsynced temporary file with exclusive creation.
    Racing publishers cannot truncate/replace each other, on Windows or POSIX.
    POSIX uses hard links; Windows uses its non-replacing atomic rename.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', prefix) or suffix not in ('.parquet', '.json'):
        raise ValueError('Unsafe short filename')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        number = 1
        while True:
            name = prefix + (f'.{number}' if number > 1 else '') + suffix
            target = directory / name
            if target.exists():
                if target.is_symlink():
                    raise ValueError('Published file cannot be a symbolic link')
                existing = target.read_bytes()
                if validate_existing is not None:
                    validate_existing(existing)
                if reuse and existing == contents:
                    return target
                number += 1
                continue
            if temporary is None:
                with tempfile.NamedTemporaryFile(dir=directory, prefix='.p-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(contents)
                    stream.flush()
                    os.fsync(stream.fileno())
            try:
                _publish(temporary, target)
            except FileExistsError:
                continue
            if os.name != 'nt':
                fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
