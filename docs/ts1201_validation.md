# TS1201 ZHA 1.3.0 验证范围

验证日期：2026-09-28；公司仓库发布准备：2026-09-29。精确指纹为 `TS1201 / _TZ3290_qazgdsae`。本次公司仓库收录保持已验证的 quirk、配套集成、码库与安装器内容不变。

## 软件与运行环境

- 实际 Home Assistant 测试环境：Python 3.14.6、Home Assistant 2026.8.0、zha 2.1.0、zha-quirks 2.2.0、zigpy 2.1.0。
- 164 项回归通过，0 失败、错误或跳过：106 项 ZHA/HA 测试和 58 项安装器测试。
- 覆盖逐属性 SQLite 提交中断后的按键保存、删除、撤销与恢复，以及真实子进程终止和读写失败后的安装恢复。无线请求使用替身；这些软件故障测试不等于主机突然断电或红外盒断电验收。
- 已在上述实际环境安装 1.3.0 并重启，核对 quirk 和配套集成加载、实体界面、已有实体标识与已保存码库/设置保留。1.3.0 更新未进行新的空调物理控制。

## 物理确认与待验收项

- 已有现场确认仅覆盖小米/米家 `xiaomi_smartir_2780` 的“制冷 26℃、自动风”命令：此前经 ZHA 空调实体发送后，用户观察到家电响应。
- 原遥控器学习 → 命名保存 → 按钮重发 → 家电响应的完整闭环、其他承诺模式/温度/风速以及红外盒断电恢复仍需逐项现场验收。
- 空调面板是命令估计，没有家电实际状态回传；传输完成也不是物理效果证明。
- 当前为公司自定义试点方案，代码收录不代表官方上游支持或全面客户验收完成。

## 发布文件完整性

以下文件与已验证的 1.3.0 版本逐字节一致。完整 16 个安装文件及目标路径见 [`TS1201_BUNDLE_MANIFEST.json`](../TS1201_BUNDLE_MANIFEST.json)。安装器只复制其中列出的 TS1201 文件，不安装其他设备配置。

| 文件 | SHA256 |
| --- | --- |
| [`zemismart_ts1201_ir_zha.py`](../zemismart_ts1201_ir_zha.py) | `bc6bc9499653aa36b5d506904b82302bf759a79830cf7d95b226407ab576dfe4` |
| [`data/ts1201-ir-codebooks.json`](../data/ts1201-ir-codebooks.json) | `62b0671e8c415c4ec299122ee7c5ed3a88eaa4924b8e6a595274278ca64549ea` |
| [`data/ts1201-ir-codebooks-LICENSE.txt`](../data/ts1201-ir-codebooks-LICENSE.txt) | `2910b8b82fd62732c842fe6ac5edd182823797f9304b95a2e432910e3f9828e6` |
| [`custom_components/ts1201_ir/manifest.json`](../custom_components/ts1201_ir/manifest.json) | `67ac4c7a25af7aa172a97cb97045ec9bd5a147a7c48bb2631b3df746f8a39514` |
| [`scripts/ts1201-install.py`](../scripts/ts1201-install.py) | `0534e477186dba17e13b0f551e65fa0d4fce06e692ae74b1a39ce029db0fb5b9` |
| [`scripts/build-ts1201-bundle-manifest.py`](../scripts/build-ts1201-bundle-manifest.py) | `d4b81ffc64897e9cf21c54fb1189cac438194b5f9331ebaac0a2ff568c3e7d40` |

码库许可证随数据发布，见 [`data/ts1201-ir-codebooks-LICENSE.txt`](../data/ts1201-ir-codebooks-LICENSE.txt)。安装、完整 HA 备份与回滚说明见 [安装指南](ts1201_zha_installation.md)。
