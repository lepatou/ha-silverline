"""Tuya local protocol frame codecs for v3.3, v3.4 (both 55AA/AES-ECB) and v3.5
(6699/AES-GCM).

v3.3 frame on the wire:

    [prefix:4][seq:4][cmd:4][size:4][payload:N][crc32:4][suffix:4]

with `size = N + 8`. CRC32 is computed over everything before the CRC bytes.
All multi-byte integers are big-endian.

v3.4 frame on the wire:

    [prefix:4][seq:4][cmd:4][size:4][payload:N][hmac_sha256:32][suffix:4]

with `size = N + 36`. The CRC32 is replaced by a keyed 32-byte HMAC-SHA256 over
everything before it. Like v3.5, every TCP connection runs a 3-message
session-key handshake (cmds 0x03/0x04/0x05); unlike v3.5 the cipher is AES-ECB
and the derived session key is `AES-ECB(real_key, local_nonce XOR remote_nonce)`.
The version header is encrypted *inside* the AES ciphertext (v3.3 keeps it
outside). See `Frame34Codec` and `derive_session_key_34`.

v3.5 frame on the wire:

    [prefix:4][unknown:2][seq:4][cmd:4][length:4][iv:12][ciphertext:N][tag:16][suffix:4]

with `length = N + 28`. GCM tag authenticates header bytes[4:18] as AAD.
Every TCP connection requires a 3-message session-key handshake (cmds 0x03/0x04/0x05)
before any data frame. See `Frame35Codec` and `derive_session_key_35`.

This package is split into one module per codec family with shared primitives
factored out (``frame`` for the 55AA wire structs / :class:`Frame`, ``crypto``
for the AES helpers). The full public surface is re-exported here so
``pysilverline.protocol.<name>`` keeps resolving exactly as before.
"""

from __future__ import annotations

from ..exceptions import IncompleteFrame as IncompleteFrame
from ..exceptions import InvalidAuth as InvalidAuth
from ..exceptions import ProtocolError as ProtocolError
from .crypto import _pkcs7_unpad as _pkcs7_unpad
from .crypto import (
    aes_decrypt,
    aes_encrypt,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    derive_session_key_34,
    derive_session_key_35,
)
from .frame import Frame, is_invalid_auth_retcode
from .v33 import FrameCodec
from .v34 import Frame34Codec
from .v35 import Frame35Codec

__all__ = [
    "Frame",
    "FrameCodec",
    "Frame34Codec",
    "Frame35Codec",
    "aes_encrypt",
    "aes_decrypt",
    "aes_gcm_encrypt",
    "aes_gcm_decrypt",
    "derive_session_key_34",
    "derive_session_key_35",
    "is_invalid_auth_retcode",
    "IncompleteFrame",
    "InvalidAuth",
    "ProtocolError",
]
