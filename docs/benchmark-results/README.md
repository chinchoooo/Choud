# Raw benchmark results

Output of `scripts/benchmark.py`, kept as evidence for the tables in [`../benchmarks.md`](../benchmarks.md).

| File | What | When |
| --- | --- | --- |
| `2026-10-18-arvismint-cloudwards.json` | 5 GB mixed folder (1,045 files) over a simulated 100 Mbps line, after the speed fixes: 7:57 up (83.8% of the line), 7:01 down (94.9%) | 2026-10-18 |

Notes: the 500 MB figures (3:31 up, 0:24 down) and the latency table were printed to a terminal and are copied into
`benchmarks.md` by hand; their JSON was not saved. Downloads of the 5 GB test are not hash-checked by the script
(it only checks runs of 600 MB or less), which the `hash_verified_on_download` field records.
