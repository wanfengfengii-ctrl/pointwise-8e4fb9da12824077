import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from archive.catalog import get_volume
from archive.files import volume_path
from archive.issue import issue
from audit.history import get_report
from audit.report import reconcile
from errors import ArchiveError, VolumeUnavailable
from intake.records import CorrectionHunk, RowOrigin, SourceRow
from intake.revisions import ingest
from reading.open import read_page
from retention.retire import retire
from workspace import initialize, transaction


SAMPLES = Path(__file__).with_name('samples')


def _sample(name):
    return json.loads((SAMPLES / f'{name}.json').read_text(encoding='utf-8'))


def _apply_sample(root, parent, name):
    sample = _sample(name)
    batch = sample['batch']
    hunks = []
    for item in sample['hunks']:
        targets = tuple(RowOrigin(*origin) for origin in item['targets'])
        replacement = []
        for member in item['replacement']:
            if 'keep' in member:
                replacement.append(RowOrigin(*member['keep']))
            else:
                line, value = member['new']
                replacement.append(SourceRow(RowOrigin(batch, line), value))
        hunks.append(CorrectionHunk(targets, tuple(replacement)))
    return ingest(root, batch, parent=parent, corrections=hunks)


def build_sample(root):
    initialize(root)
    sample = _sample('base')
    batch = sample['batch']
    original = ingest(root, batch, tuple(SourceRow(RowOrigin(batch, line), value) for line, value in sample['rows']))
    r0 = issue(root, original.revision_id, frame_rows=2)
    first = _apply_sample(root, original.revision_id, 'correction-1')
    r1 = issue(root, first.revision_id, r0)
    second = _apply_sample(root, first.revision_id, 'correction-2')
    r2 = issue(root, second.revision_id, r1)
    return r0, r1, r2


def _show_rows(rows):
    return [[row.origin.batch, row.origin.line, row.value] for row in rows]


def _check(expected, actual, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def run_demo():
    with TemporaryDirectory(prefix='headland-archive-') as temp:
        root = Path(temp)
        r0, r1, r2 = build_sample(root)
        with transaction(root) as connection:
            old_encoding = get_volume(connection, r0).encoding_id
        old_path = volume_path(root, old_encoding)
        _check(True, old_path.is_file(), 'issued base file')
        before = read_page(root, r1, 1)
        _check([['recording', 'A', 7]], _show_rows(before.rows), 'first page')
        if before.next_ticket is None:
            raise AssertionError('first page did not issue the shift ticket')
        signed = reconcile(root, r2)
        receipt = retire(root, r0)
        initialize(root)
        retired_unavailable = False
        try:
            read_page(root, r0, 5)
        except VolumeUnavailable:
            retired_unavailable = True
        resumed = read_page(root, r1, 5, before.next_ticket)
        actual = {
            'R2_rows': _show_rows(read_page(root, r2, 5).rows),
            'R1_tail': _show_rows(resumed.rows),
            'at_end': resumed.next_ticket is None,
            'R0_unavailable': retired_unavailable,
            'R0_file_present': old_path.exists(),
            'retired_volume_matches': receipt.volume_id == r0,
        }
        expected = {
            'R2_rows': [['correction-1', 'C', 11], ['correction-2', 'D', 7]],
            'R1_tail': [['correction-1', 'C', 11]],
            'at_end': True,
            'R0_unavailable': True,
            'R0_file_present': False,
            'retired_volume_matches': True,
        }
        history = get_report(root, signed.report_id)
        after = reconcile(root, r2)
        downstream_actual = {
            'total': after.totals.total,
            'missing': after.totals.missing_rows,
            'count': after.totals.total_rows,
            'ordered_origins': [[item.position, item.origin.batch, item.origin.line] for item in after.origins],
            'old_report_unchanged': history == signed,
        }
        downstream_expected = {
            'total': 18,
            'missing': 0,
            'count': 2,
            'ordered_origins': [[1, 'correction-1', 'C'], [2, 'correction-2', 'D']],
            'old_report_unchanged': True,
        }
        _check(expected, actual, 'retirement and continuation')
        _check(downstream_expected, downstream_actual, 'reconciliation')
        scenario = {
            'case_id': 't5',
            'input': {'R0': _sample('base'), 'R1': _sample('correction-1'), 'R2': _sample('correction-2'),
                      'R1_page_size_before_retirement': 1, 'retire': 'R0'},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['intake/revisions.py', 'archive/issue.py', 'retention/rewrite.py',
                           'retention/publication.py', 'reading/resume.py', 'reading/open.py', 'audit/report.py'],
            'oracle': 'Apply the two written replacements by hand, continue R1 after A, and add 11 + 7.',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, separators=(',', ':')))


def main():
    parser = argparse.ArgumentParser(description='Demonstrate the fixed-volume archive')
    commands = parser.add_subparsers(dest='command')
    page = commands.add_parser('page')
    page.add_argument('root', type=Path)
    page.add_argument('volume', type=int)
    page.add_argument('size', type=int)
    page.add_argument('ticket', nargs='?')
    report = commands.add_parser('report')
    report.add_argument('root', type=Path)
    report.add_argument('report_id', type=int)
    args = parser.parse_args()
    sys.set_int_max_str_digits(0)
    if args.command == 'page':
        print(json.dumps(asdict(read_page(args.root, args.volume, args.size, args.ticket))))
    elif args.command == 'report':
        print(json.dumps(asdict(get_report(args.root, args.report_id))))
    else:
        run_demo()


if __name__ == '__main__':
    try:
        main()
    except (ArchiveError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
