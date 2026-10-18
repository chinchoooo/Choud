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

Not yet published. Run the command above on the server and paste the two tables
(`benchmark-results-<label>.md`) here with the date, the Choud version, and the hardware. A first sanity run
on a Windows laptop with Docker Desktop (not representative, because its virtual disk makes each upload cost
two to three hundred milliseconds) already shows the design effect on a local network: a screen of 24
thumbnails took about 0.4 seconds as 24 separate requests and about 0.06 seconds as one batch request, before
adding any network distance.

| Test (line speed) | Google Drive, published | Choud |
| --- | --- | --- |
| 500 MB at 19.69 Mbps up | 3:33 (95% of the line) | |
| 500 MB at 187.95 Mbps down | 0:24 | |
| 5 GB mixed folder at 100 Mbps up | 7:15 (92% of the line) | |
| 5 GB mixed folder at 100 Mbps down | 7:18 | |
