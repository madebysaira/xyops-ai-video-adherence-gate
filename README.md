# xyOps AI Video Adherence Gate

An [xyOps](https://github.com/pixlcore/xyops) **Event Plugin** that runs a rendered
AI-video clip through [AIVideoAdherenceGate](https://github.com/madebysaira/AIVideoAdherenceGate)
as a **post-render quality gate** inside an xyOps job or visual workflow.

> Catch the "credit burn" *after* the render but *before* delivery: a clip that came
> back static, morphed, or desynced is flagged here, so your workflow can branch,
> retry, or block — instead of shipping a bad render to a client.

It speaks the [xyOps Wire Protocol](https://github.com/pixlcore/xyops/blob/main/docs/plugins.md)
(JSON over STDIN/STDOUT), emits live progress + a results table on the Job Details
page, and returns a final **exit code** that downstream workflow nodes branch on:

| Code | Meaning | Workflow action |
|------|---------|------------------|
| `0`  | PASS — all checks ok | deliver / continue |
| `1`  | WARN — at least one warning, no failure | eyeball / notify |
| `2`  | FAIL — at least one failure (or a warn with `--strict`) | retry / block |

## What it checks

- `motion_health` — detects **STATIC** (frozen) or **JITTER** (violent) clips
- `morph_drift` — detects a sudden identity/scene **morph spike**
- `lipsync_health` — approximate audio↔mouth **desync** detection
- `technical` — ffprobe resolution / codec / fps / audio checks
- `vision_adherence` — *optional* OpenAI-compatible vision scoring of the prompt↔clip contract

Pure Python 3 + ffmpeg. The `adherencegate` engine is **vendored** in this repo, so
the plugin runs standalone — no separate `pip install` required.

## Install (xyOps Conductor)

1. Copy the plugin into your conductor's plugin directory, e.g.
   `/opt/xyops/plugins/ai-video-adherence-gate/` (the whole
   `xyops_ai_video_adherence_gate/` folder).
2. Make the entry executable:
   ```bash
   chmod +x /opt/xyops/plugins/ai-video-adherence-gate/xyops_ai_video_adherence_gate/plugin.py
   ```
3. Ensure `python3` and `ffmpeg`/`ffprobe` are on `PATH` on the target satellite.
4. In the xyOps UI, create an **Event** using a custom command, e.g.
   `python3 /opt/xyops/plugins/ai-video-adherence-gate/xyops_ai_video_adherence_gate/plugin.py`
   — or register it as a custom Event Plugin via your plugin manifest.

## Event parameters

| Param ID | UI field | Description |
|----------|----------|-------------|
| `video_path` | text | Optional explicit path to the rendered clip. If omitted, the plugin auto-discovers the first video input file in the job's temp dir. |
| `prompt` | text | Optional creative contract for the *optional* vision scoring (requires `vision_key`). |
| `vision_key` | secret | OpenAI-compatible API key for vision scoring (optional). |
| `vision_base_url` | text | OpenAI-compatible base URL (optional; e.g. a local gateway). |
| `vision_model` | text | Vision model name (default `gpt-4o-mini`, optional). |
| `strict` | checkbox | Treat warnings as failures (exit `2`). |

All parameters are also passed as environment variables, per the xyOps plugin spec.

## Example job JSON (what xyOps sends on STDIN)

```json
{ "xy": 1, "type": "event", "params": { "video_path": "/renders/clip.mp4" },
  "input": { "data": {}, "files": [] } }
```

The plugin replies with wire-protocol JSON, e.g. a final line:

```json
{ "xy": 1, "code": 1, "description": "AIVideoAdherenceGate: WARN for clip.mp4" }
```

## Register on the Marketplace

Publish this repo and list it on the
[xyOps Plugin Marketplace](https://xyops.io/marketplace) so other operators can
install it one click. See `docs/plugins.md` → *Plugin Development* in the xyOps repo.

## Develop / test

```bash
python3 test_plugin.py          # stdlib harness (needs ffmpeg)
# or, if pytest is available:
python3 -m pytest test_plugin.py -v
```

The harness simulates xyOps launching the plugin (synthetic clip in a temp CWD,
job JSON on STDIN) and asserts valid protocol output for motion, static, and
missing-video cases.

## License

MIT — see [LICENSE](LICENSE). OSI-approved, per xyOps plugin requirements.

## Security

The plugin only reads the target video, runs the vendored offline checker, and
emits JSON. Vision scoring (optional) sends frames to the API key/base URL you
provide. No telemetry, no network calls unless you enable vision scoring.
