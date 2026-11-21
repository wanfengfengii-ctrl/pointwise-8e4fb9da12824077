from pathlib import Path
import json
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from archive.catalog import get_volume
from archive.files import frame_path
from archive.frames import FrameAddress
from archive.issue import issue
from audit.counts import ReadingTotals
from audit.history import get_report
from audit.origins import OriginEntry
from audit.report import reconcile
from errors import DecodeError, ReportNotFound, TicketError
from intake.records import RowOrigin, SourceRow
from intake.revisions import ingest
from reading.open import read_page
from workspace import initialize, transaction


PROJECT = Path(__file__).resolve().parents[1]


class ReadShiftTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = initialize(Path(temp.name))
        self.rows = tuple(SourceRow(RowOrigin('shift', line), value)
                          for line, value in (('A', 7), ('M', None), ('Z', 0)))
        self.revision = ingest(self.root, 'shift', self.rows).revision_id
        self.volume = issue(self.root, self.revision, frame_rows=2)

    def _report_count(self):
        with transaction(self.root) as connection:
            return connection.execute('SELECT count(*) FROM reports').fetchone()[0]

    def _frame(self, number):
        with transaction(self.root) as connection:
            encoding = get_volume(connection, self.volume).encoding_id
        return frame_path(self.root, FrameAddress(encoding, number))

    def test_page_through_missing_and_zero(self):
        page = read_page(self.root, self.volume, 2)
        self.assertEqual(page.rows, self.rows[:2])
        self.assertIsNotNone(page.next_ticket)
        tail = read_page(self.root, self.volume, 2, page.next_ticket)
        self.assertEqual(tail.rows, self.rows[2:])
        self.assertIsNone(tail.next_ticket)
        report = reconcile(self.root, self.volume)
        self.assertEqual(report.totals, ReadingTotals(3, 1, 7))
        self.assertEqual(report.origins, (OriginEntry(1, RowOrigin('shift', 'A')),
                                          OriginEntry(2, RowOrigin('shift', 'M')),
                                          OriginEntry(3, RowOrigin('shift', 'Z'))))
        self.assertEqual(get_report(self.root, report.report_id), report)

    def test_ticket_cannot_cross_volumes(self):
        another = issue(self.root, self.revision)
        ticket = read_page(self.root, self.volume, 1).next_ticket
        self.assertIsNotNone(ticket)
        with self.assertRaises(TicketError):
            read_page(self.root, another, 1, ticket)
        self.assertEqual(read_page(self.root, self.volume, 1, ticket).rows, (self.rows[1],))

    def test_resume_inside_frame(self):
        first = read_page(self.root, self.volume, 1)
        self.assertIsNotNone(first.next_ticket)
        second = read_page(self.root, self.volume, 1, first.next_ticket)
        self.assertIsNotNone(second.next_ticket)
        third = read_page(self.root, self.volume, 1, second.next_ticket)
        self.assertEqual([row.value for row in first.rows + second.rows + third.rows], [7, None, 0])
        self.assertEqual(first.rows + second.rows + third.rows, self.rows)
        self.assertIsNone(third.next_ticket)
        self.assertEqual(read_page(self.root, self.volume, 1, first.next_ticket), second)
        report = reconcile(self.root, self.volume)
        self.assertEqual([item.origin for item in report.origins], [row.origin for row in self.rows])

    def test_reopen_ticket(self):
        ticket = read_page(self.root, self.volume, 1).next_ticket
        self.assertIsNotNone(ticket)
        initialize(self.root)
        child = subprocess.run(
            [sys.executable, '-B', 'demo.py', 'page', str(self.root), str(self.volume), '2', ticket],
            cwd=PROJECT, capture_output=True, text=True, timeout=15, check=True,
        )
        self.assertEqual(json.loads(child.stdout), {
            'volume_id': self.volume,
            'rows': [{'origin': {'batch': 'shift', 'line': 'M'}, 'value': None},
                     {'origin': {'batch': 'shift', 'line': 'Z'}, 'value': 0}],
            'next_ticket': None,
        })

    def test_malformed_ticket(self):
        ticket = read_page(self.root, self.volume, 1).next_ticket
        self.assertIsNotNone(ticket)
        altered = ('A' if ticket[0] != 'A' else 'B') + ticket[1:]
        for bad in ('', '@@@', altered, ticket + '=', '票'):
            with self.subTest(ticket=bad), self.assertRaises(TicketError):
                read_page(self.root, self.volume, 1, bad)
        with self.assertRaises(ValueError):
            read_page(self.root, self.volume, 0)
        with self.assertRaises(ReportNotFound):
            get_report(self.root, 123)

    def test_incomplete_volume_does_not_issue_report(self):
        self._frame(0).unlink()
        with self.assertRaises(DecodeError):
            reconcile(self.root, self.volume)
        self.assertEqual(self._report_count(), 0)

    def test_missing_tail_frame(self):
        original = reconcile(self.root, self.volume)
        self._frame(1).unlink()
        prefix = read_page(self.root, self.volume, 2)
        self.assertEqual(prefix.rows, self.rows[:2])
        self.assertIsNotNone(prefix.next_ticket)
        with self.assertRaises(DecodeError):
            read_page(self.root, self.volume, 1, prefix.next_ticket)
        with self.assertRaises(DecodeError):
            reconcile(self.root, self.volume)
        self.assertEqual(self._report_count(), 1)
        self.assertEqual(get_report(self.root, original.report_id), original)

    def test_changed_frame_is_rejected(self):
        path = self._frame(0)
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(DecodeError):
            read_page(self.root, self.volume, 1)
        with self.assertRaises(DecodeError):
            reconcile(self.root, self.volume)
        self.assertEqual(self._report_count(), 0)
