# Benchmarks

How fast is Choud, measured in a way you can repeat and compare with other services' published tests?
This page explains what is measured, how to run it, what Google Drive's published numbers are (with
sources), and where the comparison is and is not fair. The numbers for Choud are produced by
[`scripts/benchmark.py`](../scripts/benchmark.py) on the machine that runs your server, so they describe
**your** hardware; the results table at the bottom is filled in from a run on the author's server.

## What is fair to compare, and what is not

A cloud service's upload speed depends mostly on the **internet connection between you and it**, which a
test cannot control, so independent tests either fix the connection (a throttled test machine) or report
the share of the available line the service manages to use. Choud's speed from your own network to your own
server depends on your network and your disk, not on a data centre.

So the honest, comparable question is: **on a line of a given speed, how long does the same job take, and
what share of the line does the service use?** That is what the `gizmodo` and `cloudwards` scenarios
measure. The client is held to the same speeds the published tests used (a token bucket caps the upload and
download rate), so only the service's own overhead shows: the extra time over the physical minimum.

What this does **not** compare: Google's global network and data centres (a line speed on your home
connection to your own laptop is a different path), the test machines, file contents, and counting the
client application's own work. The published tests also include the vendor's client apps; Choud's runs use
its HTTP API directly, the same way the Android and desktop apps do. Treat the side-by-side as indicative,
not as a verdict.

For the things the published tests do not measure at all (how long listing a folder, searching, or opening
a screen of photos takes), **Google publishes no latency figures** for Drive or Photos that we could find in a
credible source (see below), so there is nothing honest to compare with. The `latency` scenario reports
Choud's own numbers, and the round-trip experiment shows the design effect: one request instead of
twenty-four.

## Google Drive: published numbers and where they come from

Checked on 18 October 2026. All three are third-party tests except the limits page, which is Google's own.

| Source | Test | Google Drive result |
| --- | --- | --- |
| [Cloudwards, "The Fastest Cloud Storage Providers"](https://www.cloudwards.net/fastest-cloud-storage/) (updated 13 Oct 2026) | A 5 GB mixed folder (videos, photos, documents) from Dublin, a 1 Gbps connection **throttled to 100 Mbps**, two attempts per service | Upload 7:05 and 7:25, **average 7:15**. Download 7:16 and 7:19, **average 7:18**. The fastest listed (TeraBox Premium) averaged 7:08 up and 7:24 down. At 100 Mbps the theoretical minimum for 5 GB is 6:40 |
| [Gizmodo, "Fastest Cloud Storage"](https://gizmodo.com/best-cloud-storage/fastest) (13 Oct 2026) | A 500 MB archive of music and video, desktop apps, from Europe, **187.95 Mbps down and 19.69 Mbps up** | Upload **3:33**, download **0:24**, total 3:57, using **95%** of the available upload speed. The theoretical upload minimum was about 3:23. For comparison: pCloud 3:32 up / 0:24 down, Dropbox 3:31 / 0:26 |
| [Google, Drive API usage limits](https://developers.google.com/workspace/drive/api/guides/limits) (page updated 11 Sep 2026) | Official limits, not a speed test | 750 GB per day of uploads per user, a 5 TB maximum file size, a 750 GB maximum copy size. API quotas are measured in "quota units" (1,000,000 per minute per project, 325,000 per user, 100 units for a list call, 200 for a download) |

Reading them: Cloudwards' 100 Mbps cap means every service lands within seconds of the 6:40 minimum, so the
differences it shows are small, and Gizmodo's eight services all finished within about 40 seconds of each other.
These are plain whole-file transfers; how services behave when a large file is *edited* (re-sending only the
changed part) is a different question that these tests do not cover.

## What Choud measures

`scripts/benchmark.py` talks to the server's HTTP API like the apps do (small files in one request, files over
20 MiB in 5 MiB resumable chunks, bearer-token login), and creates everything inside one temporary folder it
removes afterwards.

| Scenario | What it does |
| --- | --- |
| `gizmodo` | Uploads then downloads one 500 MB file with the upload held to **19.69 Mbps** and the download to **187.95 Mbps**. Every downloaded file is hashed and compared with what was sent |
| `cloudwards` | Uploads then downloads a **5 GB mixed folder** (6 large "videos", 150 "photos", about 900 small "documents", four transfers at a time, like a desktop client) with both directions held to **100 Mbps** |
| `custom` | Your own size and line speed: `--size-mb`, `--up-mbps`, `--down-mbps`, `--profile single|mixed` |
| `latency` | Per-call p50/p95/p99: the health check, a 100 KB upload of new bytes, an upload of bytes the server already stores (deduplication), listing a folder of about 500 files, search by name, the library index in full and as a `304`, one thumbnail on a stable URL, and a screen of 24 thumbnails as 24 requests versus one batch request. `--rtt-ms N` adds a simulated N ms before every request to model a distant client |
| `all` | `gizmodo` + `cloudwards` + `latency` |

For the transfer scenarios the headline number is **"% of the line"**: the physical minimum time divided by
the measured time. 100% would mean no overhead at all. Google Drive's published figures work out to 95%
(Gizmodo, upload) and about 92% (Cloudwards, 6:40 against 7:15).

## How to run it

On the machine that runs Choud (this measures the server and the proxy on a fast local path), or from a
laptop or phone-class client over Tailscale (this measures the whole path). Use the address the apps use, so
Caddy is included:

```bash
cd ~/Choud
python3 -m venv /tmp/bench && /tmp/bench/bin/pip install httpx pillow
CHOUD_PASSWORD='your password' /tmp/bench/bin/python scripts/benchmark.py \
    --url http://localhost --email you@example.com --label arvismint all
```

`all` takes about 25 minutes because the two transfer tests really run at 19.69, 187.95 and 100 Mbps. You can
run `latency` on its own (about two minutes), or `gizmodo` only (about four minutes). It needs about 5 GB of
free space and creates, then deletes, a few thousand files; use a throwaway account if you would rather not
touch your own. To model a phone far away add `--rtt-ms 80`. Results are written to
`benchmark-results-<label>.md` and `.json` (the JSON keeps every sample).

Conditions that change the numbers, and should be written next to any figure you publish: the server's CPU
and disk (NVMe, SATA or USB), whether Docker uses a native filesystem (Linux) or a virtual one (Docker
Desktop on Windows or macOS adds large per-write latency, so do not publish numbers from those), whether the
database and the storage share a disk, the Choud version, and whether the client ran on the server itself.

## Results

Run on 2026-10-18 on the home server (Linux Mint, 4 logical CPUs), Choud 0.5.1, client on the same machine
over `localhost` with the line speeds simulated by the script. One run each; Drive's numbers are other
people's single runs on other networks, so read the comparison as indicative.

| Test (line speed) | Google Drive, published | Choud, first run | Choud, after the speed fixes |
| --- | --- | --- | --- |
| 500 MB at 19.69 Mbps up | 3:33 (95% of the line) | 3:43 (90.7%) | **3:31 (96.3%)** |
| 500 MB at 187.95 Mbps down | 0:24 (89%) | 0:24 (85.6%) | 0:24 (87.8%) |
| 5 GB mixed folder (1,045 files) at 100 Mbps up | 7:15 (92%) | 8:54 (74.9%) | 7:57 (83.8%) |
| 5 GB mixed folder at 100 Mbps down | 7:18 (91%) | 6:41 (99.6%) | 7:01 (94.9%) |

What changed between the two Choud columns: the upload endpoints no longer block the server while they wait
on the disk, clients send up to three chunks at once, the engine no longer reads an uploaded file twice, and
downloads use a hard link instead of copying the file.

What this says, honestly:

- A single 500 MB upload now matches Drive's published run (3:31 against 3:33; two seconds is within the
  noise of one run, so read it as level, not faster).
- Uploading a thousand mixed files improved from 74.9% to 83.8% of the line, but is still about 40 seconds
  behind Drive's published run. Each small upload still costs roughly 65 ms of server work, including the
  flush-to-disk that keeps files safe through a power cut. That is a deliberate trade, not an accident.
- The 5 GB download came out slower on the second run (94.9% against 99.6%) even though nothing in the
  download path got slower. One run each, so this is most likely noise (disk cache, other work on the
  machine), but it is reported rather than hidden. Repeat runs would show the spread.
- Choud's downloads are level with or ahead of Drive's published numbers in the mixed-folder test.

API latency on the same machine (milliseconds, median / 95th percentile):

| Call | p50 | p95 |
| --- | --- | --- |
| health check | 15.9 | 30.7 |
| upload 100 KB (new bytes) | 66.9 | 89.5 |
| list a folder of about 500 files | 133.3 | 217.0 |
| search by name | 23.3 | 36.3 |
| photo library index, full (1,575 items) | 90.2 | 173.7 |
| photo library index, nothing changed (304) | 13.1 | 15.8 |
| one thumbnail (WebP, 256 px) | 6.2 | 6.4 |
| a screen of 24 thumbnails, 24 separate requests | 150.9 | 166.5 |
| a screen of 24 thumbnails, one batch request | 14.9 | 21.9 |

The batch request makes a screen of thumbnails about ten times faster, because a page of photos is one round
trip instead of 24. That gap grows with network distance (`--rtt-ms 80` models a phone far away).
