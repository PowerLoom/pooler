#!/bin/bash

echo "Killing old processes..."
pkill -f snapshotter
# only works for debian based systems

# setting up git submodules
git submodule update --init --recursive

echo 'populating setting from environment values...';
./snapshotter_autofill.sh || exit 1

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
if command -v poetry &> /dev/null
then
    # install poetry dependencies
    poetry install --no-root
    poetry run python -m snapshotter.gunicorn_core_launcher & poetry run python -m snapshotter.system_event_detector &

else
    echo "poetry could not be found, using pip3 instead"
    # install python dependencies
    pip install -r requirements.txt
    python -m snapshotter.gunicorn_core_launcher & python -m snapshotter.system_event_detector &
fi
