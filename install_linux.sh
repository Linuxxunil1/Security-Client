#!/usr/bin/env bash
# =============================================================================
# Security Client — Linux Installer
# Supports: Ubuntu 20.04+, Debian 11+, RHEL/CentOS 8+, Fedora 36+
# Usage:    sudo bash install_linux.sh
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/linuxxunil1/security-client"
INSTALL_DIR="/opt/security-client"
SERVICE_NAME="security-client"
SERVICE_USER="security-client"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

# ---- Privilege check --------------------------------------------------------
[[ $EUID -eq 0 ]] || die "Run this installer as root:  sudo bash $0"

# ---- Locate Python 3.10+ ----------------------------------------------------
find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        command -v "$cmd" &>/dev/null || continue
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=${ver%%.*}; minor=${ver#*.}
        [[ $major -ge 3 && $minor -ge 10 ]] && { echo "$cmd"; return 0; }
    done
    return 1
}

if ! PYTHON=$(find_python); then
    info "Python 3.10+ not found — installing …"
    if   command -v apt-get &>/dev/null; then
        apt-get update -q
        apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf     &>/dev/null; then
        dnf install -y python3 python3-pip
    elif command -v yum     &>/dev/null; then
        yum install -y python3 python3-pip
    else
        die "Cannot install Python automatically. Please install Python 3.10+ and re-run."
    fi
    PYTHON=$(find_python) || die "Python 3.10+ installation failed."
fi
info "Python: $PYTHON  ($($PYTHON --version))"

# ---- Download / update client -----------------------------------------------
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing installation in $INSTALL_DIR …"
    git -C "$INSTALL_DIR" pull --ff-only
elif command -v git &>/dev/null; then
    info "Cloning repository to $INSTALL_DIR …"
    git clone --depth=1 "$REPO_URL" "$INSTALL_DIR"
else
    info "git not found — downloading archive …"
    TMP=$(mktemp -d)
    if command -v curl &>/dev/null; then
        curl -fsSL "${REPO_URL}/archive/refs/heads/main.tar.gz" -o "$TMP/client.tar.gz"
    elif command -v wget &>/dev/null; then
        wget -qO "$TMP/client.tar.gz" "${REPO_URL}/archive/refs/heads/main.tar.gz"
    else
        die "Neither git, curl, nor wget is available. Please install one and re-run."
    fi
    mkdir -p "$INSTALL_DIR"
    tar -xzf "$TMP/client.tar.gz" --strip-components=1 -C "$INSTALL_DIR"
    rm -rf "$TMP"
fi

# ---- Virtual environment + dependencies -------------------------------------
VENV="$INSTALL_DIR/.venv"
[[ -d "$VENV" ]] || { info "Creating virtual environment …"; "$PYTHON" -m venv "$VENV"; }
info "Installing Python dependencies …"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ---- Interactive configuration ----------------------------------------------
echo -e "\n${CYAN}================================================================${NC}"
echo -e "${CYAN}  Security Client Configuration${NC}"
echo -e "${CYAN}================================================================${NC}"
read -rp "  Security Server URL  [http://localhost:8000]: " SERVER_URL
SERVER_URL=${SERVER_URL:-http://localhost:8000}
read -rp "  Client display name  [$(hostname)]: " CLIENT_NAME
CLIENT_NAME=${CLIENT_NAME:-$(hostname)}
echo -e "${CYAN}================================================================${NC}\n"

# ---- Write .env -------------------------------------------------------------
cat > "$INSTALL_DIR/.env" <<EOF
SERVER_URL=${SERVER_URL}
CLIENT_NAME=${CLIENT_NAME}
CLIENT_ID=
API_KEY=
SCAN_INTERVAL=300
POLL_INTERVAL=30
LOG_LEVEL=INFO
EOF

# ---- Dedicated system user --------------------------------------------------
if ! id "$SERVICE_USER" &>/dev/null; then
    info "Creating service user '$SERVICE_USER' …"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER" 2>/dev/null \
        || useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env"

# ---- systemd unit file ------------------------------------------------------
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Security Client — security scan agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV}/bin/python ${INSTALL_DIR}/client.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable  "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# ---- Done -------------------------------------------------------------------
STATUS=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo 'unknown')
echo -e "\n${GREEN}Installation complete!${NC}"
info "Service status : $STATUS"
info "Config file    : $INSTALL_DIR/.env"
info "View logs      : journalctl -u $SERVICE_NAME -f"
info "Stop service   : systemctl stop $SERVICE_NAME"
info "Start service  : systemctl start $SERVICE_NAME"
