from snapshotter.utils.callback_helpers import GenericPreloader
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.snapshot_utils import get_block_details_in_block_range


class BlockDetailsPreloader(GenericPreloader):
    def __init__(self) -> None:
        self._logger = logger.bind(module='BlockDetailsPreloader')

    async def compute(
            self,
            epoch: EpochBase,
            rpc_helper: RpcHelper,

    ):
        min_chain_height = epoch.begin
        max_chain_height = epoch.end
        try:
            block_details = await get_block_details_in_block_range(
                from_block=min_chain_height,
                to_block=max_chain_height,
                rpc_helper=rpc_helper,
            )
            return block_details
        except Exception as e:
            self._logger.error(f'Error in block details preloader: {e}')

    async def cleanup(self):
        pass
