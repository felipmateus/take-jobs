import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_ut115_session_guard_blocks_non_local_host() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(SocketConnectBlockedError),
    ):
        sock.connect(("93.184.216.34", 80))
