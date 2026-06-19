# Home Assistant Integration Plan — AV Access HDIP100 / 4KIP200 Series

**Target devices:** HDIP100E/D (2K), 4KIP200E/D, 4KIP204E, 4KIP200M (MRX)
**Scope (this plan):** Matrix switching (TX↔RX routing) and display power/control
**Distribution:** HACS custom integration (`custom_components/avaccess_ip`)
**Source of truth:** AV Access *API Command Guide — HDIP100/4KIP200 Series, V1.0.3*

**Current validation snapshot:** the first hardware-tested revision validates manual device setup, friendly naming, hostname/MAC parsing, decoder source switching, group switching, encoder/decoder online diagnostics, and decoder display power against 4KIP200-series devices. See [`TEST-NOTES.md`](TEST-NOTES.md) for tested hardware and raw device observations.

---

## 1. What these devices are

The product line is an AV-over-IP system built around encoders (TX) and decoders (RX) connected over a Gigabit switch. Each device is named by model + 12-digit MAC (the *hostname*, e.g. `IPE935-341B22822FEF`), and the MAC is used as the device ID in routing commands. There is no central controller appliance — the "client app" (our integration) discovers devices and talks to each one directly.

Importantly, the system uses **no multicast** — TX/RX pairing rides on unicast plus UDP broadcast, so the only switch requirement is that broadcast traffic is allowed. This matters for HA deployment: the HA host must sit on the same L2 subnet as the devices for discovery and simultaneous-switch broadcasts to work.

For our two chosen use cases the relevant capabilities are:

- **Matrix switching** — assign any TX as the source of any RX (`gbconfig --source-select` / `--vsource-select` / `--asource-select` / `--ssource-select`, committed with `e e_reconnect`), with a broadcast fast-path for switching many RXs to one source at once.
- **Display power/control** — drive the display attached to an RX on/off via CEC or RS232 (`sinkpower on|off`, configured by `--sinkpower-mode`, `cec_*_cmd`, `rs232_*_cmd`), plus raw CEC passthrough.

## 2. Control surfaces and the transport layer

The API spans four distinct transports. The integration needs a transport abstraction that hides this from the entity layer.

**UDP broadcast discovery.** Send a tiny 8-byte probe (`device_type` UInt32 = 0, `device_function` UInt32 = 0) to `255.255.255.255:3335` (or the subnet broadcast). Devices reply to local UDP port **3336** with a fixed-layout binary record; we parse the 64-byte `Device_name` (the hostname) and read the sender's IP from the UDP packet. The source IP is *not* in the payload — it comes from the datagram envelope, so the listener must capture peer address. The guide recommends polling on a timer to catch devices coming and going.

**Telnet control (port 24).** After discovery yields an IP, we open a Telnet session, log in as `root`, and wait for the `/#` prompt to confirm. All stateful control and queries are shell commands over this session: `gbparam` (key-value get/set), `gbconfig` (device config flags), `e` (effect/commit commands like `e_reconnect`), `sinkpower`, `cec`, `multiview`, etc. This is the workhorse channel for our scope.

**UDP broadcast control (port 5010).** A fire-and-forget fast path to switch many RXs to one TX simultaneously: `msg_b_reconnect tx_name:session_number:rx_number rx1 rx2 … rxN` to `…:5010`. The `session_number` is a monotonically increasing integer we must track per switching event. This is the right primitive for "send all displays to source X" and avoids N sequential Telnet round-trips.

**UDP broadcast notifications (port 11002).** MRX devices announce layout changes here. Out of scope for matrix/power but worth listening-architecture awareness so we don't design it out.

**HTTP.** Preview MJPEG stream (`http://tx_ip/stream`), idle-image upload, PNG overlay upload, firmware upload. Out of scope for the initial plan except possibly the preview stream as a camera entity (noted as a stretch goal).

### 2.1 Transport design decision

Telnet is the integration's main dependency and its biggest fragility. Recommended approach: a single async transport client per device that **opens a Telnet session on demand, runs a command, reads until the `/#` prompt, and returns the response**, with a short-lived connection pool / keepalive rather than one socket held open forever (these embedded devices have limited session capacity and can drop idle sockets). Use `asyncio.open_connection` with hand-rolled prompt-reading rather than a heavyweight Telnet library, since the "protocol" is really just line I/O against a shell prompt. All command strings get built in one place so the quirky commit pattern (`e e_reconnect` after a select) is never forgotten.

A critical correctness rule from the guide: **most `gbparam s …` settings only take effect after a reboot**, while routing changes take effect after `e e_reconnect`. The transport/command layer must encode which commands are "live" vs "needs reconnect" vs "needs reboot" so the entity layer and the user aren't surprised.

## 3. Home Assistant architecture

### 3.1 Component layout

```
custom_components/avaccess_ip/
  __init__.py          # setup/unload, create coordinator + transport
  manifest.json        # domain, deps, iot_class=local_polling, ssdp/dhcp? (no — use integration discovery)
  config_flow.py       # discovery + manual host entry; options flow for poll interval
  const.py             # DOMAIN, ports (3335/3336/5010), defaults, prompt token "/#"
  coordinator.py       # DataUpdateCoordinator: discovery + per-RX source/state polling
  transport.py         # async Telnet client + UDP discovery/broadcast helpers
  device.py            # TX/RX/MRX model objects, command builders, capability flags
  media_player.py      # RX as media_player (source selection = matrix routing)
  switch.py            # RX display power (sinkpower on/off)
  select.py            # optional: explicit source select entity if media_player feels wrong
  diagnostics.py       # redacted dump for bug reports
  strings.json / translations/en.json
```

### 3.2 Entity model — the key design choice

The most natural HA mapping for AV-over-IP matrix switching is:

**Each RX (decoder) → one `media_player` entity.** The `source_list` is the set of discovered TX hostnames (shown by friendly alias where set), and `select_source` issues the routing command. This gives users the standard HA "pick a source for this output" UX, works in dashboards and voice assistants, and matches how people think about a matrix ("what is display 3 watching?"). Current source is read back via `gbconfig --show --vsource-select`.

**Each RX also → one `switch` entity for display power** (`sinkpower on`/`off`). Alternatively this can be surfaced as the media_player's on/off, but a dedicated switch is cleaner because RX power and display power are conceptually distinct, and the media_player's "off" state is ambiguous (no source vs display off). The power *method* and codes behind this switch are configured **per decoder** — see §3.6.

**Each TX (encoder) → a device** in the HA device registry (so sources have friendly names, firmware, IP as device info) but with few or no controllable entities in this scope — perhaps a diagnostic sensor for online/offline and firmware version. TXs become the *options* in every RX's source list rather than entities with their own controls.

This TX-as-source / RX-as-output model is the core of the design. **Decision: each RX is a `media_player`** (settled 2026-06-10) for the polished dashboard card and native voice/assistant source selection. We expose a deliberately narrow `supported_features` set — `SELECT_SOURCE` plus on/off only — so no fake volume/transport controls appear. Because media_player carries a single "source" concept, routing uses the **bonded** `gbconfig --source-select=MAC` (audio and RS232 follow video) rather than independent video/audio/RS232 breakaway. Independent A/V routing is therefore intentionally out of scope for this entity; if breakaway is ever needed it would be added as separate `select` entities later, reusing the same transport and command builders.

State mapping: media_player state reflects routing/power — `playing` when a source is assigned and the display is on, `idle`/`off` when no source is bound, with display power surfaced primarily through the dedicated `switch` (below) to avoid overloading media_player on/off semantics.

### 3.3 Friendly naming

Devices support an alias stored via `gbparam s alias …` / read via `gbparam g alias`. The integration should read aliases at discovery and use them as the default HA friendly name (falling back to hostname), and optionally expose a service or just respect HA's own rename. We should *not* write aliases back without user intent, since that mutates device state.

### 3.3a Per-decoder and group switching (both supported)

Both switching modes coexist; they are not exclusive. *(Settled 2026-06-10.)*

- **Per-decoder switching** is the everyday path: `media_player.select_source` on a single decoder issues `gbconfig --source-select=MAC` + `e e_reconnect` to that one device. Always available, works regardless of where HA runs.
- **Group switching** is an additional capability exposed as a Home Assistant **service** (e.g. `avaccess_ip.switch_group`) taking a list of decoder entities/targets plus one source. When HA shares the device subnet it sends the single UDP broadcast `msg_b_reconnect tx:session:count rx1 rx2 …` to `…:5010`, flipping all listed decoders together in one shot (ideal for "show this everywhere" / video-wall feeds). The integration maintains the incrementing `session_number`.
- **Graceful fallback:** if the broadcast path is unavailable (HA not on the device subnet), the same service transparently falls back to issuing `--source-select` + `e e_reconnect` to each decoder sequentially — same result, slightly slower, no UX change.

### 3.6 Per-decoder display power configuration (selectable per device)

Display power method and codes are stored on each decoder individually (the hardware keeps these as per-device parameters), because each decoder may drive a different display speaking a different protocol. *(Settled 2026-06-10.)* So this is configured **per decoder**, not globally:

- **Power method** (`gbconfig --sinkpower-mode`): selectable per decoder as **cec | rs232 | both** (default cec).
- **CEC codes** (`gbparam s cec_poweron_cmd` / `cec_standby_cmd`): default to the guide's `40 04` (on) / `ff 36` (off); a CEC display often needs no input.
- **RS232 codes** (`gbconfig --rs232-hex-cmd-enable y|n`, `gbparam s rs232_poweron_cmd` / `rs232_standby_cmd`): display-specific, entered by the user when rs232/both is selected; includes the hex-vs-ASCII toggle.

UX: these fields appear in the decoder's options/config step (alongside its IP), shown conditionally based on the selected method (CEC fields when cec/both, RS232 fields when rs232/both). The resulting `switch` then just calls `sinkpower on|off`, and the device converts to the configured protocol. Note any of these `gbparam`/`gbconfig` settings that require a reboot to take effect must be flagged to the user per the commit-semantics rule.

### 3.4 Config flow — manual per-device adding (chosen approach)

The setup model is **manual device addition by IP**, not broadcast auto-discovery. This is a deliberate decision: by entering each device's IP, the integration no longer depends on UDP broadcast to *find* devices, which means the HA host can live anywhere on the network (Docker bridge networking, a separate VLAN, etc.) and still control devices over Telnet/HTTP. Broadcast is then used only for the optional group-switch fast path (port 5010), which remains a same-subnet feature.

**Structure: a single integration ("hub") entry that you add devices into, one at a time.** A matrix inherently couples encoders and decoders — every decoder's source list *is* the set of encoders — so the devices cannot be independent config entries without awkward cross-entry plumbing. One umbrella entry sharing a single coordinator and transport is the right HA pattern here, and it keeps "every RX automatically sees all TXs as sources" trivially true.

Flow:

1. **Initial setup** — create the single "AV Access" hub entry (no IP required at this step; it's the container). 
2. **Add device step** (repeatable, via the options flow / "Configure" → "Add device"):
   - Choose **device type**: Encoder (TX) or Decoder (RX).
   - Enter the device's **IP address** (the per-device input variable you specified).
   - The integration Telnets to the IP on port 24, confirms the `/#` prompt, and reads back hostname/MAC (`/etc/version`, `gbparam g alias`, etc.) to **verify and auto-classify** the device — surfacing model and firmware so the user can confirm it matches the type they picked. The MAC becomes the stable internal identifier even though the IP is how we reach it.
   - On success, the device is registered in the HA device registry and its entities are created (media_player/switch for RX; source + diagnostics for TX).
3. **Edit device** — update a device's IP, friendly name, and decoder display-power settings; reconnects to refresh hostname, MAC, model, and firmware.
4. **Rename device** — quick options-flow action to update only the friendly name.
5. **Remove device** — options-flow action to drop a device by its entry in the list.
6. **Options** — poll interval, enable/disable the 5010 broadcast group-switch path, optional credentials placeholder for future authenticated firmware.

**Stable-IP requirement.** Because devices are addressed by manually-entered IP, each device needs a **static IP or a DHCP reservation**. A device on autoip (`169.254.x.x`) or an unreserved DHCP lease can change address on reboot and would render its entry stale until the user edits the IP. The docs and the add-device step should call this out, and the coordinator should mark a device "unavailable" (not error-spam) when its IP stops responding.

**Optional discovery assist (non-blocking, future).** Broadcast discovery (3335/3336) is *not* required for this model, but could later be offered as a convenience that pre-fills the IP field in the add-device step. It is explicitly not a dependency of setup. There is no SSDP/mDNS for these devices, so HA's native manifest discovery hooks don't apply.

### 3.5 Coordinator & polling

A single `DataUpdateCoordinator` works over the **manually-added device list** (no discovery-driven membership). Each cycle it (a) probes each device's IP for reachability and marks it available/unavailable, and (b) for each RX reads its current assigned video source so the media_player state reflects reality even when changed by front-panel button or another controller. Telnet polling of every RX on a tight interval is expensive, so default to a modest interval (e.g. 30s) and make it configurable; consider only polling source state, not full config, on each cycle.

State-change responsiveness: there is no push channel for RX routing (unlike MRX's 11002 notifications), so source readback is poll-only. Document this latency. After an HA-initiated switch we optimistically update state immediately and confirm on next poll.

## 4. Command mapping reference (in-scope features)

| HA action | Device command(s) | Notes |
|---|---|---|
| Discover devices | UDP 8-byte probe → `255.255.255.255:3335`; listen `:3336` | Parse 64-byte hostname; IP from packet envelope |
| Login / health | `telnet ip 24` → expect `/#` | Confirms reachability |
| Read firmware | `cat /etc/version` | Device info |
| Read/set alias | `gbparam g alias` / `gbparam s alias XXXX` | Friendly name default |
| **Route source to RX (primary)** | `gbconfig --source-select=MAC` then `e e_reconnect` | Bonded A/V/RS232; used by `select_source`. MAC = TX MAC, no `IPExxx-` prefix |
| Route video only (future breakaway) | `gbconfig --vsource-select=MAC` then `e e_reconnect` | Out of scope for media_player; reserved for optional select entities |
| Unbind source | `gbconfig --source-select=NULL` then `e e_reconnect` | media_player "no source" |
| Read current source | `gbconfig --show --vsource-select` (or `--source-select`) | Returns TX MAC; map back to entity |
| **Switch many RXs at once** | UDP `msg_b_reconnect tx:session:count rx1 rx2 …` → `…:5010` | Track incrementing session_number |
| **Display power on/off** | `sinkpower on` / `sinkpower off` | Converts to CEC/RS232 per config |
| Set power mode | `gbconfig --sinkpower-mode cec|rs232|both` | Default cec |
| Configure CEC on/off codes | `gbparam s cec_poweron_cmd "40 04"` / `cec_standby_cmd "ff 36"` | Display-specific |
| Configure RS232 on/off codes | `gbconfig --rs232-hex-cmd-enable y|n`; `gbparam s rs232_poweron_cmd …` | Display-specific |
| Send raw CEC | `cec -s "ADDR OPCODE; …"` | Advanced service |
| Reboot | `reboot` | Service / needed after some sets |
| Factory reset | `reset_to_default.sh;reboot` | Dangerous service, confirm |

Out-of-scope commands intentionally deferred: video wall (`e e_vw_enable_*`, `e e_vw_rotate_*`, `gbparam s xy_param`), MRX multiview (`multiview …`, 11002 notifications), forced resolution/colorspace, OSD overlay, idle/PNG image upload, preview stream, firmware upload. These are catalogued so the architecture leaves room for them.

## 5. Risks, unknowns, and things to validate on real hardware

- **Telnet robustness.** Embedded Telnet is the weakest link: prompt detection, login timing, dropped idle sockets, limited concurrent sessions, and possible per-device serialization needs. Plan for retries, a per-device command lock (no concurrent Telnet to the same device), and graceful degradation when a device is offline. *Validate session limits empirically.*
- **No authentication shown.** Login is `root` with an apparently empty/auto password. If future firmware adds auth, the config flow must accommodate it; for now treat as open and document the security implication (anyone on the LAN can control these — keep them on a trusted/VLAN segment).
- **Commit semantics.** `e e_reconnect` for routing, reboot for many `gbparam` settings. Getting this wrong causes "command silently didn't apply." Encode per-command commit requirements centrally and reflect "reboot required" to the user.
- **`gbparam g` may not reflect the live value** (guide explicitly warns the read value isn't necessarily what's currently effective, e.g. after factory reset). Treat readback as best-effort, not ground truth; prefer the dedicated `--show --vsource-select` for routing state.
- **Subnet/broadcast dependency (reduced by manual-IP model).** Per-device control no longer needs broadcast — devices are reached by their manually-entered IP, so HA can run in Docker/containers or across VLANs. Only the optional group-switch fast path (5010) still requires L2 broadcast reach; when HA isn't on the device subnet, group switching falls back to sequential per-RX Telnet commands. Document clearly.
- **Stable addressing.** Because devices are addressed by manually-entered IP, each needs a static IP or DHCP reservation; an autoip/unreserved device can change address on reboot and require an IP edit. Mark unreachable devices unavailable rather than erroring.
- **Hostname vs MAC.** Routing commands take the bare MAC; discovery and multiview use the full hostname. The command builders must convert consistently. Note the guide even contains a typo (`IPE35-…` / `IPE935-…`) — be lenient when parsing.
- **Mixed 2K/4K capabilities.** Some features (resolutions, video wall) are model-gated. The device model layer should carry capability flags keyed off the model prefix so we never send unsupported commands.
- **Polling cost & responsiveness.** No push for RX routing means poll-only state with inherent latency; balance interval against Telnet load.

## 6. Phased roadmap

**Phase 0 — Foundations.** Repo scaffold, `manifest.json` (`iot_class: local_polling`), `const.py`, transport skeleton (async Telnet client with prompt reader + optional UDP broadcast helper for the 5010 path), unit tests against a mock Telnet server. Deliverable: given an IP, the transport can log in, read back hostname/MAC/model/firmware/alias, and run a command.

**Phase 1 — Config flow + device registry (manual per-device adding).** Single "AV Access" hub entry; options-flow "Add device" step that takes device type (encoder/decoder) + IP, then Telnets in to verify and auto-classify, registering each device with proper `DeviceInfo` (model, sw_version, connections=MAC). Add/remove/edit-IP actions. Diagnostics dump. Deliverable: integration installs via HACS and you can add encoders and decoders by IP, each appearing as a device, no controls yet.

**Phase 2 — Matrix switching (core).** Coordinator polling of RX source state; `media_player` entity per RX with `source_list` of TXs and `select_source` (bonded `--source-select`); optimistic update + poll confirm. Plus the `avaccess_ip.switch_group` service for simultaneous multi-decoder switching via the 5010 broadcast, with sequential fallback when off-subnet. Deliverable: route any source to any display individually, and switch a group of displays to one source at once.

**Phase 3 — Display power/control (per decoder).** `switch` per RX for `sinkpower`; per-decoder config of sinkpower-mode (cec|rs232|both) and the CEC/RS232 on/off codes, surfaced conditionally in the decoder's config step (with reboot handling where needed); advanced `send_cec` service. Deliverable: turn each attached display on/off using that decoder's own configured method.

**Phase 4 — Polish & robustness.** Reconnect/retry hardening, per-device locks, online/offline availability, reboot/factory-reset services with confirmation, translations, README + HACS metadata, docs on subnet requirements. Deliverable: HACS-publishable release.

**Stretch / future phases (out of current scope, architecture-ready):** TX preview as `camera` (MJPEG), video wall config, MRX multiview with 11002 push notifications, forced resolution/colorspace, OSD/PNG overlay, idle-image and firmware upload.

## 7. Decisions & open questions

**Decided:**

- **Setup model** — manual per-device adding. A single "AV Access" hub entry; devices (encoders/decoders) added one at a time by choosing type and entering an IP, verified over Telnet. Removes broadcast dependency for device control; requires stable IPs. *(Settled 2026-06-10.)*
- **Entity type** — each RX is a `media_player` with a narrow feature set (source-select + on/off), routing via bonded `--source-select` (audio/RS232 follow video). Independent A/V breakaway deferred. *(Settled 2026-06-10.)*
- **Switching modes** — both per-decoder (`select_source`) and group switching (`switch_group` service via 5010 broadcast, sequential fallback off-subnet) are supported day one. *(Settled 2026-06-10.)*
- **Display power** — configured per decoder: selectable method (cec|rs232|both) and per-display on/off codes live on each decoder's config step. *(Settled 2026-06-10.)*

**Still open:**

1. **Device count** — roughly how many encoders/decoders, so polling cadence is sized appropriately (minor, given manual adding).
2. **Your displays' codes** — when we reach Phase 3, you'll want the CEC and/or RS232 on/off codes for the specific screens in the lab (CEC defaults `40 04`/`ff 36` often work; RS232 is always display-specific).
