from process_hub_core import PROC_STR_ID_TO_CLASS_MAP
from init_rabbitmq import create_rabbitmq_conn, processhub_command_publish
from message_models import ProcessHubCommand
from redis_conn import REDIS_CONN_CONF
from redis_keys import powerloom_broadcast_id_zset
from datetime import datetime
from dynaconf import settings
import timeago
import typer
import json
import time
import redis

app = typer.Typer()


@app.command()
def listProcesses():
    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    typer.secho('='*20+'Processes available to control'+'='*20, fg=typer.colors.CYAN)
    for each in PROC_STR_ID_TO_CLASS_MAP.keys():
        typer.echo(each)
    typer.secho('='*20+'Last recorded running processes:'+'='*20, fg=typer.colors.CYAN)
    for k, v in r.hgetall(name=f'powerloom:uniswap:{settings.NAMESPACE}:Processes').items():
        typer.echo(f'{k.decode("utf-8")}: {v.decode("utf-8")}')
    typer.secho('=' * 60, fg=typer.colors.CYAN)


@app.command()
def listCallbackStatus():
    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    typer.secho('='*20+'TRADE VOLUME PROCESSING STATUS'+'='*20, fg=typer.colors.CYAN)
    for k in r.scan_iter(match=f'polymarket:marketMaker:{settings.NAMESPACE}:*:tradesProcessingStatus'):
        key = k.decode('utf-8')
        contract_addr = key.split(':')[3]
        typer.secho(contract_addr, fg=typer.colors.YELLOW)
        typer.echo(r.get(k).decode('utf-8'))
        typer.echo('-'*40)
    typer.secho('='*20+'LIQUIDITY PROCESSING STATUS'+'='*20, fg=typer.colors.CYAN)
    for k in r.scan_iter(match=f'polymarket:marketMaker:{settings.NAMESPACE}:*:liquidityProcessingStatus'):
        key = k.decode('utf-8')
        contract_addr = key.split(':')[3]
        typer.secho(contract_addr, fg=typer.colors.YELLOW)
        typer.echo(r.get(k).decode('utf-8'))
        typer.echo('-'*40)

@app.command()
def listSeedLocks():
    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    typer.secho('='*20+'TRADE VOLUME SEEDING LOCKS'+'='*20, fg=typer.colors.CYAN)
    for k in r.scan_iter(match=f'polymarket:marketMaker:{settings.NAMESPACE}:*:tradeVolume:Lock'):
        key = k.decode('utf-8')
        contract_addr = key.split(':')[3]
        typer.secho(contract_addr, fg=typer.colors.YELLOW)
        typer.echo(r.get(k).decode('utf-8'))
        typer.echo('-'*40)
    typer.secho('='*20+'LIQUIDITY SEEDING LOCKS'+'='*20, fg=typer.colors.CYAN)
    for k in r.scan_iter(match=f'polymarket:marketMaker:{settings.NAMESPACE}:*:liquidity:Lock'):
        key = k.decode('utf-8')
        contract_addr = key.split(':')[3]
        typer.secho(contract_addr, fg=typer.colors.YELLOW)
        typer.echo(r.get(k).decode('utf-8'))
        typer.echo('-'*40)


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
    for broadcast_ts_tuple in res_:
        broadcast_details = json.loads(broadcast_ts_tuple[0])
        occurrence = datetime.fromtimestamp(broadcast_ts_tuple[1])
        typer.echo('-' * 40+f'\nBroadcast ID: {broadcast_details["broadcast_id"]}\t{timeago.format(occurrence, now)}')
        typer.secho(broadcast_ts_tuple[0].decode('utf-8'), fg=typer.colors.YELLOW)
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
