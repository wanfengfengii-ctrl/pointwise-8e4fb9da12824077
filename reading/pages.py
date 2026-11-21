from dataclasses import dataclass
from itertools import islice

from errors import DecodeError
from intake.records import SourceRow
from reading.tickets import Ticket, encode_ticket


@dataclass(frozen=True, slots=True)
class Page:
    volume_id: int
    rows: tuple[SourceRow, ...]
    next_ticket: str | None


def assemble_page(volume_id, decoded, start, row_count, page_size, key):
    count = min(page_size, row_count - start)
    result = tuple(islice(decoded, count))
    if len(result) != count or any(item.position != start + offset for offset, item in enumerate(result)):
        raise DecodeError('page does not cover the requested rows')
    next_ticket = None
    if start + count < row_count:
        last = result[-1]
        ticket = Ticket(volume_id, last.address.encoding_id, last.address.frame_no, last.offset + 1)
        next_ticket = encode_ticket(ticket, key)
    return Page(volume_id, tuple(item.row for item in result), next_ticket)
