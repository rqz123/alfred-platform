import threading
from collections import OrderedDict

_MAX_NODES = 1000

_pool: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()


def add(node_id: str, family_id: str, node_type: str, score: float = 0.5) -> None:
    with _lock:
        if node_id in _pool:
            _pool.move_to_end(node_id)
            _pool[node_id]["score"] = score
        else:
            if len(_pool) >= _MAX_NODES:
                _pool.popitem(last=False)  # evict LRU
            _pool[node_id] = {
                "family_id": family_id,
                "type": node_type,
                "score": score,
            }


def touch(node_id: str) -> None:
    with _lock:
        if node_id in _pool:
            _pool.move_to_end(node_id)


def get_family_nodes(family_id: str) -> list[dict]:
    with _lock:
        return [
            {"id": k, **v}
            for k, v in _pool.items()
            if v["family_id"] == family_id
        ]


def size() -> int:
    with _lock:
        return len(_pool)
