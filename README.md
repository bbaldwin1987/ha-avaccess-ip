# AV Access IP — Home Assistant Integration

A custom [Home Assistant](https://www.home-assistant.io/) integration for **AV Access HDIP100 / 4KIP200 series** AV-over-IP encoders (TX) and decoders (RX). It models a video matrix in Home Assistant: every decoder becomes a `media_player` whose source list is your set of encoders, plus per-decoder display power control.

> **Status:** early development. Phases 0–1 (transport, device model, manual add-by-IP config flow) and the entity scaffold are in place; not yet validated against hardware. See [`docs/HA-Integration-Plan.md`](docs/HA-Integration-Plan.md) for the full architecture and roadmap.

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

Out of scope for now (architecture leaves room): video wall, MRX multiview, forced resolution/color space, OSD/PNG overlay, preview stream, firmware upload.

## Requirements

- Each device must have a **stable IP** (static or DHCP reservation) — devices are added by IP.
- For the **group-switch broadcast fast path**, Home Assistant must share the devices' L2 subnet. Per-device control works from anywhere with IP reachability.

## Installation (HACS)

1. In Home Assistant, go to **HACS → Integrations → ⋮ (top right) → Custom repositories**.
2. Add this repository URL and select category **Integration**.
3. Install **AV Access IP Video Distribution**, then restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration → AV Access IP**.
5. Add each encoder and decoder by choosing its type and entering its IP address.

## Manual installation (development)

Copy `custom_components/avaccess_ip/` into your Home Assistant `config/custom_components/` directory and restart.

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
