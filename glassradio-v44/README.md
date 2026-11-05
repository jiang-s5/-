# GlassRadio V44 — video replay adapter (new reference implementation)

**Provenance warning**: the *original* V44 native sender source, full raw `v44_results.csv`, and `v44_packets_sample.csv` were not accessible. This repository does **not** claim to reproduce historical V44 paper numbers. The archived original `v44_original_frozen_config.json` is preserved **for provenance only**. This independently written Python implementation can connect user-provided recordings to a set of V44-style retrieval/cache/RAW-COPY-BIT-BYTE-RUN comparisons.

## Run

Python 3.10+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python glassradio_v44_portable.py --config video_config.json --videos recordings/session_01.mp4 recordings/session_02.mp4 --out runs/recording_comparison
```

Results: `v44_video_results.csv` (one row per video/method/observation/K), `v44_video_updates.csv` (every update), `session_manifest.csv` (input SHA-256), `verification.json` and `config_used.json`. Videos are deliberately gitignored. Do not upload recordings without participant permission.

## What is being measured?

Frames are downscaled and thresholded to 256×144 monochrome (configurable); each changed 8×8 binary tile is an update. **Lossless means exactly reconstructing those binary tile values, not the original RGB video.** `full` uses all bits for retrieval, `random` hides ~35% of bits, and `block` hides one 16-bit contiguous interval; these are **synthetic visibility masks applied to real video frames**, not verified physical occlusions. All methods see the same `(observed, mask, cache)` within each session; full target content is revealed **only for the lossless packet encoding**.

Methods: full masked-Hamming + LRU/SIEVE/GDS-cost/size approximation; recency-16/256; exact hash; bit-sliced 5- and 10-visible-bit (two independent 5-bit groups) postings; 64-candidate-then-full cascade (10-byte fixed codec-derived stop envelope). All methods use the same receiver and lossless wire protocol. `gds` is an explicit **cost/size approximation**, not certified byte-equivalent to the original V44 implementation or an official library. SIEVE is implemented from algorithm description but official reference alignment is still required.

Every tile also carries 10 **modeled** bytes of video framing metadata (frame ID 4B, row 2B, column 2B, packet length 2B) in `bytes`. The actual five-mode decoder only verifies the tile payload; no network reliability, transport ACK or video player has been implemented. Video locations are not used for retrieval.

The index is an inverted bit posting table maintained on each cache write/eviction. `postings_visited` and `index_cpu_total_us` are logged. CPU times use Python `process_time_ns()`; they **cannot** be compared directly to V44's native C++ thread CPU P99 or its laboratory 50 µs diagnostic limit. There is no RF or energy measurement.

**Important evaluation boundary**: `write_every=2`, <=6 writes per 12 updates and <=960 receiver-work-proxy per 12 updates. Cold start is fully charged (all emitted packets); unlike historical V44's artificial `2*K` prewarm, there is no synthetic cache prepopulation. Summaries are per complete recording/session and should be statistically bootstrapped at the session level; do not treat tiles as independent samples. No learned baselines are included. This is a prototype suitable for exercising the video ingestion, protocol and baselines—not a validated algorithm innovation.

To reproduce historic V44 numbers, obtain the authentic original C++ source, raw CSV, packet sample and all SHA-256 manifests from the original researcher; DO NOT relabel this output `v44_results.csv`.

## Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py -m unittest discover -s tests -v
py glassradio_v44_portable.py --config video_config.json --videos recordings\session_01.mp4 --out runs\trial
```