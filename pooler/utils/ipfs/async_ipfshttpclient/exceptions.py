import typing as ty

import multiaddr


class Error(Exception):
    """Base class for all exceptions in this module."""
    __slots__ = ()


class AddressError(Error, multiaddr.exceptions.Error):  # type: ignore[no-any-unimported, misc]
    """Raised when the provided daemon location Multiaddr does not match any
    of the supported patterns."""
    __slots__ = ('addr',)

    addr: ty.Union[str, bytes]

    def __init__(self, addr: ty.Union[str, bytes]) -> None:
        self.addr = addr
        Error.__init__(self, 'Unsupported Multiaddr pattern: {0!r}'.format(addr))
