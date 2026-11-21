from dataclasses import dataclass

from archive.catalog import get_encoding
from errors import TicketError
from reading.tickets import validate_ticket_volume


@dataclass(frozen=True, slots=True)
class ResumePosition:
    encoding_id: int
    logical_index: int


def initialize_resume_history(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS replacement_history (
            volume INTEGER NOT NULL REFERENCES volumes(id),
            old_encoding INTEGER NOT NULL,
            new_encoding INTEGER NOT NULL,
            PRIMARY KEY (volume, old_encoding)
        )
    ''')


def _active_successor(connection, volume_id, encoding_id):
    """Follow replacement history from an issuing encoding to the active one."""
    seen = {encoding_id}
    current = encoding_id
    while True:
        record = connection.execute(
            'SELECT new_encoding FROM replacement_history WHERE volume = ? AND old_encoding = ?',
            (volume_id, current),
        ).fetchone()
        if record is None:
            return current
        current = record['new_encoding']
        if current in seen:
            raise TicketError('encoding replacement history forms a cycle')
        seen.add(current)


def resolve_resume(connection, volume, ticket):
    validate_ticket_volume(ticket, volume.volume_id)
    issuing = get_encoding(connection, ticket.encoding_id)
    if issuing.volume_id != volume.volume_id:
        raise TicketError("issuing encoding belongs to another volume")
    if not 0 <= ticket.frame_no < len(issuing.frames):
        raise TicketError("ticket frame is outside the issuing layout")
    info = issuing.frames[ticket.frame_no]
    if not 1 <= ticket.after <= info.count:
        raise TicketError("ticket boundary is outside its issuing frame")
    boundary = info.start + ticket.after
    if not 0 < boundary < issuing.row_count:
        raise TicketError("ticket has no next row in this volume")
    encoding_id = _active_successor(connection, volume.volume_id, issuing.encoding_id)
    return ResumePosition(encoding_id, boundary)
