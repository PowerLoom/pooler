
async def write_transaction(
    w3, chain_id, address, private_key, contract, function, nonce, gas_price, priority_gas_multiplier, *args,
):
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
    # web3py v5: Returns a transaction dictionary.
    # This transaction dictionary can then be sent using send_transaction().
    # Get the transaction
    transaction = func(*args).build_transaction({
        'from': address,
        'gas': 500000,
        'maxFeePerGas': gas_price,
        # Priority fee starts from 0 and increases by 10% of the gas price on each retry
        'maxPriorityFeePerGas': int(priority_gas_multiplier * 0.1 * gas_price),
        'nonce': nonce,
        'chainId': chain_id,
    })

    # Sign the transaction
    # ref: https://web3py.readthedocs.io/en/v5/web3.eth.html#web3.eth.Eth.send_raw_transaction
    signed_transaction = w3.eth.account.sign_transaction(
        transaction, private_key,
    )
    # Send the transaction
    tx_hash = await w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
    # Wait for confirmation
    return tx_hash.hex()
