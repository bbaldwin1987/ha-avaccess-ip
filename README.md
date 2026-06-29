# AV Access IP — Home Assistant Integration

A custom [Home Assistant](https://www.home-assistant.io/) integration for **AV Access HDIP100 / 4KIP200 series** AV-over-IP encoders (TX) and decoders (RX). It models a video matrix in Home Assistant: every decoder becomes a `media_player` whose source list is your set of encoders, plus per-decoder display power control.

> **Status:** first hardware-tested revision. Manual device setup, per-decoder source switching, group switching, encoder/decoder online status, and decoder display power have been validated against 4KIP200-series hardware. See [`docs/HA-Integration-Plan.md`](docs/HA-Integration-Plan.md) for the full architecture and roadmap, and [`docs/TEST-NOTES.md`](docs/TEST-NOTES.md) for current validation notes.

## Supported devices

| Model | Role | Notes |
|---|---|---|
| 4KIP200E / 4KIP204E | Encoder (TX) | 4K source |
| 4KIP200D | Decoder (RX) | 4K output |
| 4KIP200M | Multiview decoder (MRX) | Multiview not yet implemented |
| HDIP100E | Encoder (TX) | 2K source |
| HDIP100D | Decoder (RX) | 2K output |

## Features (current scope)

- **Matrix switching** — each decoder is a `media_player`; pick any encoder as its source (bonded video+audio+RS232 routing).
- **Group switching** — an `avaccess_ip.switch_group` service switches several decoders to one source at once via UDP broadcast, falling back to sequential switching when Home Assistant is not on the device subnet.
- **Display power (per decoder)** — a `switch` per decoder drives the attached display on/off, using that decoder's configured method (CEC, RS232, or both) and on/off codes.
- **Samsung Frame Art Mode** — switch and service support for discrete Art Mode on/off over a decoder's RS232 Ex-Link connection.
- **Online status** — every configured encoder and decoder gets an online diagnostic entity so source-only encoders are visible in Home Assistant.
- **Device management** — add, edit, rename, and remove configured devices from the integration's Configure menu.
- **Utility services** — clear decoder source, send raw CEC commands, and reboot AV Access devices.

Out of scope for now (architecture leaves room): video wall, MRX multiview, forced resolution/color space, OSD/PNG overlay, preview stream, firmware upload.

## Requirements

- Each device must have a **stable IP** (static or DHCP reservation) — devices are added by IP.
- For the **group-switch broadcast fast path**, Home Assistant must share the devices' L2 subnet. Per-device control works from anywhere with IP reachability.

## Installation (HACS)

1. In Home Assistant, go to **HACS → Integrations → ⋮ (top right) → Custom repositories**.
2. Add this repository URL and select category **Integration**.
3. Install **AV Access IP Video Distribution**, then restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration → AV Access IP**.
5. Open **Configure** on the AV Access IP integration.
6. Add each encoder and decoder by choosing its type, entering its IP address, and entering a friendly name.
7. For decoders, choose a display profile. Use **Samsung The Frame over Ex-Link** to pre-fill the tested RS232 power settings.
8. Confirm the detected hostname, MAC address, model, and firmware before saving.

## Manual installation (development)

Copy `custom_components/avaccess_ip/` into your Home Assistant `config/custom_components/` directory and restart.

Example deployment from a development checkout:

```bash
tar -cf - custom_components/avaccess_ip | ssh root@<ha-host> 'mkdir -p /config && tar -xf - -C /config'
ssh root@<ha-host> 'ha core restart'
```

## Setup

1. Go to **Settings → Devices & services → Add integration → AV Access IP**.
2. Create the AV Access IP integration entry.
3. Open **Configure** on that integration.
4. Add encoders first, then decoders.
5. Use stable IP addresses for all devices, either static IPs or DHCP reservations.

The Configure menu contains:

- **Add a device** — add an encoder or decoder by IP address.
- **Edit a device** — update IP address, friendly name, display profile, and decoder display-power settings.
- **Rename a device** — update the friendly name stored in the integration entry.
- **Remove a device** — remove a configured device from the integration entry.
- **Settings** — adjust poll interval and group-switch broadcast behavior.

## Using The Integration

### Individual Switching

Each decoder appears as a `media_player`. Select an encoder from the source dropdown to switch that decoder:

```text
Kitchen TV → Shield
Garage TV → Zone2
```

The integration sends:

```text
gbconfig --source-select=<encoder_mac>
e e_reconnect
```

### Group Switching

Use **Developer Tools → Actions** and call `avaccess_ip.switch_group`:

```yaml
target:
  - media_player.kitchen_tv
  - media_player.garage_tv
source: Shield
```

`source` can be the encoder friendly name, hostname, or bare MAC address. When broadcast is enabled and Home Assistant is on the same subnet, the integration sends a UDP `msg_b_reconnect` broadcast on port `5010`. Otherwise it falls back to switching each decoder over Telnet.

### Display Power

Each decoder also exposes a display power switch. The switch calls `sinkpower on` and `sinkpower off` on the decoder. Configure the decoder's CEC/RS232 behavior when adding the decoder.

For Samsung Frame TVs using Ex-Link through an AV Access decoder, choose the **Samsung The Frame over Ex-Link** display profile during decoder setup/editing. It pre-fills RS232 mode with hex commands enabled:

```text
RS232 parameter: 9600-8n1
Power On: 08 22 00 00 00 02 D4
Power Off: 08 22 00 00 00 01 D5
```

Wire the decoder RS232 adapter with TX/RX crossed: AV Access TX to Samsung RX, AV Access RX to Samsung TX, and GND to GND.

### Samsung Frame Art Mode

Use `avaccess_ip.samsung_frame_art_mode` to toggle Art Mode through the Samsung Frame Ex-Link connection:

When a decoder's display profile is set to **Samsung The Frame over Ex-Link**, Home Assistant also creates a `Samsung Frame Art Mode` switch for that decoder.

```yaml
action: avaccess_ip.samsung_frame_art_mode
data:
  target:
    - media_player.kitchen_tv
  enabled: true
```

The service temporarily loads the Samsung Art Mode RS232 commands into the decoder's sinkpower command slots, calls `sinkpower on` or `sinkpower off`, then restores the configured display power RS232 commands.

### Utility Services

Clear a decoder source:

```yaml
action: avaccess_ip.clear_source
data:
  target:
    - media_player.kitchen_tv
```

Send a raw CEC command through a device:

```yaml
action: avaccess_ip.send_cec
data:
  target:
    - media_player.kitchen_tv
  cec_string: "40 04"
```

Reboot a device:

```yaml
action: avaccess_ip.reboot_device
data:
  target:
    - binary_sensor.shield_online
```

## Notes And Limitations

- Device alias readback may return `"alias" not defined`; the integration ignores that value and uses the friendly name entered during setup.
- Source state is polled. After a change made outside Home Assistant, the media player source may take up to one poll interval to update.
- Stable IPs are strongly recommended. If an IP changes, use **Configure → Edit a device** to update the stored address.
- Integration tile logos use Home Assistant's brand image system. This repository includes local `brand/icon.png` and `brand/logo.png` assets for Home Assistant versions that support local custom integration brands.
- The current display power switch is assumed state because the device API does not provide display power readback.
- Samsung Frame Art Mode requires a working RS232 Ex-Link connection and validated Samsung command codes for the target TV model.
- Video wall, MRX multiview, preview streams, overlays, and firmware upload are intentionally out of scope for this revision.

## Development

```bash
# run the unit tests (no hardware required)
pip install -r requirements_test.txt
pytest

# validate against a real device (Phase 0 spike — needs a unit on the network)
python spike.py <device_ip>
```

## License

MIT — see [LICENSE](LICENSE).
