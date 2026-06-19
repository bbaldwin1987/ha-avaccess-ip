# Changelog

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
- CEC display power on Kitchen TV.
- Device alias sentinel handling for `"alias" not defined`.

### Known Limitations

- Source state is poll-based.
- Display power is assumed state.
- Stable IPs or DHCP reservations are strongly recommended.
- Video wall, MRX multiview, preview streams, overlays, and firmware upload are not implemented.
