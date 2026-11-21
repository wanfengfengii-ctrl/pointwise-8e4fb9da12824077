from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RowOrigin:
    batch: str
    line: str


@dataclass(frozen=True, slots=True)
class SourceRow:
    origin: RowOrigin
    value: int | None


@dataclass(frozen=True, slots=True)
class CorrectionHunk:
    """Replace an exact parent range or insert at a parent gap."""

    targets: tuple[RowOrigin, ...]
    replacement: tuple[RowOrigin | SourceRow, ...]
    before: RowOrigin | None = None
