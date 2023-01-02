import asyncio
from datetime import datetime

from pooler.callback_modules.uniswap.core import (get_pair_reserves,
                                                  get_pair_trade_volume)

if __name__ == '__main__':
    toBlock = 15839788

    loop = asyncio.get_event_loop()
    rate_limit_lua_script_shas = dict()
    start_time = datetime.now()
    data = loop.run_until_complete(
        get_pair_reserves(
            loop=loop, 
            rate_limit_lua_script_shas=rate_limit_lua_script_shas, 
            pair_address='0x0e9971ff778b042d549994415fb2774b5a3fe7b6', 
            from_block=toBlock - 10,
            to_block=toBlock,
            fetch_timestamp=True,
            web3_provider={}
        )
    )
    end_time = datetime.now()

    print(f"\n\n{data}\n")
    print(f"time taken to fetch price in epoch range: {start_time} - {end_time}")
    
    rate_limit_lua_script_shas = dict()
    loop = asyncio.get_event_loop()
    start_time = datetime.now()
    data = loop.run_until_complete(
        get_pair_trade_volume(
            rate_limit_lua_script_shas, 
            data_source_contract_address='0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc', 
            min_chain_height=toBlock - 10,
            max_chain_height=toBlock,
            fetch_timestamp=True,
            web3_provider={"force_archive": True}
        )
    )
    end_time = datetime.now()
    print(f"\n\n{data}\n")
    print(f"time taken to fetch price in epoch range: {start_time} - {end_time}")
    
