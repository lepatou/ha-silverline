"""Shared 55AA frame primitives: the :class:`Frame` dataclass, the 55AA
header/footer struct formats and sizes, the frame-size cap, and the
invalid-auth retcode helper used across the v3.3 and v3.4 codecs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_HEADER_FMT = ">IIII"  # prefix, seq, cmd, size
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_FOOTER_FMT = ">II"  # crc32, suffix
_FOOTER_SIZE = struct.calcsize(_FOOTER_FMT)
# Upper bound on the wire-claimed `size` field. Real Tuya frames from a heat
# pump are well under 1 KiB; capping at 64 KiB prevents a hostile LAN peer
# from claiming a 4 GiB frame to exhaust memory while we wait for bytes.
_MAX_FRAME_SIZE = 64 * 1024

_RETCODE_INVALID_KEY = {0x00000FFF, 0xFFFFFFFF}


@dataclass(slots=True, kw_only=True)
class Frame:
    """A decoded Tuya wire frame.

    ``payload`` is the raw inner bytes; use ``FrameCodec.split_response_payload``
    or ``FrameCodec.split_request_payload`` to peel the retcode / v3.3 header
    before decryption, depending on direction.
    """

    seq: int
    cmd: int
    payload: bytes


def is_invalid_auth_retcode(retcode: int | None) -> bool:
    """Some firmwares signal a wrong local_key with these return codes."""
    return retcode is not None and retcode in _RETCODE_INVALID_KEY
