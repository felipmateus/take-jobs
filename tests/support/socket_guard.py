"""Network guard for the spawned crawl child (FR-30).

pytest-socket's session guard lives in the pytest process; a `spawn` child does not inherit it.
`install_test_socket_guard` installs the same allow-list inside the child, and it also guards
`connect_ex`, which Twisted's TCP client uses and pytest-socket does not patch.

It is a top-level function so that it pickles by reference across the spawn boundary; bind
`allow_hosts` with `functools.partial` when needed.
"""

import itertools
import socket
from collections.abc import Sequence

from pytest_socket import (
    SocketConnectBlockedError,
    host_from_connect_args,
    normalize_allowed_hosts,
    socket_allow_hosts,
)

LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def install_test_socket_guard(allow_hosts: Sequence[str] | None = None) -> None:
    """Block every outgoing TCP connection except those to `allow_hosts` (default: loopback).

    Unix sockets stay allowed. Meant for a short-lived child process: it is never undone.
    """
    allowed = list(LOOPBACK_HOSTS if allow_hosts is None else allow_hosts)
    socket_allow_hosts(allowed, allow_unix_socket=True)

    allowed_names = set(allowed) | set(
        itertools.chain.from_iterable(normalize_allowed_hosts(allowed).values())
    )
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect_ex(sock: socket.socket, *args: object) -> int:
        host = host_from_connect_args(args)
        if host in allowed_names or sock.family == socket.AF_UNIX:
            return real_connect_ex(sock, *args)  # type: ignore[arg-type]
        sock.close()
        raise SocketConnectBlockedError(sorted(allowed_names), host)

    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign,assignment]
