from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReadingTotals:
    total_rows: int
    missing_rows: int
    total: int


def count_readings(decoded_rows):
    count = 0
    missing = 0
    total = 0
    for item in decoded_rows:
        count += 1
        value = item.row.value
        if value is None:
            missing += 1
        else:
            total += value
    return ReadingTotals(count, missing, total)
