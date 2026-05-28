# zemismart-zha-quirks

用于存储 Zemismart 公司产品相关的 ZHA custom quirk 配置文件。

| 配置文件 | ZHA 匹配型号 | 指纹型号 / manufacturerName | 说明 |
| --- | --- | --- | --- |
| `223f.py` | `TS0601` | `_TZE200_jt50ea5d` | DN15-223F 超声波热量表，支持热量、水量、温度、电压等传感器 |
| `DN15-223F.py` | `TS0601` | `_TZE200_jt50ea5d` | DN15-223F 超声波热量表 quirk |
| `ZMP1.py` | `TS0601` | `_TZE284_6hrnp30w` | ZMP1 链条窗帘/卷帘电机，支持位置、电量自动刷新、方向、点动和运行状态 |
| `ZMS-206.py` | `TS0601` | `_TZE284_lnyz4a6v`, `_TZE284_1tnysxwl` | 1 路屏显开关 |
| `ZMS-206.py` | `TS0601` | `_TZE284_dmckrsxg`, `_TZE284_a2teqi5u`, `_TZE28C1000000_a2teqi5u`, `_TZE204_3ctwoaip` | 2 路屏显开关 |
| `ZMS-206.py` | `TS0601` | `_TZE284_e4pf6l87`, `_TZE284_xvywzhmi` | 3 路屏显开关 |
| `ZMS-206.py` | `TS0601` | `_TZE284_y4jqpry8`, `_TZE284_xibaabmu`, `_TZE28C1000000_xibaabmu` | 4 路屏显开关 |
| `ZN2S-L01E-SMB.py` | `TS0601` | `_TZE200_ephrk8to`, `_TZE200_ahyyfhqk`, `_TZE200_zuphzsmo`, `_TZE200_6si1pnia` | Zemismart 1/2/3/4 路场景开关，支持开关模式和场景模式切换 |
| `kes-606-复合开关.py` | `TS0726` | `_TZ3000_ovbvmhiq`, `_TZ3000_icoxotza`, `_TZ3000_cziew6eu`, `_TZ3000_hurauima` | KES 606 复合场景开关 1/2/3/4 路，支持 ZHA 开关、开关模式、上电状态和场景事件 |
| `ts0301_cirjrpxe_zm25z.py` | `TS0301` | `_TZE200_cirjrpxe` | ZM25Z 强电窗帘电机，支持位置、方向和限位动作 |
| `zm609.py` | `TS0601` | `_TZE284_o409r73p`, `_TZE28C1000000_o409r73p` | ZM609 两路美标屏显开关，支持开关、计量、屏显和配置项 |

## 安装说明

将需要的 quirk 文件复制到 Home Assistant 的 `/config/zha_quirks/` 目录，并在 `configuration.yaml` 中启用：

```yaml
zha:
  enable_quirks: true
  custom_quirks_path: /config/zha_quirks
```

复制后重启 Home Assistant。如果当前 HA 版本不能加载带横杠或中文的 Python 文件名，请将 `kes-606-复合开关.py` 改名为有效的 Python 模块名，例如 `kes_606_composite_switch.py`，文件内容无需修改。
