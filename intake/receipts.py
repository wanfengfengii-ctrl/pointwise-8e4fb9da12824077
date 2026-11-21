from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    receipt_id: int
    batch: str
    revision_id: int


def initialize_submission_receipts(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS submission_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch TEXT NOT NULL UNIQUE,
            revision INTEGER NOT NULL UNIQUE REFERENCES revisions(id)
        )
    ''')


def write_submission_receipt(connection, batch, revision):
    cursor = connection.execute(
        'INSERT INTO submission_receipts(batch, revision) VALUES (?, ?)', (batch, revision)
    )
    return SubmissionReceipt(cursor.lastrowid, batch, revision)
