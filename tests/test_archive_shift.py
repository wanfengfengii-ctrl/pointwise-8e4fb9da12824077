from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from archive.catalog import get_encoding, get_volume
from archive.issue import issue
from errors import InvalidSubmission, IssueError
from intake.records import CorrectionHunk, RowOrigin, SourceRow
from intake.revisions import ingest
from intake.store import load_source_row
from reading.open import read_page
from workspace import initialize, transaction


class ArchiveShiftTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = initialize(Path(temp.name))
        self.a = SourceRow(RowOrigin('recording', 'A'), 7)
        self.b = SourceRow(RowOrigin('recording', 'B'), 7)
        self.c = SourceRow(RowOrigin('correction', 'C'), 11)

    def _counts(self):
        with transaction(self.root) as connection:
            return tuple(connection.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                         for name in ('source_rows', 'revisions', 'submission_receipts', 'volumes'))

    def test_revision_keeps_line_origin(self):
        original = ingest(self.root, 'recording', (self.a, self.b))
        r0 = issue(self.root, original.revision_id)
        corrected = ingest(self.root, 'correction', parent=original.revision_id,
                           corrections=(CorrectionHunk((self.b.origin,), (self.c,)),))
        r1 = issue(self.root, corrected.revision_id, r0)
        self.assertEqual(read_page(self.root, r0, 5).rows, (self.a, self.b))
        self.assertEqual(read_page(self.root, r1, 5).rows, (self.a, self.c))
        self.assertNotEqual(self.a.origin, self.b.origin)
        self.assertEqual(original.batch, 'recording')
        self.assertEqual(corrected.batch, 'correction')
        with transaction(self.root) as connection:
            base = get_volume(connection, r0)
            delta = get_encoding(connection, get_volume(connection, r1).encoding_id)
            self.assertEqual([info.source_encoding for info in delta.frames], [base.encoding_id, None])
            self.assertEqual(load_source_row(connection, self.b.origin), self.b)

    def test_bad_correction_is_atomic(self):
        initial = ingest(self.root, 'recording', (self.a, self.b))
        before = self._counts()
        with self.assertRaises(InvalidSubmission):
            ingest(self.root, 'correction', parent=initial.revision_id, corrections=(
                CorrectionHunk((self.b.origin,), (self.c,)),
                CorrectionHunk((RowOrigin('recording', 'unknown'),), ()),
            ))
        self.assertEqual(self._counts(), before)
        volume = issue(self.root, initial.revision_id)
        self.assertEqual(read_page(self.root, volume, 5).rows, (self.a, self.b))
        accepted = ingest(self.root, 'correction', parent=initial.revision_id,
                          corrections=(CorrectionHunk((self.b.origin,), (self.c,)),))
        self.assertEqual(accepted.batch, 'correction')

    def test_noncontiguous_references(self):
        c = SourceRow(RowOrigin('recording', 'C'), 7)
        d = SourceRow(RowOrigin('correction', 'D'), -2)
        initial = ingest(self.root, 'recording', (self.a, self.b, c))
        base = issue(self.root, initial.revision_id, frame_rows=3)
        edited = ingest(self.root, 'correction', parent=initial.revision_id, corrections=(
            CorrectionHunk((self.b.origin, c.origin), (c.origin,)),
            CorrectionHunk((), (d,)),
        ))
        delta = issue(self.root, edited.revision_id, base)
        self.assertEqual(read_page(self.root, delta, 5).rows, (self.a, c, d))
        with transaction(self.root) as connection:
            base_encoding = get_volume(connection, base).encoding_id
            info = get_encoding(connection, get_volume(connection, delta).encoding_id).frames
            self.assertEqual([(item.start, item.count, item.source_encoding) for item in info],
                             [(0, 1, base_encoding), (1, 1, base_encoding), (2, 1, None)])

    def test_reopen_initialization(self):
        base = ingest(self.root, 'recording', (self.a, self.b))
        old_volume = issue(self.root, base.revision_id)
        edited = ingest(self.root, 'correction', parent=base.revision_id,
                        corrections=(CorrectionHunk((), (self.c,), before=self.a.origin),))
        new_volume = issue(self.root, edited.revision_id, old_volume)
        before = self._counts()
        initialize(self.root)
        initialize(self.root)
        self.assertEqual(self._counts(), before)
        self.assertEqual(read_page(self.root, old_volume, 5).rows, (self.a, self.b))
        self.assertEqual(read_page(self.root, new_volume, 5).rows, (self.c, self.a, self.b))
        with self.assertRaises(InvalidSubmission):
            ingest(self.root, 'correction', ())
        self.assertEqual(self._counts(), before)

    def test_wrong_base_and_conflicting_hunks_do_not_publish(self):
        initial = ingest(self.root, 'recording', (self.a, self.b))
        volume = issue(self.root, initial.revision_id)
        before = self._counts()
        with self.assertRaises(IssueError):
            issue(self.root, initial.revision_id, volume)
        with self.assertRaises(IssueError):
            issue(self.root, initial.revision_id + 900)
        with self.assertRaises(InvalidSubmission):
            ingest(self.root, 'correction', parent=initial.revision_id, corrections=(
                CorrectionHunk((self.a.origin, self.b.origin), (self.c,)),
                CorrectionHunk((), (SourceRow(RowOrigin('correction', 'D'), 3),), before=self.b.origin),
            ))
        with self.assertRaises(InvalidSubmission):
            ingest(self.root, 'bad', (SourceRow(RowOrigin('bad', 'A'), True),))
        self.assertEqual(self._counts(), before)

    def test_empty_revision_and_exact_large_integers(self):
        from audit.report import reconcile

        empty = ingest(self.root, 'empty', ())
        volume = issue(self.root, empty.revision_id)
        self.assertEqual(read_page(self.root, volume, 1).rows, ())
        self.assertIsNone(read_page(self.root, volume, 1).next_ticket)
        self.assertEqual(reconcile(self.root, volume).totals.total_rows, 0)
        large = -(1 << 16000)
        row = SourceRow(RowOrigin('large', 'L'), large)
        receipt = ingest(self.root, 'large', (row,))
        volume = issue(self.root, receipt.revision_id)
        self.assertEqual(read_page(self.root, volume, 1).rows, (row,))
        self.assertEqual(reconcile(self.root, volume).totals.total, large)
