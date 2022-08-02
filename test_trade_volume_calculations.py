import asyncio
import json
import requests
import time
from uniswap_functions import get_pair_contract_trades_async, load_rate_limiter_scripts
from redis_conn import provide_async_redis_conn_insta
import os
from rich.console import Console
from clean_slate import redis_cleanup_pooler_namespace
from dynaconf import settings

console = Console()


def read_json_file(directory:str, file_name: str):
    try:
        file_path = directory + file_name
        f_ = open(file_path, 'r')
    except Exception as e:
        print(f"Unable to open the {file_path} file")
        raise e
    else:
        json_data = json.loads(f_.read())
    return json_data

def write_json_file(directory:str, file_name: str, data):
    try:
        file_path = directory + file_name
        if not os.path.exists(directory):
            os.makedirs(directory)
        f_ = open(file_path, 'w')
    except Exception as e:
        print(f"Unable to open the {file_path} file")
        raise e
    else:
        json.dump(data, f_, ensure_ascii=False, indent=4)


def generate_logs_analysis(directory_path, uniswap_logs_path, powerloom_logs_path, common_logs_path, extra_logs_path):
    uniswap_data = read_json_file(directory_path, uniswap_logs_path)
    powerloom_data = read_json_file(directory_path, powerloom_logs_path)

    # Aggregate uniswap logs:
    temp_list = []
    for each_event in uniswap_data:
        for uniswap_log in uniswap_data[each_event]:
            uniswap_log["event"] = each_event
            temp_list.append(uniswap_log)
    uniswap_data = temp_list

    # Aggregate powerloom logs:
    temp_list = []
    for each_event in powerloom_data:
        for powerloom_log in powerloom_data[each_event]:
            temp_list.append(powerloom_log)
    powerloom_data = temp_list


    common_logs = []
    extra_logs = []
    for powerloom_log in powerloom_data:
        log_matched = False
        for uniswap_log in uniswap_data:
            # print(powerloom_log["transactionHash"], uniswap_log['id'])
            if powerloom_log["transactionHash"].lower() in uniswap_log['id'].lower():
                log_matched = True
                common_logs.append({
                    "powerloom": powerloom_log,
                    "uniswap": uniswap_log 
                })
                break

        if not log_matched:
            extra_logs.append({
                "powerloom": powerloom_log
            })

    write_json_file(directory_path, common_logs_path, common_logs)
    write_json_file(directory_path, extra_logs_path, extra_logs)


def calculate_common_log_stats(directory_path, file_path):
    data = read_json_file(directory_path, file_path)

    powerloom_total_trade_volume = 0
    uniswap_total_trade_volume = 0
    for obj in data:
        powerloom_total_trade_volume += int(float(obj['powerloom']["trade_amount_usd"]))
        uniswap_total_trade_volume += int(float(obj['uniswap']["amountUSD"]))

    console.print(f"\n [bold magenta]Trade volume calculated from event logs that were found common in indexers:[bold magenta]")
    console.print(f"\t [bold magenta]powerloom indexer:[bold magenta]  [bold bright_cyan]${powerloom_total_trade_volume}[bold bright_cyan]")
    console.print(f"\t [bold magenta]uniswap indexer:[bold magenta]    [bold bright_cyan]${uniswap_total_trade_volume}[bold bright_cyan]")

def calculate_extra_log_stats(directory_path, file_path, uniswap_url, uniswap_payload):
    data = read_json_file(directory_path, file_path)

    powerloom_total_trade_volume = 0
    uniswap_total_trade_volume = 0
    for obj in data:
        if 'powerloom' in obj:
            powerloom_total_trade_volume += int(float(obj['powerloom']["trade_amount_usd"]))
        if 'uniswap' in obj:
            uniswap_total_trade_volume += int(float(obj['uniswap']["amountUSD"]))

    if powerloom_total_trade_volume > 0 or uniswap_total_trade_volume > 0:
        console.print(f"\n [bold magenta]Trade volume calculated from event logs which are not common in indexers:[bold magenta]")
        if powerloom_total_trade_volume > 0:
            console.print(f"\t [bold red]Powerloom indexer found uncommon logs worth trade volume:[bold red]  [bold bright_cyan]${powerloom_total_trade_volume}[bold bright_cyan]")
        if uniswap_total_trade_volume > 0:
            console.print(f"\t [bold red]Uniswap indexer found uncommon logs worth trade volume:[bold red]  [bold bright_cyan]${uniswap_total_trade_volume}[bold bright_cyan]")

    if powerloom_total_trade_volume>0 or uniswap_total_trade_volume>0:
        print("\n")
        console.print(f"\n\t [bold magenta]Uncommon event logs file path:[bold magenta] {directory_path+file_path}")
        console.print(f"\n\t [bold magenta]uniswap_url:[bold magenta] {uniswap_url}")
        console.print(f"\n\t [bold magenta]uniswap_payload:[bold magenta] {uniswap_payload}")

@provide_async_redis_conn_insta
async def verify_trade_volume_calculations(loop, pair_contract, timePeriod, start_block, end_block, start_block_timestamp, end_block_timestamp, debug_logs, redis_conn=None):
    current_time = end_block_timestamp if isinstance(end_block_timestamp, int) else int(time.time())
    if isinstance(start_block_timestamp, int):
        from_time = start_block_timestamp
    elif timePeriod == '7d':
        from_time = current_time - 7*24*60*60
    elif timePeriod == '24h':
        from_time = current_time - 24*60*60
    else:
        from_time = current_time - 24*60*60
    
    # process logs to gather usd calculated volume on events/transaction
    processed_logs_batches = []
    batch_size = 500
    debug_trade_logs = {
        "powerloom": {"Mint": [], "Swap":[], "Burn":[]},
        "uniswap": {"mints": [], "swaps":[], "burns":[]}
    }
    console.print(f"[bright_cyan]Starting log fetch for range:[bright_cyan] {start_block} - {end_block}")
    for i in range(start_block, end_block, batch_size):
        start = end = 0
        if i+batch_size-1 > end_block:
            start = i
            end = end_block
        else:
            start = i
            end = i+batch_size-1
        
        console.print(f"[magenta]Batch:[magenta] {start} - {end}")

        rate_limiting_lua_scripts = await load_rate_limiter_scripts(redis_conn)

        # TODO: supply aioredis connection and rate limiter lua scripts
        data = await get_pair_contract_trades_async(
            ev_loop=loop, 
            rate_limit_lua_script_shas=rate_limiting_lua_scripts,
            pair_address=pair_contract, 
            from_block=start, 
            to_block=end,
            redis_conn=redis_conn,
            fetch_timestamp=False
        )
        processed_logs_batches.append(data)

    # aggregate processed logs volume (this same as what we do in _construct_trade_volume_epoch_snapshot_data function)
    total_trades_in_usd = 0
    for processed_logs in processed_logs_batches:
        for each_event in processed_logs:
            if each_event == 'timestamp':
                continue
            if debug_logs:
                debug_trade_logs["powerloom"][each_event].extend(processed_logs[each_event]['trades']['recent_transaction_logs'])
            total_trades_in_usd += processed_logs[each_event]['trades']['totalTradesUSD']
    
    trade_volume_data = {
        "powerloom_trade_volume": float(f'{total_trades_in_usd: .6f}')
    }


    # Fetch same data from *** UNISWAP THE GRAPH API ***
    uniswap_url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
    uniswap_payload = "{\"query\":\"{\\n  mints(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    feeTo,\\n    feeLiquidity,\\n    amount0,\\n    amount1\\n  },\\n  swaps(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0In,\\n    amount0Out,\\n    amount1Out,\\n    amount1In\\n  },\\n  burns(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0,\\n    amount1\\n  }\\n}\\n\",\"variables\":null}"
    headers = {'Content-Type': 'text/plain'}
    response = requests.request("POST", uniswap_url, headers=headers, data=uniswap_payload)
    if response.status_code == 200:
        total_trades_in_usd = 0
        data = json.loads(response.text)
        data = data["data"]
        for each_event in data:
            for obj in data[each_event]:
                if int(obj['timestamp']) >= int(from_time):
                    debug_trade_logs["uniswap"][each_event].append(obj)
                    total_trades_in_usd += int(float(obj['amountUSD']))
        trade_volume_data["uniswap_trade_volume"] = int(total_trades_in_usd)
    else:
        print(f"Error fetching data from uniswap THE GRAPH")
        trade_volume_data["uniswap_trade_volume"] = None

    console.print("\n[bold magenta]pair_contract:[/bold magenta]", f"[bold bright_cyan]{pair_contract}[/bold bright_cyan]\n")

    # PRINT RESULTS
    #console.print("[bold magenta]DAG CID:[/bold magenta]", f"[bold bright_cyan]{dag_cid}[/bold bright_cyan]")
    console.print(f"\n [bold magenta]{timePeriod} Trade volume calculated by each indexer:[/bold magenta]")
    console.print(f"\t [bold magenta]Powerloom indexer[bold magenta]:  [bold bright_cyan]${trade_volume_data['powerloom_trade_volume']}[bold bright_cyan]")
    console.print(f"\t [bold magenta]Uniswap indexer[bold magenta]:    [bold bright_cyan]${trade_volume_data['uniswap_trade_volume']}[bold bright_cyan]")
    print("\n")

    # print debug logs     
    if debug_logs:
        temp_directory = "temp/"
        uniswap_logs_path = "uniswap_logs.json"
        powerloom_logs_path = "powerloom_logs.json"
        common_logs_path = "common_logs.json"
        extra_logs_path = "extra_logs.json"
        
        write_json_file(temp_directory, uniswap_logs_path, debug_trade_logs["uniswap"])
        write_json_file(temp_directory, powerloom_logs_path, debug_trade_logs["powerloom"])
        generate_logs_analysis(
            temp_directory, 
            uniswap_logs_path, 
            powerloom_logs_path, 
            common_logs_path, 
            extra_logs_path
        )
        calculate_common_log_stats(temp_directory, common_logs_path)
        print("\n")
        calculate_extra_log_stats(temp_directory, extra_logs_path, uniswap_url, uniswap_payload)
        print("\n\n")

    # Clean testing redis
    if settings.from_env('testing').IS_TESTING_ENV:
        redis_cleanup_pooler_namespace({
            "host": settings['redis']['host'],
            "port": settings['redis']['port'],
            "password": settings['redis']['password'],
            "db": settings['redis']['db']
        })



if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    debug_logs = True

    # ************* CHANGE THESE VALUES ****************** 
    pair_contract = '0x004375dff511095cc5a197a54140a24efef3a416'
    timePeriod = '24h'# '24h' OR '7d' 
    start_block = 15222100 # 24h/7d old block on etherscan 
    end_block = 15222400 # latest block on etherscan
    start_block_timestamp = None # 24h/7d old timestamp_int or None
    end_block_timestamp = None # latest to_block timestamp_int or None
    # ********************************************************************

    loop.run_until_complete(
        verify_trade_volume_calculations(loop, pair_contract, timePeriod, start_block, end_block, start_block_timestamp, end_block_timestamp, debug_logs)
    )
