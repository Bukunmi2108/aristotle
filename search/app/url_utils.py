from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}


def canonical_url(value: str) -> str | None:
    if not value:
        return None

    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    query_items = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS or lowered.startswith(TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, item_value))

    netloc = parsed.netloc.lower()
    query = urlencode(query_items, doseq=True)
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def url_matches_domains(url: str, domains: list[str]) -> bool:
    if not domains:
        return True
    hostname = urlsplit(url).hostname
    if not hostname:
        return False
    hostname = hostname.lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)
