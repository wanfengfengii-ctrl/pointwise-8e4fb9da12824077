from dataclasses import dataclass

from intake.records import RowOrigin


@dataclass(frozen=True, slots=True)
class OriginEntry:
    position: int
    origin: RowOrigin


def collect_origins(decoded_rows):
    return tuple(OriginEntry(item.position + 1, item.row.origin) for item in decoded_rows)
