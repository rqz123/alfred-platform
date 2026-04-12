"""
Service registry: loads config/services.yaml and maps intents to service endpoints.
"""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger('alfred.registry')


class ServiceRegistry:
    def __init__(self):
        cfg_path = Path(__file__).parents[4] / 'config' / 'services.yaml'
        try:
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning('services.yaml not found at %s — dispatch disabled', cfg_path)
            self._map: dict[str, dict] = {}
            return

        self._map = {}
        for svc_id, svc in cfg.get('services', {}).items():
            api_key = os.environ.get(svc.get('api_key_env', ''), '')
            entry = {
                'id': svc_id,
                'name': svc.get('name', svc_id),
                'url': svc.get('url', ''),
                'api_key': api_key,
            }
            for intent in svc.get('intents', []):
                self._map[intent] = entry

        logger.info('ServiceRegistry loaded %d intent mappings', len(self._map))

    def find_service(self, intent: str) -> dict | None:
        return self._map.get(intent)
