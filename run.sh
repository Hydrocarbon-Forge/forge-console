#!/bin/sh
cd "$(dirname "$0")"
mkdir -p data
exec python3 server.py >> data/server.log 2>&1
