#!/bin/sh
set -eu

port="${ENGINE_PORT:-9000}"
curl -fsS "http://127.0.0.1:${port}/health" > /dev/null
