#!/bin/bash

#This script is run from high level docker-compose. Refer to https://github.com/PowerLoom/deploy

# TODO: Update this script according to new settings.json changes
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
cp config/settings.example.json config/settings.json

export namespace=UNISWAPV2-ph15-prod
export consensus_url="${CONSENSUS_URL:-https://offchain-consensus-api.powerloom.io}"

echo "Using Namespace: ${namespace}"
echo "Using CONSENSUS_URL: ${consensus_url}"

sed -i "s|relevant-namespace|$namespace|" config/settings.json

sed -i "s|https://rpc-url|$RPC_URL|" config/settings.json

sed -i "s|generated-uuid|$UUID|" config/settings.json

sed -i "s|https://consensus-url|$consensus_url|" config/settings.json

cp config/auth_settings.example.json config/auth_settings.json

cp config/projects.example.json config/projects.json
cp config/aggregator.example.json config/aggregator.json

echo 'settings has been populated!'
