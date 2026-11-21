from archive.catalog import drop_encoding, get_encoding, mark_retired, set_active_encoding
from retention.receipts import write_retirement_receipt


def publish_retirement(connection, files, scope, replacements, *, before_commit=None):
    target = scope.target
    target_encoding = get_encoding(connection, target.encoding_id)
    for item in replacements.items:
        connection.execute('''
            INSERT INTO replacement_history(volume, old_encoding, new_encoding)
            VALUES (?, ?, ?)
        ''', (item.original.volume_id, item.original.encoding_id, item.staged.encoding_id))
        set_active_encoding(connection, item.original.volume_id, item.staged.encoding_id)
    mark_retired(connection, target.volume_id)
    connection.execute("DELETE FROM replacement_history WHERE volume = ?", (target.volume_id,))
    obsolete = (target_encoding,) + tuple(item.original for item in replacements.items)
    for encoding in obsolete:
        files.remove_encoding(encoding)
        drop_encoding(connection, encoding.encoding_id)
    receipt = write_retirement_receipt(connection, target.volume_id)
    if before_commit is not None:
        before_commit()
    return receipt
