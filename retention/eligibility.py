from dataclasses import dataclass

from archive.catalog import VolumeEntry, direct_dependents, get_encoding, get_volume
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
    dependents = []
    for dependent_id in direct_dependents(connection, encoding.encoding_id):
        if dependent_id <= target.volume_id:
            raise RetirementError("catalog contains a non-ancestral dependency")
        dependents.append(get_volume(connection, dependent_id))
    return RetirementScope(target, tuple(dependents))
