"""Constants for the TS1201 named infrared panel."""

DOMAIN = "ts1201_ir"
MANUFACTURER = "_TZ3290_qazgdsae"
MODEL = "TS1201"
MATCH_CLUSTER_ID = 0xFC10
KEY_REVISION_ATTRIBUTE = 0x0010
CLIMATE_REVISION_ATTRIBUTE = 0x0021
EMPTY_SELECTION = "暂无已保存按键"

ACTION_NAMES = {
    "learn": "开始按键学习",
    "stop": "停止按键学习",
    "save": "确认保存新按键",
    "update": "更新所选按键编码",
    "rename": "重命名所选按键",
    "delete": "删除所选按键",
    "undo_delete": "撤销最近删除",
    "send": "发送所选按键",
}
