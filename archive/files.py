import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from archive.frames import encode_frame
from errors import DecodeError


def volume_path(root, encoding_id):
    return Path(root) / 'volumes' / f'{encoding_id}.volume'


def frame_path(root, address):
    return Path(root) / 'volumes' / f'{address.encoding_id}.{address.frame_no}.frame'


def write_frame_file(path, data):
    path = Path(path)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix='.stage-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_frame_file(path):
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise DecodeError(f'unavailable archive file {Path(path).name}') from exc


def remove_frame_file(path):
    Path(path).unlink()


def restore_frame_file(path, data):
    write_frame_file(path, data)


def _manifest(encoding):
    record = [encoding.encoding_id, encoding.volume_id, encoding.row_count,
              [[info.number, info.start, info.count, info.digest, info.source_encoding]
               for info in encoding.frames]]
    return json.dumps(record, separators=(',', ':')).encode('ascii')


def verify_manifest(root, encoding):
    if read_frame_file(volume_path(root, encoding.encoding_id)) != _manifest(encoding):
        raise DecodeError(f'volume seal mismatch for encoding {encoding.encoding_id}')


class FileChanges:
    """Undo the files of a synchronous operation if its catalog transaction fails."""

    def __init__(self, root):
        self.root = Path(root)
        self.added = []
        self.removed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            for path, data in reversed(self.removed):
                restore_frame_file(path, data)
            for path in reversed(self.added):
                path.unlink(missing_ok=True)

    def add(self, path, data):
        if path.exists():
            raise FileExistsError(path)
        write_frame_file(path, data)
        self.added.append(path)

    def remove(self, path):
        data = read_frame_file(path)
        remove_frame_file(path)
        self.removed.append((path, data))

    def write_encoding(self, encoding, frames):
        from archive.frames import FrameAddress

        for info, frame in zip(encoding.frames, frames, strict=True):
            address = FrameAddress(encoding.encoding_id, info.number)
            self.add(frame_path(self.root, address), encode_frame(frame))
        self.add(volume_path(self.root, encoding.encoding_id), _manifest(encoding))

    def remove_encoding(self, encoding):
        from archive.frames import FrameAddress

        for info in encoding.frames:
            address = FrameAddress(encoding.encoding_id, info.number)
            self.remove(frame_path(self.root, address))
        self.remove(volume_path(self.root, encoding.encoding_id))
