from dataclasses import dataclass

from archive.catalog import VolumeEntry, get_encoding, get_volume
from errors import RetirementError


@dataclass(frozen=True, slots=True)
class RetirementScope:
    target: VolumeEntry
    dependents: tuple[VolumeEntry, ...]


def assess_retirement(connection, volume_id):
    target = get_volume(connection, volume_id)
    encoding = get_encoding(connection, target.encoding_id)
    if encoding.volume_id != target.volume_id:
        raise RetirementError("active encoding belongs to a different volume")
    # Frames only ever reference encodings of earlier volumes, so one pass in
    # volume order finds every volume whose active encoding directly or
    # transitively reads an encoding that retirement takes out of service.
    obsolete = {target.encoding_id}
    dependents = []
    for record in connection.execute(
            'SELECT id FROM volumes WHERE retired = 0 AND id != ? ORDER BY id',
            (target.volume_id,)):
        volume = get_volume(connection, record['id'])
        active = get_encoding(connection, volume.encoding_id)
        if not any(info.source_encoding in obsolete for info in active.frames):
            continue
        if volume.volume_id < target.volume_id:
            raise RetirementError("catalog contains a non-ancestral dependency")
        dependents.append(volume)
        obsolete.add(active.encoding_id)
    return RetirementScope(target, tuple(dependents))
