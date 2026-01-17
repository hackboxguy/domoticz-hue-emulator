#!/bin/bash
#
# Domoticz Hue Emulator - Installation Script
# Allows Alexa to control Domoticz devices via Philips Hue emulation
#
# Usage:
#   sudo ./install.sh --domoticz-user=USERNAME --domoticz-pw=PASSWORD [--domoticz-url=URL]
#
# Options:
#   --domoticz-user=USER    Domoticz username (required)
#   --domoticz-pw=PASSWORD  Domoticz password (required)
#   --domoticz-url=URL      Domoticz URL (default: http://localhost:8080)
#   --dryrun                Run checks only, don't install anything
#   --uninstall             Remove the service and configuration
#   --help                  Show this help message
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
DOMOTICZ_URL="http://localhost:8080"
DOMOTICZ_USER=""
DOMOTICZ_PW=""
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="domoticz-hue-emulator"
UNINSTALL=false
DRYRUN=false

# Print colored messages
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
dryrun() { echo -e "${YELLOW}[DRYRUN]${NC} Would: $1"; }

# Show help
show_help() {
    echo "Domoticz Hue Emulator - Installation Script"
    echo ""
    echo "Usage:"
    echo "  sudo ./install.sh --domoticz-user=USERNAME --domoticz-pw=PASSWORD [OPTIONS]"
    echo ""
    echo "Required:"
    echo "  --domoticz-user=USER    Domoticz username"
    echo "  --domoticz-pw=PASSWORD  Domoticz password"
    echo ""
    echo "Optional:"
    echo "  --domoticz-url=URL      Domoticz URL (default: http://localhost:8080)"
    echo "  --dryrun                Run checks only, don't install anything"
    echo "  --uninstall             Remove the service and configuration"
    echo "  --help                  Show this help message"
    echo ""
    echo "Example:"
    echo "  sudo ./install.sh --domoticz-user=admin --domoticz-pw=mypassword"
    echo ""
}

# Parse command line arguments
parse_args() {
    for arg in "$@"; do
        case $arg in
            --domoticz-user=*)
                DOMOTICZ_USER="${arg#*=}"
                ;;
            --domoticz-pw=*)
                DOMOTICZ_PW="${arg#*=}"
                ;;
            --domoticz-url=*)
                DOMOTICZ_URL="${arg#*=}"
                ;;
            --uninstall)
                UNINSTALL=true
                ;;
            --dryrun|--dry-run)
                DRYRUN=true
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                error "Unknown option: $arg"
                show_help
                exit 1
                ;;
        esac
    done
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "This script must be run with sudo or as root"
        echo ""
        echo "Usage: sudo ./install.sh --domoticz-user=USER --domoticz-pw=PASSWORD"
        exit 1
    fi
}

# Uninstall function
do_uninstall() {
    info "Uninstalling Domoticz Hue Emulator..."

    # Stop and disable service
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "Stopping service..."
        systemctl stop "$SERVICE_NAME"
    fi

    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "Disabling service..."
        systemctl disable "$SERVICE_NAME"
    fi

    # Remove service file
    if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
        info "Removing service file..."
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        systemctl daemon-reload
    fi

    # Remove config (but keep example)
    if [ -f "${INSTALL_DIR}/alexa-devices.yaml" ]; then
        warn "Removing alexa-devices.yaml (your device configuration)"
        rm -f "${INSTALL_DIR}/alexa-devices.yaml"
    fi

    info "Uninstall complete. You can manually remove ${INSTALL_DIR} if desired."
    exit 0
}

# Check if Domoticz is running
check_domoticz() {
    info "Checking if Domoticz is accessible..."

    # Extract host from URL
    DOMOTICZ_HOST=$(echo "$DOMOTICZ_URL" | sed -e 's|http[s]*://||' -e 's|:[0-9]*||' -e 's|/.*||')

    # Try to reach Domoticz
    if ! curl -s --connect-timeout 5 "$DOMOTICZ_URL" > /dev/null 2>&1; then
        error "Cannot connect to Domoticz at $DOMOTICZ_URL"
        echo ""
        echo "Please ensure:"
        echo "  1. Domoticz is running"
        echo "  2. The URL is correct (use --domoticz-url=URL if not localhost:8080)"
        exit 1
    fi

    info "Domoticz is accessible at $DOMOTICZ_URL"
}

# Check if port 80 is available
check_port_80() {
    info "Checking if port 80 is available..."

    if ss -tlnp 2>/dev/null | grep -q ':80 ' || netstat -tlnp 2>/dev/null | grep -q ':80 '; then
        # Check if it's already our service
        if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            warn "Port 80 is in use by existing $SERVICE_NAME service (will be restarted)"
            return 0
        fi

        error "Port 80 is already in use by another service!"
        echo ""
        echo "The Hue emulator requires port 80 (Alexa expects Hue bridges on port 80)."
        echo ""
        echo "Check what's using port 80:"
        echo "  sudo ss -tlnp | grep :80"
        echo "  sudo netstat -tlnp | grep :80"
        echo ""
        echo "Common conflicts:"
        echo "  - Apache/Nginx web server"
        echo "  - Other home automation bridges"
        echo ""
        echo "You may need to:"
        echo "  - Stop/disable the conflicting service"
        echo "  - Change its port"
        echo "  - Run this emulator on a different machine"
        exit 1
    fi

    info "Port 80 is available"
}

# Test Domoticz authentication
test_domoticz_auth() {
    info "Testing Domoticz authentication..."

    # Domoticz uses base64 username and MD5 password hash for login
    USER_B64=$(echo -n "$DOMOTICZ_USER" | base64)
    PW_MD5=$(echo -n "$DOMOTICZ_PW" | md5sum | cut -d' ' -f1)

    # Create temp file for cookies
    COOKIE_FILE=$(mktemp)
    trap "rm -f $COOKIE_FILE" EXIT

    # Try to login
    LOGIN_RESULT=$(curl -s -c "$COOKIE_FILE" \
        "${DOMOTICZ_URL}/json.htm?type=command&param=logincheck&username=${USER_B64}&password=${PW_MD5}")

    if echo "$LOGIN_RESULT" | grep -q '"status" : "OK"'; then
        info "Domoticz authentication successful"

        # Test getting devices
        DEVICES_RESULT=$(curl -s -b "$COOKIE_FILE" "${DOMOTICZ_URL}/json.htm?type=command&param=getdevices")
        if echo "$DEVICES_RESULT" | grep -q '"status" : "OK"'; then
            info "Domoticz API access verified"
        fi
    else
        error "Domoticz authentication failed!"
        echo ""
        echo "Please check your username and password."
        echo "Login response: $LOGIN_RESULT"
        exit 1
    fi

    rm -f "$COOKIE_FILE"
    trap - EXIT
}

# Install dependencies
install_dependencies() {
    info "Checking/Installing dependencies..."

    if [ "$DRYRUN" = true ]; then
        # Check for apt (Debian/Ubuntu/Raspbian)
        if command -v apt-get &> /dev/null; then
            dryrun "apt-get install python3 python3-requests python3-yaml curl"
        elif command -v dnf &> /dev/null; then
            dryrun "dnf install python3 python3-requests python3-pyyaml curl"
        elif command -v yum &> /dev/null; then
            dryrun "yum install python3 python3-requests python3-pyyaml curl"
        else
            warn "Unknown package manager"
        fi

        # Check if already installed
        if python3 -c "import requests, yaml" 2>/dev/null; then
            info "Dependencies already installed"
        else
            warn "Dependencies need to be installed"
        fi
        return 0
    fi

    # Check for apt (Debian/Ubuntu/Raspbian)
    if command -v apt-get &> /dev/null; then
        apt-get update -qq
        apt-get install -y python3 python3-requests python3-yaml curl
    # Check for dnf (Fedora)
    elif command -v dnf &> /dev/null; then
        dnf install -y python3 python3-requests python3-pyyaml curl
    # Check for yum (CentOS/RHEL)
    elif command -v yum &> /dev/null; then
        yum install -y python3 python3-requests python3-pyyaml curl
    else
        warn "Unknown package manager. Please manually install: python3, python3-requests, python3-yaml, curl"
    fi

    # Verify Python and modules
    if ! python3 -c "import requests, yaml" 2>/dev/null; then
        error "Python modules not properly installed"
        echo "Try: pip3 install requests pyyaml"
        exit 1
    fi

    info "Dependencies installed successfully"
}

# Create configuration file
create_config() {
    info "Creating configuration file..."

    CONFIG_FILE="${INSTALL_DIR}/alexa-devices.yaml"

    if [ "$DRYRUN" = true ]; then
        dryrun "Create $CONFIG_FILE with Domoticz credentials"
        if [ -f "$CONFIG_FILE" ]; then
            warn "Existing config would be backed up to alexa-devices.yaml.bak"
        fi
        echo ""
        echo "  Config preview:"
        echo "    domoticz:"
        echo "      url: \"${DOMOTICZ_URL}\""
        echo "      username: \"${DOMOTICZ_USER}\""
        echo "      password: \"****\""
        echo ""
        return 0
    fi

    if [ -f "$CONFIG_FILE" ]; then
        warn "Configuration file already exists, backing up to alexa-devices.yaml.bak"
        cp "$CONFIG_FILE" "${CONFIG_FILE}.bak"
    fi

    # Create config from example
    cat > "$CONFIG_FILE" << EOF
# Domoticz Hue Emulator Configuration
# ====================================
# Edit this file to add your Domoticz devices and scenes.

# Domoticz Server Configuration
domoticz:
  url: "${DOMOTICZ_URL}"
  username: "${DOMOTICZ_USER}"
  password: "${DOMOTICZ_PW}"

# Hue Bridge Emulator Settings
bridge:
  port: 80                    # Port for Hue API (Alexa expects 80)
  ip: null                    # Auto-detect, or set like "192.168.1.100"

# Devices Configuration
# ---------------------
# Add your Domoticz devices here. Find IDX in Domoticz: Setup > Devices
#
# Types:
#   - switch: On/Off only
#   - dimmer: On/Off + Brightness
#   - rgb: On/Off + Brightness + Color (for RGBWW lights)
#
# Voice commands:
#   "Alexa, turn on <name>"
#   "Alexa, set <name> to 50 percent"
#   "Alexa, set <name> to red" (rgb only)

devices:
  # Example - uncomment and modify:
  # - name: "Living Room Light"
  #   idx: 10
  #   type: switch
  #
  # - name: "Bedroom Light"
  #   idx: 20
  #   type: dimmer
  #
  # - name: "RGB Lamp"
  #   idx: 30
  #   type: rgb

# Scenes/Groups Configuration
# ---------------------------
# Add your Domoticz scenes or groups here.
# Find IDX in Domoticz: Setup > More Options > Scenes/Groups
# Use Groups (not Scenes) if you need both On and Off support.

scenes:
  # Example - uncomment and modify:
  # - name: "All Lights"
  #   idx: 1
  #   description: "Controls all lights"
EOF

    chmod 600 "$CONFIG_FILE"  # Restrict access (contains credentials)

    # Change ownership to the user who ran sudo (so they can edit without sudo)
    if [ -n "$SUDO_USER" ]; then
        chown "$SUDO_USER:$SUDO_USER" "$CONFIG_FILE"
    fi

    info "Configuration created at $CONFIG_FILE"
    warn "Edit $CONFIG_FILE to add your devices!"
}

# Install systemd service
install_service() {
    info "Installing systemd service..."

    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

    if [ "$DRYRUN" = true ]; then
        dryrun "Create $SERVICE_FILE"
        dryrun "systemctl daemon-reload"
        dryrun "systemctl enable $SERVICE_NAME"
        echo ""
        echo "  Service file preview:"
        echo "    ExecStart=/usr/bin/python3 ${INSTALL_DIR}/domoticz-hue-emulator.py --config=${INSTALL_DIR}/alexa-devices.yaml"
        echo "    WorkingDirectory=${INSTALL_DIR}"
        echo ""
        return 0
    fi

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Domoticz Hue Emulator - Control Domoticz via Alexa
After=network.target

[Service]
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/domoticz-hue-emulator.py --config=${INSTALL_DIR}/alexa-devices.yaml
WorkingDirectory=${INSTALL_DIR}
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    systemctl daemon-reload

    # Enable service
    systemctl enable "$SERVICE_NAME"

    info "Service installed and enabled"
}

# Start the service
start_service() {
    if [ "$DRYRUN" = true ]; then
        dryrun "systemctl start $SERVICE_NAME"
        return 0
    fi

    info "Starting service..."

    # Stop if already running
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        systemctl stop "$SERVICE_NAME"
    fi

    systemctl start "$SERVICE_NAME"

    # Wait a moment and check status
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "Service started successfully"
    else
        error "Service failed to start!"
        echo ""
        echo "Check the logs with:"
        echo "  sudo journalctl -u $SERVICE_NAME -f"
        exit 1
    fi
}

# Print success message
print_success() {
    echo ""

    if [ "$DRYRUN" = true ]; then
        echo -e "${YELLOW}========================================${NC}"
        echo -e "${YELLOW}  Dry Run Complete - No Changes Made${NC}"
        echo -e "${YELLOW}========================================${NC}"
        echo ""
        echo "All checks passed! Run without --dryrun to install:"
        echo ""
        echo "  sudo ./install.sh --domoticz-user=${DOMOTICZ_USER} --domoticz-pw=****"
        echo ""
        return 0
    fi

    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Installation Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Add your devices to the configuration file:"
    echo "   sudo nano ${INSTALL_DIR}/alexa-devices.yaml"
    echo ""
    echo "2. Restart the service after editing:"
    echo "   sudo systemctl restart $SERVICE_NAME"
    echo ""
    echo "3. Tell Alexa to discover devices:"
    echo "   \"Alexa, discover devices\""
    echo ""
    echo "Useful commands:"
    echo "  View logs:      sudo journalctl -u $SERVICE_NAME -f"
    echo "  Restart:        sudo systemctl restart $SERVICE_NAME"
    echo "  Stop:           sudo systemctl stop $SERVICE_NAME"
    echo "  Status:         sudo systemctl status $SERVICE_NAME"
    echo "  Uninstall:      sudo ./install.sh --uninstall"
    echo ""
}

# Main installation
main() {
    parse_args "$@"
    check_root

    # Handle uninstall
    if [ "$UNINSTALL" = true ]; then
        do_uninstall
    fi

    # Check required parameters
    if [ -z "$DOMOTICZ_USER" ] || [ -z "$DOMOTICZ_PW" ]; then
        error "Missing required parameters!"
        echo ""
        show_help
        exit 1
    fi

    echo ""
    if [ "$DRYRUN" = true ]; then
        warn "DRY RUN MODE - No changes will be made"
        echo ""
    fi
    info "Starting Domoticz Hue Emulator installation..."
    echo ""

    check_domoticz
    check_port_80
    test_domoticz_auth
    install_dependencies
    create_config
    install_service
    start_service
    print_success
}

# Run main
main "$@"
