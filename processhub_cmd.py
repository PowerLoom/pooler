from typing import Optional
import json
import time
from datetime import datetime

import redis
import psutil
import typer
import timeago
from dynaconf import settings

from process_hub_core import PROC_STR_ID_TO_CLASS_MAP
from init_rabbitmq import create_rabbitmq_conn, processhub_command_publish
from message_models import ProcessHubCommand
from redis_conn import REDIS_CONN_CONF
from redis_keys import (
    powerloom_broadcast_id_zset,
    uniswap_cb_broadcast_processing_logs_zset,
    uniswap_projects_dag_verifier_status
)


app = typer.Typer()

def read_json_file(file_path: str):
    """Read given json file and return its content as a dictionary."""
    try:
        f_ = open(file_path, 'r')
    except Exception as exc:
        print(f"Unable to open the {file_path} file, error msg:{str(exc)}")
    else:
        print(f"Reading {file_path} file")
        json_data = json.loads(f_.read())
    return json_data

@app.command()
def pidStatus(connections: bool = False):

    def print_formatted_status(process_name, pid):
        try:
            process = psutil.Process(pid=pid)
            print(f"{pid} -")
            print(f"\t name: {process.name()}")
            print(f"\t status: {process.status()}")
            print(f"\t threads: {process.num_threads()}")
            print(f"\t file descriptors: {process.num_fds()}")
            print(f"\t memory: {process.memory_info()}")
            print(f"\t cpu: {process.cpu_times()}")
            print(f"\t number of connections: {len(process.connections(kind='inet'))}")
            if connections:
                print(f"\t number of connections: {process.connections(kind='inet')}")
            print("\n")
        except Exception as err:
            if(type(err).__name__ == "NoSuchProcess"):
                print(f"{pid} - NoSuchProcess")
                print(f"\t name: {process_name}\n")
            else:
                print(f"Unknown Error: {str(err)}")

    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    print("\n")
    for k, v in r.hgetall(name=f'powerloom:uniswap:{settings.NAMESPACE}:Processes').items():
        key = k.decode('utf-8')
        value = v.decode('utf-8')

        if(key == 'callback_workers'):
            value = json.loads(value)
            for i, j in value.items():
                print_formatted_status(j['id'], int(j['pid']))
        elif value.isdigit():
            print_formatted_status(key, int(value))
        else:
            print(f"# Unknown type of key:{key}, value:{value}")
    print("\n")


@app.command()
def broadcastStatus(elapsed_time: int, verbose: Optional[bool] = False):
    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    cur_ts = int(time.time())
    res_ = r.zrangebyscore(
        name=powerloom_broadcast_id_zset,
        min=cur_ts-elapsed_time,
        max=cur_ts,
        withscores=True
    )
    print(f"\n=====> {len(res_)} broadcastId exists in last {elapsed_time} secs\n")
    for k, v in res_:
        key = k.decode('utf-8')
        value = v
        typer.secho(f"{key} -", fg=typer.colors.YELLOW, bold=True)
        typer.echo(typer.style("\t timestamp: ", fg=typer.colors.MAGENTA, bold=True) + f"{value}\n")
        logs = r.zrangebyscore(
            name=uniswap_cb_broadcast_processing_logs_zset.format(f"{key}"),
            min=cur_ts-elapsed_time,
            max=cur_ts,
            withscores=True
        )
        contracts_len = 0
        sub_actions = {
            "PairReserves.SnapshotBuild": {"success": 0, "failure": 0},
            "PairReserves.SnapshotCommit": {"success": 0, "failure": 0},
            "TradeVolume.SnapshotBuild": {"success": 0, "failure": 0},
            "TradeVolume.SnapshotCommit": {"success": 0, "failure": 0},
        }
        failure_info = {
            "PairReserves.SnapshotBuild": [],
            "PairReserves.SnapshotCommit": [],
            "TradeVolume.SnapshotBuild": [],
            "TradeVolume.SnapshotCommit": [],
        }
        if logs:
            for i, j in logs:
                i = i.decode('utf-8')
                i = json.loads(i)
                i['timestamp'] = j
                if i["update"]["action"].lower().find('publish') != -1:
                    contracts_len = len(i["update"]["info"]["msg"]["contracts"])
                    typer.echo(typer.style("\t worker: ", fg=typer.colors.MAGENTA, bold=True) + f"{i['worker']}")
                    typer.echo(typer.style("\t action: ", fg=typer.colors.MAGENTA, bold=True) + f"{i['update']['action']} - {contracts_len} contracts\n")
                elif i["update"]["action"] in sub_actions:
                    if i["update"]["info"]["status"].lower() == "success":
                        sub_actions[i["update"]["action"]]["success"] += 1
                    else:
                        sub_actions[i["update"]["action"]]["failure"] += 1
                        fail_obj = {
                            'msg': i["update"]["info"]["msg"]
                        }
                        if i["update"]["info"].get('exception'):
                            fail_obj["exception"] = i["update"]["info"]["exception"]
                        if i["update"]["info"].get('error'):
                            fail_obj["error"] = i["update"]["info"]["error"]

                        failure_info[i["update"]["action"]].append(fail_obj)
            for i, j in sub_actions.items():
                typer.echo(typer.style(f"\t {i}: ", fg=typer.colors.MAGENTA, bold=True) + f"{str(j)}")
            print("\n")
            if verbose:
                for i, j in failure_info.items():
                    if len(j) > 0:
                        typer.secho(f"\t Failure in {i} : ", fg=typer.colors.RED, bold=True)
                        for k in j:
                            typer.secho(json.dumps(k, sort_keys=True, indent=4), fg=typer.colors.CYAN)
        else:
            print("\t Logs: no log found against this braodcastId")
        print("\n")


@app.command()
def dagChainStatus(dag_chain_height: int = typer.Argument(-1)):

    dag_chain_height = dag_chain_height if dag_chain_height > -1 else '-inf'

    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    pair_contracts = read_json_file('static/cached_pair_addresses.json')
    pair_projects = [
        'projectID:uniswap_pairContract_trade_volume_{}_'+settings.NAMESPACE+':{}',
        'projectID:uniswap_pairContract_pair_total_reserves_{}_'+settings.NAMESPACE+':{}'
    ]
    total_zsets = {}
    total_issue_count = {
        "CURRENT_DAG_CHAIN_HEIGHT": 0,
        "LAG_EXIST_IN_DAG_CHAIN": 0
    }

    # get highest dag chain height
    project_heights = r.hgetall(uniswap_projects_dag_verifier_status)
    if project_heights:
        for _, value in project_heights.items():
            if int(value.decode('utf-8')) > total_issue_count["CURRENT_DAG_CHAIN_HEIGHT"]:
                total_issue_count["CURRENT_DAG_CHAIN_HEIGHT"] = int(value.decode('utf-8'))

    def get_zset_data(key, min, max, pair_address):
        res = r.zrangebyscore(
            name=key.format(pair_address, "dagChainGaps"),
            min=min,
            max=max
        )
        tentative_block_height, block_height = r.mget(
            [
                key.format(f"{pair_address}", "tentativeBlockHeight"),
                key.format(f"{pair_address}", "blockHeight")
            ]
        )
        key_based_issue_stats = {
            "CURRENT_DAG_CHAIN_HEIGHT": 0
        }

        # add tentative and current block height
        if tentative_block_height:
            tentative_block_height = int(tentative_block_height.decode("utf-8")) if type(tentative_block_height) is bytes else int(tentative_block_height)
        else:
            tentative_block_height = None
        if block_height:
            block_height = int(block_height.decode("utf-8")) if type(block_height) is bytes else int(block_height)
        else:
            block_height = None
        key_based_issue_stats["CURRENT_LAG_IN_DAG_CHAIN_HEIGHT"] = tentative_block_height - block_height if tentative_block_height and block_height else None
        if key_based_issue_stats["CURRENT_LAG_IN_DAG_CHAIN_HEIGHT"] != None:
            total_issue_count["LAG_EXIST_IN_DAG_CHAIN"] = key_based_issue_stats["CURRENT_LAG_IN_DAG_CHAIN_HEIGHT"] if key_based_issue_stats["CURRENT_LAG_IN_DAG_CHAIN_HEIGHT"] > total_issue_count["LAG_EXIST_IN_DAG_CHAIN"] else total_issue_count["LAG_EXIST_IN_DAG_CHAIN"]

        if res:
            # parse zset entry
            parsed_res = []
            for entry in res:
                entry = json.loads(entry)

                # create/add issue entry in overall issue structure
                if not entry["issueType"] + "_ISSUE_COUNT" in total_issue_count:
                    total_issue_count[entry["issueType"] + "_ISSUE_COUNT" ] = 0
                if not entry["issueType"] + "_BLOCKS" in total_issue_count:
                    total_issue_count[entry["issueType"] + "_BLOCKS" ] = 0

                # create/add issue entry in "KEY BASED" issue structure
                if not entry["issueType"] + "_ISSUE_COUNT" in key_based_issue_stats:
                    key_based_issue_stats[entry["issueType"] + "_ISSUE_COUNT" ] = 0
                if not entry["issueType"] + "_BLOCKS" in key_based_issue_stats:
                    key_based_issue_stats[entry["issueType"] + "_BLOCKS" ] = 0


                # gather overall issue stats
                total_issue_count[entry["issueType"] + "_ISSUE_COUNT" ] += 1
                key_based_issue_stats[entry["issueType"] + "_ISSUE_COUNT" ] +=  1

                if entry["missingBlockHeightEnd"] == entry["missingBlockHeightStart"]:
                    total_issue_count[entry["issueType"] + "_BLOCKS" ] +=  1
                    key_based_issue_stats[entry["issueType"] + "_BLOCKS" ] +=  1
                else:
                    total_issue_count[entry["issueType"] + "_BLOCKS" ] +=  entry["missingBlockHeightEnd"] - entry["missingBlockHeightStart"] + 1
                    key_based_issue_stats[entry["issueType"] + "_BLOCKS" ] +=  entry["missingBlockHeightEnd"] - entry["missingBlockHeightStart"] + 1

                # store latest dag block height for projectId
                if entry["dagBlockHeight"] > key_based_issue_stats["CURRENT_DAG_CHAIN_HEIGHT"]:
                    key_based_issue_stats["CURRENT_DAG_CHAIN_HEIGHT"] = entry["dagBlockHeight"]

                parsed_res.append(entry)
            res = parsed_res

            print(f"{key.format(pair_address, '')} - ")
            for k, v in key_based_issue_stats.items():
                print(f"\t {k} : {v}")
        else:
            del key_based_issue_stats["CURRENT_DAG_CHAIN_HEIGHT"]
            key_based_issue_stats["tentative_block_height"] = tentative_block_height
            key_based_issue_stats["block_height"] = block_height
            print(f"{key.format(pair_address, '')} - ")
            for k, v in key_based_issue_stats.items():
                print(f"\t {k} : {v}")
            res = []
        return res

    def gather_all_zset(contracts, projects):
        for project in projects:
            for addr in contracts:
                zset_key = project.format(addr, "dagChainGaps")
                total_zsets[zset_key] = get_zset_data(project, dag_chain_height, '+inf', addr)

    gather_all_zset(pair_contracts, pair_projects)

    if total_issue_count["LAG_EXIST_IN_DAG_CHAIN"] > 3:
        total_issue_count["LAG_EXIST_IN_DAG_CHAIN"] = f"THERE IS A LAG WHILE PROCESSING CHAIN, BIGGEST LAG: {total_issue_count['LAG_EXIST_IN_DAG_CHAIN']}"
    else:
        total_issue_count["LAG_EXIST_IN_DAG_CHAIN"] = "NO LAG"


    print("\n======================================> OVERALL ISSUE STATS: \n")
    for k, v in total_issue_count.items():
        print(f"\t {k} : {v}")

    if len(total_issue_count) < 2:
        print("\n##################### NO GAPS FOUND IN CHAIN #####################\n")

    print("\n")


@app.command()
def listBroadcasts(elapsed_time: int):
    """
    Lists broadcasts sent out in the last `elapsed_time` seconds
    """
    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    typer.secho('=' * 20 + f'Broadcasts sent out in last {elapsed_time} seconds' + '=' * 20, fg=typer.colors.CYAN)
    now = datetime.now()
    cur_ts = int(time.time())
    res_ = r.zrangebyscore(
        name=powerloom_broadcast_id_zset,
        min=cur_ts-elapsed_time,
        max=cur_ts,
        withscores=True
    )
    for broadcast_id, occurrence in res_:
        broadcast_id = broadcast_id.decode('utf-8')
        occurrence = datetime.fromtimestamp(occurrence)
        typer.echo('-' * 40+f'\nBroadcast ID: {broadcast_id}\t{timeago.format(occurrence, now)}')
        typer.secho(broadcast_id, fg=typer.colors.YELLOW)
        typer.echo('-' * 40)


# https://typer.tiangolo.com/tutorial/commands/context/#configuring-the-context
@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def start(ctx: typer.Context, process_str_id: str):
    if process_str_id not in PROC_STR_ID_TO_CLASS_MAP.keys():
        typer.secho('Unknown Process identifier supplied. Check list with listProcesses command', err=True, fg=typer.colors.RED)
        return
    kwargs = dict()
    if process_str_id == 'SystemLinearEpochClock':
        # for now assuming it would only be passed as --begin <block_num> , so ctx.args[0] is 'begin'
        try:
            begin_idx = int(ctx.args[1])
        except:
            pass
        else:
            kwargs['begin'] = begin_idx

    typer.secho('Creating RabbitMQ connection...', fg=typer.colors.GREEN)
    c = create_rabbitmq_conn()
    typer.secho('Opening RabbitMQ channel...', fg=typer.colors.GREEN)
    ch = c.channel()
    proc_hub_cmd = ProcessHubCommand(
        command='start',
        proc_str_id=process_str_id,
        init_kwargs=kwargs
    )
    processhub_command_publish(ch, proc_hub_cmd.json())
    typer.secho(f'Sent command to ProcessHubCore to launch process {process_str_id} | Command: {proc_hub_cmd.json()}', fg=typer.colors.YELLOW)


@app.command()
def stop(
        process_str_id: str = typer.Argument(...),
        pid: bool = typer.Option(False, help='Using this flag allows you to pass a process ID instead of the name')
):
    if not pid:
        if process_str_id not in PROC_STR_ID_TO_CLASS_MAP.keys() and process_str_id != 'self':
            typer.secho('Unknown Process identifier supplied. Check list with listProcesses command', err=True, fg=typer.colors.RED)
            return
        else:
            typer.secho('Creating RabbitMQ connection...', fg=typer.colors.GREEN)
            c = create_rabbitmq_conn()
            typer.secho('Opening RabbitMQ channel...', fg=typer.colors.GREEN)
            ch = c.channel()
            proc_hub_cmd = ProcessHubCommand(
                command='stop',
                proc_str_id=process_str_id
            )
            processhub_command_publish(ch, proc_hub_cmd.json())
            typer.secho(f'Sent command to ProcessHubCore to stop process {process_str_id} | Command: {proc_hub_cmd.json()}', fg=typer.colors.YELLOW)
    else:
        process_str_id = int(process_str_id)
        typer.secho('Creating RabbitMQ connection...', fg=typer.colors.GREEN)
        c = create_rabbitmq_conn()
        typer.secho('Opening RabbitMQ channel...', fg=typer.colors.GREEN)
        ch = c.channel()
        proc_hub_cmd = ProcessHubCommand(
            command='stop',
            pid=process_str_id
        )
        processhub_command_publish(ch, proc_hub_cmd.json())
        typer.secho(f'Sent command to ProcessHubCore to stop process PID {process_str_id}', fg=typer.colors.YELLOW)


if __name__ == '__main__':
    app()
