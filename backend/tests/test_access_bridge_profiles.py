"""Tests for Source Access Bridge profile identity."""

from pathlib import Path

from app.services.access_bridge.profiles import (
    BrowserProfileStore,
    BrowserProfileRef,
    make_profile_id,
    profile_path,
)


def test_profile_id_includes_plugin_domain_and_proxy():
    first = make_profile_id("69shuba_com", "primary", "proxy-a")
    second = make_profile_id("69shuba_com", "primary", "proxy-b")

    assert first != second
    assert first.startswith("69shuba_com-primary-")


def test_profile_id_sanitizes_parts():
    profile_id = make_profile_id("69shuba.com", "www.69shuba.com", "")

    assert profile_id.startswith("69shuba_com-www_69shuba_com-")
    assert "/" not in profile_id
    assert "\\" not in profile_id


def test_profile_path_stays_under_root(tmp_path):
    ref = BrowserProfileRef(
        plugin_id="69shuba_com",
        domain_profile="primary",
        proxy_profile="proxy-a",
    )

    path = profile_path(tmp_path, ref)

    assert path.parent == Path(tmp_path)
    assert path.name == ref.profile_id


def test_profile_ref_roundtrip_profile_id():
    ref = BrowserProfileRef(
        plugin_id="69shuba_com",
        domain_profile="primary",
        proxy_profile="proxy-a",
    )

    assert ref.profile_id == make_profile_id("69shuba_com", "primary", "proxy-a")


def test_profile_store_reads_and_writes_storage_state(tmp_path):
    store = BrowserProfileStore(tmp_path)
    ref = BrowserProfileRef("69shuba_com", "primary", "proxy-a")
    state = {"cookies": [{"name": "sid", "value": "1", "domain": "example.com"}]}

    path = store.write_storage_state(ref, state)

    assert path.name == "storage_state.json"
    assert store.read_storage_state(ref) == state


def test_profile_store_can_use_exact_profile_id(tmp_path):
    store = BrowserProfileStore(tmp_path)
    state = {"cookies": []}

    path = store.write_storage_state_by_id("69shuba_com-primary-existing", state)

    assert path.parent.name == "69shuba_com-primary-existing"
    assert store.read_storage_state_by_id("69shuba_com-primary-existing") == state






