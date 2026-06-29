# Changelog

## Unreleased

### Added

- Samsung Frame Art Mode service over decoder RS232 Ex-Link: `avaccess_ip.samsung_frame_art_mode`.
- Samsung Frame Art Mode switch for decoders using the Samsung The Frame over Ex-Link display profile.
- Optional decoder display profile selection, including a Samsung The Frame over Ex-Link preset.
- RS232 serial parameter support in decoder display-power setup, defaulting to `9600-8n1`.

### Fixed

- Decoder RS232 display-power setup now applies settings to hardware when adding or editing a decoder.
- RS232 sinkpower mode setup now writes the active `sinkpower_mode` parameter used by tested 4KIP200D firmware.

## v0.1.0 - First Hardware-Tested Revision

### Added

- Manual AV Access IP integration setup through the Home Assistant UI.
- Add-device flow for encoders and decoders by IP address.
- Confirmation of detected hostname, MAC address, model, and firmware during device setup.
- Edit-device flow for IP address, friendly name, and decoder display-power settings.
- Rename-device and remove-device actions in the integration Configure menu.
- Encoder and decoder online diagnostic entities.
- Decoder `media_player` entities with source selection.
- Decoder display power switches using `sinkpower on` and `sinkpower off`.
- Group switching service: `avaccess_ip.switch_group`.
- Utility services: `clear_source`, `send_cec`, and `reboot_device`.
- Local brand/icon assets for Home Assistant versions that support custom integration brand images.
- Hardware validation notes in `docs/TEST-NOTES.md`.

### Validated

- 4KIP200-series encoders and decoders.
- Per-decoder switching between Shield and Zone2 sources.
- Group switching between multiple decoders.
- HACS install/update flow on a separate target Home Assistant instance.
- Device loading, individual switching, group switching, and display power on the target instance.
- CEC display power on Kitchen TV.
- Device alias sentinel handling for `"alias" not defined`.

### Known Limitations

- Source state is poll-based.
- Display power is assumed state.
- Stable IPs or DHCP reservations are strongly recommended.
- Video wall, MRX multiview, preview streams, overlays, and firmware upload are not implemented.
