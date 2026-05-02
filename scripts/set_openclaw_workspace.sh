#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/opt/automa-aoNutriDeby}"
CFG="$HOME/.openclaw/openclaw.json"
[[ -f "$CFG" ]] || CFG="$HOME/.openclaw/openclaw.json5"
[[ -f "$CFG" ]] || { echo "Falta ~/.openclaw/openclaw.json"; exit 1; }
cp -a "$CFG" "${CFG}.bak.$(date +%s)"
if command -v jq >/dev/null; then
  jq --arg r "$ROOT" '.agents.defaults.workspace=$r | .agents.defaults.repoRoot=$r' "$CFG" >"${CFG}.new" && mv "${CFG}.new" "$CFG"
else
  python3 -c "import json,sys; p=sys.argv[1]; r=sys.argv[2]; d=json.load(open(p)); d.setdefault('agents',{}).setdefault('defaults',{}); d['agents']['defaults']['workspace']=d['agents']['defaults']['repoRoot']=r; json.dump(d,open(p,'w'),indent=2); open(p,'a').write('\n')" "$CFG" "$ROOT"
fi
python3 -m json.tool "$CFG" >/dev/null && echo OK
