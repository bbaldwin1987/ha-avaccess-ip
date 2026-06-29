# AV Access IP Hardware Test Notes

These notes capture the first working hardware validation pass for the custom Home Assistant integration. The `v0.1.0` release was also installed through HACS on a separate target Home Assistant instance and passed device load, individual switching, group switching, and display-power validation.

## Test Environment

- Home Assistant host: VM on the same subnet as the AV Access devices.
- Integration deployment: copied to `/config/custom_components/avaccess_ip` for development validation, then installed/updated through HACS on the target Home Assistant instance.
- Device family tested: AV Access 4KIP200-series encoders and decoders.
- Control path: Telnet on TCP port `24`.
- Group-switch path: UDP broadcast on port `5010`.

## Tested Devices

| Friendly name | Role | IP address | Detected hostname | MAC |
|---|---|---|---|---|
| Shield | Encoder | `192.168.86.83` | `IPE935-341B2284DFBC` | `341B2284DFBC` |
| Zone2 | Encoder | `192.168.86.9` | `IPE935-341B2284DFA3` | `341B2284DFA3` |
| Kitchen TV | Decoder | `192.168.86.2` | `IPD935-341B2284B7AF` | `341B2284B7AF` |
| Garage TV | Decoder | `192.168.86.8` | `IPD935-341B2284B769` | `341B2284B769` |
| Living Room TV | Decoder | `192.168.86.82` | `IPD935-341B2284B7A7` | `341B2284B7A7` |

Living Room TV was directly probed, then loaded through the target Home Assistant instance as part of the final all-device validation pass.

## Confirmed Working

- Integration installs as a custom component.
- The AV Access IP integration entry can be created from the Home Assistant UI.
- Devices can be added manually by IP address.
- Add-device flow shows detected hostname, MAC address, model, and firmware.
- Friendly names entered in Home Assistant are preserved even when device alias readback returns `"alias" not defined`.
- Encoders appear in Home Assistant through an online diagnostic binary sensor.
- Decoders appear as `media_player` entities with source selection.
- Decoders expose display power switches.
- Kitchen TV display power works via CEC using configured CEC codes.
- Individual decoder source switching works for `Shield` and `Zone2`.
- Group switching works through `avaccess_ip.switch_group`.
- Target Home Assistant validation passed for device loading, individual switching, group switching, and display power.
- Samsung Frame Ex-Link through Kitchen TV decoder works after crossing RS232 TX/RX.
- Samsung Frame RS232 power on/off works through decoder `sinkpower` in RS232 mode.
- Samsung Frame Art Mode on was validated by temporarily loading Art Mode RS232 codes and calling `sinkpower on`.
- Source resolution works by friendly name, hostname, or MAC address.
- Device management supports add, edit, rename, remove, and global settings.
- Decoder setup/editing includes a Samsung The Frame over Ex-Link display profile that pre-fills the tested RS232 settings.
- Utility services are exposed for clear source, raw CEC, and reboot.
- Sequential switching uses the same Telnet command path as individual switching; broadcast-disabled group fallback remains a dedicated follow-up test.

## Useful Raw Device Observations

The devices present a login prompt and then a shell prompt in this form:

```text
IPE935-341B2284DFBC login:
/ #
```

The prompt has a space between `/` and `#`, so prompt parsing must accept both `/ #` and `/#`.

`hostname` returns the model-prefixed hostname:

```text
IPE935-341B2284DFBC
IPD935-341B2284B7AF
```

`cat /etc/version` returns model prefix and firmware:

```text
IPE935
V1.0.35
Fri, 18 Apr 2025 08:40:12 +0000
```

Some devices return this alias sentinel:

```text
"alias" not defined
```

The integration treats that as no alias.

## Switching Commands Validated

Read current decoder source:

```text
gbconfig --show --source-select
```

Switch decoder to an encoder:

```text
gbconfig --source-select=341B2284DFBC
e e_reconnect
```

Clear decoder source:

```text
gbconfig --source-select=NULL
e e_reconnect
```

Display power:

```text
sinkpower on
sinkpower off
```

Raw CEC command:

```text
cec -s "40 04"
```

Reboot device:

```text
reboot
```

## Samsung Frame RS232 Ex-Link Notes

Tested decoder: Kitchen TV, `192.168.86.2`, hostname `IPD935-341B2284B7AF`.

Wiring that worked:

```text
AV Access TX -> Samsung RX
AV Access RX -> Samsung TX
GND -> GND
```

Decoder RS232/sinkpower setup that worked:

```text
gbparam s sinkpower_mode rs232
gbconfig --rs232-enable=y
gbconfig --rs232-param=9600-8n1
gbconfig --rs232-hex-cmd-enable=y
gbconfig --sinkpower-rs232=y
```

Samsung Frame Ex-Link commands tested:

```text
Power On:  08 22 00 00 00 02 D4
Power Off: 08 22 00 00 00 01 D5
Art On:    08 22 0B 0B 0E 01 B1
Art Off:   08 22 0B 0B 0E 00 B2
```

The decoder firmware did not expose an obvious raw RS232 send command. The working path is to store the desired RS232 hex command in the decoder's `rs232_poweron_cmd` or `rs232_standby_cmd` slot and trigger it with `sinkpower on` or `sinkpower off`.

## Group Switching Example

Home Assistant action data:

```yaml
target:
  - media_player.kitchen_tv
  - media_player.garage_tv
source: Shield
```

The broadcast fast path sends:

```text
msg_b_reconnect <tx_hostname>:<session>:<rx_count> <rx_hostname> <rx_hostname>
```

If broadcast is unavailable, the integration falls back to sequential Telnet switching.

## Current Limitations

- Source state is poll-based; changes made outside Home Assistant are not instant.
- Display power is assumed state; the API does not expose confirmed display power readback.
- Stable IPs are strongly recommended. Device IPs can be edited from the integration's Configure menu.
- Entity registry cleanup may be needed after early development builds that created stale entities.
- Integration tile icon behavior depends on Home Assistant brand image support and frontend caching.

## Next Validation Items

- Test behavior after AV Access device reboot.
- Test switching after Home Assistant restart without reloading the integration.
- Test disabled broadcast mode to verify sequential group-switch fallback.
- Confirm Samsung Frame Art Off behavior from Home Assistant service path.
