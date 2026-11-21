import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.catalog import get_encoding, get_volume
from archive.files import frame_path, volume_path
from archive.frames import FrameAddress
from audit.history import get_report
from audit.report import reconcile
from demo import build_sample
from errors import DecodeError, VolumeUnavailable
from reading.open import read_page
from retention.receipts import find_retirement_receipt
from retention.retire import retire
from workspace import initialize, transaction


MARKER = "POINTWISE_RETIREMENT_HANDOFF_MISMATCH"
A = ["recording", "A", 7]
B = ["recording", "B", 7]
C = ["correction-1", "C", 11]
D = ["correction-2", "D", 7]


def show_rows(page):
    return [[row.origin.batch, row.origin.line, row.value] for row in page.rows]


def show_report(report):
    return {
        "count": report.totals.total_rows,
        "missing": report.totals.missing_rows,
        "newtons": report.totals.total,
        "origins": [[item.position, item.origin.batch, item.origin.line] for item in report.origins],
    }


def observe(operation, old_encoding):
    try:
        return {"result": operation()}
    except DecodeError as exc:
        if str(exc) != f"missing required encoding {old_encoding}":
            raise
        return {"error": str(exc)}


def encoding_paths(root, encoding):
    return (volume_path(root, encoding.encoding_id),) + tuple(
        frame_path(root, FrameAddress(encoding.encoding_id, item.number)) for item in encoding.frames
    )


def check(root):
    r0, r1, r2 = build_sample(root)
    with transaction(root) as connection:
        originals = tuple(get_encoding(connection, get_volume(connection, volume).encoding_id)
                          for volume in (r0, r1, r2))
    first = read_page(root, r1, 1)
    if show_rows(first) != [A] or first.next_ticket is None:
        raise AssertionError("unexpected R1 first page before retirement")
    if show_rows(read_page(root, r0, 5)) != [A, B] or show_rows(read_page(root, r2, 5)) != [C, D]:
        raise AssertionError("unexpected issued rows before retirement")
    signed = reconcile(root, r2)
    report_expected = {"count": 2, "missing": 0, "newtons": 18,
                       "origins": [[1, "correction-1", "C"], [2, "correction-2", "D"]]}
    if show_report(signed) != report_expected:
        raise AssertionError("unexpected R2 report before retirement")
    receipt = retire(root, r0)
    initialize(root)
    if receipt.volume_id != r0 or find_retirement_receipt(root, r0) != receipt:
        raise AssertionError("retirement receipt does not match R0")
    try:
        read_page(root, r0, 5)
    except VolumeUnavailable:
        pass
    else:
        raise AssertionError("retired R0 is still available")
    if any(path.exists() for path in encoding_paths(root, originals[0])):
        raise AssertionError("retired R0 encoding files remain")
    if show_rows(read_page(root, r1, 5)) != [A, C]:
        raise AssertionError("unexpected R1 rows from the beginning after retirement")
    if get_report(root, signed.report_id) != signed:
        raise AssertionError("previously signed R2 report changed")

    def r1_tail():
        page = read_page(root, r1, 5, first.next_ticket)
        return {"rows": show_rows(page), "at_end": page.next_ticket is None}

    old_r1_encoding = originals[1].encoding_id
    expected = {"R2_rows": {"result": [C, D]}, "R2_report": {"result": report_expected},
                "R1_tail": {"result": {"rows": [C], "at_end": True}}}
    actual = {
        "R2_rows": observe(lambda: show_rows(read_page(root, r2, 5)), old_r1_encoding),
        "R2_report": observe(lambda: show_report(reconcile(root, r2)), old_r1_encoding),
        "R1_tail": observe(r1_tail, old_r1_encoding),
    }
    print(json.dumps({"before": {"R1_first": [A], "R2": [C, D]}, "expected": expected, "actual": actual},
                     ensure_ascii=False, sort_keys=True))
    if actual != expected:
        print(MARKER)
        return 1
    return 0


if __name__ == "__main__":
    with TemporaryDirectory(prefix="retire-incident-") as temp:
        raise SystemExit(check(Path(temp)))
