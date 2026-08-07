# zha_namehook

`zha_namehook` 是一个 Home Assistant 自定义组件，用来把 HA 实体名称同步到屏显开关的设备端显示名称。

当前版本：`2.1.1`

## 支持内容

- ZHA Tuya / Zemismart 1-4 路屏显开关名称同步。
- 在 HA 里修改实体名称后，自动写入设备屏幕名称。
- 提供手动同步服务，适合自动同步未触发时补写。
- ZHA 屏显开关实体显示为 `light` 或 `switch` 都可以使用。
- 可选支持 Matter 设备的 User Label 写入；设备和 Matter Server 必须支持对应能力。

## ZHA Tuya 通道映射

ZHA Tuya 屏显开关使用以下名称 DP：

| 通道 | Tuya DP |
| --- | --- |
| 1 路 | DP105 |
| 2 路 | DP106 |
| 3 路 | DP107 |
| 4 路 | DP108 |

## 安装方法

把本目录复制到 HA 配置目录：

```text
/config/custom_components/zha_namehook
```

最终应该能看到：

```text
/config/custom_components/zha_namehook/manifest.json
```

然后在 `/config/configuration.yaml` 增加：

```yaml
zha_namehook:
```

保存后重启 Home Assistant。

重启后日志里应能看到类似内容：

```text
Initializing zha_namehook v2.1.1
zha_namehook ready
```

Home Assistant 会提示自定义集成未经官方测试，这是自定义组件的正常提示，不代表安装失败。

## 最简单用法

1. 打开 HA 的 ZHA 设备页面或实体页面。
2. 找到屏显开关某一路实体。
3. 修改实体名称。
4. 保存后等待几秒，开关屏幕名称会自动同步。

注意：部分屏显开关在 HA 里显示成 `light` 实体，而不是 `switch` 实体，这是正常现象。

## 手动同步服务

如果改名后没有自动同步，可以在 HA 的“开发者工具 -> 动作”里调用：

```text
zha_namehook.sync_entity_name
```

最常用参数：

```yaml
entity_id: light.example_switch_light_4
```

一般不需要填写 `channel` 和 `name`，组件会自动读取当前实体显示名称并推断通道。

如果自动推断通道不正确，可以手动指定：

```yaml
entity_id: light.example_switch_light_4
channel: 4
name: 客厅灯
```

## 直接写 ZHA Tuya 某一路名称

如果已知 ZHA 设备 IEEE，可以直接调用：

```text
zha_namehook.set_display_name
```

示例：

```yaml
ieee: a4:c1:38:94:3a:9b:31:f5
channel: 4
name: 客厅灯
```

这个服务只用于 ZHA Tuya 屏显开关。

## 可选配置

默认情况下不需要额外配置。只有当实体 ID 无法正确推断通道时，才需要手动指定：

```yaml
zha_namehook:
  entity_channels:
    light.example_switch_light: 1
    light.example_switch_light_2: 2
    light.example_switch_light_3: 3
    light.example_switch_light_4: 4
```

少数机型的屏显名称 DP 不遵循默认的 `DP105-DP108` 顺序时，可按实体覆盖名称 DP。例如 ZMD-206 三路调光开关使用 `DP106-DP108`：

```yaml
zha_namehook:
  entity_channels:
    light.example_zmd206_light: 1
    light.example_zmd206_light_2: 2
    light.example_zmd206_light_3: 3
  entity_name_dps:
    light.example_zmd206_light: 106
    light.example_zmd206_light_2: 107
    light.example_zmd206_light_3: 108
```

`entity_name_dps` 的值为 Tuya DP ID，范围为 `1-255`；未配置时继续使用默认通道映射。

如需 HA 启动后自动同步指定 ZHA 设备的实体名称，可以配置：

```yaml
zha_namehook:
  startup_sync_ieees:
    - a4:c1:38:94:3a:9b:31:f5
  startup_sync_delay: 12
```

## Matter 说明

`sync_entity_name` 会在检测到 Matter 设备时尝试写入 Matter User Label。

注意：

- HA 必须已配置 Matter。
- Matter Server 需要能通过 `core-matter-server:5580` 访问。
- 设备端点必须支持 User Label cluster。
- 如果设备不支持 User Label，日志会提示写入失败。

## 常见问题

### 实体是 light，不是 switch，能用吗？

可以。`zha_namehook` 的服务选择器支持 `light` 和 `switch`。

### 日志里看到 No datapoint handler for DP105/106/107/108，是失败吗？

通常不是失败。这个日志表示设备已经对名称 DP 回包，但当前 ZHA quirk 没有专门处理这个回包。`zmd206_screen_dimmer.py` 已缓存其 DP106-DP108 回报，不会出现该提示。

### 改名后屏幕没有变化怎么办？

先用 `zha_namehook.sync_entity_name` 手动同步一次。如果仍然失败，检查：

- 设备是否是 ZHA 或支持 User Label 的 Matter 设备。
- 实体是否属于同一个设备。
- 通道是否需要通过 `entity_channels` 手动指定。
- HA 日志中是否有 `zha_namehook` warning。

## 卸载方法

删除：

```text
/config/custom_components/zha_namehook
```

并从 `configuration.yaml` 删除：

```yaml
zha_namehook:
```

然后重启 Home Assistant。
