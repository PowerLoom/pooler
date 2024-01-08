#!/bin/bash

echo 'populating setting from environment values...';
./snapshotter_autofill.sh || exit 1

echo 'starting processes...';
pm2 start pm2.config.js

echo 'started all snapshotter scripts';

pm2 logs --lines 1000
