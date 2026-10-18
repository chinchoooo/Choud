# The Choud website

Plain HTML, CSS and JavaScript, no build step. Published to <https://chinchoooo.github.io/Choud/> by
`.github/workflows/pages.yml` whenever `site/` changes on `main`.

Preview it: `cd site && python -m http.server 8000`, then open <http://localhost:8000> (the file-drop demo needs
`localhost` or https, because Web Crypto is not available on `file://`).

Check it (drops files, compares the hash with `sha256sum`'s result, cuts the power in the demo, looks for page
overflow at 360, 768 and 1280 px in both themes, and fails on any third-party request):

```
cd scripts/site && npm i playwright@1.48.2 && node check.mjs http://localhost:8000 /tmp/shots
```

## Where every number on the page comes from

| On the page | Source |
| --- | --- |
| 3:31 up, 0:24 down (500 MB) | `docs/benchmarks.md` results table, run of 2026-10-18, v0.5.1 |
| 7:57 up, 7:01 down (5 GB, 1,045 files) | `docs/benchmark-results/2026-10-18-arvismint-cloudwards.json` |
| Drive's 3:33, 0:24, 7:15, 7:18 | Gizmodo and Cloudwards published tests, listed in `docs/benchmarks.md` |
| 15 ms, 151 ms, 13 ms | `docs/benchmarks.md` latency table (measured on the server itself) |
| 91 + 384 tests | `ctest` in `engine/` and `pytest` in `server/`, at the time of writing |
| Rented-drive column | Google's published terms and storage plans |

When any of these change, change the page and this table together.
