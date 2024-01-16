#!/bin/bash

echo "Killing old processes..."
pkill -f snapshotter
# only works for debian based systems

# setting up git submodules
git submodule update --init --recursive

# present by default on mac os
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
    curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.7.1 python3 -
fi

# install poetry dependencies
poetry install --no-root

echo 'populating setting from environment values...';
./snapshotter_autofill.sh || exit 1

poetry run python -m snapshotter.gunicorn_core_launcher & poetry run python -m snapshotter.system_event_detector &
