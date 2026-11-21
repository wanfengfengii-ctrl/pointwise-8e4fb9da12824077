from archive.catalog import get_encoding, get_volume
from errors import DecodeError
from reading.decode import iter_decoded_rows
from reading.pages import assemble_page
from reading.resume import ResumePosition, resolve_resume
from reading.tickets import get_ticket_key, parse_ticket
from workspace import transaction


def read_page(root, volume_id, page_size, ticket=None):
    """Read a fixed volume page or replay its continuation ticket."""
    if type(page_size) is not int or page_size <= 0:
        raise ValueError('page size must be a positive integer')
    with transaction(root) as connection:
        volume = get_volume(connection, volume_id)
        key = get_ticket_key(connection)
        if ticket is None:
            position = ResumePosition(volume.encoding_id, 0)
        else:
            position = resolve_resume(connection, volume, parse_ticket(ticket, key))
        encoding = get_encoding(connection, position.encoding_id)
        if encoding.volume_id != volume.volume_id:
            raise DecodeError('selected encoding belongs to another volume')
        decoded = iter_decoded_rows(connection, root, position.encoding_id, start=position.logical_index)
        return assemble_page(volume_id, decoded, position.logical_index, encoding.row_count, page_size, key)
