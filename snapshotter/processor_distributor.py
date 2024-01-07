import asyncio
import importlib
import json
import multiprocessing
import resource
from collections import defaultdict
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Union
from uuid import uuid4

import uvloop
from eth_utils.address import to_checksum_address
from eth_utils.crypto import keccak
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from web3 import Web3

from snapshotter.settings.config import preloaders
from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.data_utils import get_snapshot_submision_window
from snapshotter.utils.data_utils import get_source_chain_epoch_size
from snapshotter.utils.data_utils import get_source_chain_id
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import SnapshottersUpdatedEvent
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.models.message_models import SlotsPerDayUpdatedMessage
from snapshotter.utils.models.message_models import SnapshotProcessMessage
from snapshotter.utils.rpc import RpcHelper


class ProcessorDistributor(multiprocessing.Process):
    _anchor_rpc_helper: RpcHelper
    _async_transport: AsyncHTTPTransport
    _client: AsyncClient

    def __init__(self, name, **kwargs):
        """
        Initialize the ProcessorDistributor object.

        Args:
            name (str): The name of the ProcessorDistributor.
            **kwargs: Additional keyword arguments.

        Attributes:
            _unique_id (str): The unique ID of the ProcessorDistributor.
            _shutdown_initiated (bool): Flag indicating if shutdown has been initiated.
            _rpc_helper: The RPC helper object.
            _source_chain_id: The source chain ID.
            _projects_list: The list of projects.
            _initialized (bool): Flag indicating if the ProcessorDistributor has been initialized.
            _upcoming_project_changes (defaultdict): Dictionary of upcoming project changes.
            _preload_completion_conditions (defaultdict): Dictionary of preload completion conditions.
            _shutdown_initiated (bool): Flag indicating if shutdown has been initiated.
            _all_preload_tasks (set): Set of all preload tasks.
            _project_type_config_mapping (dict): Dictionary mapping project types to their configurations.
            _preloader_compute_mapping (dict): Dictionary mapping preloader tasks to compute resources.
        """
        super(ProcessorDistributor, self).__init__(name=name, **kwargs)
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._shutdown_initiated = False
        self._rpc_helper = None
        self._source_chain_id = None
        self._projects_list = None

        self._initialized = False
        self._upcoming_project_changes = defaultdict(list)
        self._preload_completion_conditions: Dict[int, Dict] = defaultdict(
            dict,
        )  # epoch ID to preloading complete event

        self._shutdown_initiated = False
        self._all_preload_tasks = set()
        self._project_type_config_mapping = dict()
        for project_config in projects_config:
            self._project_type_config_mapping[project_config.project_type] = project_config
            for proload_task in project_config.preload_tasks:
                self._all_preload_tasks.add(proload_task)
        self._preloader_compute_mapping = dict()

    async def _init_rpc_helper(self):
        """
        Initializes the RpcHelper instance if it is not already initialized.
        """
        if not self._rpc_helper:
            self._rpc_helper = RpcHelper()
            self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)

    async def _init_httpx_client(self):
        """
        Initializes the HTTPX client with the specified settings.
        """
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            base_url=settings.reporting.service_url,
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    async def _init_preloader_compute_mapping(self):
        """
        Initializes the preloader compute mapping by importing the preloader module and class and
        adding it to the mapping dictionary.
        """
        if self._preloader_compute_mapping:
            return

        for preloader in preloaders:
            if preloader.task_type in self._all_preload_tasks:
                preloader_module = importlib.import_module(preloader.module)
                preloader_class = getattr(preloader_module, preloader.class_name)
                self._preloader_compute_mapping[preloader.task_type] = preloader_class

    async def init_worker(self):
        """
        Initializes the worker by initializing the RPC helper, loading project metadata,
        initializing the preloader compute mapping.
        """
        if not self._initialized:
            await self._init_httpx_client()
            await self._init_rpc_helper()
            await self._load_projects_metadata()
            await self._init_preloader_compute_mapping()
            self._initialized = True

    async def _load_projects_metadata(self):
        """
        Loads the metadata for the projects, including the source chain ID, the list of projects, and the submission window
        for snapshots. It also updates the project type configuration mapping with the relevant projects.
        """
        if not self._projects_list:
            with open(settings.protocol_state.abi, 'r') as f:
                abi_dict = json.load(f)
            protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
                address=Web3.to_checksum_address(
                    settings.protocol_state.address,
                ),
                abi=abi_dict,
            )
            self._source_chain_epoch_size = await get_source_chain_epoch_size(
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )

            self._source_chain_id = await get_source_chain_id(
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )

            submission_window = await get_snapshot_submision_window(
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )
            self._submission_window = submission_window

    async def _preloader_waiter(
        self,
        epoch: EpochBase,
    ):
        """
        Wait for all preloading tasks to complete for the given epoch, and distribute snapshot build tasks if all preloading
        dependencies are satisfied.

        Args:
            epoch: The epoch for which to wait for preloading tasks to complete.

        Returns:
            None
        """

        preloader_types_l = list(self._preload_completion_conditions[epoch.epochId].keys())
        conditions: List[Awaitable] = [
            self._preload_completion_conditions[epoch.epochId][k]
            for k in preloader_types_l
        ]
        preload_results = await asyncio.gather(
            *conditions,
            return_exceptions=True,
        )
        succesful_preloads = list()
        failed_preloads = list()
        self._logger.debug(
            'Preloading asyncio gather returned with results {}',
            preload_results,
        )
        for i, preload_result in enumerate(preload_results):
            if isinstance(preload_result, Exception):
                self._logger.error(
                    f'Preloading failed for epoch {epoch.epochId} project type {preloader_types_l[i]}',
                )
                failed_preloads.append(preloader_types_l[i])
            else:
                succesful_preloads.append(preloader_types_l[i])
                self._logger.debug(
                    'Preloading successful for preloader {}',
                    preloader_types_l[i],
                )

        self._logger.debug('Final list of successful preloads: {}', succesful_preloads)
        for project_type in self._project_type_config_mapping:
            project_config = self._project_type_config_mapping[project_type]
            if not project_config.preload_tasks:
                continue
            self._logger.debug(
                'Expected list of successful preloading for project type {}: {}',
                project_type,
                project_config.preload_tasks,
            )
            if all([t in succesful_preloads for t in project_config.preload_tasks]):
                self._logger.info(
                    'Preloading dependency satisfied for project type {} epoch {}. Distributing snapshot build tasks...',
                    project_type, epoch.epochId,
                )
                await self._distribute_callbacks_snapshotting(project_type, epoch)
            else:
                self._logger.error(
                    'Preloading dependency not satisfied for project type {} epoch {}. Not distributing snapshot build tasks...',
                    project_type, epoch.epochId,
                )
            # TODO: set separate overall status for failed and successful preloads
        if epoch.epochId in self._preload_completion_conditions:
            del self._preload_completion_conditions[epoch.epochId]

    async def _exec_preloaders(
        self, msg_obj: EpochBase,
    ):
        """
        Executes preloading tasks for the given epoch object.

        Args:
            msg_obj (EpochBase): The epoch object for which preloading tasks need to be executed.

        Returns:
            None
        """
        # cleanup previous preloading complete tasks and events
        # start all preload tasks
        for preloader in preloaders:
            if preloader.task_type in self._all_preload_tasks:
                preloader_class = self._preloader_compute_mapping[preloader.task_type]
                preloader_obj = preloader_class()
                preloader_compute_kwargs = dict(
                    epoch=msg_obj,
                    rpc_helper=self._rpc_helper,
                )
                self._logger.debug(
                    'Starting preloader obj {} for epoch {}',
                    preloader.task_type,
                    msg_obj.epochId,
                )
                f = preloader_obj.compute(**preloader_compute_kwargs)
                self._preload_completion_conditions[msg_obj.epochId][preloader.task_type] = f

        for project_type, project_config in self._project_type_config_mapping.items():
            if not project_config.preload_tasks:
                # release for snapshotting
                asyncio.ensure_future(
                    self._distribute_callbacks_snapshotting(
                        project_type, msg_obj,
                    ),
                )
                continue

        asyncio.ensure_future(
            self._preloader_waiter(
                epoch=msg_obj,
            ),
        )

    async def _epoch_release_processor(self, message: EpochBase):
        """
        This method is called when an epoch is released. It enables pending projects for the epoch and executes preloaders.

        Args:
            message (EpochBase): The message containing the epoch information.
        """

        asyncio.ensure_future(self._exec_preloaders(msg_obj=message))

    async def _distribute_callbacks_snapshotting(self, project_type: str, epoch: EpochBase):
        """
        Distributes callbacks for snapshotting to the appropriate snapshotters based on the project type and epoch.

        Args:
            project_type (str): The type of project.
            epoch (EpochBase): The epoch to snapshot.

        Returns:
            None
        """

        process_unit = SnapshotProcessMessage(
            begin=epoch.begin,
            end=epoch.end,
            epochId=epoch.epochId,
        )
        # TODO: use this message to build snapshot and send

    def _is_allowed_for_slot(self, epoch: EpochBase):
        """
        Checks if the snapshotter should proceed with snapshotting for the given epoch.

        Args:
            epoch (EpochBase): The epoch to check.

        Returns:
            bool: True if the epoch falls in the snapshotter's slot, False otherwise.
        """
        N = self._slots_per_day
        epochs_in_a_day = (self._epoch_size * self._source_chain_block_time) // 86400

        snapshotter_addr = settings.instance_id
        slod_id = hash(int(snapshotter_addr.lower(), 16)) % N

        if (epoch.epochId % epochs_in_a_day) // (epochs_in_a_day // N) == slod_id:
            return True
        return False

    async def _on_message(
        self, message: Union[
            EpochBase, SnapshottersUpdatedEvent, SlotsPerDayUpdatedMessage, str,
        ], type_,
    ):

        if type_ == 'EpochReleased':

            # TODO make these dynamic later
            _is_snapshotter_enabled = True
            if _is_snapshotter_enabled:
                _is_snapshotter_enabled = int(_is_snapshotter_enabled)
            else:
                _is_snapshotter_enabled = 0

            _is_snapshotter_active = True
            if _is_snapshotter_active:
                _is_snapshotter_active = int(_is_snapshotter_active)
            else:
                _is_snapshotter_active = 0

            if _is_snapshotter_enabled and _is_snapshotter_active:
                if self._is_allowed_for_slot(message):
                    await self._epoch_release_processor(message)
                else:
                    self._logger.info('Epoch {} not in snapshotter slot, ignoring', message.epochId)
            else:
                self._logger.error('System is not active, ignoring released Epoch')

        elif type_ == 'allSnapshottersUpdated':
            if message.snapshotterAddress == to_checksum_address(settings.instance_id):
                self._snapshotter_allowed = int(message.allowed)
        elif type_ == 'DayStartedEvent':
            self._logger.info('Day started event received, setting active status to True')
            self._snapshotter_active = 1

        elif type_ == 'DailyTaskCompletedEvent':
            self._logger.info('Daily task completed event received, setting active status to False')
            self._snapshotter_active = 0

        elif type_ == 'SlotsPerDayUpdated':
            self._slots_per_day = message.slotsPerDay
            self._logger.info('Slots per day updated to {}', self._slots_per_day)

        else:
            self._logger.error(
                (
                    'Unknown message type {} received'
                ),
                type_,
            )

    def run(self) -> None:
        """
        Runs the ProcessorDistributor by setting resource limits, registering signal handlers,
        initializing the worker, and running the event loop.
        """
        self._logger = logger.bind(
            module='ProcessDistributor',
        )
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        self._anchor_rpc_helper = RpcHelper(
            rpc_settings=settings.anchor_chain_rpc,
        )
        protocol_abi = read_json_file(settings.protocol_state.abi, self._logger)
        self._protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=to_checksum_address(
                settings.protocol_state.address,
            ),
            abi=protocol_abi,
        )
        try:
            source_block_time = self._protocol_state_contract.functions.SOURCE_CHAIN_BLOCK_TIME().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for source chain block time: {}',
                e,
            )
        else:
            self._source_chain_block_time = source_block_time / 10 ** 4
            self._logger.debug('Set source chain block time to {}', self._source_chain_block_time)

        try:
            epoch_size = self._protocol_state_contract.functions.EPOCH_SIZE().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for epoch size: {}',
                e,
            )
        else:
            self._epoch_size = epoch_size

        try:
            slots_per_day = self._protocol_state_contract.functions.SLOTS_PER_DAY().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for epoch size: {}',
                e,
            )
        else:
            self._slots_per_day = slots_per_day

        ev_loop = asyncio.get_event_loop()
        ev_loop.run_until_complete(self.init_worker())

        # TODO: Run something here
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
