import socket

import pytest
from pytest_socket import SocketBlockedError

import hatchway


def test_package_imports_with_version() -> None:
    assert isinstance(hatchway.__version__, str)
    assert hatchway.__version__


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("example.com", 443), timeout=1)
