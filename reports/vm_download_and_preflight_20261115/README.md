# Official VM Download and Benchmark Preflight (2026-11-15)

## Completed

- Downloaded the official image through the Hugging Face mirror: https://hf-mirror.com/datasets/xlangai/ubuntu_osworld/resolve/main/Ubuntu-x86.zip
- Archive: `E:\CUA-Lab\cache\Ubuntu-x86.zip`
- SHA-256: `8228ac1ea1fa7d10146a49278a22ab0ffde32c97848962b860fc9ad1b073860b`
- Extracted VM: `E:\CUA-Lab\vm\Ubuntu-x86\Ubuntu.vmx`
- Guest IP: `192.168.121.140`
- VMware snapshot: `init_state`
- Guest OSWorld server checks:
  - `GET /screenshot` returned PNG.
  - `GET /accessibility` returned JSON.
  - `POST /execute` with read-only `id` returned `uid=1000(user)`.
- Runner environment: `E:\CUA-Lab\envs\redteamcua312`, Python 3.12.11. RedTeamCUA locked dependencies, EasyOCR, pyautogui, Ariadne, and LangGraph imports passed.
- `python -m cua_guard.redteamcua --help` passed.
- Docker Desktop engine was started; server version `29.9.2`.

## Codex Provider Verification

The local Codex configuration identifies the supplied credential as an OpenAI-compatible Responses provider, not a DeepSeek Chat Completions key:

- Base URL: `https://www.fhl.mom`
- Wire API: Responses
- Model: `gpt-5.6-sol`

Ariadne now supports this provider only when `MODEL_WIRE_API=responses` is explicitly set. A real VM screenshot was sent once through the Responses API and returned validated JSON with 17 visible elements. The request used the local Codex credential in process memory only; the credential is not stored in this report.

The Ariadne test suite passed after the adapter change: 150 tests passed, 21 environment-dependent tests skipped.

## Evidence

- [VM screenshot](vm_screenshot.png)
- [Accessibility tree](vm_accessibility.json)

## Not Yet a Benchmark Result

No model-driven task or official score was produced. RTC-Bench still requires a valid, authorized model API key (`MODEL_API_KEY` is absent from the current process) and initialized Reddit, OwnCloud, and Rocket.Chat web replicas. Do not use the unrecognized `api_key.txt` as a credential without identifying its provider and purpose.

Next gate: deploy the three web replicas, set an authorized model key locally, then run one benign and one adversarial case. Confirm `traj.jsonl`, `result.txt`, `adversary_result.txt`, Ariadne SQLite/provenance artifacts, and snapshot revert before scaling to 96/288/864 cases.

This report records environment preflight only; it does not claim ASR, task success, or completed benchmark coverage.
