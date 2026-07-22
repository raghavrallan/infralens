#!/bin/sh
set -eu

# Provider executors are deliberately self-checking at startup. Images still
# ship with pinned CLI binaries for fast, deterministic starts; this fallback
# makes a Container Apps revision recover if a binary is missing.
provider="${EXECUTOR_PROVIDER:-}"
case "$provider" in
  azure|aws|github) ;;
  *)
    echo "EXECUTOR_PROVIDER must be azure, aws, or github" >&2
    exit 64
    ;;
esac

has_command() {
  command -v "$1" >/dev/null 2>&1
}

install_packages() {
  if has_command apt-get; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends "$@"
    rm -rf /var/lib/apt/lists/*
  elif has_command apk; then
    apk add --no-cache "$@"
  else
    echo "No supported package manager is available to install provider CLI" >&2
    exit 69
  fi
}

ensure_network_tools() {
  if has_command curl && has_command tar && has_command gzip; then
    return
  fi
  if has_command apt-get; then
    install_packages ca-certificates curl tar gzip
  else
    install_packages ca-certificates curl tar gzip
  fi
}

install_azure_cli() {
  echo "[executor] Azure CLI missing; installing it before starting the worker"
  install_packages ca-certificates curl gnupg
  if ! has_command dpkg; then
    echo "Azure CLI fallback installation requires a Debian-based image" >&2
    exit 69
  fi
  . /etc/os-release
  codename="${VERSION_CODENAME:-}"
  if [ -z "$codename" ] && has_command lsb_release; then
    codename="$(lsb_release -cs)"
  fi
  if [ -z "$codename" ]; then
    echo "Unable to determine the base distribution codename for Azure CLI" >&2
    exit 69
  fi
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc -o /tmp/microsoft.asc
  gpg --dearmor --yes --output /etc/apt/trusted.gpg.d/microsoft.gpg /tmp/microsoft.asc
  rm -f /tmp/microsoft.asc
  printf 'deb [arch=%s] https://packages.microsoft.com/repos/azure-cli/ %s main\n' \
    "$(dpkg --print-architecture)" "$codename" > /etc/apt/sources.list.d/azure-cli.list
  apt-get update -qq
  apt-get install -y --no-install-recommends azure-cli
  rm -rf /var/lib/apt/lists/*
}

install_aws_cli() {
  echo "[executor] AWS CLI missing; installing it before starting the worker"
  ensure_network_tools
  install_packages unzip
  machine="$(uname -m)"
  case "$machine" in
    x86_64) arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
    *) echo "Unsupported AWS CLI architecture: $machine" >&2; exit 69 ;;
  esac
  tmpdir="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${arch}.zip" -o "$tmpdir/awscliv2.zip"
  unzip -q "$tmpdir/awscliv2.zip" -d "$tmpdir"
  "$tmpdir/aws/install" --update
  rm -rf "$tmpdir"
}

install_github_cli() {
  echo "[executor] GitHub CLI missing; installing it before starting the worker"
  ensure_network_tools
  version="${GH_CLI_VERSION:-2.76.2}"
  machine="$(uname -m)"
  case "$machine" in
    x86_64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) echo "Unsupported GitHub CLI architecture: $machine" >&2; exit 69 ;;
  esac
  tmpdir="$(mktemp -d)"
  archive="gh_${version}_linux_${arch}.tar.gz"
  curl -fsSL "https://github.com/cli/cli/releases/download/v${version}/${archive}" -o "$tmpdir/$archive"
  tar -xzf "$tmpdir/$archive" -C "$tmpdir"
  install -m 0755 "$tmpdir/gh_${version}_linux_${arch}/bin/gh" /usr/local/bin/gh
  rm -rf "$tmpdir"
}

case "$provider" in
  azure) has_command az || install_azure_cli ;;
  aws) has_command aws || install_aws_cli ;;
  github) has_command gh || install_github_cli ;;
esac

case "$provider" in
  azure) cli_version="$(az version --output json 2>&1 | head -c 200)" ;;
  aws) cli_version="$(aws --version 2>&1 | head -c 200)" ;;
  github) cli_version="$(gh --version 2>&1 | head -n 1 | head -c 200)" ;;
esac
echo "[executor] $provider CLI ready: $cli_version"

if [ "$#" -eq 0 ]; then
  echo "No executor command was provided" >&2
  exit 64
fi
exec "$@"
