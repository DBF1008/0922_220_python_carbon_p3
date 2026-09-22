#!/bin/sh
# Run the full carbon unit test suite manually.
set -e
cd "$(dirname "$0")"
export GRAPHITE_NO_PREFIX=true
export PYTHONPATH=lib
exec trial carbon
