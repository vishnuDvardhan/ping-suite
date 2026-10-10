#!/usr/bin/env bash
# netem.sh - add/remove fake network problems with Linux tc netem.
#
# tc  = "traffic control". It manages the queue (qdisc) that packets pass
#       through before leaving a network interface.
# netem = a qdisc that delays, drops, duplicates, corrupts or reorders
#       packets on purpose. It acts on EGRESS (outgoing) packets only.
#
# On loopback (lo) every packet leaves through lo once. A ping has TWO
# packets (request + reply), so with "loss 20%" each one is dropped with
# p = 0.2, and the round trip fails with p = 1 - 0.8*0.8 = 0.36 (36%).
# For ~20% round-trip loss on lo, use loss ~10.6% (1 - sqrt(0.8)).
#
# Needs root and the sch_netem kernel module (sudo modprobe sch_netem).
#
# Usage:
#   sudo ./netem.sh on  lo "loss 20%"
#   sudo ./netem.sh on  lo "delay 50ms 10ms loss 5%"   # 50+-10 ms delay
#   sudo ./netem.sh show lo
#   sudo ./netem.sh off lo
set -euo pipefail
cmd=${1:-show}; dev=${2:-lo}; rules=${3:-"loss 20%"}

case "$cmd" in
  on)   # "replace" works whether or not a qdisc is already there
        tc qdisc replace dev "$dev" root netem $rules ;;
  off)  tc qdisc del dev "$dev" root 2>/dev/null || true ;;
  show) tc -s qdisc show dev "$dev" ;;   # -s prints drop counters
  *)    echo "usage: $0 on|off|show [dev] [rules]"; exit 1 ;;
esac
tc qdisc show dev "$dev"

# Other useful rules:
#   delay 100ms              fixed delay
#   delay 100ms 20ms         delay with +-20 ms jitter
#   loss 10% 25%             correlated (bursty) loss
#   duplicate 1%             duplicate packets
#   corrupt 1%               flip random bits (checksums should catch it)
#   reorder 25% 50% delay 10ms   send some packets early -> reordering
#   rate 1mbit               bandwidth limit
