import asyncio
import json
import requests
import time
from uniswap_functions import get_pair_contract_trades_async
import os


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

    powerloom_total_trade_value = 0
    uniswap_total_trade_value = 0
    for obj in data:
        powerloom_total_trade_value += int(float(obj['powerloom']["trade_amount_usd"]))
        uniswap_total_trade_value += int(float(obj['uniswap']["amountUSD"]))

    print("\nCommon logs trade values: ")
    print(f"\t powerloom_total_trade_value: {powerloom_total_trade_value}")
    print(f"\t uniswap_total_trade_value: {uniswap_total_trade_value}")

def calculate_extra_log_stats(directory_path, file_path, uniswap_url, uniswap_payload):
    data = read_json_file(directory_path, file_path)

    powerloom_total_trade_value = 0
    uniswap_total_trade_value = 0
    for obj in data:
        if 'powerloom' in obj:
            powerloom_total_trade_value += int(float(obj['powerloom']["trade_amount_usd"]))
        if 'uniswap' in obj:
            uniswap_total_trade_value += int(float(obj['uniswap']["amountUSD"]))

    print("\nExtra logs trade values: ")
    print(f"\t powerloom_total_trade_value: {powerloom_total_trade_value}")
    print(f"\t uniswap_total_trade_value: {uniswap_total_trade_value}")

    if powerloom_total_trade_value>0 or uniswap_total_trade_value>0:
        print(f"\n\t extra logs file path: {directory_path+file_path}")
        print(f"\n\t uniswap_url: {uniswap_url}")
        print(f"\n\t uniswap_payload: {uniswap_payload}")

async def verify_trade_volume_calculations(loop, pair_contract, start_block, end_block, debug_logs):
    current_time = int(time.time())
    
    # process logs to gather usd calculated value on events/transaction
    processed_logs_batches = []
    batch_size = 1000
    debug_trade_logs = {
        "powerloom": {"Mint": [], "Swap":[], "Burn":[]},
        "uniswap": {"mints": [], "swaps":[], "burns":[]}
    }
    print(f"Starting log fetch for range: {start_block} - {end_block}")
    for i in range(start_block, end_block, batch_size):
        start = end = 0
        if i+batch_size-1 > end_block:
            start = i
            end = end_block
        else:
            start = i
            end = i+batch_size-1
        
        print(f"Batch: {start} - {end}")
        # TODO: supply aioredis connection
        data = await get_pair_contract_trades_async(loop, pair_contract, start, end)
        processed_logs_batches.append(data)

    # aggregate processed logs values (this same as what we do in _construct_trade_volume_epoch_snapshot_data function)
    total_trades_in_usd = 0
    for processed_logs in processed_logs_batches:
        for each_event in processed_logs:
            if each_event == 'timestamp':
                continue
            if debug_logs:
                debug_trade_logs["powerloom"][each_event].extend(processed_logs[each_event]['trades']['recent_transaction_logs'])
            total_trades_in_usd += processed_logs[each_event]['trades']['totalTradesUSD']
    
    trade_volume_data = {
        "powerloom_24h_trade_volume": float(f'{total_trades_in_usd: .6f}')
    }


    # Fetch same data from *** UNISWAP THE GRAPH API ***
    uniswap_url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
    uniswap_payload = "{\"query\":\"{\\n  mints(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    feeTo,\\n    feeLiquidity,\\n    amount0,\\n    amount1\\n  },\\n  swaps(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0In,\\n    amount0Out,\\n    amount1Out,\\n    amount1In\\n  },\\n  burns(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0,\\n    amount1\\n  }\\n}\\n\",\"variables\":null}"
    headers = {'Content-Type': 'text/plain'}
    response = requests.request("POST", uniswap_url, headers=headers, data=uniswap_payload)
    if response.status_code == 200:
        timestamp_24h = current_time - 60 * 60 * 24
        total_trades_in_usd = 0
        data = json.loads(response.text)
        data = data["data"]
        for each_event in data:
            for obj in data[each_event]:
                if int(obj['timestamp']) >= int(timestamp_24h):
                    debug_trade_logs["uniswap"][each_event].append(obj)
                    total_trades_in_usd += int(float(obj['amountUSD']))
        trade_volume_data["uniswap_24h_trade_volume"] = int(total_trades_in_usd)
    else:
        print(f"Error fetching data from uniswap THE GRAPH")
        trade_volume_data["uniswap_24h_trade_volume"] = None
    

    # PRINT RESULTS
    print("\n Results:")
    for k, v in trade_volume_data.items():
        print(f"\t {k} : {v}\n")

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
        calculate_extra_log_stats(temp_directory, extra_logs_path, uniswap_url, uniswap_payload)



if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    debug_logs = True

    # ************* CHANGE THESE VALUES FOR CURRENT TIME ****************** 
    pair_contract = '0xae461ca67b15dc8dc81ce7615e0320da1a9ab8d5'
    start_block = 14525918 # 24h old block on etherscan 
    end_block = 14532376 # latest block on etherscan
    # ********************************************************************

    loop.run_until_complete(
        verify_trade_volume_calculations(loop, pair_contract, start_block, end_block, debug_logs)
    )
