from dataclasses import dataclass
import json

from errors import DecodeError
from intake.records import RowOrigin, SourceRow


@dataclass(frozen=True, slots=True)
class FrameAddress:
    encoding_id: int
    frame_no: int


@dataclass(frozen=True, slots=True)
class LiteralFrame:
    start: int
    rows: tuple[SourceRow, ...]


@dataclass(frozen=True, slots=True)
class ReferenceFrame:
    start: int
    address: FrameAddress
    offset: int
    length: int


def frame_length(frame):
    return len(frame.rows) if isinstance(frame, LiteralFrame) else frame.length


def encode_frame(frame):
    if isinstance(frame, LiteralFrame):
        record = {
            'start': frame.start,
            'rows': [[row.origin.batch, row.origin.line,
                      None if row.value is None else format(row.value, 'x')] for row in frame.rows],
        }
    else:
        record = {
            'start': frame.start,
            'ref': [frame.address.encoding_id, frame.address.frame_no],
            'offset': frame.offset,
            'length': frame.length,
        }
    return json.dumps(record, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('ascii')


def _number(value, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid frame coordinate')
    return value


def _decode_row(record):
    if not isinstance(record, list) or len(record) != 3:
        raise ValueError('invalid literal row')
    batch, line, encoded = record
    if not all(isinstance(label, str) and label.strip() for label in (batch, line)):
        raise ValueError('invalid row origin')
    if encoded is None:
        value = None
    else:
        if not isinstance(encoded, str):
            raise ValueError('invalid encoded reading')
        value = int(encoded, 16)
        if format(value, 'x') != encoded:
            raise ValueError('invalid encoded reading')
    return SourceRow(RowOrigin(batch, line), value)


def decode_frame_record(data):
    try:
        record = json.loads(data)
        if not isinstance(record, dict):
            raise ValueError('expected frame object')
        start = _number(record.get('start'), 0)
        if record.keys() == {'start', 'rows'}:
            rows = record['rows']
            if not isinstance(rows, list) or not rows:
                raise ValueError('empty or invalid literal frame')
            return LiteralFrame(start, tuple(_decode_row(row) for row in rows))
        if record.keys() == {'start', 'ref', 'offset', 'length'}:
            reference = record['ref']
            if not isinstance(reference, list) or len(reference) != 2:
                raise ValueError('invalid reference address')
            address = FrameAddress(_number(reference[0], 1), _number(reference[1], 0))
            return ReferenceFrame(start, address, _number(record['offset'], 0), _number(record['length'], 1))
        raise ValueError('unrecognized frame fields')
    except (TypeError, ValueError) as exc:
        raise DecodeError('invalid frame record') from exc


def validate_frame_layout(spans, row_count):
    cursor = 0
    for start, count in spans:
        if start != cursor or type(count) is not int or count <= 0:
            raise DecodeError('frame layout has a gap, overlap or empty frame')
        cursor += count
    if cursor != row_count:
        raise DecodeError('frame layout does not cover the declared volume')
