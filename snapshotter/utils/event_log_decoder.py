from typing import Any
from typing import Dict
from typing import List

from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract


class EventLogDecoder:
    @staticmethod
    def compute_event_topic(event_abi: Dict[str, Any]) -> str:
        """Compute the topic for a given event ABI."""
        signature = f"{event_abi['name']}({','.join([input_['type'] for input_ in event_abi['inputs']])})"
        return Web3.keccak(text=signature).hex()

    def __init__(self, contract: Contract):
        self.contract = contract
        self.event_abis = [abi for abi in self.contract.abi if abi['type'] == 'event']
        self._sign_abis = {self.compute_event_topic(abi): abi for abi in self.event_abis}
        self._name_abis = {abi['name']: abi for abi in self.event_abis}

    def _decode(self, value):
        if isinstance(value, (bytes, HexBytes)):
            return value.hex()
        else:
            return value

    def decode_log(self, result: Dict[str, Any]):
        return self.decode_event_input(result['topics'], result['data'])

    def decode_event_input(self, topics: List[str], data: str) -> Dict[str, Any]:

        selector = topics[0]
        other_topics = topics[1:]
        event_abi = self._get_event_abi_by_selector(selector)
        data = bytes.fromhex(data[2:])

        out = {}

        for input_info, topic in zip([input_ for input_ in event_abi['inputs'] if input_['indexed']], other_topics):
            out[input_info['name']] = self.contract.web3.codec.decode_abi(
                [input_info['type']], bytes.fromhex(topic[2:]),
            )[0]

        decoded_data = self.contract.web3.codec.decode_abi(
            [input_['type'] for input_ in event_abi['inputs'] if not input_['indexed']], data,
        )

        for key, value in zip([input_['name'] for input_ in event_abi['inputs'] if not input_['indexed']], decoded_data):
            out[key] = self._decode(value)

        return out

    def _get_event_abi_by_selector(self, selector: HexBytes) -> Dict[str, Any]:
        if selector not in self._sign_abis:
            raise ValueError('Event is not presented in contract ABI.')
        return self._sign_abis[selector]
