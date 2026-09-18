#!/usr/bin/env bash
# deploy/aws.sh -- the aws platform: the adapter contract (deploy, live, url, health) over the AWS
# CLI, on ECS or Lambda. The work is in scripts/realm/aws.py; see its docstring for the settings.
exec "$(git rev-parse --show-toplevel)/scripts/realm/realm" aws "$@"
