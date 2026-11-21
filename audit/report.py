from audit.counts import count_readings
from audit.history import save_report
from audit.origins import collect_origins
from reading.decode import decode_volume
from workspace import transaction


def reconcile(root, volume_id):
    """Sign a report after consuming every row of a fixed volume."""
    with transaction(root, write=True) as connection:
        decoded = decode_volume(connection, root, volume_id)
        return save_report(connection, volume_id, count_readings(decoded), collect_origins(decoded))
