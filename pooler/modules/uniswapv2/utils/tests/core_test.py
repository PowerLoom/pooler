import asyncio
from datetime import datetime

import httpx

from ..core import get_pair_reserves
from ..core import get_pair_trade_volume
from pooler.settings.config import settings

if __name__ == '__main__':
    contract = '0xae461ca67b15dc8dc81ce7615e0320da1a9ab8d5'
    consensus_epoch_tracker_url = (
        f'{settings.consensus.url}{settings.consensus.epoch_tracker_path}'
    )
    response = httpx.get(url=consensus_epoch_tracker_url)
    if response.status_code != 200:
        raise Exception(
            f'Error while fetching current epoch data: {response.status_code}',
        )
    current_epoch = response.json()
    to_block = current_epoch['epochEndBlockHeight']
    from_block = current_epoch['epochStartBlockHeight']

    loop = asyncio.get_event_loop()
    rate_limit_lua_script_shas = dict()
    start_time = datetime.now()
    data = loop.run_until_complete(
        get_pair_reserves(
            loop=loop,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas,
            pair_address=contrat,
            from_block=from_block,
            to_block=to_block,
            fetch_timestamp=True,
            web3_provider={},
        ),
    )
    end_time = datetime.now()

    print(f'\n\n{data}\n')
    print(
        f'time taken to fetch price in epoch range: {start_time} - {end_time}',
    )

    rate_limit_lua_script_shas = dict()
    loop = asyncio.get_event_loop()
    start_time = datetime.now()
    data = loop.run_until_complete(
        get_pair_trade_volume(
            rate_limit_lua_script_shas,
            data_source_contract_address=(
                contract
            ),
            min_chain_height=from_block,
            max_chain_height=to_block,
            fetch_timestamp=True,
            web3_provider={},
        ),
    )
    end_time = datetime.now()
    print(f'\n\n{data}\n')
    print(
        f'time taken to fetch price in epoch range: {start_time} - {end_time}',
    )
