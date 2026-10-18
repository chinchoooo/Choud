#!/usr/bin/env bash
# Measure the Android app on a connected device or emulator (adb must be on PATH or ADB set).
#
#   android/tools/perf.sh start [runs]     cold start time (am start -W TotalTime), median of N runs
#   android/tools/perf.sh jank             scroll the Photos grid and print janky-frame stats
#   android/tools/perf.sh net slow|normal  emulator only: add 150 ms delay and 4 Mbps (or reset)
#   android/tools/perf.sh log              recent request timings from the app's own activity log
#
# Numbers worth recording go in docs/mobile-perf.md next to the budgets.
set -uo pipefail

ADB="${ADB:-adb}"
PKG=cloud.personal.sync
export MSYS_NO_PATHCONV=1

case "${1:-}" in
start)
    runs="${2:-5}"
    times=()
    for _ in $(seq "$runs"); do
        "$ADB" shell am force-stop "$PKG"
        sleep 1
        t="$("$ADB" shell am start -W -n "$PKG/.MainActivity" | tr -d '\r' | sed -n 's/^TotalTime: //p')"
        times+=("$t")
        sleep 2
    done
    printf 'cold start TotalTime (ms): %s\n' "${times[*]}"
    printf 'median: %s ms\n' "$(printf '%s\n' "${times[@]}" | sort -n | awk '{a[NR]=$1} END {print a[int((NR+1)/2)]}')"
    ;;
jank)
    "$ADB" shell dumpsys gfxinfo "$PKG" reset >/dev/null
    for _ in $(seq 10); do
        "$ADB" shell input swipe 540 1600 540 400 90
        sleep 0.3
    done
    "$ADB" shell dumpsys gfxinfo "$PKG" | grep -E "Total frames rendered|Janky frames|50th|90th|95th|99th"
    ;;
net)
    case "${2:-}" in
    slow)  "$ADB" emu network delay 150 && "$ADB" emu network speed 4000 && echo "emulator network: 150 ms delay, 4 Mbps" ;;
    normal) "$ADB" emu network delay none && "$ADB" emu network speed full && echo "emulator network: normal" ;;
    *) echo "usage: perf.sh net slow|normal" >&2; exit 1 ;;
    esac
    ;;
log)
    "$ADB" shell run-as "$PKG" tail -n 60 files/activity.log | cut -c1-160
    ;;
*)
    sed -n '2,10p' "$0"
    exit 1
    ;;
esac
