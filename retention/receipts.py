from dataclasses import dataclass

from workspace import transaction, valid_id


@dataclass(frozen=True, slots=True)
class RetirementReceipt:
    receipt_id: int
    volume_id: int


def initialize_retirement_receipts(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS retirement_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume INTEGER NOT NULL UNIQUE REFERENCES volumes(id)
        )
    ''')


def write_retirement_receipt(connection, volume_id):
    cursor = connection.execute('INSERT INTO retirement_receipts(volume) VALUES (?)', (volume_id,))
    return RetirementReceipt(cursor.lastrowid, volume_id)


def find_retirement_receipt(root, volume_id):
    if not valid_id(volume_id):
        return None
    with transaction(root) as connection:
        record = connection.execute('SELECT id FROM retirement_receipts WHERE volume = ?', (volume_id,)).fetchone()
        return None if record is None else RetirementReceipt(record['id'], volume_id)
