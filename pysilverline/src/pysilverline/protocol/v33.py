"""Tuya local protocol v3.3 — AES-128-ECB / 55AA frames with CRC32 trailer.

v3.3 frame on the wire:

    [prefix:4][seq:4][cmd:4][size:4][payload:N][crc32:4][suffix:4]

with `size = N + 8`. CRC32 is computed over everything before the CRC bytes.
All multi-byte integers are big-endian.
"""

from __future__ import annotations

import binascii
import itertools
import json
import struct
from typing import Any

from .. import const
from ..exceptions import IncompleteFrame, InvalidAuth, ProtocolError
from .crypto import aes_decrypt, aes_encrypt
from .frame import (
    _FOOTER_FMT,
    _FOOTER_SIZE,
    _HEADER_FMT,
    _HEADER_SIZE,
    _MAX_FRAME_SIZE,
    Frame,
)


class FrameCodec:
    """Encodes outbound frames and decodes inbound ones for one device.

    Sequence numbers monotonically increase per outbound frame; the codec is
    not thread-safe, callers should serialize use within their own locks.
    """

    def __init__(self, local_key: str) -> None:
        self._key = local_key.encode("utf-8")
        if len(self._key) != 16:
            raise ValueError("local_key must be 16 ASCII characters")
        self._seq = itertools.count(1)

    def next_seq(self) -> int:
        return next(self._seq)

    @staticmethod
    def extract_seq_from_wire(wire: bytes) -> int:
        # 55AA header: prefix(4) + seq(4) + …
        return int.from_bytes(wire[4:8], "big")

    def encode(self, cmd: int, body: dict[str, Any]) -> bytes:
        """Build a complete frame for `cmd` with JSON-serialized `body`."""

        plaintext = json.dumps(body, separators=(",", ":")).encode("utf-8")
        ciphertext = aes_encrypt(plaintext, self._key)
        if cmd not in const.CMDS_WITHOUT_HEADER:
            payload = const.PROTOCOL_33_HEADER + ciphertext
        else:
            payload = ciphertext

        seq = self.next_seq()
        size = len(payload) + _FOOTER_SIZE
        header = struct.pack(_HEADER_FMT, const.FRAME_PREFIX, seq, cmd, size)
        body_bytes = header + payload
        crc = binascii.crc32(body_bytes) & 0xFFFFFFFF
        return body_bytes + struct.pack(_FOOTER_FMT, crc, const.FRAME_SUFFIX)

    def decode(self, data: bytes) -> tuple[Frame, bytes]:
        """Decode the first complete frame from `data`.

        Returns the decoded frame (with its raw inner payload — the v3.3
        header and any retcode prefix are NOT stripped here, since that
        depends on whether the frame is a request or a response) and the
        unconsumed remainder of the buffer.

        Raises ``IncompleteFrame`` when more bytes are needed before a
        frame can be decoded — caller should accumulate more bytes and
        retry. Raises ``ProtocolError`` only when the bytes that have
        arrived violate the spec (bad prefix/suffix/size/CRC), in which
        case the connection is desynchronized and must be dropped.
        """

        if len(data) < _HEADER_SIZE + _FOOTER_SIZE:
            raise IncompleteFrame("header not yet complete")
        prefix, seq, cmd, size = struct.unpack(_HEADER_FMT, data[:_HEADER_SIZE])
        # Validate the prefix BEFORE the size cap: a peer that sends
        # garbage shaped vaguely like a Tuya frame might also produce a
        # plausibly-sized but bogus size field, and we want the more
        # specific "bad prefix" diagnostic in the logs.
        if prefix != const.FRAME_PREFIX:
            raise ProtocolError(f"bad prefix 0x{prefix:08x}")
        if size > _MAX_FRAME_SIZE:
            raise ProtocolError(f"frame too large: {size}")
        total = _HEADER_SIZE + size
        if len(data) < total:
            raise IncompleteFrame(f"need {total - len(data)} more bytes")

        payload_end = total - _FOOTER_SIZE
        payload = data[_HEADER_SIZE:payload_end]
        crc, suffix = struct.unpack(_FOOTER_FMT, data[payload_end:total])
        if suffix != const.FRAME_SUFFIX:
            raise ProtocolError(f"bad suffix 0x{suffix:08x}")
        if crc != binascii.crc32(data[:payload_end]) & 0xFFFFFFFF:
            raise ProtocolError("CRC mismatch")

        return Frame(seq=seq, cmd=cmd, payload=payload), data[total:]

    @staticmethod
    def split_response_payload(cmd: int, payload: bytes) -> tuple[int | None, bytes]:
        """Peel a 4-byte retcode and a v3.3 header off a response payload.

        Use this on frames received in response to commands we sent
        (CONTROL/DP_QUERY/DP_REFRESH). Spontaneous pushes (CMD_STATUS,
        CMD_HEART_BEAT) carry no retcode, so callers should pass them
        directly to ``decrypt_body``.
        """
        retcode: int | None = None
        body = payload
        if cmd in (const.CMD_CONTROL, const.CMD_DP_QUERY, const.CMD_DP_REFRESH):
            if len(body) >= 4:
                retcode = struct.unpack(">I", body[:4])[0]
                body = body[4:]
        # Match the full 15-byte v3.3 header, not just its 3-byte ASCII
        # prefix — at ~1/16M frames a random AES ciphertext would otherwise
        # begin with 33 2e 33 and we'd peel 15 bytes off real payload.
        if body.startswith(const.PROTOCOL_33_HEADER):
            body = body[len(const.PROTOCOL_33_HEADER) :]
        return retcode, body

    @staticmethod
    def split_request_payload(payload: bytes) -> bytes:
        """Strip the optional v3.3 header from a push frame payload.

        Real WBR3 firmwares send spontaneous ``CMD_STATUS`` pushes shaped
        as ``[4-byte zero retcode][v3.3 header][ciphertext]``, even though
        the Tuya protocol notes describe pushes as headerless. We peel
        either shape so push DPs decrypt correctly.
        """
        # Use the full 15-byte v3.3 header; the bare 3-byte ASCII prefix
        # is a 1/16M collision target on encrypted bytes.
        if payload.startswith(const.PROTOCOL_33_HEADER):
            return payload[len(const.PROTOCOL_33_HEADER) :]
        if len(payload) >= 4 and payload[4:].startswith(const.PROTOCOL_33_HEADER):
            return payload[4 + len(const.PROTOCOL_33_HEADER) :]
        return payload

    def decrypt_body(self, body: bytes) -> dict[str, Any]:
        """Decrypt a payload body and parse it as JSON.

        Empty bodies return an empty dict. A failure to decrypt with our
        key raises ``InvalidAuth`` (signals reauth at the user). A
        successful decrypt followed by garbled output (non-UTF8 / non-JSON
        / non-object) raises ``ProtocolError`` instead — the key is fine,
        a frame just got corrupted on the wire, and triggering a reauth
        flow over transient corruption would punish the user for a single
        bit-flip.
        """

        if not body:
            return {}
        try:
            plaintext = aes_decrypt(body, self._key)
        except (ProtocolError, ValueError) as err:
            raise InvalidAuth("decryption failed — local_key likely wrong") from err
        try:
            parsed = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ProtocolError("decrypted payload is not JSON") from err
        if not isinstance(parsed, dict):
            raise ProtocolError(
                f"decrypted payload is not a JSON object: {type(parsed).__name__}"
            )
        return parsed
