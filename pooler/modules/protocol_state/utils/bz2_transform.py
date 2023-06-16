import bz2
from typing import Union

from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage, PowerloomSnapshotSubmittedMessage


def chunked(size, source):
    for i in range(0, len(source), size):
        yield source[i: i + size]


def bz2_archive_transformation(data: bytes, msg_obj: Union[PowerloomSnapshotSubmittedMessage, PowerloomCalculateAggregateMessage]):
    compressor = bz2.BZ2Compressor()
    out = b''
    for chunk in chunked(1024, data):
        out += compressor.compress(chunk)
    out += compressor.flush()
    return out


def bz2_unzip(data: bytes):
    uncompressed = b''
    decompressor = bz2.BZ2Decompressor()
    for chunk in chunked(1024, data):
        uncompressed += decompressor.decompress(chunk)
    return uncompressed

