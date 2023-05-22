import asyncio
import aio_pika
from pooler.settings.config import settings
from pooler.utils.ipfs_async import async_ipfs_client as ipfs_client
from web3 import Web3
from eth_account.messages import encode_structured_data
from eip712_structs import EIP712Struct, Address, Uint
from eip712_structs import make_domain
from coincurve import PrivateKey, PublicKey
import sha3
from eth_utils import big_endian_to_int
from pooler.utils.file_utils import read_json_file
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PayloadCommitMessage
from web3.middleware import geth_poa_middleware

logger = logger.bind(module="Commit Payload Consumer")

CONTRACT_ADDRESS = settings.protocol_state.address
ACCOUNT_ADDRESS = "0xFB0cd42862824030e98D7c60Ef4FeBb3dA44cd09"
keccak_hash = lambda x: sha3.keccak_256(x).digest()
domain_separator = make_domain(name='PowerloomProtocolContract', version='0.1', chainId=100,
                                verifyingContract=CONTRACT_ADDRESS)


class Request(EIP712Struct):
    deadline = Uint()


def get_web3_instance():
    w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:7545'))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3


def get_contract(w3):
    contract_abi = read_json_file(
        settings.protocol_state.abi,
        logger,
    )

    return w3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)


class Web3TxnManager:
    def __init__(self):
        self.w3 = get_web3_instance()
        self.contract = get_contract(self.w3)
        self.account_address = ACCOUNT_ADDRESS
        self.nonce = self.w3.eth.getTransactionCount(self.account_address)

    def submit_snapshot(self, snapshot_cid, epoch_end, project_id, private_key):
        request, signature = self.generate_signature(private_key)
        txn = self.contract.functions.submitSnapshot(snapshot_cid, epoch_end, project_id, request,
                                                     signature).buildTransaction(
            {
                'chainId': 100,
                'gas': 2000000,
                'gasPrice': self.w3.toWei('0.1', 'gwei'),
                'nonce': self.nonce,
            }
        )
        signed_txn = self.w3.eth.account.sign_transaction(txn, private_key=private_key)
        txn_hash = self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
        self.nonce += 1
        return txn_hash.hex()

    def generate_signature(self, private_key):
        block = self.w3.eth.getBlock('latest')['number']

        deadline = block + 10
        request = Request(deadline=deadline)

        signable_bytes = request.signable_bytes(domain_separator)
        pk = PrivateKey.from_hex(private_key)
        signature = pk.sign_recoverable(signable_bytes, hasher=keccak_hash)
        v = signature[64] + 27
        r = big_endian_to_int(signature[0:32])
        s = big_endian_to_int(signature[32:64])

        final_sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big') + v.to_bytes(1, 'big')
        request_ = {'deadline': deadline}
        return request_, final_sig


txn_manager = Web3TxnManager()


async def on_message(message: aio_pika.IncomingMessage):
    data = PayloadCommitMessage.parse_raw(message.body)
    logger.info(f"Received message: {data}")
    logger.info("Snapshot message received")
    payload = data.message
    cid = await generate_cid(payload)
    logger.info(f"CID: {cid}")

    txn_hash = txn_manager.submit_snapshot(cid, data.epochId, data.projectId, private_key='')
    logger.info(f"Txn Hash: {txn_hash}")

    await message.ack()


async def generate_cid(json_data):
    cid = await ipfs_client.async_add_json(json_data)
    return cid


async def main(loop):
    connection_url = f"amqp://{settings.rabbitmq.user}:{settings.rabbitmq.password}@{settings.rabbitmq.host}:5672/"
    connection = await aio_pika.connect_robust(connection_url, loop=loop)

    async with connection:
        channel = await connection.channel()
        exchange_name = f"{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}"
        routing_key = f"powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.*"
        queue_name = f"powerloom-backend-commit-payload-queue:{settings.namespace}:{settings.instance_id}"

        exchange = await channel.get_exchange(exchange_name)
        queue = await channel.get_queue(queue_name)
        await queue.bind(exchange, routing_key)

        logger.info(f"Consumer is ready to receive messages with routing key: {routing_key}")

        async for message in queue.iterator():
            await on_message(message)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.create_task(main(loop))
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Consumer stopped")
    finally:
        loop.close()
