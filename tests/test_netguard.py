import socket
import threading

import pytest

from wort import netguard


@pytest.fixture(autouse=True)
def _restore():
    yield
    netguard.uninstall()


def serve():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True).start()
    return srv


def test_loopback_is_allowed():
    srv = serve()
    netguard.install()
    with socket.create_connection(srv.getsockname(), timeout=2):
        pass
    srv.close()


def test_other_hosts_are_blocked_without_touching_the_network():
    netguard.install()
    s = socket.socket()
    with pytest.raises(netguard.NetworkBlocked):
        s.connect(("93.184.216.34", 443))
    with pytest.raises(netguard.NetworkBlocked):
        s.connect_ex(("10.0.0.5", 8456))
    s.close()


def test_dns_for_other_names_is_blocked_but_numeric_is_not_a_lookup():
    netguard.install()
    with pytest.raises(netguard.NetworkBlocked):
        socket.getaddrinfo("example.com", 443)
    assert socket.getaddrinfo("127.0.0.1", 80)  # numeric loopback: fine


def test_udp_send_to_other_host_is_blocked():
    netguard.install()
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with pytest.raises(netguard.NetworkBlocked):
        u.sendto(b"x", ("8.8.8.8", 53))
    u.close()


def test_only_the_configured_endpoint_passes_the_guard():
    netguard.install({("192.0.2.10", 8456)})
    s = socket.socket()
    s.settimeout(0.2)
    # allowed by the guard: it then tries the real network (unroutable test address) -> OSError, not NetworkBlocked
    try:
        s.connect(("192.0.2.10", 8456))
    except netguard.NetworkBlocked:
        pytest.fail("the allowed endpoint was blocked")
    except OSError:
        pass
    with pytest.raises(netguard.NetworkBlocked):
        s.connect(("192.0.2.10", 8457))  # same host, other port
    s.close()


def test_unix_sockets_and_socketpair_still_work():
    netguard.install()
    a, b = socket.socketpair()
    a.sendall(b"hi")
    assert b.recv(2) == b"hi"
    a.close(); b.close()
    import asyncio
    asyncio.run(asyncio.sleep(0))  # asyncio's self-pipe must keep working
