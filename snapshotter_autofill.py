from functools import wraps
import os
import re
import subprocess
from dotenv import load_dotenv


temp_files = [
    'projects.json',
    'settings.json',
    '.env',
]


def temp_files_cleanup(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        finally:
            # print('Deleting temp files...')
            for file in temp_files:
                os.remove(file)
    return wrapper


def replace_in_file(file_path, pattern, replacement):
    with open(file_path, 'r+') as file:
        content = file.read()
        content_new = re.sub(pattern, replacement, content, flags = re.M)
        file.seek(0)
        file.write(content_new)
        file.truncate()


@temp_files_cleanup
def main():
    os.system('cp config/projects.example.json ./projects.json')
    os.system('cp config/settings.example.json ./settings.json')
    if not os.path.isfile('.env'):
        print(".env file not found, please create one!")
        print("creating .env file...")
        os.system('cp env.example ./.env')

        SOURCE_RPC_URL = input("Enter SOURCE_RPC_URL: ")
        replace_in_file('.env', '<source-rpc-url>', SOURCE_RPC_URL)

        SIGNER_ACCOUNT_ADDRESS = input("Enter SIGNER_ACCOUNT_ADDRESS: ")
        replace_in_file('.env', '<signer-account-address>', SIGNER_ACCOUNT_ADDRESS)

        SIGNER_ACCOUNT_PRIVATE_KEY = input("Enter SIGNER_ACCOUNT_PRIVATE_KEY: ")
        replace_in_file('.env', '<signer-account-private-key>', SIGNER_ACCOUNT_PRIVATE_KEY)

    load_dotenv()

    # ... rest of the code follows the same pattern, using os.getenv to get environment variables and input to get user input

    env_vars = ['SOURCE_RPC_URL', 'SIGNER_ACCOUNT_ADDRESS', 'PROST_RPC_URL', 'PROTOCOL_STATE_CONTRACT', 'SIGNER_ACCOUNT_PRIVATE_KEY']

    for var in env_vars:
        if not os.getenv(var):
            print(f"{var} not found, please set this in your .env!")
            exit(1)

    optional_vars = ['RELAYER_HOST', 'IPFS_URL', 'SLACK_REPORTING_URL', 'POWERLOOM_REPORTING_URL', 'WEB3_STORAGE_TOKEN', 'NAMESPACE']

    for var in optional_vars:
        if os.getenv(var):
            print(f"Found {var} {os.getenv(var)}")

    os.chdir('config')
    config_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
    os.chdir('../')
    os.chdir('snapshotter/modules/computes')
    compute_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
    namespace_hash = f"{config_hash}-{compute_hash}"
    print(f"Namespace hash: {namespace_hash}")

    os.chdir('../../..')
    print(os.getcwd())
    namespace = os.getenv('NAMESPACE', namespace_hash)
    ipfs_url = os.getenv('IPFS_URL', '')
    ipfs_api_key = os.getenv('IPFS_API_KEY', '')
    ipfs_api_secret = os.getenv('IPFS_API_SECRET', '')
    web3_storage_token = os.getenv('WEB3_STORAGE_TOKEN', '')
    relayer_host = os.getenv('RELAYER_HOST', 'https://relayer-prod1d.powerloom.io')
    slack_reporting_url = os.getenv('SLACK_REPORTING_URL', '')
    powerloom_reporting_url = os.getenv('POWERLOOM_REPORTING_URL', '')

    if not ipfs_url:
        ipfs_api_key = ''
        ipfs_api_secret = ''

    print(f"Using Namespace: {namespace}")
    print(f"Using Prost RPC URL: {os.getenv('PROST_RPC_URL')}")
    print(f"Using IPFS URL: {ipfs_url}")
    print(f"Using IPFS API KEY: {ipfs_api_key}")
    print(f"Using protocol state contract: {os.getenv('PROTOCOL_STATE_CONTRACT')}")
    print(f"Using slack reporting url: {slack_reporting_url}")
    print(f"Using powerloom reporting url: {powerloom_reporting_url}")
    print(f"Using web3 storage token: {web3_storage_token}")
    print(f"Using relayer host: {relayer_host}")
    print(os.getcwd())
    replace_in_file('settings.json', 'relevant-namespace', namespace)
    replace_in_file('settings.json', 'account-address', os.getenv('SIGNER_ACCOUNT_ADDRESS'))
    replace_in_file('settings.json', 'https://rpc-url', os.getenv('SOURCE_RPC_URL'))
    replace_in_file('settings.json', 'https://prost-rpc-url', os.getenv('PROST_RPC_URL'))
    replace_in_file('settings.json', 'web3-storage-token', web3_storage_token)
    replace_in_file('settings.json', 'ipfs-writer-url', ipfs_url)
    replace_in_file('settings.json', 'ipfs-writer-key', ipfs_api_key)
    replace_in_file('settings.json', 'ipfs-writer-secret', ipfs_api_secret)
    replace_in_file('settings.json', 'ipfs-reader-url', ipfs_url)
    replace_in_file('settings.json', 'ipfs-reader-key', ipfs_api_key)
    replace_in_file('settings.json', 'ipfs-reader-secret', ipfs_api_secret)
    replace_in_file('settings.json', 'protocol-state-contract', os.getenv('PROTOCOL_STATE_CONTRACT'))
    replace_in_file('settings.json', 'https://slack-reporting-url', slack_reporting_url)
    replace_in_file('settings.json', 'https://powerloom-reporting-url', powerloom_reporting_url)
    replace_in_file('settings.json', 'signer-account-private-key', os.getenv('SIGNER_ACCOUNT_PRIVATE_KEY'))
    replace_in_file('settings.json', 'https://relayer-url', relayer_host)

    os.system('cp settings.json config/settings.json')
    os.system('cp projects.json config/projects.json')
    print('settings have been populated!')

if __name__ == "__main__":
    main()
