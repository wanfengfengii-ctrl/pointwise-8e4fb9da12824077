from archive.files import FileChanges
from reading.decode import iter_decoded_rows
from retention.eligibility import assess_retirement
from retention.publication import publish_retirement
from retention.rewrite import check_replacements, stage_replacements
from workspace import transaction


def retire(root, volume_id, *, before_commit=None):
    """Retire a fixed volume after checking and publishing readable replacements."""
    with FileChanges(root) as files, transaction(root, write=True) as connection:
        scope = assess_retirement(connection, volume_id)
        # Read the target, including its seal, before taking any files out of service.
        for _ in iter_decoded_rows(connection, root, scope.target.encoding_id):
            pass
        replacements = stage_replacements(connection, root, files, scope)
        check_replacements(connection, root, scope, replacements)
        return publish_retirement(connection, files, scope, replacements, before_commit=before_commit)
