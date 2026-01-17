#!/usr/bin/env python3
"""
Domoticz Hue Emulator
Emulates a Philips Hue Bridge to allow Alexa to control Domoticz devices via local network.

Usage:
    sudo python3 domoticz-hue-emulator.py --config=/path/to/alexa-devices.yaml
"""

import argparse
import socket
import struct
import threading
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import uuid
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Generate a consistent bridge ID based on MAC-like format
BRIDGE_ID = "001788FFFE" + uuid.getnode().to_bytes(6, 'big')[-3:].hex().upper()
BRIDGE_UUID = f"2f402f80-da50-11e1-9b23-{uuid.getnode():012x}"


def load_config(config_path):
    """Load configuration from YAML or JSON file."""
    path = Path(config_path)

    if not path.exists():
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)

    content = path.read_text()

    # Try YAML first, fall back to JSON
    if path.suffix in ['.yaml', '.yml']:
        try:
            import yaml
            config = yaml.safe_load(content)
        except ImportError:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            sys.exit(1)
    else:
        config = json.loads(content)

    return config


def build_devices_dict(config):
    """Build the DEVICES dictionary from config file."""
    devices = {}
    light_id = 1

    # Add regular devices (handle None case)
    for device in config.get('devices') or []:
        devices[str(light_id)] = {
            "name": device['name'],
            "idx": device['idx'],
            "type": device.get('type', 'switch'),
            "is_scene": False
        }
        light_id += 1

    # Add scenes as virtual switches (handle None case)
    for scene in config.get('scenes') or []:
        devices[str(light_id)] = {
            "name": scene['name'],
            "idx": scene['idx'],
            "type": "scene",
            "is_scene": True,
            "description": scene.get('description', '')
        }
        light_id += 1

    return devices


def get_local_ip():
    """Get the local IP address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip


class DomoticzController:
    """Interface to Domoticz API."""

    def __init__(self, base_url, username="", password=""):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._logged_in = False

    def _ensure_login(self):
        """Login to Domoticz if credentials are provided."""
        if self._logged_in or not self.username:
            return True

        import base64
        import hashlib

        url = f"{self.base_url}/json.htm"
        params = {
            "type": "command",
            "param": "logincheck",
            "username": base64.b64encode(self.username.encode()).decode(),
            "password": hashlib.md5(self.password.encode()).hexdigest()
        }
        try:
            response = self.session.get(url, params=params, timeout=5)
            data = response.json()
            if data.get("status") == "OK":
                logger.info(f"Logged in to Domoticz as {self.username}")
                self._logged_in = True
                return True
            else:
                logger.error(f"Domoticz login failed: {data}")
                return False
        except Exception as e:
            logger.error(f"Domoticz login error: {e}")
            return False

    def switch_light(self, idx, command):
        """Turn a switch on or off."""
        self._ensure_login()
        url = f"{self.base_url}/json.htm"
        params = {
            "type": "command",
            "param": "switchlight",
            "idx": idx,
            "switchcmd": "On" if command else "Off"
        }
        try:
            response = self.session.get(url, params=params, timeout=5)
            logger.info(f"Domoticz switch {idx} -> {'On' if command else 'Off'}: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Domoticz error: {e}")
            return False

    def switch_scene(self, idx, command):
        """Activate or deactivate a scene."""
        self._ensure_login()
        url = f"{self.base_url}/json.htm"
        params = {
            "type": "command",
            "param": "switchscene",
            "idx": idx,
            "switchcmd": "On" if command else "Off"
        }
        try:
            response = self.session.get(url, params=params, timeout=5)
            logger.info(f"Domoticz scene {idx} -> {'On' if command else 'Off'}: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Domoticz scene error: {e}")
            return False

    def set_dimmer(self, idx, level):
        """Set dimmer level (0-100)."""
        self._ensure_login()
        url = f"{self.base_url}/json.htm"
        params = {
            "type": "command",
            "param": "switchlight",
            "idx": idx,
            "switchcmd": "Set Level",
            "level": level
        }
        try:
            response = self.session.get(url, params=params, timeout=5)
            logger.info(f"Domoticz dimmer {idx} -> {level}%: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Domoticz error: {e}")
            return False

    def set_rgb_color(self, idx, hue=None, saturation=None, brightness=None):
        """Set RGB light color and brightness."""
        self._ensure_login()
        url = f"{self.base_url}/json.htm"
        params = {
            "type": "command",
            "param": "setcolbrightnessvalue",
            "idx": idx,
            "iswhite": "false"
        }

        if hue is not None:
            params["hue"] = int(hue * 360 / 65535)

        if saturation is not None:
            params["saturation"] = int(saturation * 100 / 254)

        if brightness is not None:
            params["brightness"] = int(brightness * 100 / 254)

        try:
            response = self.session.get(url, params=params, timeout=5)
            logger.info(f"Domoticz RGB {idx} -> hue={params.get('hue')}, sat={params.get('saturation')}, bri={params.get('brightness')}: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Domoticz RGB error: {e}")
            return False

    def set_white_color(self, idx, color_temp, brightness=None):
        """
        Set white color temperature using dedicated white channels.
        color_temp: Hue API mireds (153-500), lower = cooler, higher = warmer

        For RGBWW lamps, uses the cold white (cw) and warm white (ww) LED channels.
        """
        self._ensure_login()
        url = f"{self.base_url}/json.htm"

        # Convert mireds to cw/ww mix
        # Mireds 153 = 6500K (cool white) -> cw=255, ww=0
        # Mireds 500 = 2000K (warm white) -> cw=0, ww=255
        mired_min, mired_max = 153, 500
        normalized = (color_temp - mired_min) / (mired_max - mired_min)
        normalized = max(0, min(1, normalized))  # Clamp to 0-1

        # Interpolate between cold and warm white
        cw = int(255 * (1 - normalized))  # 255 -> 0
        ww = int(255 * normalized)         # 0 -> 255

        # Build color JSON for Domoticz (m=2 = White mode for RGBWW)
        color_json = json.dumps({"m": 2, "t": 0, "r": 0, "g": 0, "b": 0, "cw": cw, "ww": ww})

        bri_level = int(brightness * 100 / 254) if brightness else 100

        params = {
            "type": "command",
            "param": "setcolbrightnessvalue",
            "idx": idx,
            "color": color_json,
            "brightness": bri_level
        }

        try:
            response = self.session.get(url, params=params, timeout=5)
            logger.info(f"Domoticz White {idx} -> cw={cw}, ww={ww}, bri={bri_level}%: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Domoticz white error: {e}")
            return False

    def set_brightness(self, idx, brightness):
        """Set brightness only without changing color."""
        self._ensure_login()
        url = f"{self.base_url}/json.htm"
        level = int(brightness * 100 / 254)
        params = {
            "type": "command",
            "param": "switchlight",
            "idx": idx,
            "switchcmd": "Set Level",
            "level": level
        }
        try:
            response = self.session.get(url, params=params, timeout=5)
            logger.info(f"Domoticz brightness {idx} -> {level}%: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Domoticz brightness error: {e}")
            return False

    def get_device_status(self, idx, is_scene=False):
        """Get current device or scene status from Domoticz."""
        self._ensure_login()
        url = f"{self.base_url}/json.htm"

        if is_scene:
            params = {"type": "command", "param": "getscenes"}
        else:
            params = {"type": "command", "param": "getdevices", "rid": idx}

        try:
            response = self.session.get(url, params=params, timeout=5)
            data = response.json()

            if is_scene:
                # Find the specific scene
                for scene in data.get("result", []):
                    if str(scene.get("idx")) == str(idx):
                        return {
                            "on": scene.get("Status") == "On",
                            "bri": 254,
                            "hue": 0,
                            "sat": 0
                        }
            else:
                if data.get("result"):
                    device = data["result"][0]
                    is_on = device.get("Status", "Off") != "Off"
                    # For dimmer/RGB, use Level; for simple switches, use 254 when on
                    level = device.get("Level", 0)
                    if level == 0 and is_on:
                        level = 100  # Treat on switches as 100%
                    status = {
                        "on": is_on,
                        "bri": int(level * 2.54),
                        "hue": 0,
                        "sat": 0
                    }
                    if "Color" in device:
                        try:
                            color = json.loads(device["Color"]) if isinstance(device["Color"], str) else device["Color"]
                            r, g, b = color.get("r", 0), color.get("g", 0), color.get("b", 0)
                            h, s, v = self._rgb_to_hsv(r, g, b)
                            status["hue"] = int(h * 65535)
                            status["sat"] = int(s * 254)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    return status
        except Exception as e:
            logger.error(f"Domoticz status error: {e}")

        return {"on": False, "bri": 0, "hue": 0, "sat": 0}

    @staticmethod
    def _rgb_to_hsv(r, g, b):
        """Convert RGB (0-255) to HSV (0-1 range)."""
        r, g, b = r / 255.0, g / 255.0, b / 255.0
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        v = max_c
        if max_c == min_c:
            return 0, 0, v
        s = (max_c - min_c) / max_c
        rc = (max_c - r) / (max_c - min_c)
        gc = (max_c - g) / (max_c - min_c)
        bc = (max_c - b) / (max_c - min_c)
        if r == max_c:
            h = bc - gc
        elif g == max_c:
            h = 2.0 + rc - bc
        else:
            h = 4.0 + gc - rc
        h = (h / 6.0) % 1.0
        return h, s, v


class HueAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler for Hue API requests from Alexa."""

    # Class variables set by main()
    devices = {}
    domoticz = None
    bridge_ip = None
    http_port = 80

    def log_message(self, format, *args):
        logger.info(f"HTTP: {args[0]}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/description.xml":
            self._send_description()
            return

        if path.startswith("/api"):
            self._handle_api_get(path)
            return

        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api"):
            self._handle_api_post(path)
            return
        self.send_error(404)

    def do_PUT(self):
        path = urlparse(self.path).path
        if path.startswith("/api"):
            self._handle_api_put(path)
            return
        self.send_error(404)

    def _send_description(self):
        """Send UPnP device description XML."""
        xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
    <specVersion><major>1</major><minor>0</minor></specVersion>
    <URLBase>http://{self.bridge_ip}:{self.http_port}/</URLBase>
    <device>
        <deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>
        <friendlyName>Philips Hue ({self.bridge_ip})</friendlyName>
        <manufacturer>Royal Philips Electronics</manufacturer>
        <manufacturerURL>http://www.philips.com</manufacturerURL>
        <modelDescription>Philips hue Personal Wireless Lighting</modelDescription>
        <modelName>Philips hue bridge 2015</modelName>
        <modelNumber>BSB002</modelNumber>
        <modelURL>http://www.meethue.com</modelURL>
        <serialNumber>{BRIDGE_ID}</serialNumber>
        <UDN>uuid:{BRIDGE_UUID}</UDN>
    </device>
</root>"""
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.end_headers()
        self.wfile.write(xml.encode())

    def _handle_api_get(self, path):
        """Handle GET requests to /api endpoints."""
        parts = path.split("/")

        if path.endswith("/lights") or (len(parts) == 3 and parts[2]):
            lights = self._get_all_lights()
            if path.endswith("/lights"):
                self._send_json(lights)
            else:
                self._send_json({"lights": lights})
            return

        if "/lights/" in path:
            light_id = parts[-1]
            if light_id in self.devices:
                self._send_json(self._get_light_state(light_id))
                return

        self._send_json({})

    def _handle_api_post(self, path):
        """Handle POST requests (user registration)."""
        content_length = int(self.headers.get('Content-Length', 0))
        self.rfile.read(content_length)
        self._send_json([{"success": {"username": "alexa-hue-emulator"}}])

    def _handle_api_put(self, path):
        """Handle PUT requests (light control)."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        logger.info(f"PUT {path}: {data}")

        parts = path.split("/")
        if "lights" in parts and "state" in parts:
            light_id = parts[parts.index("lights") + 1]
            result = self._control_light(light_id, data)
            self._send_json(result)
            return

        self._send_json([])

    def _get_all_lights(self):
        """Get all lights in Hue format."""
        lights = {}
        for light_id in self.devices:
            lights[light_id] = self._get_light_state(light_id)
        return lights

    def _get_light_state(self, light_id):
        """Get single light state in Hue format."""
        device = self.devices.get(light_id, {})
        is_scene = device.get("is_scene", False)
        status = self.domoticz.get_device_status(device.get("idx", 0), is_scene)
        device_type = device.get("type", "switch")

        # Determine Hue device type and model
        if device_type == "rgb":
            hue_type = "Extended color light"
            model_id = "LCT015"
            product_name = "Hue color lamp"
            color_mode = "hs"
        elif device_type == "dimmer":
            hue_type = "Dimmable light"
            model_id = "LWB010"
            product_name = "Hue white lamp"
            color_mode = "ct"
        elif device_type == "scene":
            hue_type = "On/Off plug-in unit"
            model_id = "LOM001"
            product_name = "Hue smart plug"
            color_mode = "ct"
        else:
            hue_type = "On/Off plug-in unit"
            model_id = "LOM001"
            product_name = "Hue smart plug"
            color_mode = "ct"

        return {
            "state": {
                "on": status["on"],
                "bri": status["bri"],
                "hue": status.get("hue", 0),
                "sat": status.get("sat", 0),
                "effect": "none",
                "xy": [0.0, 0.0],
                "ct": 500,
                "alert": "none",
                "colormode": color_mode,
                "reachable": True
            },
            "type": hue_type,
            "name": device.get("name", f"Light {light_id}"),
            "modelid": model_id,
            "manufacturername": "Philips",
            "productname": product_name,
            "uniqueid": f"00:17:88:01:00:{light_id.zfill(2)}:00:00-0b",
            "swversion": "1.0"
        }

    def _control_light(self, light_id, data):
        """Control a light or scene via Domoticz."""
        if light_id not in self.devices:
            return [{"error": {"description": "Light not found"}}]

        device = self.devices[light_id]
        idx = device["idx"]
        device_type = device.get("type", "switch")
        is_scene = device.get("is_scene", False)
        result = []

        # Handle on/off
        if "on" in data:
            if is_scene:
                self.domoticz.switch_scene(idx, data["on"])
            else:
                self.domoticz.switch_light(idx, data["on"])
            result.append({
                "success": {f"/lights/{light_id}/state/on": data["on"]}
            })

        # For RGB lights, handle color, white, and brightness
        if device_type == "rgb" and not is_scene:
            hue = data.get("hue")
            sat = data.get("sat")
            bri = data.get("bri")
            ct = data.get("ct")  # Color temperature (white mode)

            # White/warm white mode (color temperature)
            if ct is not None:
                self.domoticz.set_white_color(idx, ct, brightness=bri)
                result.append({"success": {f"/lights/{light_id}/state/ct": ct}})
                if bri is not None:
                    result.append({"success": {f"/lights/{light_id}/state/bri": bri}})

            # Color mode (hue/saturation)
            elif hue is not None or sat is not None:
                self.domoticz.set_rgb_color(idx, hue=hue, saturation=sat, brightness=bri)
                if hue is not None:
                    result.append({"success": {f"/lights/{light_id}/state/hue": hue}})
                if sat is not None:
                    result.append({"success": {f"/lights/{light_id}/state/sat": sat}})
                if bri is not None:
                    result.append({"success": {f"/lights/{light_id}/state/bri": bri}})

            # Brightness only (no color change)
            elif bri is not None:
                self.domoticz.set_brightness(idx, bri)
                result.append({"success": {f"/lights/{light_id}/state/bri": bri}})

        # For dimmer lights, handle brightness
        elif device_type == "dimmer" and "bri" in data and not is_scene:
            level = int(data["bri"] / 2.54)
            self.domoticz.set_dimmer(idx, level)
            result.append({"success": {f"/lights/{light_id}/state/bri": data["bri"]}})

        # For switch/scene devices, acknowledge bri even though we ignore it
        # (Alexa sends bri with on commands and expects confirmation)
        elif device_type in ("switch", "scene") and "bri" in data:
            result.append({"success": {f"/lights/{light_id}/state/bri": data["bri"]}})

        return result


class SSDPResponder:
    """Responds to SSDP M-SEARCH requests from Alexa."""

    SSDP_ADDR = "239.255.255.250"
    SSDP_PORT = 1900

    def __init__(self, http_port, bridge_ip):
        self.http_port = http_port
        self.bridge_ip = bridge_ip
        self.running = False

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._listen, daemon=True)
        thread.start()
        logger.info(f"SSDP responder started on {self.SSDP_ADDR}:{self.SSDP_PORT}")

    def stop(self):
        self.running = False

    def _listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind(("", self.SSDP_PORT))
        except OSError as e:
            logger.error(f"Cannot bind to SSDP port: {e}")
            logger.info("Try running with sudo or use a different port")
            return

        mreq = struct.pack("4sl", socket.inet_aton(self.SSDP_ADDR), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1)

        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                message = data.decode('utf-8', errors='ignore')

                if "M-SEARCH" in message and ("ssdp:all" in message or "device:basic" in message.lower() or "upnp:rootdevice" in message):
                    logger.info(f"SSDP M-SEARCH from {addr}")
                    self._send_response(sock, addr)

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"SSDP error: {e}")

    def _send_response(self, sock, addr):
        """Send SSDP response to Alexa."""
        response = f"""HTTP/1.1 200 OK\r
HOST: 239.255.255.250:1900\r
CACHE-CONTROL: max-age=100\r
EXT:\r
LOCATION: http://{self.bridge_ip}:{self.http_port}/description.xml\r
SERVER: Linux/3.14.0 UPnP/1.0 IpBridge/1.24.0\r
hue-bridgeid: {BRIDGE_ID}\r
ST: urn:schemas-upnp-org:device:basic:1\r
USN: uuid:{BRIDGE_UUID}::urn:schemas-upnp-org:device:basic:1\r
\r
"""
        sock.sendto(response.encode(), addr)
        logger.info(f"SSDP response sent to {addr}")


def main():
    parser = argparse.ArgumentParser(
        description='Philips Hue Bridge Emulator for Domoticz',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sudo python3 hue_emulator.py --config=/home/pi/alexa-devices.yaml
  sudo python3 hue_emulator.py -c /etc/hue-emulator/config.yaml

Config file format (YAML):
  domoticz:
    url: "http://192.168.1.149:8080"
    username: "admin"
    password: "secret"

  devices:
    - name: "Living Room Light"
      idx: 10
      type: rgb

  scenes:
    - name: "Party Mode"
      idx: 1
"""
    )
    parser.add_argument('-c', '--config', required=True,
                        help='Path to YAML/JSON config file')

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Extract settings
    domoticz_config = config.get('domoticz', {})
    bridge_config = config.get('bridge', {})

    domoticz_url = domoticz_config.get('url', 'http://localhost:8080')
    domoticz_username = domoticz_config.get('username', '')
    domoticz_password = domoticz_config.get('password', '')

    http_port = bridge_config.get('port', 80)
    bridge_ip = bridge_config.get('ip') or get_local_ip()

    # Build devices dictionary
    devices = build_devices_dict(config)

    # Count devices and scenes
    num_devices = len([d for d in devices.values() if not d.get('is_scene')])
    num_scenes = len([d for d in devices.values() if d.get('is_scene')])

    # Initialize Domoticz controller
    domoticz = DomoticzController(domoticz_url, domoticz_username, domoticz_password)

    # Set class variables for HTTP handler
    HueAPIHandler.devices = devices
    HueAPIHandler.domoticz = domoticz
    HueAPIHandler.bridge_ip = bridge_ip
    HueAPIHandler.http_port = http_port

    # Print startup banner
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           Philips Hue Emulator for Domoticz                  ║
╠══════════════════════════════════════════════════════════════╣
║  Config:     {args.config:<47} ║
║  Bridge IP:  {bridge_ip:<47} ║
║  HTTP Port:  {http_port:<47} ║
║  Domoticz:   {domoticz_url:<47} ║
║  Devices:    {num_devices:<47} ║
║  Scenes:     {num_scenes:<47} ║
╠══════════════════════════════════════════════════════════════╣
║  Tell Alexa: "Discover devices"                              ║
╚══════════════════════════════════════════════════════════════╝
""")

    # List configured devices and scenes
    print("Configured devices:")
    for light_id, device in devices.items():
        device_type = "SCENE" if device.get('is_scene') else device.get('type', 'switch').upper()
        print(f"  [{light_id}] {device['name']} (idx: {device['idx']}, type: {device_type})")
    print()

    # Start SSDP responder
    ssdp = SSDPResponder(http_port, bridge_ip)
    ssdp.start()

    # Start HTTP server
    try:
        server = HTTPServer(("", http_port), HueAPIHandler)
        logger.info(f"HTTP server started on port {http_port}")
        server.serve_forever()
    except PermissionError:
        logger.error(f"Permission denied for port {http_port}. Try: sudo python3 {__file__}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        ssdp.stop()


if __name__ == "__main__":
    main()
