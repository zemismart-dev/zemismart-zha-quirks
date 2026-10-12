# Zemismart ZHA Custom Quirks

English | [简体中文](README.zh-CN.md)

Custom ZHA quirk files for Zemismart products in Home Assistant. Match the complete device fingerprint in the table below before choosing a file; support and validation limits vary by model.

**Zemismart website: [www.zemismart.com](https://www.zemismart.com/)**

## About Zemismart

Zemismart offers smart-home products including motorized curtains and blinds, switches, lighting, sensors, and gateways. Visit the [official website](https://www.zemismart.com/) for product information. Protocol and platform compatibility depend on the specific model; the files in this repository cover only the listed fingerprints and features.

## Device configurations

| Configuration file | ZHA model match | Fingerprint model / manufacturerName | Description |
| --- | --- | --- | --- |
| `214c.py` | `TS0601` | `_TZE284_vuwtqx0t` | 214C ultrasonic water meter valve: total water consumption, valve control, automatic cleaning, instantaneous flow, temperature, and voltage |
| `223f.py` | `TS0601` | `_TZE200_jt50ea5d` | DN15-223F ultrasonic heating/cooling meter: DP7 heat-metering switch, DP8 accumulated thermal energy, water volume, temperature, voltage, meter number, and periodic reporting |
| `ZN2S-US01U-ZK.py` | `TS0601` | `_TZE284_rzdkn5rx` | ZN2S-US01U-ZK single-gang switch: relay, countdown, indicator mode, backlight, power-on state, child lock, backlight brightness, and on/off colors; unknown DPs are read-only diagnostics |
| `ZN2S-US3U-DH-H.py` | `TS0601` | `_TZE204_znvwzxkq` | ZN2S-US3U-DH-H three-gang dimmer (named from the supplied product screenshot): independent switching/brightness, minimum/maximum brightness for all three gangs, countdowns for the first two gangs, power-on state, backlight mode/color/brightness/on/off, and child lock; light type and the third-gang countdown are not exposed |
| `ZMP1.py` | `TS0601` | `_TZE284_6hrnp30w` | ZMP1 chain curtain/roller-blind motor: position, automatic battery refresh, direction, limit-setting actions, and inching |
| `zemismart_zm16b.py` | `TS0601` | `_TZE2841000000_3mzb0sdz` | New-batch ZM16B roller-blind motor; reuses the built-in ZM16B open/stop/close, position, battery, direction, and limit mappings; the older `_TZE284_3mzb0sdz` fingerprint continues to use built-in support, and physical behavior of the new batch awaits customer validation |
| `ZMS-206.py` | `TS0601` | `_TZE284_lnyz4a6v`, `_TZE284_1tnysxwl` | Single-gang display switch |
| `ZMS-206.py` | `TS0601` | `_TZE284_dmckrsxg`, `_TZE284_a2teqi5u`, `_TZE28C1000000_a2teqi5u`, `_TZE204_3ctwoaip` | Two-gang display switch |
| `ZMS-206.py` | `TS0601` | `_TZE284_e4pf6l87`, `_TZE284_xvywzhmi` | Three-gang display switch |
| `ZMS-206.py` | `TS0601` | `_TZE284_y4jqpry8`, `_TZE28C1000000_y4jqpry8`, `by _TZE28C1000000_y4jqpry8`, `_TZE284_xibaabmu`, `_TZE28C1000000_xibaabmu` | Four-gang display switch; also accepts the customer-provided manufacturer string with the `by ` prefix |
| `ZN2S-L01E-SMB.py` | `TS0601` | `_TZE200_ephrk8to`, `_TZE200_ahyyfhqk`, `_TZE200_zuphzsmo`, `_TZE200_6si1pnia` | Zemismart 1/2/3/4-gang scene switches with switch/scene mode selection |
| `kes-606-复合开关.py` | `TS0726` | `_TZ3000_ovbvmhiq`, `_TZ3000_icoxotza`, `_TZ3000_cziew6eu`, `_TZ3000_hurauima` | KES 606 composite 1/2/3/4-gang scene switches: ZHA switching, switch mode, power-on state, and scene events |
| `pm07db_tyz.py` | `TS0601` | `_TZE2841000000_zm8zpwas` | PF-PM07D battery-powered Zigbee water valve: valve control, battery, and fault codes; DP7/DP8 are parsed internally without creating HA entities |
| `ts0301_cirjrpxe_zm25z.py` | `TS0301` | `_TZE200_cirjrpxe` | ZM25Z mains-powered curtain motor: position, direction, and limit-setting actions |
| [`zemismart_ts1201_ir_zha.py`](zemismart_ts1201_ir_zha.py) | `TS1201` | `_TZ3290_qazgdsae` | IR remote pilot version 1.3.0; brand matching, named learned buttons, and the air-conditioner panel require the companion files and integration in the [complete installation guide (Chinese)](docs/ts1201_zha_installation.md) |
| `zemismart_zps_z1.py` | `TS0601` | `_TZE284_ft7qqpx3` | ZPS-Z1 24 GHz mmWave presence sensor: occupancy, illuminance, detection distance, sensitivity, zone switches, energy thresholds, and automatic calibration |
| `zmd206_screen_dimmer.py` | `TS0601` | 1-gang: `_TZE28C1000000_5aico93l`, `_TZE284_5aico93l`<br>2-gang: `_TZE284_pyh4zt7w`<br>3-gang: `_TZE28C1000000_k9e7ihec`, `_TZE284_k9e7ihec` | ZMD-206 display dimmer: per-gang switching/brightness, brightness limits, load type, countdown, power-on behavior, backlight, indicator, child lock, fade speed, and display-name reporting |
| `zemismart_zmr4.py` | `TS0044` | `_TZ3000_xwuveizv` | ZMR4 four-button wireless remote: single/double/long-press events for each button, action entities, 12 local simulation buttons, and shared battery reporting |
| `zm90e_td_250n.py` | `TS0601` | `_TZE284_fzo2pocs` | ZM90E-TD-250N window opener: open/stop/close, target and reached positions, motor-direction switching, open/middle/closed limit setting and reset, and operating mode |
| `zmz609.py` | `TS0601` | 2-gang: `_TZE284_o409r73p`, `_TZE28C1000000_o409r73p`<br>3-gang: `_TZE284_oy1nuaa5` | ZMZ609 US-style display switch: two/three-gang switching, metering, display, and configuration options |

## Installing a ZHA quirk

Copy the required quirk file to Home Assistant's `/config/zha_quirks/` directory and enable it in `configuration.yaml`:

```yaml
zha:
  enable_quirks: true
  custom_quirks_path: /config/zha_quirks
```

Restart Home Assistant after copying the file. If your HA version cannot load Python filenames that begin with a digit or contain hyphens or Chinese characters, rename `214c.py` to `water_valve_214c.py`, or `kes-606-复合开关.py` to `kes_606_composite_switch.py`. No changes to the file contents are needed.

When replacing an existing configuration, remove the old file for the same device to avoid loading duplicate quirks.

## ZM16B new-batch fingerprint

[`zemismart_zm16b.py`](zemismart_zm16b.py) matches only `TS0601 / _TZE2841000000_3mzb0sdz` and reuses the feature mappings for ZHA's built-in older fingerprint, `_TZE284_3mzb0sdz`. The older fingerprint remains handled by built-in support. Copy this file using the installation instructions above; there is no need to change the device's manufacturer string.

The configuration has passed software regression checks for exact matching, open/stop/close, position, and battery. Actual movement, direction, limits, and persistence on the new batch have not yet been verified. The upstream fingerprint addition was submitted in [ZHA PR #5423](https://github.com/zigpy/zha-device-handlers/pull/5423); check that PR and your installed version to determine whether upstream support is included. This file is adapted from ZHA's Apache-2.0-licensed built-in definition. See [`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt) for the complete license.

## Validation scope for the two additional TS0601 configurations

`ZN2S-US01U-ZK.py` and `ZN2S-US3U-DH-H.py` are standalone Quirk v2 files that match only the complete fingerprints listed in the table and do not depend on other custom files. Loading, entity creation, and device protocol transmission/reception were verified on 2026-09-28 with Home Assistant 2026.8.0, ZHA 2.1.0, zigpy 2.1.0, and zha-quirks 2.2.0. This does not establish compatibility with older versions. Actual light/indicator colors, the physical-button child lock, and recovery after a power interruption still require on-site confirmation.

The three-gang file is named `ZN2S-US3U-DH-H.py` based on the supplied product screenshot; the upstream alias for the same fingerprint is ZN2S-RS3E-DH. Only the filename was changed: the ZHA interface still uses `TS0601 3-gang dimmer`. Identify the device by its complete fingerprint in the table. DP4/10 have duplicate and undefined reported values and are kept as raw diagnostics with writes rejected. DP18/20/102/105 are not exposed, and the third-gang countdown is unsupported. Automatic-off reports were received for short countdowns on the first two gangs, but a separate report resetting the first-gang countdown to zero has not been confirmed.

On the single-gang device, DP19/209/210 are raw diagnostics only and reject writes; DP105 name writing is not exposed. These limitations are recorded separately from supported features; complete physical acceptance of all features is not claimed.

## TS1201 IR remote pilot

Matches exactly `TS1201 / _TZ3290_qazgdsae`, not every device with the TS1201 model name.

Copying `zemismart_ts1201_ir_zha.py` alone provides basic Zosung IR transmission, reception, and learning support. For full brand/codebook matching, air-conditioner control, and named-button panels, download the complete repository and install `data/`, `custom_components/ts1201_ir/`, and the quirk according to the [TS1201 installation guide (Chinese)](docs/ts1201_zha_installation.md). The companion integration is an optional pilot extension; other devices do not depend on it.

This solution is intended for engineering deployment and limited customer pilots. The companion integration version documented here is **1.3.0**. A device status of “transmission complete” does not confirm that the appliance physically responded. See the [validation record (Chinese)](docs/ts1201_validation.md) for confirmed physical behavior and pending acceptance items, including learning and recovery after a power interruption. See the [user guide (Chinese)](docs/ts1201_customer_guide.md) for everyday operation.

## Display-name synchronization

Display-name synchronization has moved to the separate Home Assistant custom integration [Screen Switch Name Hook](https://github.com/zemismart-dev/screen-switch-name-hook).

This repository primarily contains ZHA quirks, together with the optional TS1201 pilot integration described above. The display-name synchronization integration is maintained separately and is not distributed with this repository.
