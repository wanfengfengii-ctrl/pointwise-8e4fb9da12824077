from dataclasses import dataclass
import json

from audit.counts import ReadingTotals
from audit.origins import OriginEntry
from errors import ReportNotFound
from intake.records import RowOrigin
from workspace import transaction, valid_id


@dataclass(frozen=True, slots=True)
class SignedReport:
    report_id: int
    volume_id: int
    totals: ReadingTotals
    origins: tuple[OriginEntry, ...]


def initialize_report_history(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume INTEGER NOT NULL REFERENCES volumes(id),
            row_count INTEGER NOT NULL,
            missing_count INTEGER NOT NULL,
            total_hex TEXT NOT NULL,
            origin_snapshot TEXT NOT NULL
        )
    ''')


def save_report(connection, volume_id, totals, origins):
    snapshot = json.dumps([[item.position, item.origin.batch, item.origin.line] for item in origins],
                          separators=(',', ':'))
    cursor = connection.execute('''
        INSERT INTO reports(volume, row_count, missing_count, total_hex, origin_snapshot)
        VALUES (?, ?, ?, ?, ?)
    ''', (volume_id, totals.total_rows, totals.missing_rows, format(totals.total, 'x'), snapshot))
    return SignedReport(cursor.lastrowid, volume_id, totals, tuple(origins))


def get_report(root, report_id):
    if not valid_id(report_id):
        raise ReportNotFound(f'unknown report {report_id!r}')
    with transaction(root) as connection:
        record = connection.execute('SELECT * FROM reports WHERE id = ?', (report_id,)).fetchone()
        if record is None:
            raise ReportNotFound(f'unknown report {report_id!r}')
        totals = ReadingTotals(record['row_count'], record['missing_count'], int(record['total_hex'], 16))
        origins = tuple(OriginEntry(position, RowOrigin(batch, line))
                        for position, batch, line in json.loads(record['origin_snapshot']))
        return SignedReport(report_id, record['volume'], totals, origins)
