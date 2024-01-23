import hashlib
import json

from loguru import logger
from web3 import HTTPProvider
from web3 import Web3

from snapshotter.settings.config import aggregator_config
from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.models.settings_model import AggregateOn


def write_transaction(w3, address, private_key, contract, function, nonce, *args):
    """ Writes a transaction to the blockchain
    Args:
            w3 (web3.Web3): Web3 object
            address (str): The address of the account
            private_key (str): The private key of the account
            contract (web3.eth.contract): Web3 contract object
            function (str): The function to call
            *args: The arguments to pass to the function
    Returns:
            str: The transaction hash
    """
    # Create the function
    func = getattr(contract.functions, function)
    # Get the transaction
    transaction = func(*args).build_transaction({
        'from': address,
        'gas': 2000000,
        'gasPrice': w3.to_wei('0.0001', 'gwei'),
        'nonce': nonce,
        'chainId': CHAIN_ID,
    })
    # Sign the transaction
    signed_transaction = w3.eth.account.sign_transaction(
        transaction, private_key=private_key,
    )
    # Send the transaction
    tx_hash = w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
    # Wait for confirmation
    return tx_hash.hex()


def write_transaction_with_receipt(w3, address, private_key, contract, function, nonce, *args):
    """ Writes a transaction using write_transaction, wait for confirmation and retry doubling gas price if failed
    Args:
        w3 (web3): Web3 object
        address (str): The address of the account
        private_key (str): The private key of the account
        contract (web3.eth.contract): Web3 contract object
        function (str): The function to call
        *args: The arguments to pass to the function
    Returns:
        str: The transaction hash
    """
    tx_hash = write_transaction(
        w3, address, private_key, contract, function, nonce, *args,
    )

    # Wait for confirmation
    # receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return tx_hash, receipt


def generate_base_project_id(project_type, contract):
    """
    Generate the base project ID based on the project type and contract.
    Args:
        project_type (str): The type of the project.
        contract (str): The contract associated with the project.
    Returns:
        str: The generated base project ID.
    """
    project_id = f'{project_type}:{contract}:{settings.namespace}'
    return project_id


def generate_aggregation_single_type_project_id(type_, underlying_project):
    """
    Generate the project ID for single project aggregation based on the type and underlying project.
    Args:
        type_ (str): The type of the aggregation project.
        underlying_project (str): The underlying project for aggregation.
    Returns:
        str: The generated project ID for single project aggregation.
    """
    contract = underlying_project.split(':')[-2]
    project_id = f'{type_}:{contract}:{settings.namespace}'
    return project_id


def generate_aggregation_multiple_type_project_id(type_, underlying_projects):
    """
    Generate the project ID for multiple project aggregation based on the type and underlying projects.
    Args:
        type_ (str): The type of the aggregation project.
        underlying_projects (list): The list of underlying projects for aggregation.
    Returns:
        str: The generated project ID for multiple project aggregation.
    """
    unique_project_id = ''.join(sorted(underlying_projects))
    project_hash = hashlib.sha3_256(unique_project_id.encode()).hexdigest()
    project_id = f'{type_}:{project_hash}:{settings.namespace}'
    return project_id


def generate_all_projects():
    """
    Generate all projects based on the configuration.
    Returns:
        list: The list of all generated project IDs.
    """
    base_projects = []

    for project_config in projects_config:
        project_type = project_config.project_type
        contracts = project_config.projects
        for contract in contracts:
            base_projects.append(generate_base_project_id(project_type, contract.lower()))

    aggregate_projects = []
    for config in aggregator_config:
        type_ = config.project_type
    
        if config.aggregate_on == AggregateOn.single_project:
            for underlying_project in base_projects:
                if config.filters.project_type not in underlying_project:
                    continue
                
                # Adding to base projects because other aggregates might filter based on these ids
                base_projects.append(generate_aggregation_single_type_project_id(type_, underlying_project))

        elif config.aggregate_on == AggregateOn.multi_project:
            aggregate_projects.append(generate_aggregation_multiple_type_project_id(type_, config.project_types_to_wait_for))

    total_projects = base_projects + aggregate_projects
    return total_projects


def main(
    protocol_state_contract,
    DEPLOYER_ADDRESS,
    DEPLOYER_PRIVATE_KEY,
    ALL_SNAPSHOTTERS,
    MASTER_SNAPSHOTTERS,
    VALIDATORS,
    MIN_SNAPSHOTTERS_FOR_CONSENSUS,
    SNAPSHOT_SUBMISSION_WINDOW,
):

    nonce = w3.eth.get_transaction_count(DEPLOYER_ADDRESS)
    projects_ = generate_all_projects()
    projects = projects_[:-4]
    pretest_projects = projects_[-4:]
    # split projects in chunks of 10 and add them to the contract

    for i in range(0, len(projects), 10):
        chunk = projects[i:i + 10]
        tx_hash, receipt = write_transaction_with_receipt(
            w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updateAllProjects', nonce, chunk, [
                True,
            ] * len(chunk),
        )
        nonce += 1
        logger.info(
            'Added all projects to contract',
            tx_hash=tx_hash,
            receipt=receipt,
        )

    for i in range(0, len(pretest_projects), 10):
        chunk = pretest_projects[i:i + 10]
        tx_hash, receipt = write_transaction_with_receipt(
            w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updatePretestProjects', nonce, chunk, [
                True,
            ] * len(chunk),
        )
        nonce += 1
        logger.info(
            'Added pretest projects to contract',
            tx_hash=tx_hash,
            receipt=receipt,
        )

    # add all snaphotters to the contract
    tx_hash, receipt = write_transaction_with_receipt(
        w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updateAllSnapshotters', nonce, ALL_SNAPSHOTTERS, [
            True,
        ] * len(ALL_SNAPSHOTTERS),
    )
    nonce += 1
    logger.info(
        'Added all snaphotters to contract',
        tx_hash=tx_hash,
        receipt=receipt,
    )

    # add master snaphotters to the contract
    tx_hash, receipt = write_transaction_with_receipt(
        w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updateMasterSnapshotters', nonce, MASTER_SNAPSHOTTERS, [
            True,
        ] * len(MASTER_SNAPSHOTTERS),
    )
    nonce += 1

    logger.info(
        'Added master snaphotters to contract',
        tx_hash=tx_hash,
        receipt=receipt,
    )

    # add validators to the contract
    tx_hash, receipt = write_transaction_with_receipt(
        w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updateValidators', nonce, VALIDATORS, [
            True,
        ] * len(VALIDATORS),
    )
    nonce += 1

    logger.info(
        'Added validators to contract',
        tx_hash=tx_hash,
        receipt=receipt,
    )

    # set min snaphotters for consensus
    tx_hash, receipt = write_transaction_with_receipt(
        w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updateMinSnapshottersForConsensus', nonce, MIN_SNAPSHOTTERS_FOR_CONSENSUS,
    )
    nonce += 1

    logger.info(
        'Set min snaphotters for consensus',
        tx_hash=tx_hash,
        receipt=receipt,
    )

    # set snaphotter submission window
    tx_hash, receipt = write_transaction_with_receipt(
        w3, DEPLOYER_ADDRESS, DEPLOYER_PRIVATE_KEY, protocol_state_contract, 'updateSnapshotSubmissionWindow', nonce, SNAPSHOT_SUBMISSION_WINDOW,
    )
    nonce += 1

    logger.info(
        'Set snaphotter submission window',
        tx_hash=tx_hash,
        receipt=receipt,
    )


if __name__ == '__main__':

    PROTOCOL_STATE_CONTRACT_ADDRESS = '0x941E1D50af7a6C411c9D97767a4EB533a99c9EB8'
    # load abi from json file and create contract object
    with open(settings.protocol_state.abi, 'r') as f:
        abi = json.load(f)

    w3 = Web3(HTTPProvider(settings.anchor_chain_rpc.full_nodes[0].url))

    protocol_state_contract = w3.eth.contract(
        address=PROTOCOL_STATE_CONTRACT_ADDRESS, abi=abi,
    )

    CHAIN_ID = w3.eth.chain_id

    DEPLOYER_ADDRESS = '0xFB0cd42862824030e98D7c60Ef4FeBb3dA44cd09'
    DEPLOYER_PRIVATE_KEY = '9cab8a1a206435e2ad3b99779a804c7168112940f90a1e4b0c745b9b30f8fcc8'

    ALL_SNAPSHOTTERS = [
	'0x46dA1B70438524802A3f0295d16A201570F484a2'


    ]

    MASTER_SNAPSHOTTERS = [
	'0x46dA1B70438524802A3f0295d16A201570F484a2'


    ]

    VALIDATORS = ['0x36de5A91a12C56135e46976620BceA5b87a25a31']

    MIN_SNAPSHOTTERS_FOR_CONSENSUS = 1

    SNAPSHOT_SUBMISSION_WINDOW = 50

    main(
        protocol_state_contract,
        DEPLOYER_ADDRESS,
        DEPLOYER_PRIVATE_KEY,
        ALL_SNAPSHOTTERS,
        MASTER_SNAPSHOTTERS,
        VALIDATORS,
        MIN_SNAPSHOTTERS_FOR_CONSENSUS,
        SNAPSHOT_SUBMISSION_WINDOW,
    )
