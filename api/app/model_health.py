from dataclasses import dataclass
from time import monotonic


PRIMARY_UNAVAILABLE_TTL_SECONDS = 15 * 60


@dataclass(frozen=True)
class ProviderUnavailable:
    provider: str
    reason: str
    expires_at: float


_unavailable: dict[str, ProviderUnavailable] = {}


def mark_provider_unavailable(
    provider: str,
    reason: str,
    ttl_seconds: float = PRIMARY_UNAVAILABLE_TTL_SECONDS,
) -> None:
    _unavailable[provider] = ProviderUnavailable(
        provider=provider,
        reason=reason,
        expires_at=monotonic() + ttl_seconds,
    )


def get_provider_unavailable(provider: str) -> ProviderUnavailable | None:
    marker = _unavailable.get(provider)
    if marker is None:
        return None

    if marker.expires_at <= monotonic():
        _unavailable.pop(provider, None)
        return None

    return marker
