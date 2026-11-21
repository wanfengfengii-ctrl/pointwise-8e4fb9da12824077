from archive.frames import FrameAddress, LiteralFrame, ReferenceFrame


def _base_positions(base_rows, encoding):
    positions = {}
    for info in encoding.frames:
        address = FrameAddress(encoding.encoding_id, info.number)
        for offset in range(info.count):
            positions[base_rows[info.start + offset]] = (address, offset)
    return positions


def plan_delta(rows, base_rows, encoding, frame_rows):
    positions = _base_positions(base_rows, encoding)
    frames = []
    start = 0
    while start < len(rows):
        source = positions.get(rows[start])
        end = start + 1
        if source is None:
            while end < len(rows) and end - start < frame_rows and rows[end] not in positions:
                end += 1
            frames.append(LiteralFrame(start, tuple(rows[start:end])))
        else:
            address, offset = source
            while end < len(rows) and positions.get(rows[end]) == (address, offset + end - start):
                end += 1
            frames.append(ReferenceFrame(start, address, offset, end - start))
        start = end
    return tuple(frames)
