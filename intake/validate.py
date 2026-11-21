from dataclasses import dataclass

from errors import InvalidSubmission
from intake.records import CorrectionHunk, RowOrigin, SourceRow


@dataclass(frozen=True, slots=True)
class ResolvedHunk:
    start: int
    stop: int
    rows: tuple[SourceRow, ...]


def _label(value):
    if not isinstance(value, str) or not value.strip():
        raise InvalidSubmission('source batch and line labels must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise InvalidSubmission('source labels must be valid Unicode') from exc


def _origin(origin):
    if not isinstance(origin, RowOrigin):
        raise InvalidSubmission('expected a source origin')
    _label(origin.batch)
    _label(origin.line)


def _new_row(batch, row, seen):
    if not isinstance(row, SourceRow):
        raise InvalidSubmission('expected a new source row')
    _origin(row.origin)
    if row.origin.batch != batch or row.origin in seen:
        raise InvalidSubmission('new origins must be unique and belong to this submission')
    if row.value is not None and type(row.value) is not int:
        raise InvalidSubmission('a reading must be an integer or None')
    seen.add(row.origin)
    return row


def _items(items, label):
    if isinstance(items, (str, bytes, dict)):
        raise InvalidSubmission(f'{label} must be an ordered collection')
    try:
        return tuple(items)
    except TypeError as exc:
        raise InvalidSubmission(f'{label} must be an ordered collection') from exc


def validate_submission(batch, rows):
    _label(batch)
    seen = set()
    return tuple(_new_row(batch, row, seen) for row in _items(rows, 'rows'))


def _parent_index(index, origin):
    _origin(origin)
    try:
        return index[origin]
    except KeyError as exc:
        raise InvalidSubmission(f'unknown parent origin {origin.batch}/{origin.line}') from exc


def validate_correction(batch, parent_rows, corrections):
    _label(batch)
    corrections = _items(corrections, 'corrections')
    if not corrections:
        raise InvalidSubmission('a correction needs at least one hunk')
    index = {row.origin: position for position, row in enumerate(parent_rows)}
    added_origins = set()
    resolved = []
    additions = []
    for hunk in corrections:
        if not isinstance(hunk, CorrectionHunk):
            raise InvalidSubmission('expected a correction hunk')
        targets = _items(hunk.targets, 'targets')
        replacement = _items(hunk.replacement, 'replacement')
        if targets:
            if hunk.before is not None:
                raise InvalidSubmission('a replacement cannot also specify an insertion anchor')
            positions = tuple(_parent_index(index, origin) for origin in targets)
            start = positions[0]
            stop = start + len(positions)
            if positions != tuple(range(start, stop)):
                raise InvalidSubmission('targets must be a contiguous parent range in parent order')
        else:
            if not replacement:
                raise InvalidSubmission('an insertion requires new rows')
            start = len(parent_rows) if hunk.before is None else _parent_index(index, hunk.before)
            stop = start

        kept = set()
        rows = []
        for item in replacement:
            if isinstance(item, RowOrigin):
                position = _parent_index(index, item)
                if not start <= position < stop or item in kept:
                    raise InvalidSubmission('a kept origin must occur once within the replaced range')
                kept.add(item)
                rows.append(parent_rows[position])
            else:
                rows.append(_new_row(batch, item, added_origins))
                additions.append(item)
        resolved.append(ResolvedHunk(start, stop, tuple(rows)))

    resolved.sort(key=lambda hunk: hunk.start)
    for left, right in zip(resolved, resolved[1:]):
        if left.start == right.start or left.stop > right.start:
            raise InvalidSubmission('correction hunks conflict in the parent revision')
    return tuple(resolved), tuple(additions)
