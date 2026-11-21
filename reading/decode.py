from dataclasses import dataclass
from hashlib import sha256

from archive.catalog import get_encoding, get_volume
from archive.files import frame_path, read_frame_file, verify_manifest
from archive.frames import FrameAddress, LiteralFrame, decode_frame_record, frame_length
from errors import DecodeError
from intake.records import SourceRow


@dataclass(frozen=True, slots=True)
class DecodedRow:
    position: int
    row: SourceRow
    address: FrameAddress
    offset: int


class _FrameReader:
    def __init__(self, connection, root):
        self.connection = connection
        self.root = root
        self.encodings = {}

    def encoding(self, encoding_id):
        if encoding_id not in self.encodings:
            encoding = get_encoding(self.connection, encoding_id)
            verify_manifest(self.root, encoding)
            self.encodings[encoding_id] = encoding
        return self.encodings[encoding_id]

    def descriptor(self, address):
        encoding = self.encoding(address.encoding_id)
        if not 0 <= address.frame_no < len(encoding.frames):
            raise DecodeError(f'missing required frame {address.encoding_id}/{address.frame_no}')
        return encoding, encoding.frames[address.frame_no]

    def record(self, address, info):
        data = read_frame_file(frame_path(self.root, address))
        if sha256(data).hexdigest() != info.digest:
            raise DecodeError(f'frame seal mismatch for {address.encoding_id}/{address.frame_no}')
        frame = decode_frame_record(data)
        source = None if isinstance(frame, LiteralFrame) else frame.address.encoding_id
        if (frame.start, frame_length(frame), source) != (info.start, info.count, info.source_encoding):
            raise DecodeError('frame does not match its catalog descriptor')
        return frame

    def expand(self, address, length):
        offset = 0
        while True:
            encoding, info = self.descriptor(address)
            if offset + length > info.count:
                raise DecodeError('reference outside source frame')
            frame = self.record(address, info)
            if isinstance(frame, LiteralFrame):
                return frame.rows[offset:offset + length]
            base, source = self.descriptor(frame.address)
            if base.volume_id >= encoding.volume_id:
                raise DecodeError('reference does not point to an earlier volume')
            if frame.offset + frame.length > source.count:
                raise DecodeError('reference outside source frame')
            address = frame.address
            offset += frame.offset

    def rows(self, encoding, start):
        for info in encoding.frames:
            if start >= info.start + info.count:
                continue
            address = FrameAddress(encoding.encoding_id, info.number)
            rows = self.expand(address, info.count)
            for offset in range(max(0, start - info.start), info.count):
                yield DecodedRow(info.start + offset, rows[offset], address, offset)


def iter_decoded_rows(connection, root, encoding_id, *, start=0):
    reader = _FrameReader(connection, root)
    encoding = reader.encoding(encoding_id)
    if type(start) is not int or not 0 <= start <= encoding.row_count:
        raise DecodeError('start lies outside the fixed volume')
    return reader.rows(encoding, start)


def decode_volume(connection, root, volume_id):
    volume = get_volume(connection, volume_id)
    return tuple(iter_decoded_rows(connection, root, volume.encoding_id))
