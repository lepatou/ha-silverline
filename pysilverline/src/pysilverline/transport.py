"""TCP transport helpers for the Silverline client.

Low-coupling socket primitives extracted from ``SilverlineClient``: opening a
connection (mapping connect failures to :class:`CannotConnect`) and closing a
writer while swallowing OS errors. These carry no client state, so they live
here as plain module functions.
"""

from __future__ import annotations

import asyncio

from .exceptions import CannotConnect


def close_writer_silent(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except OSError:
        pass


async def open_tcp(
    host: str,
    port: int,
    timeout: float,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        return await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except (OSError, asyncio.TimeoutError) as err:
        raise CannotConnect(f"connect {host}:{port}: {err}") from err
