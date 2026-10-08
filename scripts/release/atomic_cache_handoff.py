"""Gap-free directory-entry exchange. No unlink/copy fallback on unsupported OS."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import sys
import tempfile


class AtomicHandoffError(OSError):
    pass


def exchange(left: Path, right: Path) -> None:
    """Both directory entries must exist on the same filesystem, including links."""
    left, right = Path(left).absolute(), Path(right).absolute()
    if left.parent.resolve() != left.parent or right.parent.resolve() != right.parent:
        raise AtomicHandoffError('handoff parent is aliased')
    if left.lstat().st_dev != right.lstat().st_dev:
        raise AtomicHandoffError('handoff crosses filesystems')
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        function = getattr(library, 'renamex_np', None)
        if function is None:
            raise AtomicHandoffError('atomic exchange is unavailable')
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(os.fsencode(left), os.fsencode(right), 2)  # RENAME_SWAP
    elif sys.platform.startswith('linux'):
        function = getattr(library, 'renameat2', None)
        if function is None:
            raise AtomicHandoffError('atomic exchange is unavailable')
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(-100, os.fsencode(left), -100, os.fsencode(right), 2)  # RENAME_EXCHANGE
    else:
        raise AtomicHandoffError('atomic exchange is unsupported on this platform')
    if result:
        number = ctypes.get_errno()
        raise AtomicHandoffError(number, os.strerror(number))
    for directory in {left.parent, right.parent}:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def probe(parent: Path) -> None:
    """Exercise directory↔link exchange on the actual filesystem, outside cache."""
    parent = Path(parent)
    if parent.resolve() != parent or not parent.is_dir():
        raise AtomicHandoffError('probe parent must be an existing canonical directory')
    temporary = Path(tempfile.mkdtemp(prefix='.sulde-exchange-probe-', dir=parent))
    try:
        original, target, link = temporary/'original', temporary/'target', temporary/'link'
        original.mkdir(); target.mkdir()
        (original/'marker').write_text('old', encoding='utf-8')
        (target/'marker').write_text('new', encoding='utf-8')
        link.symlink_to(target, target_is_directory=True)
        exchange(original, link)
        if not original.is_symlink() or (original/'marker').read_text(encoding='utf-8') != 'new':
            raise AtomicHandoffError('exchange did not preserve the published path')
        exchange(original, link)
        if original.is_symlink() or (original/'marker').read_text(encoding='utf-8') != 'old':
            raise AtomicHandoffError('reverse exchange did not restore the original directory')
    finally:
        shutil.rmtree(temporary)
