#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/../.. && pwd)"
cd "$REPO_ROOT"

MODE="${1:-dry-run}"
SERVER="${2:-remote}"

if [[ "$MODE" != "dry-run" && "$MODE" != "--apply" && "$MODE" != "apply" ]]; then
  echo "usage: $0 [dry-run|--apply] [server]" >&2
  exit 2
fi

APPLY=0
if [[ "$MODE" == "--apply" || "$MODE" == "apply" ]]; then
  APPLY=1
fi

STATE_DIR="${REPO_ROOT}/.state"
ALIASES_PATH="${STATE_DIR}/sql_asset_aliases.json"
SLOTS_PATH="${STATE_DIR}/sql_workflow_slots.json"
BINDINGS_PATH="${STATE_DIR}/sql_character_bindings.json"

if [[ ! -f "$ALIASES_PATH" || ! -f "$SLOTS_PATH" || ! -f "$BINDINGS_PATH" ]]; then
  echo "[relational_cleanup_migration] missing one or more required state files." >&2
  echo "expected:" >&2
  echo "  - $ALIASES_PATH" >&2
  echo "  - $SLOTS_PATH" >&2
  echo "  - $BINDINGS_PATH" >&2
  exit 2
fi

KEEP_CHARACTERS="${KEEP_CHARACTERS:-char_bets,char_matt}"
KEEP_OBJECTS="${KEEP_OBJECTS:-obj_hat}"

if [[ "$APPLY" -eq 0 ]]; then
  echo "[relational_cleanup_migration] mode=dry-run keep_characters=${KEEP_CHARACTERS} keep_objects=${KEEP_OBJECTS}"
else
  echo "[relational_cleanup_migration] mode=apply keep_characters=${KEEP_CHARACTERS} keep_objects=${KEEP_OBJECTS}"
fi

APPLY_MODE="$APPLY" KEEP_CHARACTERS="$KEEP_CHARACTERS" KEEP_OBJECTS="$KEEP_OBJECTS" python3 - <<'PY'
import json
import os
import shutil
import time
from pathlib import Path

repo_root = Path(os.getcwd())
state_dir = repo_root / ".state"
aliases_path = state_dir / "sql_asset_aliases.json"
slots_path = state_dir / "sql_workflow_slots.json"
bindings_path = state_dir / "sql_character_bindings.json"

apply_mode = os.environ.get("APPLY_MODE", "0") == "1"
keep_chars = [x.strip().lower() for x in os.environ.get("KEEP_CHARACTERS", "char_bets,char_matt").split(",") if x.strip()]
keep_objs = [x.strip().lower() for x in os.environ.get("KEEP_OBJECTS", "obj_hat").split(",") if x.strip()]

with aliases_path.open("r", encoding="utf-8") as f:
    aliases_payload = json.load(f)
with slots_path.open("r", encoding="utf-8") as f:
    slots_payload = json.load(f)
with bindings_path.open("r", encoding="utf-8") as f:
    bindings_payload = json.load(f)

aliases = list(aliases_payload.get("aliases", []))
slots = list(slots_payload.get("slots", []))
bindings = list(bindings_payload.get("bindings", []))

new_aliases = []
for row in aliases:
    alias = str(row.get("alias_name", "")).strip().lower()
    kind = str(row.get("kind", "")).strip().lower()
    if kind == "character" and alias in keep_chars:
        new_aliases.append(row)
    elif kind == "object" and alias in keep_objs:
        new_aliases.append(row)

required_slots = [
    {"workflow_table": "img2img_reference", "slot_name": "subject", "slot_kind": "character", "binding_key": "input_image"},
    {"workflow_table": "img2img_controlnet", "slot_name": "subject", "slot_kind": "character", "binding_key": "input_image"},
    {"workflow_table": "img2img_2_inputs", "slot_name": "subject", "slot_kind": "character", "binding_key": "198.image"},
    {"workflow_table": "img2img_2_inputs", "slot_name": "hat", "slot_kind": "object", "binding_key": "213.image"},
]

slot_index = {}
for row in slots:
    key = (str(row.get("workflow_table", "")).lower(), str(row.get("slot_name", "")).lower())
    if key[0] and key[1]:
        slot_index[key] = row
for row in required_slots:
    key = (row["workflow_table"].lower(), row["slot_name"].lower())
    if key not in slot_index:
        slot_index[key] = {
            **row,
            "created_at": 0.0,
            "updated_at": 0.0,
        }
new_slots = list(slot_index.values())

new_bindings = []

removed_aliases = max(0, len(aliases) - len(new_aliases))
removed_bindings = len(bindings)
added_slots = max(0, len(new_slots) - len(slots))

print(
    f"preview aliases_before={len(aliases)} aliases_after={len(new_aliases)} "
    f"removed_aliases={removed_aliases}"
)
print(
    f"preview bindings_before={len(bindings)} bindings_after={len(new_bindings)} "
    f"removed_bindings={removed_bindings}"
)
print(
    f"preview slots_before={len(slots)} slots_after={len(new_slots)} "
    f"added_slots={added_slots}"
)

if not apply_mode:
    print("dry_run=1 no_changes_written=1")
    raise SystemExit(0)

backup_dir = state_dir / "backups" / f"relational_cleanup_{int(time.time())}"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(aliases_path, backup_dir / aliases_path.name)
shutil.copy2(slots_path, backup_dir / slots_path.name)
shutil.copy2(bindings_path, backup_dir / bindings_path.name)

aliases_payload["aliases"] = new_aliases
slots_payload["slots"] = new_slots
bindings_payload["bindings"] = new_bindings

aliases_path.write_text(json.dumps(aliases_payload, indent=2), encoding="utf-8")
slots_path.write_text(json.dumps(slots_payload, indent=2), encoding="utf-8")
bindings_path.write_text(json.dumps(bindings_payload, indent=2), encoding="utf-8")

print(f"apply_done backup_dir={backup_dir}")
PY

if [[ "$APPLY" -eq 1 ]]; then
  comfysql sql "$SERVER" --sql "SHOW CHARACTERS; SHOW OBJECTS;"
fi
