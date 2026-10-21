#!/bin/sh
set -eu

database_exists="$(psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'litellm'")"
if [ "${database_exists}" != "1" ]; then
  psql -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE litellm'
fi
