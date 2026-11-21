from archive.catalog import get_encoding, get_volume, register_volume
from archive.delta import plan_delta
from archive.files import FileChanges
from archive.frames import LiteralFrame
from errors import DecodeError, IssueError, UnknownRevision, VolumeUnavailable
from intake.store import load_revision
from reading.decode import iter_decoded_rows
from workspace import transaction


def build_full_frames(rows, frame_rows=2):
    if type(frame_rows) is not int or frame_rows <= 0:
        raise IssueError('frame size must be a positive integer')
    return tuple(LiteralFrame(start, tuple(rows[start:start + frame_rows]))
                 for start in range(0, len(rows), frame_rows))


def issue(root, revision_id, base_volume=None, *, frame_rows=2):
    """Publish a fixed volume, optionally reusing frames from an earlier revision."""
    if type(frame_rows) is not int or frame_rows <= 0:
        raise IssueError('frame size must be a positive integer')
    with FileChanges(root) as files, transaction(root, write=True) as connection:
        try:
            rows = load_revision(connection, revision_id)
            if base_volume is None:
                frames = build_full_frames(rows, frame_rows)
            else:
                base = get_volume(connection, base_volume)
                if base.revision_id >= revision_id:
                    raise IssueError('a base volume must belong to an earlier revision')
                base_encoding = get_encoding(connection, base.encoding_id)
                base_rows = tuple(item.row for item in iter_decoded_rows(connection, root, base.encoding_id))
                frames = plan_delta(rows, base_rows, base_encoding, frame_rows)
        except (UnknownRevision, VolumeUnavailable, DecodeError) as exc:
            raise IssueError(str(exc)) from exc
        entry = register_volume(connection, revision_id, frames, len(rows))
        files.write_encoding(get_encoding(connection, entry.encoding_id), frames)
        return entry.volume_id
