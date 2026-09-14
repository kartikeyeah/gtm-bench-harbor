#!/bin/sh
set -eu
umask 077
mkdir -p /logs/verifier
chmod 700 /logs/verifier /tests
cd /tests
exec python -I /tests/grade.py
