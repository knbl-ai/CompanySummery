import re
from urllib.parse import urlparse

PRIVATE_IP_PATTERNS = [
    re.compile(r"^127\."),
    re.compile(r"^10\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[0-1])\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^0\."),
    re.compile(r"^169\.254\."),
    re.compile(r"^::1$"),
    re.compile(r"^fc00:", re.IGNORECASE),
    re.compile(r"^fe80:", re.IGNORECASE),
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "kubernetes.default",
    "kubernetes.default.svc",
}


def validate_url(url_string: str) -> tuple[bool, str | None]:
    """Validate a URL for SSRF protection. Returns (is_valid, reason)."""
    try:
        parsed = urlparse(url_string)
    except Exception:
        return False, "Invalid URL format."

    if parsed.scheme not in ("http", "https"):
        return False, f"Protocol '{parsed.scheme}' is not allowed. Only http and https are permitted."

    hostname = parsed.hostname or ""
    lower_hostname = hostname.lower()

    if lower_hostname in BLOCKED_HOSTNAMES:
        return False, "Access to internal or private resources is not allowed."

    if lower_hostname.endswith((".internal", ".local", ".localhost")):
        return False, "Access to internal or private resources is not allowed."

    for pattern in PRIVATE_IP_PATTERNS:
        if pattern.search(hostname):
            return False, "Access to internal or private resources is not allowed."

    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are not allowed."

    # Decimal IP (e.g., http://2130706433)
    if re.match(r"^\d+$", hostname):
        return False, "Numeric IP addresses are not allowed."

    # Octal IP
    if re.match(r"^0[0-7]+\.", hostname):
        return False, "Octal IP addresses are not allowed."

    # Hex IP
    if re.match(r"^0x[0-9a-f]+", hostname, re.IGNORECASE):
        return False, "Hexadecimal IP addresses are not allowed."

    return True, None
