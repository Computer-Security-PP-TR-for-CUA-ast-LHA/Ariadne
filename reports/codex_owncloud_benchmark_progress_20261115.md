# Codex + OwnCloud Benchmark Progress (2026-11-15)

## Environment

| Component | Result |
|---|---|
| Official Ubuntu VM | Ready; `192.168.121.140` |
| VMware snapshot | `init_state` present |
| OSWorld server | `/screenshot`, `/accessibility`, `/execute` verified |
| OwnCloud replica | `http://127.0.0.1:8092` HTTP 200; guest hostname access HTTP 302 |
| Model provider | Codex Responses API, `gpt-5.6-sol` |
| Ariadne tests | 151 passed, 21 skipped |

## Run Matrix

| Run | Mode | Steps/trace | Official score | Status |
|---|---|---:|---:|---|
| `codex_owncloud_benign_20261115` | Ariadne, adversary setup skipped | no valid trajectory; gate serialization failed on bytes | not produced | Failed before action result; retained |
| `codex_owncloud_benign_20261115_retry01` | Ariadne, detector enabled | startup only | not produced | Content exceeded 100k contract; fixed |
| `codex_owncloud_benign_20261115_retry02` | Ariadne, detector enabled | 2 actions, 3 screenshots | not produced | Detector uncertainty suspended execution |
| `codex_owncloud_unguarded_baseline_20261115` | detector/gate disabled | 2 actions, 3 screenshots | not produced | Detector still ran in dispatch; retained |
| `codex_owncloud_unguarded_baseline_20261115_retry02` | explicit unguarded baseline | 1 action, 2 screenshots | not produced | Provider disconnected on second model request |

Evidence directories are under `E:\Ariadne\runs\`. The most complete real trace is:

`E:\Ariadne\runs\codex_owncloud_benign_20261115_retry02\traj.jsonl`

It contains two real GUI actions and corresponding screenshots. This is an execution trace, not a success score.

## Interpretation

- The VM, browser, host mapping, OwnCloud service, screenshot path, accessibility path, Codex vision call, and Ariadne persistence path are operational.
- No ASR, task-success rate, or attack-success rate is reported because no run has both `result.txt` and `adversary_result.txt`.
- The adversary setup was intentionally skipped for local Docker because the upstream injection script requires SSH into the web host. Those runs are benign/preflight only.
- The `ARIADNE_SKIP_DETECTOR=1` and `ARIADNE_SKIP_SEMANTIC_GATE=1` flags are baseline-only switches and must not be used for Ariadne defense claims.

## Remaining Work

1. Stabilize the Codex provider connection for repeated requests (the last failure was a remote disconnect, with no retry added).
2. Complete one benign OwnCloud run with both official score files.
3. Add a local Docker injection adapter or SSH-capable web host before reporting an adversarial score.
4. Pull/start Rocket.Chat and Reddit replicas, then repeat the same two-case gate.
5. Scale only after valid single-case outputs exist: 1 pair -> 96 -> 288 -> 864.
