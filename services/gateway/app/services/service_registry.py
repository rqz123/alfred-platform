"""
Service registry: loads config/services.yaml and maps intents to service endpoints.
"""

import logging
import os
from pathlib import Path

import yaml

from app.core.config import get_settings

logger = logging.getLogger('alfred.registry')


class ServiceRegistry:
    def __init__(self):
        # Resolve config path: env override → /config (Docker) → repo root (local dev)
        env_path = os.environ.get('SERVICES_YAML_PATH')
        if env_path:
            cfg_path = Path(env_path)
        else:
            docker_path = Path('/config/services.yaml')
            # Local dev: __file__ is .../alfred-platform/services/gateway/app/services/service_registry.py
            # parents[4] = alfred-platform repo root
            parents = Path(__file__).parents
            repo_path = parents[4] / 'config' / 'services.yaml' if len(parents) > 4 else Path('/nonexistent')
            cfg_path = docker_path if docker_path.exists() else repo_path
        try:
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning('services.yaml not found at %s — dispatch disabled', cfg_path)
            self._map: dict[str, dict] = {}
            return

        settings = get_settings()
        self._map = {}
        for svc_id, svc in cfg.get('services', {}).items():
            api_key_env = svc.get('api_key_env', '')
            # pydantic-settings reads .env file + env vars; os.environ fallback for unknown keys
            api_key = getattr(settings, api_key_env.lower(), None) or os.environ.get(api_key_env, '')
            # url_env allows Docker deployments to override localhost URLs
            # e.g. OURCENTS_URL=http://ourcents:8001 overrides services.yaml default
            url = os.environ.get(svc.get('url_env', ''), '') or svc.get('url', '')
            entry = {
                'id': svc_id,
                'name': svc.get('name', svc_id),
                'url': url,
                'api_key': api_key,
            }
            for intent in svc.get('intents', []):
                self._map[intent] = entry

        logger.info('ServiceRegistry loaded %d intent mappings', len(self._map))

    def find_service(self, intent: str) -> dict | None:
        return self._map.get(intent)
