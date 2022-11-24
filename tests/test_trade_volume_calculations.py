import asyncio
import json
import requests
import time
from uniswap_functions import get_pair_trade_volume, load_rate_limiter_scripts
from redis_conn import provide_async_redis_conn_insta
import os
from rich.console import Console
from clean_slate import redis_cleanup_pooler_namespace
from dynaconf import settings
from ipfs_async import client as ipfs_client
from rich.table import Table
from web3 import Web3


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

def pretty_relative_time(time_diff_secs):
    weeks_per_month = 365.242 / 12 / 7
    intervals = [('minute', 60), ('hour', 60), ('day', 24), ('week', 7),
                 ('month', weeks_per_month), ('year', 12)]

    unit, number = 'second', abs(time_diff_secs)
    for new_unit, ratio in intervals:
        new_number = float(number) / ratio
        # If the new number is too small, don't go to the next unit.
        if new_number < 2:
            break
        unit, number = new_unit, new_number
    shown_num = int(number)
    return '{} {}'.format(shown_num, unit + (' ago' if shown_num == 1 else 's ago'))

async def get_dag_cid_output(dag_cid):
    out = await ipfs_client.dag.get(dag_cid)
    if not out:
        return {}
    return out.as_json()

async def get_payload_cid_output(cid):
    out = await ipfs_client.cat(cid)
    if not out:
        return {}
    return json.loads(out.decode('utf-8'))

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
                # if format(powerloom_log["trade_amount_usd"], ".2f") != format(float(uniswap_log["amountUSD"]), ".2f"):
                #     print(powerloom_log["transactionHash"], "\ntimestamp: ", uniswap_log["timestamp"], "\nblock number : ", powerloom_log["blockNumber"], "\nrpc trade volume: ", powerloom_log["trade_amount_usd"],"\n uniswap api trade volume : ",  uniswap_log["amountUSD"], "\n\n")
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


    table = Table(title=f"[bold magenta]Trade volume calculated from event logs that were found common in indexers:[/bold magenta]", show_header=True, header_style="bold magenta")
    table.add_column("Powerloom indexer", justify="center", min_width=30)
    table.add_column("Uniswap indexer", justify="center", min_width=30)
    table.add_row(
        f"{int(powerloom_total_trade_volume)}", 
        f"{int(uniswap_total_trade_volume)}"
    )
    console.print(table)

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
        table = Table(title=f"[bold red]Trade volume calculated from event logs which are not common in indexers:[/bold red]", show_header=True, header_style="bold magenta")
        table.add_column("Powerloom indexer", justify="center", min_width=30)
        table.add_column("Uniswap indexer", justify="center", min_width=30)
        table.add_row(
            f"{int(powerloom_total_trade_volume)}", 
            f"{int(uniswap_total_trade_volume)}"
        )
        console.print(table)
        print("\n")

    if powerloom_total_trade_volume>0 or uniswap_total_trade_volume>0:
        console.print(f"\n\t [bold magenta]Uncommon event logs file path:[bold magenta] {directory_path+file_path}")
        console.print(f"\n\t [bold magenta]uniswap_url:[bold magenta] {uniswap_url}")
        console.print(f"\n\t [bold magenta]uniswap_payload:[bold magenta] {uniswap_payload}")




async def verify_trade_volume_cids(data_cid, timePeriod):

    data = await get_payload_cid_output(data_cid)

    timePeriod = 'trade_volume_24h_cids' if timePeriod == '24h' else 'trade_volume_7d_cids'
    trade_volume_cids = data['resultant'][timePeriod]
    total_trade_volume_usd = 0

    dag_cid = trade_volume_cids['latest_dag_cid']
    raw_event_logs = []
    dag_block_count = 1

    metadata = {
        4500: "bafyreidftmeynvjyqszkrgtha2i5jmujw6bce2q2qal66gl53eabrk42cq",
        4000: "bafyreibghv2wvybszpfmkkqhmugxxkqm7o2eouh6puzwpta52egfywfeh4",
        3500: "bafyreie3xjvpfyekvcuhj6ucx4iac2ppv2pd7ftokakxwssblqda74utx4",
        3000: "bafyreid5gtgr73rgyyzbxuwuz6js2ke4kk23s7tdwcixwfuldshciyb5ua"
    }
    
    while (trade_volume_cids['oldest_dag_cid'] != dag_cid):
        dagBlockData = await get_dag_cid_output(dag_cid)

        payload_cid = dagBlockData['data']['cid']['/']
        payloadData = await get_payload_cid_output(payload_cid)

        raw_event_logs.append({
            "logs": payloadData['events']['Swap']['logs'] + payloadData['events']['Mint']['logs'] + payloadData['events']['Burn']['logs'],
            "totalTrade": payloadData["totalTrade"],
            "totalFee": payloadData["totalFee"],
            "token0TradeVolume": payloadData["token0TradeVolume"],
            "token1TradeVolume": payloadData["token1TradeVolume"],
            "token0TradeVolumeUSD": payloadData["token0TradeVolumeUSD"],
            "token1TradeVolumeUSD": payloadData["token1TradeVolumeUSD"]
        })

        total_trade_volume_usd += float(payloadData["totalTrade"])

        if dag_block_count % 500 == 0:
            console.print(f"[bold magenta]processed {dag_block_count} dag blocks..[/bold magenta]")

        if dagBlockData['prevCid'] == None:
            dag_cid = metadata[dagBlockData['height'] - 1]
        else:
            dag_cid = dagBlockData['prevCid']["/"]
        dag_block_count += 1

    console.print(f"[bold magenta] Total dag blocks: {dag_block_count}[/bold magenta]")
    write_json_file('./temp/', 'powerloom_snapshot_data.json', raw_event_logs)
    return total_trade_volume_usd

@provide_async_redis_conn_insta
async def verify_trade_volume_calculations(loop, pair_contract, timePeriod, start_block, end_block, start_block_timestamp, end_block_timestamp, pair_contract_cid, debug_logs, redis_conn=None):
    
    # set timestamps
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

    # create batch of block-range to fetch event logs
    console.print(f"[bright_cyan]Call RPC to fetch event logs in block range:[bright_cyan] {start_block} - {end_block}")
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

        # call trade volume helper function
        data = await get_pair_trade_volume(
            ev_loop=loop, 
            rate_limit_lua_script_shas=rate_limiting_lua_scripts,
            pair_address=pair_contract, 
            from_block=start, 
            to_block=end,
            redis_conn=redis_conn,
            fetch_timestamp=False,
            web3_provider={"force_archive": True}
        )
        processed_logs_batches.append(data)

    # aggregate processed logs volume (this same as what we do in _construct_trade_volume_epoch_snapshot_data function)
    total_trades_in_usd = 0.0
    for processed_logs in processed_logs_batches:
        tracking_event = 'Swap'
        for key, value in processed_logs[tracking_event].items():
            if key == 'logs':
                debug_trade_logs["powerloom"][tracking_event].extend(value)
            if key == 'trades':
                total_trades_in_usd += value['totalTradesUSD']
    
    trade_volume_data = {
        "powerloom_trade_volume": float(f'{total_trades_in_usd: .6f}')
    }

    # Fetch trade volume data from *** UNISWAP GRAPH API ***
    console.print("\n[bright_cyan]Fetching uniswap subgraph data...[/bright_cyan]")
    uniswap_url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
    skip = 0
    trade_volume_data["uniswap_trade_volume"] = 0
    while(True):
        uniswap_payload = "{\"query\":\"{\\n  swaps(orderBy: timestamp, orderDirection: desc, first: 1000, skip: "+str(skip)+" where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lte: "+ str(current_time)+ ",\\n    timestamp_gte: "+ str(from_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0In,\\n    amount0Out,\\n    amount1Out,\\n    amount1In\\n  }\\n}\\n\",\"variables\":null}"
        headers = {'Content-Type': 'text/plain'}
        response = requests.request("POST", uniswap_url, headers=headers, data=uniswap_payload)
        if response.status_code == 200:
            total_trades_in_usd = 0.0
            data = json.loads(response.text)
            if data.get('data'):
                swaps = data["data"]["swaps"]
                for obj in swaps:
                    debug_trade_logs["uniswap"]["swaps"].append(obj)
                    total_trades_in_usd += float(obj['amountUSD'])
                trade_volume_data["uniswap_trade_volume"] += total_trades_in_usd
                skip += 1000
            else: 
                break
        else:
            print(f"Error fetching data from uniswap THE GRAPH")
            trade_volume_data["uniswap_trade_volume"] = None        

    # Fetch trade volume data from Powerloom IPFS snapshots  
    # console.print("\n[bright_cyan]Calculating trade volume using powerloom ipfs snapshot:[/bright_cyan]")
    # powerloom_snapshot_result = await verify_trade_volume_cids(pair_contract_cid, timePeriod)
    # console.print("\n[bold magenta]pair_contract:[/bold magenta]", f"[bold bright_cyan]{pair_contract}[/bold bright_cyan]\n")

    # PRINT RESULTS
    print("\n")
    table = Table(title=f"[bold magenta]{timePeriod} Trade volume calculated by each indexer:[/bold magenta]", show_header=True, header_style="bold magenta")
    # table.add_column("Powerloom IPFS snapshot", justify="center")
    table.add_column("Powerloom RPC functions", justify="center")
    table.add_column("Uniswap API", justify="center")
    table.add_row(
        # f"{int(powerloom_snapshot_result)}", 
        f"{int(trade_volume_data['powerloom_trade_volume'])}", 
        f"{int(trade_volume_data['uniswap_trade_volume'])}"
    )
    console.print(table)
    print("\n")

    # print debug logs     
    if debug_logs:
        temp_directory = "temp/"
        uniswap_logs_path = "uniswap_logs.json"
        powerloom_logs_path = "powerloom_logs.json"
        common_logs_path = "common_logs.json"
        extra_logs_path = "extra_logs.json"
        
        # write resulting logs to temporary file
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


async def generate_trade_volume_report(loop, pair_contract, timePeriod, debug_logs):
    
    if timePeriod not in ["24h", "7d"]:
        console.print(f"\n [bold red] Invalid time period[/bold red]")
        return


    # get start and end block for give timeperiod using powerloom public api
    response = requests.request("GET", "https://uniswapv2-staging.powerloom.io//api/v1/api/v2-pairs", headers={'Content-Type': 'text/plain'}, data={})
    if response.status_code == 200:
        response = json.loads(response.text)
    else:
        console.print(f"\n [bold red] Powerloom /v2-pairs api failed to respond[/bold red]")
        return


    start_block = response.get(f'begin_block_height_{timePeriod}')
    start_block_timestamp = response.get(f'begin_block_timestamp_{timePeriod}')
    end_block = response.get('block_height')
    end_block_timestamp = response.get('block_timestamp')

    # find cid for given pair_contract and timeperiod
    pair_contract_cid = None
    for contract_obj in response.get('data'):
        if Web3.toChecksumAddress(contract_obj.get('contractAddress')) == Web3.toChecksumAddress(pair_contract):
            pair_contract_cid = contract_obj.get(f'cid_volume_{timePeriod}')
            break

    # call trade volume helpers and uniswap subgraph api
    await verify_trade_volume_calculations(loop, pair_contract, timePeriod, start_block, end_block, start_block_timestamp, end_block_timestamp, pair_contract_cid, debug_logs)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    # ************* CHANGE THESE VALUES ****************** 
    pair_contract = '0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc'
    timePeriod = '24h' # '24h' OR '7d'
    # ********************************************************************

    loop.run_until_complete(
        generate_trade_volume_report(loop, pair_contract, timePeriod, True)
    )