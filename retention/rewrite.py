from dataclasses import dataclass

from archive.catalog import EncodingEntry, get_encoding, register_encoding
from archive.issue import build_full_frames
from errors import RetirementError
from intake.records import SourceRow
from reading.decode import iter_decoded_rows


@dataclass(frozen=True, slots=True)
class Replacement:
    original: EncodingEntry
    staged: EncodingEntry
    original_rows: tuple[SourceRow, ...]


@dataclass(frozen=True, slots=True)
class ReplacementSet:
    items: tuple[Replacement, ...]


def stage_replacements(connection, root, files, scope):
    items = []
    for volume in scope.dependents:
        original = get_encoding(connection, volume.encoding_id)
        rows = tuple(item.row for item in iter_decoded_rows(connection, root, original.encoding_id))
        frames = build_full_frames(rows, frame_rows=64)
        staged = register_encoding(connection, volume.volume_id, frames, len(rows))
        files.write_encoding(staged, frames)
        items.append(Replacement(original, staged, rows))
    return ReplacementSet(tuple(items))


def check_replacements(connection, root, scope, replacements):
    expected = tuple(volume.encoding_id for volume in scope.dependents)
    if tuple(item.original.encoding_id for item in replacements.items) != expected:
        raise RetirementError('replacement set does not cover the assessed obligations')
    for item in replacements.items:
        candidate = get_encoding(connection, item.staged.encoding_id)
        if candidate.volume_id != item.original.volume_id or candidate.row_count != item.original.row_count:
            raise RetirementError('replacement belongs to a different fixed result')
        if any(info.source_encoding is not None for info in candidate.frames):
            raise RetirementError('replacement must be independently decodable')
        actual = tuple(decoded.row for decoded in iter_decoded_rows(connection, root, candidate.encoding_id))
        if actual != item.original_rows:
            raise RetirementError('replacement changed the original sequence, readings, or origins')
