import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schema import ClientConfig

# Root of the monorepo (two levels up from apps/api/app/config/)
_REPO_ROOT = Path(__file__).parents[4]
_CONFIG_DIR = _REPO_ROOT / "config"

# Populated at startup (or reloaded in dev)
_registry: dict[str, ClientConfig] = {}


def _load_all(config_dir: Path) -> dict[str, ClientConfig]:
    configs: dict[str, ClientConfig] = {}
    yaml_files = sorted(config_dir.glob("*.yaml"))

    for path in yaml_files:
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML parse error in {path.name}: {exc}") from exc

        try:
            cfg = ClientConfig.model_validate(raw)
        except ValidationError as exc:
            # Re-raise with filename so the error names both field and file
            messages = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ValueError(f"Config error in {path.name}: {messages}") from exc

        if cfg.client_id in configs:
            existing = next(p for p in yaml_files if yaml.safe_load(p.read_text()).get("client_id") == cfg.client_id and p != path)
            raise ValueError(
                f"Duplicate client_id {cfg.client_id!r} in {path.name} and {existing.name}"
            )

        configs[cfg.client_id] = cfg

    return configs


class ConfigRegistry:
    def __init__(self, config_dir: Path | None = None) -> None:
        self._dir = config_dir or _CONFIG_DIR
        self._dev_reload = os.getenv("DEV_CONFIG_RELOAD", "0") == "1"
        self._configs: dict[str, ClientConfig] = {}
        self._load()

    def _load(self) -> None:
        if self._dir.exists():
            self._configs = _load_all(self._dir)

    def _maybe_reload(self) -> None:
        if self._dev_reload:
            self._load()

    def get(self, client_id: str) -> ClientConfig:
        self._maybe_reload()
        cfg = self._configs.get(client_id)
        if cfg is None:
            raise KeyError(f"Unknown client_id: {client_id!r}")
        return cfg

    def all(self) -> list[ClientConfig]:
        self._maybe_reload()
        return list(self._configs.values())


# Module-level singleton — created at import time (startup)
_registry_instance: ConfigRegistry | None = None


def get_registry() -> ConfigRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ConfigRegistry()
    return _registry_instance
