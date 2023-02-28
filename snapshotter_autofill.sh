#!/bin/bash

#This script is run from high level docker-compose. Refer to https://github.com/PowerLoom/deploy

set -e

echo 'populating setting from environment values...';

if [ -z "$RPC_URL" ]; then
    echo "RPC URL not found, please set this in your .env!";
    exit 1;
fi

if [ -z "$UUID" ]; then
    echo "UUID not found, please set this in your .env!";
    exit 1;
fi

echo "Got RPC URL: ${RPC_URL}"

echo "Got UUID: ${UUID}"

echo "Got CONSENSUS_URL: ${CONSENSUS_URL}"
cp pooler/settings/settings.example.json pooler/settings/settings.json

export namespace=UNISWAPV2-ph15-prod
export consensus_url="${CONSENSUS_URL:-https://offchain-consensus-api.powerloom.io}"

echo "Using Namespace: ${namespace}"
echo "Using CONSENSUS_URL: ${consensus_url}"

sed -i "s|relevant-namespace|$namespace|" pooler/settings/settings.json

sed -i "s|https://rpc-url|$RPC_URL|" pooler/settings/settings.json

sed -i "s|generated-uuid|$UUID|" pooler/settings/settings.json

sed -i "s|http://offchain-consensus:9030|$consensus_url|" pooler/settings/settings.json

#rm pooler/settings/settings.json.old

cp pooler/auth/settings/auth_settings.example.json pooler/auth/settings/auth_settings.json

cp pooler/static/cached_pair_addresses_docker.json pooler/static/cached_pair_addresses.json

echo 'settings has been populated!'