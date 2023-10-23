

class TVLProcessor(GenericProcessorSnapshot):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='TVLProcessor')

    async def compute(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,
    ):
        self._logger.debug(f'total value locked {data_source_contract_address}, computation init time {time.time()}')

        result = get_total_value_locked(
            data_source_contract_address=data_source_contract_address,
            min_chain_height=min_chain_height,
            max_chain_height=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
        )

        self._logger.debug(f'total value locked {data_source_contract_address}, computation end time {time.time()}')
        return result
