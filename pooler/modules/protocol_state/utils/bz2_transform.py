import bz2
import json
from typing import Union

from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage, PowerloomSnapshotSubmittedMessage


def bz2_archive_transformation(data: dict, msg_obj: Union[PowerloomSnapshotSubmittedMessage, PowerloomCalculateAggregateMessage]):
    return bz2.compress(json.dumps(data).encode('utf-8'))


def bz2_unzip(data: bytes):
    return bz2.decompress(data)
