import asyncio
import json
import time
from typing import Dict
from typing import Union
from urllib.parse import urljoin

import httpx
import sha3
import tenacity
from coincurve import PrivateKey
from eip712_structs import EIP712Struct
from eip712_structs import make_domain
from eip712_structs import String
from eip712_structs import Uint
from eth_utils import big_endian_to_int
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from ipfs_cid import cid_sha256_hash
from ipfs_client.dag import IPFSAsyncClientError
from ipfs_client.main import AsyncIPFSClient
from pydantic import BaseModel
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential
from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import misc_notification_callback_result_handler
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import SnapshotterIssue
from snapshotter.utils.models.data_models import SnapshotterReportState
from snapshotter.utils.models.message_models import SnapshotProcessMessage
from snapshotter.utils.models.message_models import SnapshotSubmittedMessage
from snapshotter.utils.models.message_models import SnapshotSubmittedMessageLite
from snapshotter.utils.rpc import RpcHelper


class Request(EIP712Struct):
    deadline = Uint()
    snapshotCid = String()
    epochId = Uint()
    projectId = String()


def web3_storage_retry_state_callback(retry_state: tenacity.RetryCallState):
    """
    Callback function to handle retry attempts for web3 storage upload.

    Args:
        retry_state (tenacity.RetryCallState): The current state of the retry call.

    Returns:
        None
    """
    if retry_state and retry_state.outcome.failed:
        logger.warning(
            f'Encountered web3 storage upload exception: {retry_state.outcome.exception()} | args: {retry_state.args}, kwargs:{retry_state.kwargs}',
        )


def relayer_submit_retry_state_callback(retry_state: tenacity.RetryCallState):
    """
    Callback function to handle retry attempts for relayer submit.

    Args:
        retry_state (tenacity.RetryCallState): The current state of the retry call.

    Returns:
        None
    """
    if retry_state and retry_state.outcome.failed:
        logger.warning(
            f'Encountered relayer submit exception: {retry_state.outcome.exception()} | args: {retry_state.args}, kwargs:{retry_state.kwargs}',
        )


def ipfs_upload_retry_state_callback(retry_state: tenacity.RetryCallState):
    """
    Callback function to handle retry attempts for IPFS uploads.

    Args:
        retry_state (tenacity.RetryCallState): The current state of the retry attempt.

    Returns:
        None
    """
    if retry_state and retry_state.outcome.failed:
        logger.warning(
            f'Encountered ipfs upload exception: {retry_state.outcome.exception()} | args: {retry_state.args}, kwargs:{retry_state.kwargs}',
        )


class GenericAsyncWorker:
    _async_transport: AsyncHTTPTransport
    _rpc_helper: RpcHelper
    _anchor_rpc_helper: RpcHelper
    _httpx_client: AsyncClient
    _web3_storage_upload_transport: AsyncHTTPTransport
    _web3_storage_upload_client: AsyncClient

    def __init__(self):
        """
        Initializes a GenericAsyncWorker instance.

        Args:
            name (str): The name of the worker.
            **kwargs: Additional keyword arguments to pass to the superclass constructor.
        """
        self._running_callback_tasks: Dict[str, asyncio.Task] = dict()
        self.protocol_state_contract = None

        self.protocol_state_contract_address = settings.protocol_state.address
        self.initialized = False
        self.logger = logger.bind(module='GenericAsyncWorker')

    @retry(
        wait=wait_random_exponential(multiplier=1, max=10),
        stop=stop_after_attempt(5),
        retry=tenacity.retry_if_not_exception_type(httpx.HTTPStatusError),
        after=web3_storage_retry_state_callback,
    )
    async def _upload_web3_storage(self, snapshot: bytes):
        """
        Uploads the given snapshot to web3 storage.

        Args:
            snapshot (bytes): The snapshot to upload.

        Returns:
            None

        Raises:
            HTTPError: If the upload fails.
        """
        web3_storage_settings = settings.web3storage
        # if no api token is provided, skip
        if not web3_storage_settings.api_token:
            return
        files = {'file': snapshot}
        r = await self._web3_storage_upload_client.post(
            url=f'{web3_storage_settings.url}{web3_storage_settings.upload_url_suffix}',
            files=files,
        )
        r.raise_for_status()
        resp = r.json()
        self.logger.info('Uploaded snapshot to web3 storage: {} | Response: {}', snapshot, resp)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=10),
        stop=stop_after_attempt(5),
        retry=tenacity.retry_if_not_exception_type(IPFSAsyncClientError),
        after=ipfs_upload_retry_state_callback,
    )
    async def _upload_to_ipfs(self, snapshot: bytes, _ipfs_writer_client: AsyncIPFSClient):
        """
        Uploads a snapshot to IPFS using the provided AsyncIPFSClient.

        Args:
            snapshot (bytes): The snapshot to upload.
            _ipfs_writer_client (AsyncIPFSClient): The IPFS client to use for uploading.

        Returns:
            str: The CID of the uploaded snapshot.
        """
        snapshot_cid = await _ipfs_writer_client.add_bytes(snapshot)
        return snapshot_cid

    async def _commit_payload(
            self,
            task_type: str,
            _ipfs_writer_client: AsyncIPFSClient,
            project_id: str,
            epoch: Union[
                SnapshotProcessMessage,
                SnapshotSubmittedMessage,
                SnapshotSubmittedMessageLite,
            ],
            snapshot: BaseModel,
            storage_flag: bool,
    ):
        """
        Commits the given snapshot to IPFS and web3 storage (if enabled), and sends messages to the event detector and relayer
        dispatch queues.

        Args:
            task_type (str): The type of task being committed.
            _ipfs_writer_client (AsyncIPFSClient): The IPFS client to use for uploading the snapshot.
            project_id (str): The ID of the project the snapshot belongs to.
            epoch (Union[SnapshotProcessMessage, SnapshotSubmittedMessage,
            SnapshotSubmittedMessageLite]): The epoch the snapshot belongs to.
            snapshot (BaseModel): The snapshot to commit.
            storage_flag (bool): Whether to upload the snapshot to web3 storage.

        Returns:
            snapshot_cid (str): The CID of the uploaded snapshot.
        """
        # upload to IPFS
        snapshot_json = json.dumps(snapshot.dict(by_alias=True), sort_keys=True, separators=(',', ':'))
        snapshot_bytes = snapshot_json.encode('utf-8')
        try:
            if settings.ipfs.url:
                snapshot_cid = await self._upload_to_ipfs(snapshot_bytes, _ipfs_writer_client)
            else:
                snapshot_cid = cid_sha256_hash(snapshot_bytes)
        except Exception as e:
            self.logger.opt(exception=True).error(
                'Exception uploading snapshot to IPFS for epoch {}: {}, Error: {},'
                'sending failure notifications', epoch, snapshot, e,
            )
            notification_message = SnapshotterIssue(
                instanceID=settings.instance_id,
                issueType=SnapshotterReportState.MISSED_SNAPSHOT.value,
                projectID=project_id,
                epochId=str(epoch.epochId),
                timeOfReporting=str(time.time()),
                extra=json.dumps({'issueDetails': f'Error : {e}'}),
            )
            await send_failure_notifications_async(
                client=self._client, message=notification_message,
            )
        else:

            # submit to relayer
            try:
                await self._submit_to_relayer(snapshot_cid, epoch.epochId, project_id)
            except Exception as e:
                self.logger.opt(exception=True).error(
                    'Exception submitting snapshot to relayer for epoch {}: {}, Error: {},'
                    'sending failure notifications', epoch, snapshot, e,
                )
                notification_message = SnapshotterIssue(
                    instanceID=settings.instance_id,
                    issueType=SnapshotterReportState.MISSED_SNAPSHOT.value,
                    projectID=project_id,
                    epochId=str(epoch.epochId),
                    timeOfReporting=str(time.time()),
                    extra=json.dumps({'issueDetails': f'Error : {e}'}),
                )
                await send_failure_notifications_async(
                    client=self._client, message=notification_message,
                )

        # upload to web3 storage
        if storage_flag:
            asyncio.ensure_future(self._upload_web3_storage(snapshot_bytes))

        return snapshot_cid

    @retry(
        wait=wait_random_exponential(multiplier=1, max=10),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
        after=relayer_submit_retry_state_callback,
    )
    async def _submit_to_relayer(self, snapshot_cid: str, epoch_id: int, project_id: str):
        """
        Submits the given snapshot to the relayer.

        Args:
            snapshot_cid (str): The CID of the snapshot to submit.
            epoch (int): The epoch the snapshot belongs to.
            project_id (str): The ID of the project the snapshot belongs to.

        Returns:
            None
        """
        request_, signature = self.generate_signature(snapshot_cid, epoch_id, project_id)
        # submit to relayer
        f = asyncio.ensure_future(
            self._client.post(
                url=urljoin(settings.relayer.host, settings.relayer.endpoint),
                json={
                    'request': request_,
                    'signature': '0x' + str(signature.hex()),
                    'projectId': project_id,
                    'epochId': epoch_id,
                    'snapshotCid': snapshot_cid,
                    'contractAddress': self.protocol_state_contract_address,
                },
            ),
        )
        f.add_done_callback(misc_notification_callback_result_handler)
        self.logger.info(
            'Submitted snapshot CID {} to relayer | Epoch: {} | Project: {}',
            snapshot_cid,
            epoch_id,
            project_id,
        )

    async def _init_rpc_helper(self):
        """
        Initializes the RpcHelper objects for the worker and anchor chain, and sets up the protocol state contract.
        """
        self._rpc_helper = RpcHelper(rpc_settings=settings.rpc)
        self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)

        self.protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=Web3.to_checksum_address(
                self.protocol_state_contract_address,
            ),
            abi=read_json_file(
                settings.protocol_state.abi,
                self.logger,
            ),
        )

        self._anchor_chain_id = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.chain_id
        self._keccak_hash = lambda x: sha3.keccak_256(x).digest()
        self._domain_separator = make_domain(
            name='PowerloomProtocolContract', version='0.1', chainId=self._anchor_chain_id,
            verifyingContract=self.protocol_state_contract_address,
        )
        self._signer_private_key = PrivateKey.from_hex(settings.signer_private_key)

    def generate_signature(self, snapshot_cid, epoch_id, project_id):
        current_block = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.block_number

        deadline = current_block + settings.protocol_state.deadline_buffer
        request = Request(
            deadline=deadline,
            snapshotCid=snapshot_cid,
            epochId=epoch_id,
            projectId=project_id,
        )

        signable_bytes = request.signable_bytes(self._domain_separator)
        signature = self._signer_private_key.sign_recoverable(signable_bytes, hasher=self._keccak_hash)
        v = signature[64] + 27
        r = big_endian_to_int(signature[0:32])
        s = big_endian_to_int(signature[32:64])

        final_sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big') + v.to_bytes(1, 'big')
        request_ = {'deadline': deadline, 'snapshotCid': snapshot_cid, 'epochId': epoch_id, 'projectId': project_id}
        return request_, final_sig

    async def _init_httpx_client(self):
        """
        Initializes the HTTPX client and transport objects for making HTTP requests.
        """
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=200,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )
        self._web3_storage_upload_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=200,
                max_keepalive_connections=settings.web3storage.max_idle_conns,
                keepalive_expiry=settings.web3storage.idle_conn_timeout,
            ),
        )
        self._web3_storage_upload_client = AsyncClient(
            timeout=Timeout(timeout=settings.web3storage.timeout),
            follow_redirects=False,
            transport=self._web3_storage_upload_transport,
            headers={'Authorization': 'Bearer ' + settings.web3storage.api_token},
        )

    async def _init_protocol_meta(self):
        # TODO: combine these into a single call
        try:
            source_block_time = await self._anchor_rpc_helper.web3_call(
                [self.protocol_state_contract.functions.SOURCE_CHAIN_BLOCK_TIME()],
            )
        except Exception as e:
            self.logger.exception(
                'Exception in querying protocol state for source chain block time: {}',
                e,
            )
        else:
            source_block_time = source_block_time[0]
            self._source_chain_block_time = source_block_time / 10 ** 4
            self.logger.debug('Set source chain block time to {}', self._source_chain_block_time)
        try:
            epoch_size = await self._anchor_rpc_helper.web3_call(
                [self.protocol_state_contract.functions.EPOCH_SIZE()],
            )
        except Exception as e:
            self.logger.exception(
                'Exception in querying protocol state for epoch size: {}',
                e,
            )
        else:
            self._epoch_size = epoch_size[0]
            self.logger.debug('Set epoch size to {}', self._epoch_size)

    async def init(self):
        """
        Initializes the worker by initializing the HTTPX client, and RPC helper.
        """
        if not self.initialized:
            await self._init_httpx_client()
            await self._init_rpc_helper()
            await self._init_protocol_meta()
        self.initialized = True
