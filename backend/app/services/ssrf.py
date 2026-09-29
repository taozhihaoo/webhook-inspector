"""SSRF protection for the replay feature.

Replay targets are validated at multiple layers before any connection:

1. Scheme: https only by default (http:// requires ALLOW_HTTP_REPLAY=true);
   every other scheme (file:, gopher:, ftp:, ...) is rejected.
2. Hostname: localhost and private/internal DNS suffixes are rejected, as are
   classic IP-obfuscation encodings (decimal / hex / octal forms) that OS
   resolvers would happily translate into loopback or private addresses.
3. IP literals: loopback, RFC1918, link-local (incl. cloud metadata
   169.254.169.254), CGNAT (100.64/10), benchmarking ranges, reserved,
   multicast, unspecified, and IPv4-mapped IPv6 addresses.
4. DNS: the hostname is resolved and *every* resolved address must pass the
   same IP checks (blocks "DNS name pointing at a private IP"). The validated
   addresses are returned so the caller can pin the connection to one of them
   (see app.services.replay_service._PinningBackend) — this closes the
   validate/connect gap that DNS rebinding attacks exploit.
5. Redirects are followed manually and every hop is re-validated with the
   same rules, so a public URL cannot 302 into an internal address.
"""

import asyncio
import ipaddress
from urllib.parse import urlparse

INSECURE_SCHEMES_HINT = "Replay targets must use https:// (http requires ALLOW_HTTP_REPLAY=true)"

BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata.goog"}

# Networks that modern ipaddress.is_private no longer covers but must never be
# replay targets: shared/CGNAT space and benchmarking ranges.
EXTRA_BLOCKED_NETWORKS = [
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / shared address space
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
]


class UnsafeTargetError(Exception):
    """Raised when a replay target fails SSRF validation."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # ::ffff:a.b.c.d must be judged by its embedded IPv4 address.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    return any(ip in network for network in EXTRA_BLOCKED_NETWORKS)


def _looks_like_obfuscated_ip(hostname: str) -> bool:
    """Detect decimal / hex / octal IP encodings that resolvers accept.

    "2130706433" is 127.0.0.1, "0x7f000001" likewise, "0177.0.0.1" is octal.
    Legitimate DNS names never use these forms.
    """
    host = hostname.lower().rstrip(".")
    if host.isdigit():
        return True
    if "0x" in host:
        return True
    return any(
        len(label) > 1 and label.startswith("0") and label[1:].isdigit()
        for label in host.split(".")
    )


def check_hostname(hostname: str) -> None:
    """Reject hostnames that can only refer to the local host / private infra."""
    host = hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeTargetError(f"Host '{host}' is not allowed")
    if _looks_like_obfuscated_ip(host):
        raise UnsafeTargetError(f"Hostname '{host}' looks like an obfuscated IP address")


def check_ip(ip: str) -> None:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        raise UnsafeTargetError(f"Invalid IP address: {ip}") from None
    if is_blocked_ip(parsed):
        raise UnsafeTargetError(f"Target resolves to a private/reserved address ({ip})")


async def default_resolver(hostname: str) -> list[str]:
    """Resolve a hostname to all of its IP addresses."""
    loop = asyncio.get_running_loop()

    def _resolve() -> list[str]:
        import socket

        results = socket.getaddrinfo(hostname, None)
        return sorted({info[4][0] for info in results})

    return await loop.run_in_executor(None, _resolve)


async def validate_target(
    url: str,
    *,
    allow_http: bool,
    allow_private: bool,
    resolver=default_resolver,
) -> list[str]:
    """Validate a replay target and return the validated IP addresses.

    Raises UnsafeTargetError when blocked. The returned list lets the caller
    pin the TCP connection to a validated address (DNS rebinding defence).
    Empty list means private networks are explicitly allowed (demo mode).
    """
    parts = urlparse(url)

    allowed_schemes = {"https"} | ({"http"} if allow_http else set())
    if parts.scheme not in allowed_schemes:
        if parts.scheme in {"", "http"}:
            raise UnsafeTargetError(INSECURE_SCHEMES_HINT)
        raise UnsafeTargetError(f"Scheme '{parts.scheme or 'none'}:' is not allowed")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeTargetError("Target URL has no hostname")
    if parts.username or parts.password:
        raise UnsafeTargetError("Credentials embedded in the target URL are not allowed")

    if allow_private:
        return []

    check_hostname(hostname)

    try:
        ipaddress.ip_address(hostname)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        check_ip(hostname)
        return [hostname]

    try:
        ips = await resolver(hostname)
    except OSError as exc:
        raise UnsafeTargetError(f"DNS resolution failed for '{hostname}'") from exc
    if not ips:
        raise UnsafeTargetError(f"DNS resolution returned no addresses for '{hostname}'")
    for ip in ips:
        check_ip(ip)
    return ips
