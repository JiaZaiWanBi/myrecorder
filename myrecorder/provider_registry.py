from __future__ import annotations

from .providers.base import StreamProvider
from .providers.direct_m3u8 import DirectM3U8Provider

from .providers.nicochannel import NicoChannelProvider


def build_provider_registry() -> dict[str, StreamProvider]:
    providers: list[StreamProvider] = [
        DirectM3U8Provider(),
        NicoChannelProvider(name="nicochannel"),
    ]
    return {provider.name: provider for provider in providers}
