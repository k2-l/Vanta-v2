from __future__ import annotations

from collections import OrderedDict


class LRUDict(OrderedDict):
    """OrderedDict with a maximum size that evicts the least-recently-used entry on overflow.

    Usage:
        cache = LRUDict(maxsize=200)
        cache[key] = value          # auto-evicts oldest entry when len > maxsize
        cache.move_to_end(key)      # mark key as most-recently-used
    """

    def __init__(self, maxsize: int, *args, **kwargs):
        self._maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)  # evict LRU entry
