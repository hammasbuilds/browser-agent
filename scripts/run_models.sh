#!/usr/bin/env bash
# Run the model arm end to end: qwen2.5:14b-instruct acting under every encoding.
#
#   scripts/run_models.sh --dry-run    print the job list and the call estimate, touch nothing
#   scripts/run_models.sh              check RAM / GPU / Ollama, then run and report
#
# Every generation is cached under cache/, so an interrupted run resumes where it stopped.
# Needs results/oracle_episodes.jsonl (from `browser-agent oracle`): the per-seed step budget
# and the job list come from it.
set -euo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV

MODEL="${MODEL:-qwen2.5:14b-instruct}"
SEEDS="${SEEDS:-10}"
NUM_CTX="${NUM_CTX:-16384}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
MIN_FREE_RAM_GB="${MIN_FREE_RAM_GB:-5}"
MIN_FREE_VRAM_MB="${MIN_FREE_VRAM_MB:-12000}"

ARGS=(--model "$MODEL" --seeds "$SEEDS" --num-ctx "$NUM_CTX" --url "$OLLAMA_URL" --encoder all)

if [[ "${1:-}" == "--dry-run" ]]; then
  exec uv run browser-agent agent --dry-run "${ARGS[@]}"
fi

free_ram_gb() {
  if command -v powershell >/dev/null 2>&1; then
    powershell -NoProfile -Command \
      "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB)" | tr -d '\r'
  else
    awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo
  fi
}

ram=$(free_ram_gb)
if (( ram < MIN_FREE_RAM_GB )); then
  echo "only ${ram} GB RAM free (need ${MIN_FREE_RAM_GB}); not starting" >&2
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi not found; the 14B model needs a GPU" >&2
  exit 1
fi
vram=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n1 | tr -d ' \r')
if (( vram < MIN_FREE_VRAM_MB )); then
  echo "only ${vram} MiB VRAM free (need ${MIN_FREE_VRAM_MB}); is another job on the GPU?" >&2
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv >&2 || true
  exit 1
fi

if ! curl -sf "$OLLAMA_URL/api/tags" | grep -q "\"$MODEL\""; then
  echo "Ollama at $OLLAMA_URL is not serving $MODEL (try: ollama pull $MODEL)" >&2
  exit 1
fi

echo "RAM ${ram} GB free, VRAM ${vram} MiB free, $MODEL available; starting."
uv run browser-agent agent --dry-run "${ARGS[@]}"
uv run browser-agent agent "${ARGS[@]}"
uv run browser-agent agent-report
