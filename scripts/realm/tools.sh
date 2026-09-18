#!/usr/bin/env bash
# tools.sh -- the release pipeline's and the gate's tools, at pinned versions, checked against
# pinned sha256s.
#
#   bash scripts/realm/tools.sh <tool>...    prints each tool's path, fetching it if needed
#
# A tool already on PATH at exactly the pinned version is used as it is. Otherwise its pinned
# release is downloaded into .realm/tools/ and checked against the sha256 written below, not one
# read from the download site. So CI and a laptop run the same binaries, and a tampered download
# is refused. Linux only (amd64 and arm64), like the release workflows.
#
# The container images the release checks use are pinned in release.sh, by tag and digest.

set -euo pipefail
root="$(git rev-parse --show-toplevel)"
dir="$root/.realm/tools"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64|Linux-amd64)  arch=amd64 ;;
  Linux-aarch64|Linux-arm64) arch=arm64 ;;
  *) arch="" ;;
esac

# tool -> version | download URL (ARCH is replaced) | sha256 for amd64 | for arm64 | archive member
#
# Terraform's sums are from HashiCorp's terraform_1.16.2_SHA256SUMS, whose signature was checked
# on 2026-09-18: a good signature by subkey 374E C75B 4859 1360 4A83 1CC7 C820 C6D5 CD27 AB87 of
# HashiCorp Security's key C874 011F 0AB4 0511 0D02 1055 3436 5D94 72D7 468F, the fingerprint
# keys.openpgp.org holds for security@hashicorp.com (verified email). tflint's and its AWS
# ruleset's are from their releases' checksums.txt; the ruleset's amd64 binary is byte for byte
# the one `tflint --init` installed after checking that release's signature. The ruleset comes
# from here rather than `tflint --init`, which asks GitHub's API (60 calls an hour without a
# token) and would fail the gate now and then. Check the same way when changing a pin.
spec() {
  case "$1" in
    syft)
      echo "1.51.1|https://github.com/anchore/syft/releases/download/v1.51.1/syft_1.51.1_linux_ARCH.tar.gz|8fcb33017a0dc1058298c923c436d19dfa68ae93968e0b423248542e3afb9fc3|a7fd2b784e6664acd44719270574f6cd8c6864fc2b1700bf9099bd1cccda7d7f|syft" ;;
    cosign)
      echo "3.1.3|https://github.com/sigstore/cosign/releases/download/v3.1.3/cosign-linux-ARCH|4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71|c5d324e091826b0d7a78eb16fef316450b4eb9aaec045611c08ba06f5e73220a|" ;;
    osv-scanner)
      echo "2.5.1|https://github.com/google/osv-scanner/releases/download/v2.5.1/osv-scanner_linux_ARCH|f9f25499a2c8cc367b3af45df2ea7eeca7fbccceab9c35079968f4b3652194be|3d0f5aa5a6baa8eb32bcef247388e149ef6030a6634ccae6fa0d62681fb27a6d|" ;;
    terraform)
      echo "1.16.2|https://releases.hashicorp.com/terraform/1.16.2/terraform_1.16.2_linux_ARCH.zip|0d17011f0c4664539b164b044903d04e296c86c13cb9f28040076c65cfb3985a|c040bd1e3122b4290f70f74288d8c5a54ddd4254a3e52a29e7cc666653f50a0a|terraform" ;;
    tflint-ruleset-aws)
      echo "0.48.0|https://github.com/terraform-linters/tflint-ruleset-aws/releases/download/v0.48.0/tflint-ruleset-aws_linux_ARCH.zip|531444ac5dd989ce3117b2ab695d52e52599020a41df8b2a8811add2f6764164|2ed71f6801c63be1f08db2d99b4f7ee7b06dc67f2d58fa46e6731d5ad94e8650|tflint-ruleset-aws" ;;
    tflint)
      echo "0.64.0|https://github.com/terraform-linters/tflint/releases/download/v0.64.0/tflint_linux_ARCH.zip|cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537|560da89aacf59389d4eb029730dd5b109b7288096c32f2726a0d9e783a5ea8eb|tflint" ;;
    *) return 1 ;;
  esac
}

# The version a binary reports, to recognise the pinned one already on PATH.
reported() {
  case "$1" in
    syft)        "$2" version 2>/dev/null | sed -n 's/^Version: *//p' ;;
    cosign)      "$2" version 2>/dev/null | sed -n 's/^GitVersion: *v//p' ;;
    osv-scanner) "$2" --version 2>/dev/null | sed -n 's/^osv-scanner version: *//p' ;;
    terraform)   "$2" version 2>/dev/null | sed -n '1s/^Terraform v//p' ;;
    tflint)      "$2" --version 2>/dev/null | sed -n 's/^TFLint version //p' ;;
    # tflint-ruleset-aws is a plugin, not a command: it's never taken from PATH.
  esac
}

interrupted() {  # interrupted <exit code>: stop the download and remove what it wrote
  [ -z "${pid:-}" ] || kill "$pid" 2>/dev/null || true
  rm -f "${tmp:-}"
  echo "tools.sh: interrupted; removed the partial download" >&2
  exit "$1"
}

fetch() {
  local tool="$1" version url sum_amd64 sum_arm64 member sum target tmp pid=""
  IFS='|' read -r version url sum_amd64 sum_arm64 member <<<"$(spec "$tool")"
  target="$dir/$tool-$version"
  if [ -x "$target" ]; then echo "$target"; return 0; fi
  if on_path="$(command -v "$tool")" && [ "$(reported "$tool" "$on_path")" = "$version" ]; then
    echo "$on_path"; return 0
  fi
  if [ -z "$arch" ]; then
    echo "tools.sh: $tool $version: install it on PATH (downloads are for Linux amd64/arm64)" >&2
    return 1
  fi
  sum="$sum_amd64"; [ "$arch" = arm64 ] && sum="$sum_arm64"
  url="${url//ARCH/$arch}"
  mkdir -p "$dir"
  # Interrupted, the partial download goes too. curl runs in the background so the signal is
  # handled at once (bash runs a trap only after a foreground command ends).
  trap 'interrupted 130' INT
  trap 'interrupted 143' TERM
  tmp="$(mktemp "$dir/.download.XXXXXX")"
  echo "tools.sh: fetching $tool $version" >&2
  curl -sSfL "$url" -o "$tmp" &
  pid=$!
  if ! wait "$pid"; then
    trap - INT TERM
    rm -f "$tmp"; echo "tools.sh: couldn't download $url" >&2; return 1
  fi
  trap - INT TERM
  if ! echo "$sum  $tmp" | sha256sum -c --status -; then
    rm -f "$tmp"; echo "tools.sh: $tool $version failed its checksum; refusing it" >&2; return 1
  fi
  if [ -n "$member" ] && [[ "$url" == *.zip ]]; then  # python, since unzip isn't everywhere
    python3 -c 'import sys, zipfile; open(sys.argv[3], "wb").write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))' \
      "$tmp" "$member" "$target"
    rm -f "$tmp"
  elif [ -n "$member" ]; then
    tar -xzf "$tmp" -C "$dir" "$member" && mv "$dir/$member" "$target"
    rm -f "$tmp"
  else
    mv "$tmp" "$target"
  fi
  chmod 0755 "$target"
  echo "$target"
}

[ $# -gt 0 ] || { sed -n '2,12p' "$0"; exit 2; }
for tool in "$@"; do
  spec "$tool" >/dev/null || { echo "tools.sh: unknown tool '$tool'" >&2; exit 2; }
  fetch "$tool"
done
