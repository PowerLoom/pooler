import web3.datastructures
from pydantic import ValidationError
from redis import asyncio as aioredis

from snapshotter.utils.callback_helpers import GenericDelegateProcessor
from snapshotter.utils.default_logger import logger
from snapshotter.utils.helper_functions import attribute_dict_to_dict
from snapshotter.utils.models.message_models import PowerloomDelegateTxReceiptWorkerResponseMessage
from snapshotter.utils.models.message_models import PowerloomDelegateWorkerRequestMessage
from snapshotter.utils.rpc import RpcHelper


class TxReceiptProcessor(GenericDelegateProcessor):
    def __init__(self) -> None:
        self._logger = logger.bind(module='TxReceiptPreloader')

    async def compute(
            self,
            msg_obj: PowerloomDelegateWorkerRequestMessage,
            redis_conn: aioredis.Redis,
            rpc_helper: RpcHelper,
    ):
        """Function used to process the received message object."""
        self._logger.trace(
            'Processing tx receipt fetch for {}', msg_obj,
        )
        if 'tx_hash' not in msg_obj.extra:
            raise ValidationError(
                f'No tx_hash found in'
                f' {msg_obj.extra}. Skipping...',
            )
        tx_hash = msg_obj.extra['tx_hash']
        tx_receipt_obj: web3.datastructures.AttributeDict = await rpc_helper.get_transaction_receipt(
            tx_hash,
            redis_conn,
        )
        tx_receipt_dict = attribute_dict_to_dict(tx_receipt_obj)
        return PowerloomDelegateTxReceiptWorkerResponseMessage(
            txHash=tx_hash,
            requestId=msg_obj.requestId,
            txReceipt=tx_receipt_dict,
            epochId=msg_obj.epochId,
        )
