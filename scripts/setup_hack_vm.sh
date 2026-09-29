#!/usr/bin/env bash
set -euo pipefail

# TURNUP / MilestoSmiles — Hack the Climate team 09 VM helper.
# This script never prints or fetches Key Vault secrets.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${AZ:-}" ]]; then
  if command -v az >/dev/null 2>&1; then
    AZ="$(command -v az)"
  else
    AZ="$ROOT_DIR/work/azure-cli-venv/bin/az"
  fi
fi
if [[ -z "${AZURE_CONFIG_DIR+x}" && "$AZ" == "$ROOT_DIR/work/azure-cli-venv/bin/az" ]]; then
  AZURE_CONFIG_DIR="$ROOT_DIR/work/azure-config"
fi
RESOURCE_GROUP="rg-hack-team09-swc"
VM_NAME="vm-hack-team09"
SSH_KNOWN_HOSTS="$ROOT_DIR/work/azure-auth/known_hosts"

if [[ ! -x "$AZ" ]]; then
  echo "Azure CLI not found at $AZ" >&2
  exit 1
fi

if [[ -n "${AZURE_CONFIG_DIR:-}" ]]; then
  export AZURE_CONFIG_DIR
fi
mkdir -p "$(dirname "$SSH_KNOWN_HOSTS")"
touch "$SSH_KNOWN_HOSTS"

if ! "$AZ" account show --query id -o tsv >/dev/null 2>&1; then
  echo "No active Azure CLI login found. Starting device-code login ..."
  TERM_PROGRAM="${TERM_PROGRAM:-vscode}" "$AZ" login --use-device-code
fi

if ! "$AZ" extension show --name ssh >/dev/null 2>&1; then
  echo "Installing the Azure SSH extension ..."
  "$AZ" extension add --name ssh --yes
fi

echo "Checking Azure access for $RESOURCE_GROUP ..."
"$AZ" account show --query '{subscription:name,subscriptionId:id,user:user.name}' -o table
"$AZ" group show --name "$RESOURCE_GROUP" --query '{name:name,location:location}' -o table

echo "Connecting to $VM_NAME ..."
exec "$AZ" ssh vm --name "$VM_NAME" --resource-group "$RESOURCE_GROUP" --only-show-errors -- \
  -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS" \
  -o StrictHostKeyChecking=accept-new
