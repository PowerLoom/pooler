import asyncio
import json
from collections import defaultdict
from typing import Union

from eth_utils.address import to_checksum_address
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from web3 import Web3

from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.data_utils import get_snapshot_submision_window
from snapshotter.utils.data_utils import get_source_chain_epoch_size
from snapshotter.utils.data_utils import get_source_chain_id
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import DailyTaskCompletedEvent
from snapshotter.utils.models.data_models import DayStartedEvent
from snapshotter.utils.models.data_models import EpochReleasedEvent
from snapshotter.utils.models.data_models import SlotsPerDayUpdatedEvent
from snapshotter.utils.models.data_models import SnapshotFinalizedEvent
from snapshotter.utils.models.data_models import SnapshottersUpdatedEvent
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.models.message_models import SnapshotProcessMessage
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.snapshot_worker import SnapshotAsyncWorker


class ProcessorDistributor:
    _anchor_rpc_helper: RpcHelper
    _async_transport: AsyncHTTPTransport
    _client: AsyncClient

    def __init__(self):
        """
        Initialize the ProcessorDistributor object.

        Args:
            name (str): The name of the ProcessorDistributor.
            **kwargs: Additional keyword arguments.

        Attributes:
            _rpc_helper: The RPC helper object.
            _source_chain_id: The source chain ID.
            _projects_list: The list of projects.
            _initialized (bool): Flag indicating if the ProcessorDistributor has been initialized.
            _upcoming_project_changes (defaultdict): Dictionary of upcoming project changes.
            _project_type_config_mapping (dict): Dictionary mapping project types to their configurations.
        """
        self._rpc_helper = None
        self._source_chain_id = None
        self._projects_list = None

        self._initialized = False
        self._upcoming_project_changes = defaultdict(list)
        self._project_type_config_mapping = dict()
        for project_config in projects_config:
            self._project_type_config_mapping[project_config.project_type] = project_config
        self._snapshotter_enabled = True
        self._snapshotter_active = True
        self.snapshot_worker = SnapshotAsyncWorker()

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

    async def init(self):
        """
        Initializes the worker by initializing the RPC helper, loading project metadata.
        """
        if not self._initialized:

            self._logger = logger.bind(
                module='ProcessDistributor',
            )
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

            try:
                allowed_snapshotters = self._protocol_state_contract.functions.getSnapshotters().call()
                if to_checksum_address(settings.instance_id) in allowed_snapshotters:
                    self._snapshotter_enabled = True
                else:
                    self._snapshotter_enabled = False
            except Exception as e:
                self._logger.exception(
                    'Exception in querying protocol state for snapshotters: {}',
                    e,
                )
                self._snapshotter_enabled = False
            self._logger.info('Snapshotter enabled: {}', self._snapshotter_enabled)

            try:
                self._current_day = self._protocol_state_contract.functions.dayCounter().call()

                task_completion_status = self._protocol_state_contract.functions.checkUserTaskStatusForDay(
                    to_checksum_address(settings.instance_id),
                    self._current_day,
                ).call()
                if task_completion_status:
                    self._snapshotter_active = False
                else:
                    self._snapshotter_active = True
            except Exception as e:
                self._logger.exception(
                    'Exception in querying protocol state for snapshotters: {}',
                    e,
                )
                self._snapshotter_active = False
            self._logger.info('Snapshotter active: {}', self._snapshotter_active)

            await self._init_httpx_client()
            await self._init_rpc_helper()
            await self._load_projects_metadata()
            await self.snapshot_worker.init_worker()

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

    async def _epoch_release_processor(self, message: EpochReleasedEvent):
        """
        This method is called when an epoch is released. It start the snapshotting process for the epoch.

        Args:
            message (EpochBase): The message containing the epoch information.
        """

        epoch = EpochBase(
            begin=message.begin,
            end=message.end,
            epochId=message.epochId,
            day=self._current_day,
        )
        for project_type, _ in self._project_type_config_mapping.items():
            # release for snapshotting
            asyncio.ensure_future(
                self._distribute_callbacks_snapshotting(
                    project_type, epoch,
                ),
            )

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
            day=epoch.day,
        )

        asyncio.ensure_future(
            self.snapshot_worker.process_task(process_unit, project_type),
        )

    def _is_allowed_for_slot(self, epoch: EpochBase):
        """
        Checks if the snapshotter should proceed with snapshotting for the given epoch.

        Args:
            epoch (EpochBase): The epoch to check.

        Returns:
            bool: True if the epoch falls in the snapshotter's slot, False otherwise.
        """
        N = self._slots_per_day
        self._logger.info('Slots per day: {}', N)
        epochs_in_a_day = 86400 // (self._epoch_size * self._source_chain_block_time)
        self._logger.info('Epochs in a day: {}', epochs_in_a_day)
        snapshotter_addr = settings.instance_id
        slot_id = hash(int(snapshotter_addr.lower(), 16)) % N
        # slot_id = 0
        self._logger.info('Snapshotter ID: {}', slot_id)
        if (epoch.epochId % epochs_in_a_day) // (epochs_in_a_day // N) == slot_id:
            return True
        return False

    async def process_event(
        self, type_: str, event: Union[
            EpochReleasedEvent,
            SnapshotFinalizedEvent,
            SnapshottersUpdatedEvent,
            SlotsPerDayUpdatedEvent,
            DayStartedEvent,
            DailyTaskCompletedEvent,
        ],
    ):
        """
        Process an event based on its type.

        Args:
            type_ (str): The type of the event.
            event (Union[EpochReleasedEvent, SnapshotFinalizedEvent, SnapshottersUpdatedEvent, SlotsPerDayUpdatedEvent, DayStartedEvent, DailyTaskCompletedEvent]): The event object.

        Returns:
            None
        """
        if type_ == 'EpochReleased':

            if self._snapshotter_enabled and self._snapshotter_active:
                if self._is_allowed_for_slot(event):
                    await self._epoch_release_processor(event)
                else:
                    self._logger.info('Epoch {} not in snapshotter slot, ignoring', event.epochId)
            else:
                self._logger.info('System is not active, ignoring released Epoch')

        elif type_ == 'allSnapshottersUpdated':
            if event.snapshotterAddress == to_checksum_address(settings.instance_id):
                self._snapshotter_enabled = event.allowed

        elif type_ == 'DayStartedEvent':
            self._logger.info('Day started event received, setting active status to True')
            self._snapshotter_active = True

        elif type_ == 'DailyTaskCompletedEvent':
            self._logger.info('Daily task completed event received, setting active status to False')
            self._snapshotter_active = False

        elif type_ == 'SlotsPerDayUpdated':
            self._slots_per_day = event.slotsPerDay
            self._logger.info('Slots per day updated to {}', self._slots_per_day)

        else:
            self._logger.error(
                (
                    'Unknown message type {} received'
                ),
                type_,
            )
