import pytest

from custom_components.media_metadata_patcher.sources import SOURCES, MetadataSource


def test_keys_are_unique_and_match_classes():
    assert SOURCES
    for key, cls in SOURCES.items():
        assert issubclass(cls, MetadataSource)
        assert cls.key == key
        assert cls.name
        assert cls.poll_interval.total_seconds() >= 5


@pytest.mark.parametrize("source_cls", list(SOURCES.values()))
@pytest.mark.parametrize("content_id", [None, "", "x-rincon-queue:RINCON_X#4", "not a uri"])
def test_match_is_safe_on_unrelated_input(source_cls, content_id):
    assert source_cls().match(content_id) is None
