"""Registry of metadata sources. Order is match priority."""

from __future__ import annotations

from .base import Metadata, MetadataSource
from .bbc import BbcSoundsSource

SOURCES: dict[str, type[MetadataSource]] = {
    source.key: source
    for source in (
        BbcSoundsSource,
    )
}

__all__ = ["SOURCES", "Metadata", "MetadataSource"]
