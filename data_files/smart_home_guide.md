# Smart Home Device Guide

## Home Assistant Integration
ARIA connects to Home Assistant at http://127.0.0.1:8123 using a long-lived access token.
All smart home devices are automatically discovered and can be controlled by voice or text.

## Supported Device Types

### Lights & Switches
- Turn on/off any light or switch using natural language
- Example: "Turn on the living room light" → [IOT:turn_on|light.living_room]
- Example: "Turn off all fans" → [IOT:turn_off|fan.bedroom_fan]

### Dimmers
- Set brightness percentage (0-100%)
- Example: "Set bedroom light to 60%" → [GENERIC:dimmer|generic.bedroom_dimmer|60]

### Multi-Channel Switches
- Control individual channels of multi-switch devices
- Example: "Turn on channel 2" → [GENERIC:turn_on|generic.wall_switch|2]

### Fans
- Set fan speed (1=low, 2=medium, 3=high)
- Example: "Set fan to high speed" → [GENERIC:fan|generic.ceiling_fan|3]

### Irrigation Systems
- Control water irrigation via HA switches
- Example: "Turn on irrigation" → [IOT:turn_on|switch.irrigation]

## Generic IP Devices (LAN)
Devices connected directly via IP (Tasmota ESP8266/ESP32):
- Must have an IP address on the local network
- Controlled via HTTP commands (Tasmota-compatible)
- Managed through the IoT Control panel in ARIA Nexus

## Sensors (read-only)
- Temperature, humidity, motion, door/window sensors
- Just ask ARIA: "What's the temperature?" — it will read from HA states
- No control tag needed for sensor readings

## Home Assistant Entities
Common entity prefixes:
- light.* — smart lights
- switch.* — switches and relays  
- fan.* — fans
- climate.* — thermostats
- sensor.* — sensors (read-only)
- binary_sensor.* — on/off sensors (motion, door, etc.)
