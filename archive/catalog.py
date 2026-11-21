from dataclasses import dataclass
from hashlib import sha256

from archive.frames import ReferenceFrame, encode_frame, frame_length, validate_frame_layout
from errors import DecodeError, VolumeUnavailable
from workspace import valid_id


@dataclass(frozen=True, slots=True)
class VolumeEntry:
    volume_id: int
    revision_id: int
    encoding_id: int


@dataclass(frozen=True, slots=True)
class FrameInfo:
    number: int
    start: int
    count: int
    digest: str
    source_encoding: int | None


@dataclass(frozen=True, slots=True)
class EncodingEntry:
    encoding_id: int
    volume_id: int
    row_count: int
    frames: tuple[FrameInfo, ...]


def initialize_catalog(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS volumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision INTEGER NOT NULL REFERENCES revisions(id),
            active INTEGER,
            retired INTEGER NOT NULL DEFAULT 0 CHECK (retired IN (0, 1))
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS encodings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume INTEGER NOT NULL REFERENCES volumes(id),
            row_count INTEGER NOT NULL CHECK (row_count >= 0)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS frame_catalog (
            encoding INTEGER NOT NULL REFERENCES encodings(id) ON DELETE CASCADE,
            frame_no INTEGER NOT NULL,
            first_row INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            digest TEXT NOT NULL,
            source_encoding INTEGER,
            PRIMARY KEY (encoding, frame_no)
        )
    ''')
    connection.execute('CREATE INDEX IF NOT EXISTS frame_by_source ON frame_catalog(source_encoding)')


def register_encoding(connection, volume_id, frames, row_count):
    validate_frame_layout(((frame.start, frame_length(frame)) for frame in frames), row_count)
    cursor = connection.execute(
        'INSERT INTO encodings(volume, row_count) VALUES (?, ?)', (volume_id, row_count)
    )
    encoding_id = cursor.lastrowid
    descriptors = tuple(
        FrameInfo(number, frame.start, frame_length(frame), sha256(encode_frame(frame)).hexdigest(),
                  frame.address.encoding_id if isinstance(frame, ReferenceFrame) else None)
        for number, frame in enumerate(frames)
    )
    connection.executemany('''
        INSERT INTO frame_catalog(encoding, frame_no, first_row, row_count, digest, source_encoding)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ((encoding_id, info.number, info.start, info.count, info.digest, info.source_encoding)
          for info in descriptors))
    return EncodingEntry(encoding_id, volume_id, row_count, descriptors)


def register_volume(connection, revision_id, frames, row_count):
    cursor = connection.execute('INSERT INTO volumes(revision) VALUES (?)', (revision_id,))
    encoding = register_encoding(connection, cursor.lastrowid, frames, row_count)
    set_active_encoding(connection, encoding.volume_id, encoding.encoding_id)
    return VolumeEntry(encoding.volume_id, revision_id, encoding.encoding_id)


def get_volume(connection, volume_id):
    record = None
    if valid_id(volume_id):
        record = connection.execute(
            'SELECT id, revision, active FROM volumes WHERE id = ? AND retired = 0', (volume_id,)
        ).fetchone()
    if record is None or record['active'] is None:
        raise VolumeUnavailable(f'volume {volume_id!r} is unavailable')
    return VolumeEntry(record['id'], record['revision'], record['active'])


def get_encoding(connection, encoding_id):
    record = None
    if valid_id(encoding_id):
        record = connection.execute(
            'SELECT volume, row_count FROM encodings WHERE id = ?', (encoding_id,)
        ).fetchone()
    if record is None:
        raise DecodeError(f'missing required encoding {encoding_id!r}')
    frames = tuple(
        FrameInfo(row['frame_no'], row['first_row'], row['row_count'], row['digest'], row['source_encoding'])
        for row in connection.execute('''
            SELECT frame_no, first_row, row_count, digest, source_encoding
            FROM frame_catalog WHERE encoding = ? ORDER BY frame_no
        ''', (encoding_id,))
    )
    if any(frame.number != number for number, frame in enumerate(frames)):
        raise DecodeError(f'invalid frame numbering for encoding {encoding_id}')
    validate_frame_layout(((frame.start, frame.count) for frame in frames), record['row_count'])
    return EncodingEntry(encoding_id, record['volume'], record['row_count'], frames)


def direct_dependents(connection, encoding_id):
    return tuple(
        row['id'] for row in connection.execute('''
            SELECT DISTINCT volume.id
            FROM frame_catalog AS frame JOIN volumes AS volume ON volume.active = frame.encoding
            WHERE frame.source_encoding = ? AND volume.retired = 0 ORDER BY volume.id
        ''', (encoding_id,))
    )


def set_active_encoding(connection, volume_id, encoding_id):
    owner = connection.execute('SELECT volume FROM encodings WHERE id = ?', (encoding_id,)).fetchone()
    if owner is None or owner['volume'] != volume_id:
        raise DecodeError('encoding belongs to a different volume')
    cursor = connection.execute('UPDATE volumes SET active = ? WHERE id = ? AND retired = 0',
                                (encoding_id, volume_id))
    if cursor.rowcount != 1:
        raise VolumeUnavailable(f'volume {volume_id!r} is unavailable')


def mark_retired(connection, volume_id):
    cursor = connection.execute('UPDATE volumes SET active = NULL, retired = 1 WHERE id = ? AND retired = 0',
                                (volume_id,))
    if cursor.rowcount != 1:
        raise VolumeUnavailable(f'volume {volume_id!r} is unavailable')


def drop_encoding(connection, encoding_id):
    connection.execute('DELETE FROM encodings WHERE id = ?', (encoding_id,))
