# zemismart-zha-quirks

用于存储 Zemismart 公司产品相关的 ZHA custom quirk 配置文件。

| 配置文件 | ZHA 匹配型号 | 指纹型号 / manufacturerName | 说明 |
| --- | --- | --- | --- |
| `214c.py` | `TS0601` | `_TZE284_vuwtqx0t` | 214C 超声波水表阀，支持累计用水、阀门开关、自动清洗、瞬时流量、温度和电压 |
| `223f.py` | `TS0601` | `_TZE200_jt50ea5d` | DN15-223F 超声波热/冷表，支持 DP7 热量计量开关、DP8 累计热量、水量、温度、电压、表号和周期上报 |
| `zemismart_rzdkn5rx_zha.py` | `TS0601` | `_TZE284_rzdkn5rx` | ZN2S-US01U-ZK 单路开关，支持继电器、倒计时、指示灯模式、背光、上电状态、童锁、背光亮度及开/关颜色；未知 DP 仅只读诊断 |
| `zemismart_zn2s_rs3e_dh_zha.py` | `TS0601` | `_TZE204_znvwzxkq` | 三路调光器（商品 SKU 待确认），支持独立开关/亮度、三路亮度上下限、前两路倒计时、上电状态、背光模式/颜色/亮度/开关及童锁；不开放灯类型与第三路倒计时 |
| `ZMP1.py` | `TS0601` | `_TZE284_6hrnp30w` | ZMP1 链条窗帘/卷帘电机，支持位置、电量自动刷新、方向、限位动作和点动 |
| `ZMS-206.py` | `TS0601` | `_TZE284_lnyz4a6v`, `_TZE284_1tnysxwl` | 1 路屏显开关 |
| `ZMS-206.py` | `TS0601` | `_TZE284_dmckrsxg`, `_TZE284_a2teqi5u`, `_TZE28C1000000_a2teqi5u`, `_TZE204_3ctwoaip` | 2 路屏显开关 |
| `ZMS-206.py` | `TS0601` | `_TZE284_e4pf6l87`, `_TZE284_xvywzhmi` | 3 路屏显开关 |
| `ZMS-206.py` | `TS0601` | `_TZE284_y4jqpry8`, `_TZE28C1000000_y4jqpry8`, `by _TZE28C1000000_y4jqpry8`, `_TZE284_xibaabmu`, `_TZE28C1000000_xibaabmu` | 4 路屏显开关；兼容客户提供的含 `by ` 前缀字符串 |
| `ZN2S-L01E-SMB.py` | `TS0601` | `_TZE200_ephrk8to`, `_TZE200_ahyyfhqk`, `_TZE200_zuphzsmo`, `_TZE200_6si1pnia` | Zemismart 1/2/3/4 路场景开关，支持开关模式和场景模式切换 |
| `kes-606-复合开关.py` | `TS0726` | `_TZ3000_ovbvmhiq`, `_TZ3000_icoxotza`, `_TZ3000_cziew6eu`, `_TZ3000_hurauima` | KES 606 复合场景开关 1/2/3/4 路，支持 ZHA 开关、开关模式、上电状态和场景事件 |
| `pm07db_tyz.py` | `TS0601` | `_TZE2841000000_zm8zpwas` | PF-PM07D 电池版 Zigbee 水阀，支持阀门开关、电量和故障码；DP7/DP8 仅内部解析，不创建 HA 实体 |
| `ts0301_cirjrpxe_zm25z.py` | `TS0301` | `_TZE200_cirjrpxe` | ZM25Z 强电窗帘电机，支持位置、方向和限位动作 |
| `zemismart_zps_z1.py` | `TS0601` | `_TZE284_ft7qqpx3` | ZPS-Z1 24 GHz 毫米波存在传感器，支持占用、照度、检测距离、灵敏度、区域开关、能量阈值和自动校准 |
| `zmd206_screen_dimmer.py` | `TS0601` | 1 路: `_TZE28C1000000_5aico93l`, `_TZE284_5aico93l`<br>2 路: `_TZE284_pyh4zt7w`<br>3 路: `_TZE28C1000000_k9e7ihec`, `_TZE284_k9e7ihec` | ZMD-206 屏显调光开关，支持每路开关/亮度、亮度上下限、负载类型、倒计时、上电行为、背光、指示灯、童锁、渐变速度和屏显名称回报 |
| `zemismart_zmr4.py` | `TS0044` | `_TZ3000_xwuveizv` | ZMR4 四键无线遥控器，支持每键单击、双击、长按事件、动作实体、12 个本地模拟按钮及共享电量 |
| `zm90e_td_250n.py` | `TS0601` | `_TZE284_fzo2pocs` | ZM90E-TD-250N 推窗器，支持开/停/关、目标位置与到达位置、电机运行方向切换、开/中/关限位设置与复位、运行模式 |
| `zmz609.py` | `TS0601` | 2 路: `_TZE284_o409r73p`, `_TZE28C1000000_o409r73p`<br>3 路: `_TZE284_oy1nuaa5` | ZMZ609 美标屏显开关，支持两路/三路开关、计量、屏显和配置项 |

## ZHA quirk 安装说明

将需要的 quirk 文件复制到 Home Assistant 的 `/config/zha_quirks/` 目录，并在 `configuration.yaml` 中启用：

```yaml
zha:
  enable_quirks: true
  custom_quirks_path: /config/zha_quirks
```

复制后重启 Home Assistant。如果当前 HA 版本不能加载数字开头、带横杠或中文的 Python 文件名，请将 `214c.py` 改名为 `water_valve_214c.py`，或将 `kes-606-复合开关.py` 改名为 `kes_606_composite_switch.py`，文件内容无需修改。

## 两款新增 TS0601 配置的验证范围

`zemismart_rzdkn5rx_zha.py` 与 `zemismart_zn2s_rs3e_dh_zha.py` 均为独立 Quirk v2 文件，只匹配表中完整指纹，不依赖其他自定义文件。2026-09-28 已在 Home Assistant 2026.8.0、ZHA 2.1.0、zigpy 2.1.0、zha-quirks 2.2.0 环境验证加载、实体生成及设备协议收发；不据此承诺更旧版本兼容。实际灯光/指示灯颜色、本地按键童锁及断电恢复仍待现场确认。

三路文件名沿用上游同指纹别名 ZN2S-RS3E-DH；实机商品 SKU 尚未确认，界面使用 `TS0601 3-gang dimmer`，不要将其视为 ZN-USC1U-HT 窗帘开关。DP4/10 有重复和未定义值回报，仅保留原始诊断并拒绝写入；DP18/20/102/105 尚未开放，第三路倒计时不受支持。前两路短倒计时已收到自动关闭回报，但第一路的自动归零独立回报尚未证实。

单路 DP19/209/210 仅保留原始诊断并拒绝写入，DP105 名称写入未开放。以上限制与正常支持的功能分别记录，不声明物理全功能验收通过。

## 屏显名称同步

屏显名称同步功能已迁移到独立的 Home Assistant 自定义集成
[Screen Switch Name Hook](https://github.com/zemismart-dev/screen-switch-name-hook)。
本仓库只维护 ZHA quirk；屏显名称同步集成不随本仓库发布。
