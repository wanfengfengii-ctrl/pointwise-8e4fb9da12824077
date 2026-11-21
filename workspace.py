from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3


def valid_id(value):
    return type(value) is int and 0 < value <= (1 << 63) - 1


@contextmanager
def transaction(root, *, write=False, create=False):
    database = Path(root) / 'catalog.sqlite3'
    if not create and not database.is_file():
        raise FileNotFoundError(database)
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def initialize(root):
    """Create an empty workspace or open an existing one without resetting it."""
    from archive.catalog import initialize_catalog
    from audit.history import initialize_report_history
    from intake.receipts import initialize_submission_receipts
    from intake.store import initialize_intake
    from reading.resume import initialize_resume_history
    from reading.tickets import initialize_ticket_key
    from retention.receipts import initialize_retirement_receipts

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'volumes').mkdir(exist_ok=True)
    with transaction(root, write=True, create=True) as connection:
        initialize_intake(connection)
        initialize_submission_receipts(connection)
        initialize_catalog(connection)
        initialize_ticket_key(connection)
        initialize_resume_history(connection)
        initialize_report_history(connection)
        initialize_retirement_receipts(connection)
    return root
