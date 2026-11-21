from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from archive.catalog import get_encoding, get_volume
from archive.files import frame_path, volume_path
from archive.frames import FrameAddress
from archive.issue import issue
from audit.counts import ReadingTotals
from audit.history import get_report
from audit.origins import OriginEntry
from audit.report import reconcile
from demo import build_sample
from errors import PublicationAborted, VolumeUnavailable
from intake.records import CorrectionHunk, RowOrigin, SourceRow
from intake.revisions import ingest
from reading.open import read_page
from reading.tickets import get_ticket_key, parse_ticket
from retention.receipts import find_retirement_receipt
from retention.retire import retire
from workspace import initialize, transaction


PROJECT = Path(__file__).resolve().parents[1]
A = SourceRow(RowOrigin('recording', 'A'), 7)
B = SourceRow(RowOrigin('recording', 'B'), 7)
C = SourceRow(RowOrigin('correction-1', 'C'), 11)
D = SourceRow(RowOrigin('correction-2', 'D'), 7)


class RetireShiftTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.r0, self.r1, self.r2 = build_sample(self.root)

    def _encoding(self, volume):
        with transaction(self.root) as connection:
            return get_encoding(connection, get_volume(connection, volume).encoding_id)

    def _old_ticket(self):
        first = read_page(self.root, self.r1, 1)
        self.assertEqual(first.rows, (A,))
        self.assertIsNotNone(first.next_ticket)
        return first.next_ticket

    def _files(self):
        return {path.name: path.read_bytes() for path in (self.root / 'volumes').iterdir()}

    def _child(self, command, *args):
        result = subprocess.run(
            [sys.executable, '-B', 'demo.py', command, str(self.root), *map(str, args)],
            cwd=PROJECT, capture_output=True, text=True, timeout=15, check=True,
        )
        return json.loads(result.stdout)

    def test_retire_transitive_base(self):
        old = [self._encoding(volume) for volume in (self.r0, self.r1, self.r2)]
        self.assertEqual(old[1].frames[0].source_encoding, old[0].encoding_id)
        self.assertEqual(old[2].frames[0].source_encoding, old[1].encoding_id)
        self.assertEqual(read_page(self.root, self.r0, 5).rows, (A, B))
        self.assertEqual(read_page(self.root, self.r2, 5).rows, (C, D))
        ticket = self._old_ticket()
        receipt = retire(self.root, self.r0)
        self.assertEqual(find_retirement_receipt(self.root, self.r0), receipt)
        self.assertEqual(receipt.volume_id, self.r0)
        with self.assertRaises(VolumeUnavailable):
            read_page(self.root, self.r0, 5)
        for encoding in old:
            self.assertFalse(volume_path(self.root, encoding.encoding_id).exists())
            for info in encoding.frames:
                self.assertFalse(frame_path(self.root, FrameAddress(encoding.encoding_id, info.number)).exists())
        rows_on_disk = []
        for path in (self.root / 'volumes').glob('*.frame'):
            rows_on_disk.extend(json.loads(path.read_bytes()).get('rows', ()))
        self.assertNotIn(['recording', 'B', '7'], rows_on_disk)
        self.assertIn(['recording', 'A', '7'], rows_on_disk)
        self.assertIn(['correction-2', 'D', '7'], rows_on_disk)
        self.assertEqual(read_page(self.root, self.r2, 5).rows, (C, D))
        tail = read_page(self.root, self.r1, 5, ticket)
        self.assertEqual(tail.rows, (C,))
        self.assertIsNone(tail.next_ticket)
        self.assertEqual(self._child('page', self.r1, 5, ticket), json.loads(json.dumps(asdict(tail))))
        self.assertEqual([row['origin']['line'] for row in self._child('page', self.r2, 5)['rows']], ['C', 'D'])
        self.assertEqual(reconcile(self.root, self.r2).totals, ReadingTotals(2, 0, 18))

    def test_retirement_handoff_incident(self):
        # INCIDENT.md: the night shift keeps the R1 ticket and QC signs R2
        # before R0 retires; after the handoff and a reopen every retained
        # volume must still deliver its original sequence.
        first = read_page(self.root, self.r1, 1)
        self.assertEqual(first.rows, (A,))
        self.assertIsNotNone(first.next_ticket)
        ticket = first.next_ticket
        signed = reconcile(self.root, self.r2)
        self.assertEqual(signed.totals, ReadingTotals(2, 0, 18))
        self.assertEqual(signed.origins, (OriginEntry(1, C.origin), OriginEntry(2, D.origin)))
        old = [self._encoding(volume) for volume in (self.r0, self.r1, self.r2)]
        self.assertEqual(old[2].frames[0].source_encoding, old[1].encoding_id)
        receipt = retire(self.root, self.r0)
        initialize(self.root)
        self.assertEqual(find_retirement_receipt(self.root, self.r0), receipt)
        with self.assertRaises(VolumeUnavailable):
            read_page(self.root, self.r0, 5)
        for encoding in old:
            self.assertFalse(volume_path(self.root, encoding.encoding_id).exists())
            for info in encoding.frames:
                self.assertFalse(frame_path(self.root, FrameAddress(encoding.encoding_id, info.number)).exists())
        rows_on_disk = []
        for path in (self.root / 'volumes').glob('*.frame'):
            rows_on_disk.extend(json.loads(path.read_bytes()).get('rows', ()))
        self.assertNotIn(['recording', 'B', '7'], rows_on_disk)
        # R2 reads from the head and reconciles to the same 18 newtons.
        self.assertEqual(read_page(self.root, self.r2, 5).rows, (C, D))
        again = reconcile(self.root, self.r2)
        self.assertEqual(again.totals, ReadingTotals(2, 0, 18))
        self.assertEqual(again.origins, (OriginEntry(1, C.origin), OriginEntry(2, D.origin)))
        # The pre-retirement R1 ticket continues at C and reaches the end,
        # in this process and in a fresh one.
        tail = read_page(self.root, self.r1, 5, ticket)
        self.assertEqual(tail.rows, (C,))
        self.assertIsNone(tail.next_ticket)
        self.assertEqual(self._child('page', self.r1, 5, ticket), json.loads(json.dumps(asdict(tail))))
        # The report signed before retirement is unchanged.
        self.assertEqual(get_report(self.root, signed.report_id), signed)

    def test_signed_report_stays_fixed(self):
        signed = reconcile(self.root, self.r2)
        self.assertEqual(signed.totals, ReadingTotals(2, 0, 18))
        self.assertEqual(signed.origins, (OriginEntry(1, C.origin), OriginEntry(2, D.origin)))
        retire(self.root, self.r0)
        self.assertEqual(get_report(self.root, signed.report_id), signed)
        self.assertEqual(self._child('report', signed.report_id), json.loads(json.dumps(asdict(signed))))

    def test_failed_retirement_keeps_reads(self):
        ticket = self._old_ticket()
        original_files = self._files()
        signed = reconcile(self.root, self.r2)
        original = tuple(self._encoding(volume) for volume in (self.r0, self.r1, self.r2))
        reached = []

        def abort_publication():
            reached.append(not volume_path(self.root, original[0].encoding_id).exists())
            raise PublicationAborted('fixture stops before commit')

        with self.assertRaisesRegex(PublicationAborted, 'fixture stops before commit'):
            retire(self.root, self.r0, before_commit=abort_publication)
        self.assertEqual(reached, [True])
        initialize(self.root)
        self.assertEqual(self._files(), original_files)
        self.assertEqual(tuple(self._encoding(volume) for volume in (self.r0, self.r1, self.r2)), original)
        self.assertEqual(read_page(self.root, self.r0, 5).rows, (A, B))
        self.assertEqual(read_page(self.root, self.r2, 5).rows, (C, D))
        self.assertEqual(read_page(self.root, self.r1, 5, ticket).rows, (C,))
        self.assertEqual(self._child('page', self.r1, 5, ticket)['rows'][0]['origin']['line'], 'C')
        self.assertEqual(get_report(self.root, signed.report_id), signed)
        self.assertIsNone(find_retirement_receipt(self.root, self.r0))
        self.assertEqual(retire(self.root, self.r0).volume_id, self.r0)

    def test_leaf_retirement(self):
        encoding = self._encoding(self.r2)
        receipt = retire(self.root, self.r2)
        initialize(self.root)
        self.assertEqual(find_retirement_receipt(self.root, self.r2), receipt)
        self.assertFalse(volume_path(self.root, encoding.encoding_id).exists())
        self.assertEqual(read_page(self.root, self.r1, 5).rows, (A, C))
        self.assertEqual(read_page(self.root, self.r0, 5).rows, (A, B))
        with self.assertRaises(VolumeUnavailable):
            read_page(self.root, self.r2, 5)

    def test_retained_detached(self):
        retire(self.root, self.r0)
        r1 = self._encoding(self.r1)
        r2 = self._encoding(self.r2)
        self.assertTrue(all(frame.source_encoding is None for frame in r1.frames + r2.frames))
        self.assertEqual(read_page(self.root, self.r1, 5).rows, (A, C))
        self.assertEqual(read_page(self.root, self.r2, 5).rows, (C, D))
        retire(self.root, self.r1)
        self.assertEqual(read_page(self.root, self.r2, 5).rows, (C, D))

    def test_old_frame_reopen(self):
        ticket = self._old_ticket()
        original = self._encoding(self.r1)
        with transaction(self.root) as connection:
            fields = parse_ticket(ticket, get_ticket_key(connection))
        self.assertEqual((fields.encoding_id, fields.frame_no, fields.after), (original.encoding_id, 0, 1))
        self.assertEqual([(frame.start, frame.count) for frame in original.frames], [(0, 1), (1, 1)])
        retire(self.root, self.r0)
        self.assertEqual([(frame.start, frame.count) for frame in self._encoding(self.r1).frames], [(0, 2)])
        result = self._child('page', self.r1, 1, ticket)
        self.assertEqual(result['rows'], [{'origin': {'batch': 'correction-1', 'line': 'C'}, 'value': 11}])
        self.assertIsNone(result['next_ticket'])

    def test_reported_leaf_retired(self):
        signed = reconcile(self.root, self.r2)
        retire(self.root, self.r0)
        retire(self.root, self.r2)
        with self.assertRaises(VolumeUnavailable):
            read_page(self.root, self.r2, 5)
        self.assertEqual(self._child('report', signed.report_id), json.loads(json.dumps(asdict(signed))))
        self.assertEqual(get_report(self.root, signed.report_id).totals, ReadingTotals(2, 0, 18))

    def test_old_ticket_followed_by_inherited_row_and_missing(self):
        with transaction(self.root) as connection:
            original_revision = get_volume(connection, self.r0).revision_id
        x = SourceRow(RowOrigin('late', 'X'), 7)
        missing = SourceRow(RowOrigin('late', 'M'), None)
        zero = SourceRow(RowOrigin('late', 'Z'), 0)
        correction = ingest(self.root, 'late', parent=original_revision, corrections=(
            CorrectionHunk((), (x,), before=A.origin),
            CorrectionHunk((B.origin,), (missing, zero)),
        ))
        late = issue(self.root, correction.revision_id, self.r0)
        first = read_page(self.root, late, 1)
        self.assertEqual(first.rows, (x,))
        self.assertIsNotNone(first.next_ticket)
        retire(self.root, self.r0)
        remainder = []
        ticket = first.next_ticket
        for _ in range(3):
            self.assertIsNotNone(ticket)
            page = read_page(self.root, late, 1, ticket)
            remainder.extend(page.rows)
            ticket = page.next_ticket
        self.assertIsNone(ticket)
        self.assertEqual(remainder, [A, missing, zero])
        report = reconcile(self.root, late)
        self.assertEqual(report.totals, ReadingTotals(4, 1, 14))
        self.assertEqual([item.origin for item in report.origins], [x.origin, A.origin, missing.origin, zero.origin])
