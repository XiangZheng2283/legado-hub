from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app import config
from app.services import plugin_runtime_state
from conftest import pytest_ignore_collect


def test_pytest_runtime_paths_do_not_use_workspace_data() -> None:
    backend_root = (Path(__file__).resolve().parents[2] / "backend").resolve()
    runtime_root = config.DATA_DIR.resolve().parent

    assert runtime_root != backend_root
    assert not runtime_root.is_relative_to(backend_root)
    assert hasattr(config, "RUNTIME_DIR")
    assert config.DATA_DIR.resolve().parent == runtime_root
    assert config.CONFIG_DIR.resolve().parent == runtime_root
    assert config.GENERATED_DIR.resolve().parent == runtime_root
    assert config.RUNTIME_DIR.resolve().parent == runtime_root
    assert config.DB_PATH.resolve().parent == config.DATA_DIR.resolve()
    assert config.APP_CONFIG_PATH.resolve().parent == config.CONFIG_DIR.resolve()
    assert config.COOKIE_DIR.resolve().parent == config.CONFIG_DIR.resolve()
    assert plugin_runtime_state.RUNTIME_DIR.resolve() == config.RUNTIME_DIR.resolve()
    assert plugin_runtime_state.STATE_FILE.resolve().parent == config.RUNTIME_DIR.resolve()

    writable_paths = (
        config.DATA_DIR,
        config.CONFIG_DIR,
        config.GENERATED_DIR,
        config.RUNTIME_DIR,
        config.DB_PATH,
        config.APP_CONFIG_PATH,
        config.COOKIE_DIR,
    )
    for writable_path in writable_paths:
        assert writable_path.resolve().is_relative_to(runtime_root)


def test_pytest_ignore_collect_defers_for_allowlisted_test() -> None:
    assert pytest_ignore_collect(Path(__file__), None) is None


def test_pytest_ignore_collect_ignores_test_outside_allowlist() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_path = repo_root / "dev-assets/tests/test_ai_client.py"

    assert pytest_ignore_collect(test_path, None) is True


def test_plugin_scheduler_initialization_does_not_mutate_cookie_store(
    tmp_path, monkeypatch
) -> None:
    from app.services.cookie_store import CookieStore
    from app.source_plugins import scheduler as scheduler_module

    cookie_store = CookieStore(base_dir=tmp_path / "cookies")
    cookie_store.save("no_cookie_source", {"cookies": {}})
    plugin = SimpleNamespace(
        metadata=SimpleNamespace(
            id="no_cookie_source",
            enabled=True,
            declares_cookies=False,
        )
    )
    loader = SimpleNamespace(load_all=lambda: {"no_cookie_source": plugin})
    monkeypatch.setattr(scheduler_module, "CookieStore", lambda: cookie_store)

    scheduler_module.PluginScheduler(loader=loader, config={})

    assert cookie_store.path_for("no_cookie_source").exists()


def test_plugin_scheduler_propagates_loader_failure() -> None:
    from app.source_plugins import scheduler as scheduler_module

    def load_all():
        raise RuntimeError("broken plugin")

    loader = SimpleNamespace(load_all=load_all)

    with pytest.raises(RuntimeError, match="broken plugin"):
        scheduler_module.PluginScheduler(loader=loader, config={})


def test_lexicon_updater_uses_target_filesystem_for_temp_directory(
    tmp_path, monkeypatch
) -> None:
    from app.services.lexicon_updater import LexiconUpdater

    lexicon_dir = tmp_path / "lexicons"
    download_dirs: list[Path] = []
    updater = LexiconUpdater(lexicon_dir=lexicon_dir)

    def fake_download(target_dir: Path) -> str:
        download_dirs.append(target_dir)
        (target_dir / "words.txt").write_text("测试\n", encoding="utf-8")
        return "test-sha"

    monkeypatch.setattr(updater, "_download_lexicon", fake_download)

    result = updater.check_and_update()

    assert result.success is True
    assert len(download_dirs) == 1
    assert download_dirs[0].parent == lexicon_dir
    assert not download_dirs[0].exists()


def test_docker_plugin_delivery_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (repo_root / "deploy/docker/entrypoint.sh").read_text(encoding="utf-8")
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    plugin_mount = yaml.safe_load(
        (repo_root / "docker-compose.plugins.yml").read_text(encoding="utf-8")
    )

    assert "plugins/sources/official" in dockerignore
    assert "plugins/sources/thirdparty" not in dockerignore
    assert "backend/runtime" in dockerignore
    assert "plugins/sources/thirdparty/ /opt/legadohub/plugins/thirdparty/" in dockerfile
    assert "ENTRYPOINT [\"legadohub-entrypoint\"]" in dockerfile
    assert "COPY --chown=legadohub:legadohub plugins/ /app/plugins/" not in dockerfile
    assert "/opt/legadohub/plugins/thirdparty" in entrypoint
    assert "/app/plugins/sources/thirdparty" in entrypoint
    assert "cp -a" in entrypoint
    volumes = compose["services"]["legadohub"]["volumes"]
    assert not any("/app/backend/data" in volume for volume in volumes)
    assert not any("/app/backend/config" in volume for volume in volumes)
    assert not any("/app/backend/generated" in volume for volume in volumes)
    assert not any("/app/backend/runtime" in volume for volume in volumes)
    assert compose["services"]["legadohub"].get("read_only") is not True
    assert any(
        volume.endswith(":/app/plugins/sources/official:ro")
        for volume in volumes
    )
    assert any(
        volume.endswith(":/app/plugins/sources/thirdparty:rw")
        for volume in plugin_mount["services"]["legadohub"]["volumes"]
    )
