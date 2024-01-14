#!/bin/bash

# only works for debian based systems

# setting up git submodules
git submodule update --init --recursive

# check if wget is installed
# only for mac os, linux should have wget installed by default
if ! command -v wget &> /dev/null
then
    echo "wget could not be found"
    # install wget
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew install wget
fi

if ! command -v python3 &> /dev/null
then
    echo "python3 could not be found"
    # install python3
    sudo apt update
    sudo apt install python3
fi

# check if pip is installed
if ! command -v pip3 &> /dev/null
then
    echo "pip3 could not be found"
    # install pip3
    sudo apt update
    sudo apt install python3-pip
fi

# check if poetry is installed
if ! command -v poetry &> /dev/null
then
    echo "poetry could not be found"
    # install poetry
    curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.5.0 python3 -
fi

# install poetry dependencies
poetry install --no-root

export NVM_DIR=$HOME/.nvm;
if [ -s "$NVM_DIR/nvm.sh" ]; then
    source $NVM_DIR/nvm.sh;
fi

# check nvm is installed
if ! command -v nvm &> /dev/null
then
    echo "nvm could not be found"
    # install nvm
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

fi

# check node is installed
if ! command -v node &> /dev/null
then
    echo "node could not be found"
    # install node
    nvm install node
    nvm use node
fi


# check pm2 is installed
if ! command -v pm2 &> /dev/null
then
    echo "pm2 could not be found"
    # install pm2
    sudo npm install pm2 -g
fi


echo 'populating setting from environment values...';
./snapshotter_autofill.sh || exit 1

echo 'starting processes...';
pm2 start pm2.config.js

echo 'started all snapshotter scripts';

pm2 logs --lines 1000
