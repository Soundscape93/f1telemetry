#!/usr/bin/env bash
# The one apt front-end for every workflow here (ci.yml, release.yml and therefore the tag.yml
# path too, which calls release.yml).
#
# Why this exists: `sudo apt-get update && sudo apt-get install -y ...` has no upper bound. apt
# retries ZERO times by default, and its 120 s timeout only fires on a fully idle connection - a
# mirror that trickles bytes resets that timer forever. So one sick Ubuntu mirror turns a 90-second
# step into a job that runs to the 6-hour default job timeout. That is what happened on the v0.8.1
# staging -> main merge (ci + tag, both stalled at noble-security InRelease) and again the next day.
#
# Usage: bash .github/scripts/apt-install.sh <package> [package...]
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <package> [package...]" >&2
  exit 2
fi

# Already installed? Then never touch the network at all. The runner images ship more than one might think.
missing=()
for pkg in "$@"; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ "${#missing[@]}" -eq 0 ]; then
  echo "apt-install: all present, skipping apt entirely: $*"
  exit 0
fi
echo "apt-install: need ${#missing[*]}"

# Acquire::Retries      apt retries a failed fetch itself (default 0).
# Acquire::*::Timeout   caps a stalled connection at 20 s rather than the 120 s default.
# DPkg::Lock::Timeout   waits for unattended-upgrades to let go instead of failing outright.
APT_OPTS=(
  -o Acquire::Retries=3
  -o Acquire::http::Timeout=20
  -o Acquire::https::Timeout=20
  -o DPkg::Lock::Timeout=120
)

# --no-install-recommends is deliberate and matches every existing call site. Do NOT drop it to
# "fix" a missing TeX font - see PACKAGING.md: the guide-pdf set names its two would-be Recommends
# (texlive-fonts-recommended, lmodern) explicitly for exactly that reason.
#
# timeout(1) is the backstop the apt options cannot provide: only an external clock bounds a mirror
# that keeps dribbling bytes.
for attempt in 1 2 3; do
  echo "apt-install: attempt $attempt/3"
  if timeout -k 15s 240s sudo apt-get "${APT_OPTS[@]}" update \
     && timeout -k 15s 600s sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a \
          apt-get "${APT_OPTS[@]}" install -y --no-install-recommends "${missing[@]}"; then
    echo "apt-install: installed ${missing[*]}"
    exit 0
  fi
  # timeout(1) kills apt, and apt's locks are flock()s on an open fd - the kernel drops them when
  # the process dies. Nothing to clean up by hand; rm-ing lock files here would only risk
  # corrupting a dpkg state that is actually fine.
  echo "apt-install: attempt $attempt failed or timed out" >&2
  if [ "$attempt" -lt 3 ]; then sleep $((attempt * 20)); fi
done

echo "apt-install: giving up after 3 attempts - see the log above." >&2
exit 1
