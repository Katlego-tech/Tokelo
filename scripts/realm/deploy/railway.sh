#!/usr/bin/env bash
# deploy/railway.sh -- the railway platform: the adapter contract (deploy, live, url) over
# Railway's API. The work is in scripts/realm/railway.py; see its docstring for the settings.
exec "$(git rev-parse --show-toplevel)/scripts/realm/realm" railway "$@"
