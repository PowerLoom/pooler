from collections import OrderedDict
from copy import copy
from functools import wraps
from typing import Hashable
from typing import NamedTuple
from typing import Set

from frozendict import frozendict

# Modified https://jellis18.github.io/post/2021-11-25-lru-cache/


class LruCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.__cache: OrderedDict = OrderedDict()

    def get(self, key: Hashable):
        if key not in self.__cache:
            return None
        self.__cache.move_to_end(key)
        return self.__cache[key]

    def insert(self, key: Hashable, value) -> None:
        if len(self.__cache) == self.capacity:
            self.__cache.popitem(last=False)
        self.__cache[key] = value
        self.__cache.move_to_end(key)

    def __len__(self) -> int:
        return len(self.__cache)

    def clear(self) -> None:
        self.__cache.clear()


class CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int
    currsize: int


class LruCacheRpc:
    def __init__(self, maxsize: int, args: Set):
        self.__cache = LruCache(capacity=maxsize)
        self.__hits = 0
        self.__misses = 0
        self.__maxsize: Final = maxsize
        self.__args = args

    def __make_immutable(self, arg):
        if isinstance(arg, dict):
            return frozendict(arg)
        if isinstance(arg, list):
            return tuple(arg)
        if isinstance(arg, set):
            return frozenset(arg)
        return arg

    def __call__(self, fn):
        wraps(fn)

        async def decorated(*args, **kwargs):
            kwargs_data = copy(kwargs)
            kwargs_data.update(zip(fn.__code__.co_varnames, args))
            cache_args = []

            for kwarg in kwargs_data:
                if kwarg in self.__args:
                    cache_args.append(str(kwargs_data[kwarg]))
            cache_args = hash(tuple(cache_args))
            if not cache_args:
                ret = await fn(*args, **kwargs)
            else:
                ret = self.__cache.get(cache_args)
                if ret is None:
                    self.__misses += 1
                    try:
                        ret = await fn(*args, **kwargs)
                        if ret:
                            self.__cache.insert(cache_args, ret)
                    except:
                        pass
                else:
                    self.__hits += 1

            return ret

        return decorated
