import asyncio
from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger as rest_logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.rpc import RpcHelper

from snapshotter.settings.config import aggregator_config
from snapshotter.settings.config import projects_config
from snapshotter.utils.models.settings_model import AggregateOn
from snapshotter.utils.helper_functions import gen_multiple_type_project_id
from snapshotter.utils.helper_functions import gen_single_type_project_id
from snapshotter.utils.redis.redis_keys import stored_projects_key

from snapshotter.utils.data_utils import snapshotter_last_finalized_check


async def test_last_finalized_check():

    anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
    aioredis_pool = RedisPoolCache()
    await aioredis_pool.populate()
    redis_conn = aioredis_pool._aioredis_pool
    protocol_state_contract_abi = read_json_file(
        settings.protocol_state.abi,
        rest_logger,
    )
    protocol_state_contract_address = settings.protocol_state.address
    protocol_state_contract = anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
        address=Web3.toChecksumAddress(
            protocol_state_contract_address,
        ),
        abi=protocol_state_contract_abi,
    )

    all_projects = []

    for project_config in projects_config:
        all_projects += [f'{project_config.project_type}:{project.lower()}:{settings.namespace}' for project in project_config.projects]

    for config in aggregator_config:
        if config.aggregate_on == AggregateOn.single_project:
            project_ids = filter(lambda x: config.filters.projectId in x, all_projects)
            all_projects += [
                gen_single_type_project_id(config.project_type, project_id)
                for project_id in project_ids
            ]
        if config.aggregate_on == AggregateOn.multi_project:
            all_projects.append(gen_multiple_type_project_id(config.project_type, config.projects_to_wait_for))

    await redis_conn.sadd(
        stored_projects_key(),
        *all_projects,
    )

    unfinalized_projects = await snapshotter_last_finalized_check(
        redis_conn,
        protocol_state_contract,
        anchor_rpc_helper,
    )

    print(unfinalized_projects)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_last_finalized_check())