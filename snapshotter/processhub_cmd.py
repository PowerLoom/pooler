import json

import psutil
import redis
import typer

from snapshotter.init_rabbitmq import create_rabbitmq_conn
from snapshotter.init_rabbitmq import processhub_command_publish
from snapshotter.process_hub_core import PROC_STR_ID_TO_CLASS_MAP
from snapshotter.settings.config import settings
from snapshotter.utils.models.message_models import ProcessHubCommand
from snapshotter.utils.redis.redis_conn import REDIS_CONN_CONF

app = typer.Typer()


@app.command()
def pidStatus(connections: bool = False):
    def print_formatted_status(process_name, pid):
        try:
            process = psutil.Process(pid=pid)
            print(f'{pid} -')
            print(f'\t name: {process.name()}')
            print(f'\t status: {process.status()}')
            print(f'\t threads: {process.num_threads()}')
            print(f'\t file descriptors: {process.num_fds()}')
            print(f'\t memory: {process.memory_info()}')
            print(f'\t cpu: {process.cpu_times()}')
            print(
                f"\t number of connections: {len(process.connections(kind='inet'))}",
            )
            if connections:
                print(
                    f"\t number of connections: {process.connections(kind='inet')}",
                )
            print('\n')
        except Exception as err:
            if type(err).__name__ == 'NoSuchProcess':
                print(f'{pid} - NoSuchProcess')
                print(f'\t name: {process_name}\n')
            else:
                print(f'Unknown Error: {str(err)}')

    r = redis.Redis(**REDIS_CONN_CONF, single_connection_client=True)
    print('\n')
    for k, v in r.hgetall(
        name=f'powerloom:uniswap:{settings.namespace}:{settings.instance_id}:Processes',
    ).items():
        key = k.decode('utf-8') 
        value = v.decode('utf-8')

        if key == 'callback_workers':
            value = json.loads(value)
            for i, j in value.items():
                print_formatted_status(j['id'], int(j['pid']))
        elif value.isdigit():
            print_formatted_status(key, int(value))
        else:
            print(f'# Unknown type of key:{key}, value:{value}')
    print('\n')


# https://typer.tiangolo.com/tutorial/commands/context/#configuring-the-context
@app.command(
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
def start(ctx: typer.Context, process_str_id: str):
    if process_str_id not in PROC_STR_ID_TO_CLASS_MAP.keys():
        typer.secho(
            'Unknown Process identifier supplied. Check list with listProcesses command',
            err=True,
            fg=typer.colors.RED,
        )
        return
    kwargs = dict()

    typer.secho('Creating RabbitMQ connection...', fg=typer.colors.GREEN)
    c = create_rabbitmq_conn()
    typer.secho('Opening RabbitMQ channel...', fg=typer.colors.GREEN)
    ch = c.channel()
    proc_hub_cmd = ProcessHubCommand(
        command='start',
        proc_str_id=process_str_id,
        init_kwargs=kwargs,
    )
    processhub_command_publish(ch, proc_hub_cmd.json())
    typer.secho(
        f'Sent command to ProcessHubCore to launch process {process_str_id} | Command: {proc_hub_cmd.json()}',
        fg=typer.colors.YELLOW,
    )


@app.command()
def stop(
    process_str_id: str = typer.Argument(...),
    pid: bool = typer.Option(
        False,
        help='Using this flag allows you to pass a process ID instead of the name',
    ),
):
    if not pid:
        if (
            process_str_id not in PROC_STR_ID_TO_CLASS_MAP.keys() and
            process_str_id != 'self'
        ):
            typer.secho(
                'Unknown Process identifier supplied. Check list with listProcesses command',
                err=True,
                fg=typer.colors.RED,
            )
            return
        else:
            typer.secho(
                'Creating RabbitMQ connection...',
                fg=typer.colors.GREEN,
            )
            c = create_rabbitmq_conn()
            typer.secho('Opening RabbitMQ channel...', fg=typer.colors.GREEN)
            ch = c.channel()
            proc_hub_cmd = ProcessHubCommand(
                command='stop',
                proc_str_id=process_str_id,
            )
            processhub_command_publish(ch, proc_hub_cmd.json())
            typer.secho(
                f'Sent command to ProcessHubCore to stop process {process_str_id} | Command: {proc_hub_cmd.json()}',
                fg=typer.colors.YELLOW,
            )
    else:
        process_str_id = int(process_str_id)
        typer.secho('Creating RabbitMQ connection...', fg=typer.colors.GREEN)
        c = create_rabbitmq_conn()
        typer.secho('Opening RabbitMQ channel...', fg=typer.colors.GREEN)
        ch = c.channel()
        proc_hub_cmd = ProcessHubCommand(
            command='stop',
            pid=process_str_id,
        )
        processhub_command_publish(ch, proc_hub_cmd.json())
        typer.secho(
            f'Sent command to ProcessHubCore to stop process PID {process_str_id}',
            fg=typer.colors.YELLOW,
        )


if __name__ == '__main__':
    app()
