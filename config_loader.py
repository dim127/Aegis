import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "aegis_config.json")
ENV_PREFIX = "AEGIS_"


def load_config(path: str = None) -> Dict[str, Any]:
    path = path or os.environ.get("AEGIS_CONFIG", DEFAULT_CONFIG_PATH)
    config = {}
    if os.path.exists(path):
        with open(path) as f:
            config = json.load(f)
        logger.info(f"Config loaded from {path}")
    else:
        logger.warning(f"Config file not found: {path}, using defaults")
    return config


def merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def from_env() -> Dict[str, Any]:
    config = {}
    for env_key, env_val in os.environ.items():
        if env_key.startswith(ENV_PREFIX):
            parts = env_key[len(ENV_PREFIX):].lower().split("__")
            current = config
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = _parse_env_value(env_val)
    return config


def _parse_env_value(value: str):
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    if value.lower() == "none":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def get_strategy_config(config: Dict[str, Any], strategy_name: str = "AegisStrategy") -> Dict[str, Any]:
    return config.get("strategy", {}).get(strategy_name, {})


def get_config(config: Dict[str, Any] = None) -> Dict[str, Any]:
    if config is not None:
        return merge_config(load_config(), config)
    return merge_config(load_config(), from_env())


def save_config(config: Dict[str, Any], path: str = None):
    path = path or os.environ.get("AEGIS_CONFIG", DEFAULT_CONFIG_PATH)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config saved to {path}")
