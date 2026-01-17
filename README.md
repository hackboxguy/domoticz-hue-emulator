# Domoticz Hue Emulator

Control your Domoticz home automation devices with Amazon Alexa voice commands - no Philips cloud account, no subscriptions, no third-party skills.

This project emulates a Philips Hue Bridge on your local network, allowing Alexa to discover and control your Domoticz devices as if they were Hue lights. Device commands stay on your local network (Echo → Emulator → Domoticz), though Alexa still requires internet for voice recognition.

## Features

- **Local Device Control** - No Philips Hue cloud, no subscriptions, no third-party skills
- **Voice Commands** - "Alexa, turn on Living Room Light"
- **Dimming Support** - "Alexa, set Bedroom Light to 50 percent"
- **RGB Color Control** - "Alexa, set Light to red" or "Alexa, set Light to warm white"
- **Scenes/Groups** - Control multiple devices with one command
- **Easy Configuration** - Simple YAML config file
- **Auto-Start** - Runs as a systemd service

## Requirements

- Raspberry Pi or Linux server on the same network as Alexa
- Domoticz running with devices configured
- Python 3.7+
- Port 80 available (required for Hue Bridge emulation)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/hackboxguy/domoticz-hue-emulator.git
cd domoticz-hue-emulator

# Test installation (dry run)
sudo ./install.sh --domoticz-user=YOUR_USER --domoticz-pw=YOUR_PW --dryrun

# Install
sudo ./install.sh --domoticz-user=YOUR_USER --domoticz-pw=YOUR_PW

# Edit configuration to add your devices
nano alexa-devices.yaml

# Restart service
sudo systemctl restart domoticz-hue-emulator

# Tell Alexa to discover devices
# "Alexa, discover devices"
```

## Installation Options

```bash
# Basic installation (Domoticz on same machine)
sudo ./install.sh --domoticz-user=admin --domoticz-pw=mypassword

# Remote Domoticz server
sudo ./install.sh --domoticz-user=admin --domoticz-pw=mypassword --domoticz-url=http://192.168.1.100:8080

# Dry run (test without making changes)
sudo ./install.sh --domoticz-user=admin --domoticz-pw=mypassword --dryrun

# Uninstall
sudo ./install.sh --uninstall
```

## Configuration

Edit `alexa-devices.yaml` to add your Domoticz devices:

```yaml
# Domoticz connection (set by installer)
domoticz:
  url: "http://localhost:8080"
  username: "admin"
  password: "yourpassword"

# Devices - find IDX in Domoticz: Setup > Devices
devices:
  - name: "Living Room Light"
    idx: 10
    type: switch          # On/Off only

  - name: "Bedroom Light"
    idx: 20
    type: dimmer          # On/Off + Brightness

  - name: "RGB Lamp"
    idx: 30
    type: rgb             # On/Off + Brightness + Color

# Scenes/Groups - find IDX in Domoticz: Setup > More Options > Scenes/Groups
scenes:
  - name: "All Lights"
    idx: 1
    description: "Controls all lights"
```

### Device Types

| Type | Capabilities | Example Voice Commands |
|------|-------------|------------------------|
| `switch` | On/Off | "Alexa, turn on Kitchen Light" |
| `dimmer` | On/Off, Brightness | "Alexa, set Bedroom to 50 percent" |
| `rgb` | On/Off, Brightness, Color | "Alexa, set Lamp to red" |

### Finding Device IDX

1. Open Domoticz web interface
2. Go to **Setup > Devices**
3. Find your device and note the **IDX** column value

### Scenes vs Groups

- **Scenes**: Only support ON (activate)
- **Groups**: Support both ON and OFF

Use Domoticz Groups if you need to turn devices off with voice commands.

## Voice Commands

### Basic Commands
- "Alexa, turn on [device name]"
- "Alexa, turn off [device name]"

### Dimming (dimmer/rgb types)
- "Alexa, set [device name] to 50 percent"
- "Alexa, dim [device name]"
- "Alexa, brighten [device name]"

### Colors (rgb type only)
- "Alexa, set [device name] to red"
- "Alexa, set [device name] to blue"
- "Alexa, set [device name] to warm white"
- "Alexa, set [device name] to cool white"

### Custom Phrases with Alexa Routines

For custom phrases like "Alexa, let's start the party":

1. Create a scene in `alexa-devices.yaml` named "Party Mode"
2. Open Alexa app > More > Routines > + (create)
3. When this happens: Voice > "let's start the party"
4. Add action: Smart Home > Control device > "Party Mode" > Turn On
5. Save

Now "Alexa, let's start the party" triggers your Domoticz scene!

## Service Management

```bash
# View logs
sudo journalctl -u domoticz-hue-emulator -f

# Restart service (after config changes)
sudo systemctl restart domoticz-hue-emulator

# Stop service
sudo systemctl stop domoticz-hue-emulator

# Start service
sudo systemctl start domoticz-hue-emulator

# Check status
sudo systemctl status domoticz-hue-emulator

# Disable auto-start
sudo systemctl disable domoticz-hue-emulator
```

## Troubleshooting

### Alexa doesn't discover devices

1. Ensure the service is running:
   ```bash
   sudo systemctl status domoticz-hue-emulator
   ```

2. Check if port 80 is in use by another service:
   ```bash
   sudo ss -tlnp | grep :80
   ```

3. Verify SSDP multicast is working (check logs):
   ```bash
   sudo journalctl -u domoticz-hue-emulator -f
   ```

4. Try device discovery again: "Alexa, discover devices"

### Device shows "not responding"

1. Check Domoticz connectivity:
   ```bash
   curl http://localhost:8080
   ```

2. Verify device IDX is correct in config

3. Check logs for API errors:
   ```bash
   sudo journalctl -u domoticz-hue-emulator -f
   ```

### Port 80 already in use

The Hue Bridge protocol requires port 80. Check what's using it:

```bash
sudo ss -tlnp | grep :80
```

Common conflicts: Apache, Nginx, other home automation bridges. Stop or reconfigure the conflicting service.

### Authentication errors

Verify your Domoticz credentials work:

```bash
# The install script tests this automatically
sudo ./install.sh --domoticz-user=USER --domoticz-pw=PW --dryrun
```

## How It Works

1. **SSDP Discovery**: The emulator responds to Alexa's UPnP/SSDP discovery requests on UDP port 1900, announcing itself as a Philips Hue Bridge.

2. **Hue API Emulation**: When Alexa connects, it receives Hue-compatible JSON responses describing your devices as "lights".

3. **Command Translation**: Voice commands are translated to Domoticz API calls:
   - "Turn on" → `switchlight&switchcmd=On`
   - "Set to 50%" → `switchlight&switchcmd=Set Level&level=50`
   - "Set to red" → `setcolbrightnessvalue&color=...`

4. **Local Device Control**: The device control stays on your local network - no Philips Hue cloud, no subscriptions, no third-party Alexa skills. Note: Alexa itself still requires internet for voice recognition (Amazon processes speech in their cloud), but the actual device commands go directly from Echo to your local emulator.

## License

MIT License - see [LICENSE](LICENSE) file.

## Contributing

Issues and pull requests welcome at: https://github.com/hackboxguy/domoticz-hue-emulator
