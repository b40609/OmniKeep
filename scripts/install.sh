#!/usr/bin/env bash
# OmniKeep 安裝腳本（macOS、Linux）。
#
# 檢查 git、Python 3.12+、Node.js 20.19+；clone、建立 .venv、安裝依賴、產生 .env、
# 建置前端、設定開機自動啟動（Linux 用 systemd 使用者服務，macOS 用 launchd）、啟動服務，
# 最後把 stdio MCP 與 omnikeep-setup Skill 註冊到 Claude Code、Codex、Antigravity。
# 可以重複執行：已完成的步驟會略過，不會覆寫既有的 .env 或資料庫。
#
# 一行安裝：
#   curl -fsSL https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.sh | bash
# 先看會做什麼：
#   bash scripts/install.sh --dry-run
#
# 選項：
#   --dir PATH        安裝位置。預設：從 repo 內執行時用這個 repo；否則 ~/OmniKeep
#   --repo URL        git 來源（預設 https://github.com/b40609/OmniKeep.git）
#   --branch NAME     分支（預設 main）
#   --dry-run         只列出會做的事，不改任何東西
#   --no-start        不啟動服務
#   --no-service      不設定自動啟動（systemd／launchd）
#   --no-register     不註冊到 agent
#   --agents LIST     只註冊這些 agent，逗號分隔：claude,codex,antigravity（預設：偵測到的全部）
#   --agent-home DIR  改用別的家目錄註冊 agent（測試用；直接寫設定檔，不呼叫 claude、codex 指令）
set -euo pipefail

REPO="https://github.com/b40609/OmniKeep.git"
BRANCH="main"
INSTALL_DIR=""
DRY_RUN=0
NO_START=0
NO_SERVICE=0
NO_REGISTER=0
REGISTER_ARGS=()
HEALTH_URL="http://127.0.0.1:5000/health"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --no-service) NO_SERVICE=1; shift ;;
    --no-register) NO_REGISTER=1; shift ;;
    --agents) REGISTER_ARGS+=(--agents "$2"); shift 2 ;;
    --agent-home) REGISTER_ARGS+=(--home "$2"); shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "不認得的選項：$1" >&2; exit 2 ;;
  esac
done

step() { printf '==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '    [注意] %s\n' "$*"; }
# 實際執行一段指令；dry-run 時只印出說明。
act() {
  local description="$1"; shift
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '    [dry-run] %s\n' "$description"
    return 0
  fi
  note "$description"
  "$@"
}

is_omnikeep_repo() {
  [ -n "${1:-}" ] && [ -f "$1/run.py" ] && [ -f "$1/mcp_server.py" ]
}

# ── 1. 檢查必要工具 ──────────────────────────────────────────────

step "檢查 git、Python 3.12+、Node.js 20.19+"
MISSING=()
command -v git >/dev/null 2>&1 || MISSING+=("git")

BASE_PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$BASE_PYTHON" ] || MISSING+=("python3.12+")

node_ok() {
  command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 || return 1
  local version major minor
  version="$(node --version 2>/dev/null)"; version="${version#v}"
  major="${version%%.*}"; minor="${version#*.}"; minor="${minor%%.*}"
  # Vite 7 needs Node 20.19+ or 22.12+.
  if [ "$major" -eq 20 ]; then [ "$minor" -ge 19 ]; return; fi
  if [ "$major" -eq 22 ]; then [ "$minor" -ge 12 ]; return; fi
  [ "$major" -ge 23 ]
}
node_ok || MISSING+=("node20.19+")

if [ ${#MISSING[@]} -gt 0 ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    hint="brew install git python@3.13 node"
  else
    hint="sudo apt install git python3 python3-venv nodejs npm（或用你的套件管理員；Node 版本不夠新時改用 nvm 或 NodeSource）"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    warn "缺少：${MISSING[*]}。實際執行前要先安裝：$hint"
  else
    echo "缺少：${MISSING[*]}。請先安裝：$hint" >&2
    exit 1
  fi
fi
[ -n "$BASE_PYTHON" ] && note "Python：$("$BASE_PYTHON" --version 2>&1)（$BASE_PYTHON）"
command -v node >/dev/null 2>&1 && note "Node.js $(node --version)"

# ── 2. 取得程式碼 ────────────────────────────────────────────────

if [ -z "$INSTALL_DIR" ]; then
  SCRIPT_REPO=""
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
  if is_omnikeep_repo "$SCRIPT_REPO"; then INSTALL_DIR="$SCRIPT_REPO"; else INSTALL_DIR="$HOME/OmniKeep"; fi
fi
case "$INSTALL_DIR" in /*|[A-Za-z]:[\/]*) ;; *) INSTALL_DIR="$PWD/$INSTALL_DIR" ;; esac

step "取得程式碼：$INSTALL_DIR"
if is_omnikeep_repo "$INSTALL_DIR"; then
  note "已經有 OmniKeep，略過 clone（不會自動更新；要更新請自己 git pull）。"
elif [ -d "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
  echo "$INSTALL_DIR 已存在而且不是空的，也不是 OmniKeep。請換一個 --dir。" >&2
  exit 1
else
  act "git clone --branch $BRANCH $REPO $INSTALL_DIR" git clone --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
fi

VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"

# ── 3. Python 依賴 ───────────────────────────────────────────────

step "建立 .venv 並安裝 Python 依賴（第一次約需幾分鐘）"
if [ -x "$VENV_PYTHON" ]; then
  note ".venv 已存在。"
else
  act "${BASE_PYTHON:-python3} -m venv .venv" "${BASE_PYTHON:-python3}" -m venv "$INSTALL_DIR/.venv"
fi
install_requirements() {
  "$VENV_PYTHON" -m pip install --disable-pip-version-check -q --upgrade pip
  "$VENV_PYTHON" -m pip install --disable-pip-version-check -q -r "$INSTALL_DIR/requirements.txt"
}
act "pip install -r requirements.txt" install_requirements

# ── 4. 首次設定檔 ────────────────────────────────────────────────

step "產生 .env（只在不存在時；存取金鑰隨機產生，不會顯示）"
ENV_EXISTED=0
if [ -f "$INSTALL_DIR/.env" ]; then
  ENV_EXISTED=1
  note ".env 已存在，不覆寫。"
else
  act "python scripts/bootstrap_env.py" "$VENV_PYTHON" "$INSTALL_DIR/scripts/bootstrap_env.py" --project-dir "$INSTALL_DIR"
fi

# ── 5. 前端 ──────────────────────────────────────────────────────

step "建置前端（npm ci、npm run build）"
build_frontend() {
  (cd "$INSTALL_DIR/frontend" && npm ci --no-audit --no-fund && npm run build)
}
act "npm ci; npm run build" build_frontend

# ── 6. 自動啟動 ──────────────────────────────────────────────────

LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omnikeep/logs"
SERVICE_KIND="none"
if [ "$NO_SERVICE" -eq 1 ]; then
  step "略過自動啟動（--no-service）"
elif [ "$(uname -s)" = "Darwin" ]; then
  SERVICE_KIND="launchd"
  PLIST="$HOME/Library/LaunchAgents/com.omnikeep.server.plist"
  step "設定 launchd 自動啟動：$PLIST"
  write_plist() {
    mkdir -p "$(dirname "$PLIST")" "$LOG_DIR"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.omnikeep.server</string>
  <key>ProgramArguments</key>
  <array><string>$VENV_PYTHON</string><string>-B</string><string>$INSTALL_DIR/run.py</string></array>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/service.stdout.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/service.stderr.log</string>
</dict>
</plist>
PLIST
  }
  if [ -f "$PLIST" ]; then
    note "已存在，不覆寫。"
  else
    act "寫入 $PLIST（KeepAlive：結束後自動重啟）" write_plist
  fi
elif command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  SERVICE_KIND="systemd"
  UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/omnikeep.service"
  step "設定 systemd 使用者服務：$UNIT"
  write_unit() {
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<UNIT
[Unit]
Description=OmniKeep
After=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_PYTHON -B $INSTALL_DIR/run.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable omnikeep.service
  }
  if [ -f "$UNIT" ]; then
    note "已存在，不覆寫。"
  else
    act "寫入 $UNIT 並 enable（Restart=always）" write_unit
  fi
  note "要在登出後也繼續執行：loginctl enable-linger \"$USER\""
else
  step "找不到 systemd 使用者服務，略過自動啟動；之後用 nohup 啟動。"
fi

# ── 7. 啟動 ──────────────────────────────────────────────────────

healthy() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null | grep -q '"healthy"'
  else
    "$VENV_PYTHON" -c "import json,sys,urllib.request as u; d=json.load(u.urlopen('$HEALTH_URL', timeout=3)); sys.exit(0 if d.get('status')=='healthy' else 1)" 2>/dev/null
  fi
}

start_nohup() {
  mkdir -p "$LOG_DIR"
  (cd "$INSTALL_DIR" && nohup "$VENV_PYTHON" -B run.py >>"$LOG_DIR/service.stdout.log" 2>>"$LOG_DIR/service.stderr.log" &)
}

SERVICE_UP=0
if [ "$NO_START" -eq 1 ]; then
  step "略過啟動（--no-start）"
else
  step "啟動 OmniKeep"
  if [ "$DRY_RUN" -eq 0 ] && healthy; then
    SERVICE_UP=1
    note "已經有 OmniKeep 在 $HEALTH_URL 執行。"
  else
    case "$SERVICE_KIND" in
      launchd) act "launchctl load -w $PLIST" launchctl load -w "$PLIST" ;;
      systemd) act "systemctl --user start omnikeep.service" systemctl --user start omnikeep.service ;;
      *) act "nohup .venv/bin/python run.py &（log：$LOG_DIR）" start_nohup ;;
    esac
    if [ "$DRY_RUN" -eq 0 ]; then
      ok=0
      for _ in $(seq 1 45); do
        sleep 2
        if healthy; then ok=1; break; fi
      done
      if [ "$ok" -eq 1 ]; then
        SERVICE_UP=1
        note "OmniKeep 已啟動：http://127.0.0.1:5000"
      else
        warn "90 秒內沒等到 $HEALTH_URL 回應。看 $LOG_DIR 的 service.stderr.log。"
      fi
    fi
  fi
fi

# ── 8. 註冊到 agent ──────────────────────────────────────────────

if [ "$NO_REGISTER" -eq 1 ]; then
  step "略過 agent 註冊（--no-register）"
else
  step "註冊 MCP 與 Skill 到 Claude Code、Codex、Antigravity"
  REGISTER="$INSTALL_DIR/scripts/register_agents.py"
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ -f "$REGISTER" ]; then
      runner="$VENV_PYTHON"; [ -x "$runner" ] || runner="${BASE_PYTHON:-python3}"
      "$runner" "$REGISTER" --project-dir "$INSTALL_DIR" --python "$VENV_PYTHON" --dry-run ${REGISTER_ARGS[@]+"${REGISTER_ARGS[@]}"}
    else
      printf '    [dry-run] python scripts/register_agents.py --project-dir %s\n' "$INSTALL_DIR"
    fi
  else
    "$VENV_PYTHON" "$REGISTER" --project-dir "$INSTALL_DIR" --python "$VENV_PYTHON" ${REGISTER_ARGS[@]+"${REGISTER_ARGS[@]}"}
  fi
fi

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "以上是 dry-run，沒有改動任何東西。"
else
  echo "安裝完成。"
  if [ "$SERVICE_UP" -eq 1 ] && [ "$ENV_EXISTED" -eq 0 ]; then
    echo "在這台電腦用瀏覽器打開 http://127.0.0.1:5000 就能直接使用，不用登入。"
  elif [ "$SERVICE_UP" -eq 1 ]; then
    # An older .env may still say LOCAL_AUTO_LOGIN=false, which keeps the login page.
    echo "在這台電腦用瀏覽器打開 http://127.0.0.1:5000 就能使用，預設不用登入。"
    echo "看到登入頁的話（例如 .env 裡寫了 LOCAL_AUTO_LOGIN=false），輸入 .env 的 API_KEY。"
  fi
  echo "下一步：開一個新的 agent session（Claude Code、Codex 或 Antigravity），說「幫我設定 OmniKeep」。"
fi
