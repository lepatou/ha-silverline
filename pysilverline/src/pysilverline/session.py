"""Protocol-version negotiation and session-key handshakes.

Extracted from ``SilverlineClient``: these routines run once per connect, take
no client instance state, and return the chosen ``(reader, writer, codec,
version)`` for the façade to install. Keeping them out of the client keeps the
read/dispatch/reconnect loops (which read monkeypatched module constants and are
bound to instance state) clean and patch-safe.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import logging
import os
from collections.abc import Awaitable, Callable

from . import const
from .exceptions import (
    CannotConnect,
    IncompleteFrame,
    InvalidAuth,
    ProtocolError,
)
from .protocol import (
    Frame,
    Frame34Codec,
    Frame35Codec,
    FrameCodec,
    aes_decrypt,
    derive_session_key_34,
    derive_session_key_35,
)
from .transport import close_writer_silent

_LOGGER = logging.getLogger(__name__)

_HANDSHAKE_TIMEOUT: float = 5.0  # per-probe timeout for v3.5 negotiation


async def negotiate(
    *,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    host: str,
    pinned: str | None,
    known: str | None,
    codec_33: FrameCodec,
    codec_34: Frame34Codec,
    codec_35: Frame35Codec,
    open_tcp: Callable[
        [], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
    ],
) -> tuple[
    asyncio.StreamReader,
    asyncio.StreamWriter,
    FrameCodec | Frame34Codec | Frame35Codec,
    str,
]:
    """Select the protocol version, running a handshake where required.

    Returns the ``(reader, writer, codec, version)`` to use — possibly a
    *fresh* ``(reader, writer)`` pair, since a failed probe can leave the
    original socket unusable. Raises CannotConnect or InvalidAuth when a pinned
    or previously-confirmed version fails.

    ``pinned`` is the caller-pinned version (or None to auto-probe); ``known``
    holds the pinned value, or the version confirmed on a prior connect —
    either way a known version skips the blind probe.

    Resolution order:
      * pinned / already-confirmed v3.3 → no handshake;
      * pinned / already-confirmed v3.4 or v3.5 → that handshake only,
        failing loudly (and surfacing wrong-key as InvalidAuth);
      * unpinned, nothing confirmed yet → blind probe v3.5 → v3.4 → v3.3,
        each on a fresh socket so a poisoned probe never taints the next.
    """
    handshakes: tuple[
        tuple[
            str,
            FrameCodec | Frame34Codec | Frame35Codec,
            Callable[..., Awaitable[bool]],
        ],
        ...,
    ] = (
        ("3.5", codec_35, handshake_35),
        ("3.4", codec_34, handshake_34),
    )

    if pinned == "3.3" or (pinned is None and known == "3.3"):
        return reader, writer, codec_33, "3.3"

    # A specific handshake version is required (pinned to it, or confirmed
    # on an earlier connection so reconnects re-handshake the same version).
    for ver, codec, handshake in handshakes:
        if pinned == ver or (pinned is None and known == ver):
            try:
                ok = await handshake(reader, writer, codec, host, probe=False)
            except Exception:
                close_writer_silent(writer)
                raise
            if ok:
                return reader, writer, codec, ver
            close_writer_silent(writer)
            raise CannotConnect(f"v{ver} handshake with {host} failed")

    # Blind auto-probe: try each handshake, then fall back to plain v3.3.
    for ver, codec, handshake in handshakes:
        try:
            ok = await handshake(reader, writer, codec, host, probe=True)
        except Exception:
            # Only a v3.5 wrong-key (InvalidAuth) reaches here — its 6699
            # framing already proved the device is v3.5, so we must NOT
            # swallow it into a v3.3 fallback. v3.4 swallows its own
            # ambiguous auth failures internally (probe=True → False).
            close_writer_silent(writer)
            raise
        if ok:
            return reader, writer, codec, ver
        # Probe failed → the socket may be poisoned; open a fresh one for
        # the next protocol. The penalty is paid once: the detected version
        # sticks and future reconnects skip straight to it.
        close_writer_silent(writer)
        _LOGGER.debug("v%s probe failed for %s; trying next protocol", ver, host)
        reader, writer = await open_tcp()

    return reader, writer, codec_33, "3.3"


async def handshake_35(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    codec_35: Frame35Codec,
    host: str,
    *,
    probe: bool = False,
) -> bool:
    """Perform the v3.5 three-message session-key negotiation.

    Returns True on success.  Propagates InvalidAuth (wrong key) regardless
    of ``probe``: the 6699 prefix already proves the peer speaks v3.5, so a
    decrypt failure is unambiguously a bad key, never a v3.3 device.
    Returns False on any other failure (wrong protocol version, timeout,
    network error) so the caller can fall back.
    """
    local_nonce = os.urandom(16)
    codec = codec_35

    # --- Step 1: send SESS_KEY_NEG_START (cmd 0x03) ---
    try:
        wire = codec.encode_raw(const.SESS_KEY_NEG_START, local_nonce)
        writer.write(wire)
        await writer.drain()
    except (OSError, ConnectionError):
        return False

    # --- Step 2: receive SESS_KEY_NEG_RESP (cmd 0x04) ---
    buf = bytearray()
    try:
        frame = await asyncio.wait_for(
            _recv_frame(reader, codec, buf),
            timeout=_HANDSHAKE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return False
    except InvalidAuth:
        raise
    except Exception:
        return False

    if frame.cmd != const.SESS_KEY_NEG_RESP:
        return False

    # Decrypted payload: [retcode(4)] + remote_nonce(16) + HMAC-SHA256(32)
    raw = frame.payload
    if len(raw) >= 52 and raw[0:1] != b"{":
        raw = raw[4:]  # strip retcode
    if len(raw) < 48:
        return False

    remote_nonce = raw[:16]
    expected_hmac = _hmac.new(codec_35._real_key, local_nonce, hashlib.sha256).digest()
    if not _hmac.compare_digest(expected_hmac, raw[16:48]):
        _LOGGER.debug("v3.5 handshake HMAC mismatch for %s", host)
        return False

    # --- Step 3: derive session key, send SESS_KEY_NEG_FINISH (cmd 0x05) ---
    # The FINISH frame itself is still encrypted with the REAL key — the
    # device only switches to the session key for data frames *after* it
    # has decoded FINISH (mirrors TinyTuya's _negotiate_session_key, where
    # self.local_key is reassigned in finalize() only after FINISH is sent).
    # Switching the codec before encoding FINISH would ship it under the
    # session key, which a real device cannot decrypt → handshake fails.
    session_key = derive_session_key_35(local_nonce, remote_nonce, codec_35._real_key)

    finish_hmac = _hmac.new(codec_35._real_key, remote_nonce, hashlib.sha256).digest()
    try:
        wire = codec.encode_raw(const.SESS_KEY_NEG_FINISH, finish_hmac)
        writer.write(wire)
        await writer.drain()
    except (OSError, ConnectionError):
        return False

    # Only now switch to the session key — it lands before connect() starts
    # the read loop, so there is no race with inbound data frames.
    codec.update_session_key(session_key)
    return True


async def _recv_frame(
    reader: asyncio.StreamReader,
    codec: Frame34Codec | Frame35Codec,
    buf: bytearray,
) -> Frame:
    """Accumulate bytes from ``reader`` until one complete handshake frame decodes.

    Shared by the v3.4 and v3.5 handshakes — the only structural difference is
    the codec, which decodes its own framing.
    """
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            raise CannotConnect("connection closed during handshake")
        buf.extend(chunk)
        try:
            frame, _ = codec.decode(bytes(buf))
            return frame
        except IncompleteFrame:
            continue


async def handshake_34(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    codec_34: Frame34Codec,
    host: str,
    *,
    probe: bool,
) -> bool:
    """Perform the v3.4 three-message session-key negotiation.

    Returns True on success. A wrong key shows up as the device's RESP
    failing to authenticate (its keyed HMAC trailer won't verify under our
    derived real key): when v3.4 is *required* (``probe=False``) that
    surfaces as InvalidAuth → reauth; during a *blind probe*
    (``probe=True``) it is swallowed to False so the caller can fall back —
    v3.3 shares the 55AA framing and would also fail to authenticate here,
    so an auth failure mid-probe cannot be assumed to mean "wrong key".
    Any non-auth failure (wrong version, timeout, network) returns False.
    """
    local_nonce = os.urandom(16)
    codec = codec_34
    real_key = codec_34._real_key

    # --- Step 1: send SESS_KEY_NEG_START (cmd 0x03) ---
    # The nonce is AES-ECB-encrypted with the real key (v3.4 encrypts every
    # frame, handshake included) but carries no version header.
    try:
        writer.write(codec.encode_raw(const.SESS_KEY_NEG_START, local_nonce))
        await writer.drain()
    except (OSError, ConnectionError):
        return False

    # --- Step 2: receive SESS_KEY_NEG_RESP (cmd 0x04) ---
    buf = bytearray()
    try:
        frame = await asyncio.wait_for(
            _recv_frame(reader, codec, buf),
            timeout=_HANDSHAKE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return False
    except InvalidAuth:
        # The frame's keyed HMAC trailer did not verify. Required → wrong
        # key (reauth); probe → most likely not a v3.4 device, fall back.
        if probe:
            return False
        raise
    except Exception:
        return False

    if frame.cmd != const.SESS_KEY_NEG_RESP:
        return False

    # Decrypt RESP → remote_nonce(16) + HMAC-SHA256(real_key, local_nonce)(32).
    # An unencrypted 4-byte retcode may prefix the ciphertext (present iff
    # the payload length is 4 over a 16-byte boundary).
    raw = frame.payload
    if len(raw) % 16 == 4:
        raw = raw[4:]
    try:
        plaintext = aes_decrypt(raw, real_key)
    except (ProtocolError, ValueError):
        if probe:
            return False
        raise InvalidAuth("v3.4 RESP decrypt failed — local_key likely wrong")
    if len(plaintext) < 48:
        return False
    remote_nonce = plaintext[:16]
    expected_hmac = _hmac.new(real_key, local_nonce, hashlib.sha256).digest()
    if not _hmac.compare_digest(expected_hmac, plaintext[16:48]):
        _LOGGER.debug("v3.4 handshake inner-HMAC mismatch for %s", host)
        return False

    # --- Step 3: derive session key, send SESS_KEY_NEG_FINISH (cmd 0x05) ---
    # FINISH is still encrypted/authenticated with the REAL key; the codec
    # switches to the session key only AFTER it is on the wire (mirrors
    # _handshake_35 and TinyTuya, where local_key is reassigned in
    # finalize() only once FINISH has been sent).
    session_key = derive_session_key_34(local_nonce, remote_nonce, real_key)
    finish_hmac = _hmac.new(real_key, remote_nonce, hashlib.sha256).digest()
    try:
        writer.write(codec.encode_raw(const.SESS_KEY_NEG_FINISH, finish_hmac))
        await writer.drain()
    except (OSError, ConnectionError):
        return False

    codec.update_session_key(session_key)
    return True
