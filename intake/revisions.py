import sqlite3

from errors import InvalidSubmission, UnknownRevision
from intake.receipts import write_submission_receipt
from intake.store import insert_source_rows, load_revision, save_revision
from intake.validate import validate_correction, validate_submission
from workspace import transaction


def apply_correction(parent_rows, hunks):
    """Apply validated hunks, all indexed against the same frozen parent."""
    rows = []
    cursor = 0
    for hunk in hunks:
        rows.extend(parent_rows[cursor:hunk.start])
        rows.extend(hunk.rows)
        cursor = hunk.stop
    rows.extend(parent_rows[cursor:])
    return tuple(rows)


def ingest(root, batch, rows=None, *, parent=None, corrections=None):
    """Accept an initial recording or one whole correction and return its receipt."""
    initial = parent is None
    if initial:
        if rows is None or corrections is not None:
            raise InvalidSubmission('initial submission requires rows only')
        additions = validate_submission(batch, rows)
    elif rows is not None or corrections is None:
        raise InvalidSubmission('correction requires a fixed parent and hunks')

    try:
        with transaction(root, write=True) as connection:
            if initial:
                frozen = additions
            else:
                parent_rows = load_revision(connection, parent)
                hunks, additions = validate_correction(batch, parent_rows, corrections)
                frozen = apply_correction(parent_rows, hunks)
            existing = connection.execute('SELECT id FROM revisions WHERE batch = ?', (batch,)).fetchone()
            if existing is not None:
                raise InvalidSubmission('source batch has already been submitted')
            insert_source_rows(connection, additions)
            revision = save_revision(connection, batch, parent, frozen)
            return write_submission_receipt(connection, batch, revision)
    except UnknownRevision as exc:
        raise InvalidSubmission('correction parent is unavailable') from exc
    except sqlite3.IntegrityError as exc:
        raise InvalidSubmission('submission conflicts with stored origins or revisions') from exc
