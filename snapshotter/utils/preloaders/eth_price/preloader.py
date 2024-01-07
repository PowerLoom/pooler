from snapshotter.utils.callback_helpers import GenericPreloader
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.snapshot_utils import get_eth_price_usd


class EthPricePreloader(GenericPreloader):
    def __init__(self) -> None:
        self._logger = logger.bind(module='BlockDetailsPreloader')

    async def compute(
            self,
            epoch: EpochBase,
            rpc_helper: RpcHelper,

    ):
        min_chain_height = epoch.begin
        max_chain_height = epoch.end
        # get eth price for all blocks in range
        # return dict of block_height: eth_price
        try:
            eth_price_dict = await get_eth_price_usd(
                from_block=min_chain_height,
                to_block=max_chain_height,
                rpc_helper=rpc_helper,
            )
            return eth_price_dict
        except Exception as e:
            self._logger.error(f'Error in Eth Price preloader: {e}')

    async def cleanup(self):
        pass
