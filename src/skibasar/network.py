"""LAN address detection and QR codes for connecting phones."""

import socket

import segno

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_local(host: str | None) -> bool:
    return host in LOCAL_HOSTS


def lan_ip() -> str | None:
    """Own address on the local network, or ``None`` when there is none (no packets are sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


def lan_url(port: int) -> str | None:
    ip = lan_ip()
    return f"http://{ip}:{port}" if ip else None


def qr_svg(text: str) -> str:
    return segno.make(text, error="m").svg_inline(scale=6, border=2, dark="#000", light="#fff")


def qr_terminal(text: str) -> str:
    import io

    buf = io.StringIO()
    segno.make(text, error="l").terminal(out=buf, compact=True, border=1)
    return buf.getvalue()
