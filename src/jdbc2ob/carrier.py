from pathlib import Path
from typing import List, Tuple, Optional

from .event import FlowEvent


class CarrierBuildError(Exception):
    pass


def _looks_like_mysql_packet_start(data: bytes) -> Tuple[bool, Optional[str]]:
    if len(data) < 4:
        return False, "less than 4 bytes"
    payload_len = int.from_bytes(data[:3], "little")
    if payload_len == 0:
        return True, None
    if payload_len > 0xFFFFFF:
        return False, "payload length impossible"
    if payload_len > 1024 * 1024:
        return False, "first MySQL packet length unusually large: %d" % payload_len
    return True, None


def build_random_access_carrier(events: List[FlowEvent], session_dir: Path) -> Path:
    """
    Build namedpipe_payload.bin for Connector/J NamedPipeSocketFactory RandomAccessFile behavior.

    File layout:
        S2C actual bytes, C2S zero placeholders, S2C actual bytes, C2S zero placeholders...

    Only namedpipe_payload.bin is written.
    """
    if not events:
        raise CarrierBuildError("no events captured")
    if events[0].direction != "s2c":
        raise CarrierBuildError("first event is not s2c; MySQL server must speak first")

    carrier = bytearray()
    carrier_path = session_dir / "namedpipe_payload.bin"

    for ev in events:
        if ev.direction == "s2c":
            ok, reason = _looks_like_mysql_packet_start(ev.data)
            if ev.index == 1 and not ok:
                raise CarrierBuildError("first s2c chunk is not a valid MySQL packet start: %s" % reason)
            carrier.extend(ev.data)
        elif ev.direction == "c2s":
            # JDBC will write over this range when namedPipePath points to the generated file.
            carrier.extend(b"\x00" * ev.length)
        else:
            raise CarrierBuildError("unknown direction: %s" % ev.direction)

    carrier_path.write_bytes(bytes(carrier))
    validate_carrier(events, carrier_path)
    return carrier_path


def validate_carrier(events: List[FlowEvent], carrier_path: Path) -> None:
    data = carrier_path.read_bytes()
    cursor = 0
    if not events:
        raise CarrierBuildError("no events to validate")

    for ev in events:
        segment = data[cursor:cursor + ev.length]
        if len(segment) != ev.length:
            raise CarrierBuildError("carrier ended early at event %d" % ev.index)

        if ev.direction == "s2c":
            if segment != ev.data:
                raise CarrierBuildError("s2c mismatch at offset %d event %d" % (cursor, ev.index))
            if ev.index == 1:
                ok, reason = _looks_like_mysql_packet_start(segment)
                if not ok:
                    raise CarrierBuildError("first s2c invalid at offset 0: %s" % reason)
        else:
            if segment != b"\x00" * ev.length:
                raise CarrierBuildError("c2s placeholder not zeroed at offset %d event %d" % (cursor, ev.index))

        cursor += ev.length
