# Original V44 artifact status

Available in previous work: technical report `GlassRadio_V44_report_zh.pdf`, frozen configuration, and an independent packet verifier. The verifier expects `v44_packets_sample.csv` **and** `v44_results.csv`, neither available as recoverable originals in the present workspace. Therefore original V44 result reproduction **cannot** currently be certified.

The original configuration is copied verbatim to `v44_original_frozen_config.json`. It describes a native 8x8 64-bit stream with four experimental arms (main/long/evict/oracle) and 50µs lab CPU diagnostic constraints. The Python adapter's `video_config.json` is a **different, new protocol-compatible recording evaluation configuration**, not a frozen original experimental setting. Direct numerical comparison between the two would be invalid.

## Minimum handoff requirements for archival V44 verification

- Original native sender source and its exact commit/build flags.
- `v44_results.csv`, `v44_packets_sample.csv`, test trace generator and seed mapping.
- Build environment, SHA manifests, and the exact binary packet format.
- Original train/calibrate/test partition and any learned model checkpoints.

These omissions must be resolved before calling this a complete restoration of historical V44.