from errors import InvalidSubmission, UnknownRevision
from intake.records import RowOrigin, SourceRow
from workspace import valid_id


def initialize_intake(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS source_rows (
            batch TEXT NOT NULL, line TEXT NOT NULL, value_hex TEXT,
            PRIMARY KEY (batch, line)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent INTEGER REFERENCES revisions(id),
            batch TEXT NOT NULL UNIQUE
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS revision_members (
            revision INTEGER NOT NULL REFERENCES revisions(id),
            position INTEGER NOT NULL,
            batch TEXT NOT NULL,
            line TEXT NOT NULL,
            PRIMARY KEY (revision, position),
            UNIQUE (revision, batch, line),
            FOREIGN KEY (batch, line) REFERENCES source_rows(batch, line)
        )
    ''')


def _source(record):
    value_hex = record['value_hex']
    value = None if value_hex is None else int(value_hex, 16)
    return SourceRow(RowOrigin(record['batch'], record['line']), value)


def load_source_row(connection, origin):
    record = connection.execute(
        'SELECT batch, line, value_hex FROM source_rows WHERE batch = ? AND line = ?',
        (origin.batch, origin.line),
    ).fetchone()
    if record is None:
        raise InvalidSubmission(f'unknown source origin {origin.batch}/{origin.line}')
    return _source(record)


def insert_source_rows(connection, rows):
    connection.executemany(
        'INSERT INTO source_rows(batch, line, value_hex) VALUES (?, ?, ?)',
        ((row.origin.batch, row.origin.line, None if row.value is None else format(row.value, 'x'))
         for row in rows),
    )


def save_revision(connection, batch, parent, rows):
    cursor = connection.execute('INSERT INTO revisions(parent, batch) VALUES (?, ?)', (parent, batch))
    revision = cursor.lastrowid
    connection.executemany(
        'INSERT INTO revision_members(revision, position, batch, line) VALUES (?, ?, ?, ?)',
        ((revision, position, row.origin.batch, row.origin.line) for position, row in enumerate(rows)),
    )
    return revision


def load_revision(connection, revision):
    if not valid_id(revision) or connection.execute(
        'SELECT id FROM revisions WHERE id = ?', (revision,)
    ).fetchone() is None:
        raise UnknownRevision(f'unknown revision {revision!r}')
    records = connection.execute('''
        SELECT source.batch, source.line, source.value_hex
        FROM revision_members AS member
        JOIN source_rows AS source USING (batch, line)
        WHERE member.revision = ?
        ORDER BY member.position
    ''', (revision,))
    return tuple(_source(record) for record in records)
