"""ZHA support for Zemismart TS1201 / _TZ3290_qazgdsae.

Uses the installed zhaquirks.tuya.ts1201 Zosung transport, reviewed against
zha-device-handlers 8c8e861c9bf8e4eb389fb42ecdc00cfe3a893452.
Requires zha-quirks >= 2.2.0 (tested with 2.2.0 and 2.2.2).

Only the exact manufacturer/model and endpoint 1's existing Zosung server
clusters are accepted. Other interviewed endpoints/clusters are preserved;
no battery or Green Power endpoint is inferred from related TS1201 variants.

IRSend and IRLearn are local synthetic commands of cluster 0xE004, exposed
through ZHA's Manage Zigbee Device or issue_zigbee_cluster_command action.
Read attribute 0x0000 on that cluster to retrieve last_learned_ir_code.
Learned codes are held in memory by upstream: copy them to persistent storage.

Optional company quick-match UI is enabled by the neighboring
ts1201-ir-codebooks.json (the repository's data/ path is also accepted).
Selected brand, confirmed codebook ID and transfer sequence use normal local
ZCL attributes, persisted by zigpy's database. Unconfirmed match authorization
is deliberately process-local, so restarting requires another test.
"""

import asyncio
import base64
from dataclasses import dataclass, field
from enum import EnumType
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Final
from uuid import uuid4

from zigpy.device import Device
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.zcl import BaseAttributeDefs, BaseCommandDefs, foundation

from zhaquirks import LocalDataCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.device import CustomZigpyDevice
from zhaquirks.tuya.ts1201 import ZosungIRControl, ZosungIRTransmit

MANUFACTURER = "_TZ3290_qazgdsae"
MODEL = "TS1201"
MATCH_CLUSTER_ID = 0xFC10
TRANSFER_TIMEOUT = 30
KEY_REVISION_ATTRIBUTE = 0x0010
KEY_METADATA_ATTRIBUTE = 0x0011
KEY_PENDING_ATTRIBUTE = 0x0012
KEY_DELETED_ATTRIBUTE = 0x0013
KEY_SLOT_BASE = 0x0100
CLIMATE_STATE_ATTRIBUTE = 0x0020
CLIMATE_REVISION_ATTRIBUTE = 0x0021
MAX_KEYS = 32
MAX_CAPTURE_BYTES = 16384
MAX_EXPANDED_BYTES = 131072
KEY_LEARN_TIMEOUT = 60
KEY_PENDING_TTL = 600


def _load_codebooks() -> dict | None:
    paths = [
        Path(__file__).with_name("ts1201-ir-codebooks.json"),
        Path(__file__).parent / "data/ts1201-ir-codebooks.json",
    ]
    path = next((path for path in paths if path.is_file()), None)
    if path is None:
        return None  # Basic learning and explicit IRSend remain usable.
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1:
        raise ValueError("Unsupported TS1201 quick-match codebook schema")
    brand_ids = [brand["id"] for brand in data["brands"]]
    candidate_ids = [candidate["id"] for candidate in data["candidates"]]
    if len(set(brand_ids)) != len(brand_ids) or len(set(candidate_ids)) != len(
        candidate_ids
    ):
        raise ValueError("Duplicate TS1201 brand or codebook ID")
    for candidate in data["candidates"]:
        test = candidate["test"]
        if (
            candidate["brandId"] not in brand_ids
            or test["mode"] != "cool"
            or not 10 <= test["temperature"] <= 35
            or not test["fan"]
        ):
            raise ValueError("Invalid TS1201 quick-match state")
        _validate_code(test["code"])
        _validate_code(candidate["offCode"])
    return data


def _validate_code(code: str) -> None:
    if not isinstance(code, str) or not code:
        raise ValueError("请填写有效的 Zosung Base64 红外码")
    raw = base64.b64decode(code, validate=True)
    if not raw or base64.b64encode(raw).decode() != code:
        raise ValueError("红外码必须是完整的标准 Base64")


def _check_reply(response):
    status = getattr(response, "status", None)
    if status is not None and status != foundation.Status.SUCCESS:
        raise ValueError(f"设备拒绝红外命令：{status}")
    return response


CODEBOOKS = _load_codebooks()
BRANDS = {brand["id"]: brand for brand in (CODEBOOKS or {}).get("brands", [])}
CANDIDATES = {item["id"]: item for item in (CODEBOOKS or {}).get("candidates", [])}
CONTROL_STATES = {}
for _candidate_id, _candidate in CANDIDATES.items():
    if _candidate.get("control"):
        _states = {}
        for _state in _candidate["control"]["states"]:
            _key = (_state["mode"], _state["temperature"], _state["fan"])
            _validate_code(_state["code"])
            if _key in _states and _states[_key]["code"] != _state["code"]:
                raise ValueError(f"Conflicting AC state in codebook {_candidate_id}")
            _states[_key] = _state
        CONTROL_STATES[_candidate_id] = _states
# Stable tokens survive source ordering changes. Refuse collisions instead of
# silently reassigning a user's persisted brand when the codebook is updated.
BRAND_TOKENS = {
    bid: int.from_bytes(hashlib.sha256(bid.encode()).digest()[:2], "big") or 1
    for bid in BRANDS
}
if len(set(BRAND_TOKENS.values())) != len(BRAND_TOKENS):
    raise ValueError("TS1201 brand token collision")
BRANDS_BY_TOKEN = {token: bid for bid, token in BRAND_TOKENS.items()}
Brand = EnumType.__call__(
    t.enum16,
    "Brand",
    {
        "请选择品牌": 0,
        **{
            brand["label"].replace(" ", "_"): BRAND_TOKENS[bid]
            for bid, brand in BRANDS.items()
        },
    },
)


def _status_text(value: str) -> str:
    return value.encode("utf-8")[:250].decode("utf-8", errors="ignore")


def _description(candidate: dict) -> str:
    test = candidate["test"]
    family = [
        item for item in CANDIDATES.values() if item["brandId"] == candidate["brandId"]
    ]
    position = next(
        index for index, item in enumerate(family, 1) if item["id"] == candidate["id"]
    )
    fan = {"auto": "自动风", "low": "低风", "medium": "中风", "high": "高风"}.get(
        test["fan"], test["fan"]
    )
    return f"第 {position}/{len(family)} 套：{candidate['label'][:40]}，制冷 {test['temperature']:g}℃ {fan}"


@dataclass
class _Transfer:
    purpose: str
    candidate_id: str | None
    seq: int | None = None
    cancelled: bool = False
    finishing: bool = False
    completion_received: bool = False
    chunks: dict[int, int] = field(default_factory=dict)
    timer: Any = None
    climate_desired: dict | None = None


class _ClimateControl:
    """Exact codebook control with persisted intentions and command estimates."""

    def __init__(self, owner):
        self.owner = owner
        self._request = None
        self._lock = None

    def _candidate(self):
        candidate = CANDIDATES.get(self.owner.get("saved_codebook"))
        return candidate if candidate and candidate.get("control") else None

    @staticmethod
    def _initial(candidate):
        desired = {
            "power": True,
            "mode": candidate["test"]["mode"],
            "temperature": candidate["test"]["temperature"],
            "fan": candidate["test"]["fan"],
        }
        return {
            "version": 1,
            "codebook_id": candidate["id"],
            "desired": desired,
            "estimated": dict(desired),
            "pending": False,
            "requested": None,
            "estimate_stale": False,
            "status": "根据已确认试机设置初始化；仅为命令估计，未读取空调实际状态或室温。",
        }

    def _state(self, candidate):
        raw = self.owner.get(CLIMATE_STATE_ATTRIBUTE)
        if not raw:
            return self._initial(candidate)
        try:
            state = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("空调控制状态无法读取，请重新确认匹配码库") from exc
        if state.get("version") != 1 or state.get("codebook_id") != candidate["id"]:
            return self._initial(candidate)
        if state.get("pending") and not self._live_request():
            state.update(
                pending=False,
                requested=None,
                estimate_stale=True,
                status="上次控制传输未确认完成；保留上次命令估计，不会自动重发。",
            )
        return state

    def _live_request(self):
        return (
            self._request is not None
            and self.owner._active
            and self._request["epoch"] is self.owner._epoch
        )

    def _write(self, state):
        state["status"] = _status_text(state["status"])
        self.owner._update_attribute(
            CLIMATE_STATE_ATTRIBUTE,
            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        )
        revision = int(self.owner.get(CLIMATE_REVISION_ATTRIBUTE, 0) or 0)
        self.owner._update_attribute(
            CLIMATE_REVISION_ATTRIBUTE, (revision + 1) % 0x100000000
        )

    @staticmethod
    def _constraint(candidate, mode):
        return candidate["control"].get("modeConstraints", {}).get(mode, {})

    def _temperature(self, candidate, mode):
        constraint = self._constraint(candidate, mode)
        applicable = constraint.get("temperatureApplicable") is not False
        values = sorted(
            constraint.get("temperatures")
            or candidate["control"]["temperature"]["values"]
        )
        if not applicable:
            values = sorted(candidate["control"]["temperature"]["values"])
        gaps = [right - left for left, right in zip(values, values[1:])]
        step = (
            gaps[0]
            if gaps and all(math.isclose(gap, gaps[0], abs_tol=1e-6) for gap in gaps)
            else None
        )
        return {
            "min": values[0],
            "max": values[-1],
            "step": step,
            "values": values,
            "applicable": applicable,
        }

    def snapshot(self):
        """Expose capabilities and estimates without IR bytes or fake telemetry."""
        candidate = self._candidate()
        if candidate is None:
            return {
                "version": 1,
                "available": False,
                "codebook_id": self.owner.get("saved_codebook") or None,
                "label": "",
                "modes": [],
                "fans": [],
                "temperature": {
                    "min": None,
                    "max": None,
                    "step": None,
                    "values": [],
                    "applicable": False,
                },
                "mode_constraints": {},
                "desired": None,
                "estimated": None,
                "requested": None,
                "pending": False,
                "estimate_stale": True,
                "status": "请先确认保存带完整控制表的空调码库。",
            }
        state = self._state(candidate)
        constraint = self._constraint(candidate, state["desired"]["mode"])
        return {
            "version": 1,
            "available": self.owner._active,
            "codebook_id": candidate["id"],
            "label": candidate["label"],
            "modes": ["off", *candidate["control"]["modes"]],
            "fans": list(constraint.get("fans") or candidate["control"]["fans"]),
            "temperature": self._temperature(candidate, state["desired"]["mode"]),
            "mode_constraints": json.loads(json.dumps(constraint)),
            "desired": dict(state["desired"]),
            "estimated": dict(state["estimated"]),
            "requested": dict(state["requested"]) if state.get("requested") else None,
            "pending": bool(state.get("pending")),
            "estimate_stale": bool(state.get("estimate_stale")),
            "status": state["status"],
        }

    def reset(self, candidate):
        """Initialize a new explicit match confirmation without transmitting."""
        self._request = None
        if candidate.get("control"):
            self._write(self._initial(candidate))

    def deactivate(self):
        """Forget transient requests without promoting persisted pending state."""
        self._request = None
        self._lock = None

    def invalidate_estimate(self, reason):
        """Mark an estimate uncertain after another IR path could change a load."""
        candidate = self._candidate()
        if candidate:
            state = self._state(candidate)
            state.update(estimate_stale=True, status=reason)
            self._write(state)

    def begin_wire(self, transfer):
        """Track whether the pending request reached the IR sender."""
        if transfer.purpose == "climate":
            if self._live_request():
                self._request["sent"] = True
        else:
            self.invalidate_estimate(
                "已开始发送其他红外指令；空调估计可能已过期，请观察实际状态。"
            )

    def failed(self, transfer, reason):
        """Retain prior tuples when a climate transfer fails or times out."""
        if transfer.purpose != "climate":
            return
        self._failure(reason)

    def _failure(self, reason):
        candidate = self._candidate()
        request = self._request
        if not candidate or not request or request["codebook_id"] != candidate["id"]:
            self._request = None
            return
        state = self._state(candidate)
        self._request = None
        state.update(
            pending=False,
            requested=None,
            estimate_stale=state["estimate_stale"] or request["sent"],
            status=f"{reason}；保留上次命令估计，请观察空调。",
        )
        self._write(state)

    def completed(self, transfer):
        """Commit only the exact tuple whose matching protocol transfer finished."""
        candidate = self._candidate()
        if (
            not candidate
            or transfer.candidate_id != candidate["id"]
            or transfer.cancelled
        ):
            if transfer.purpose == "climate":
                self._request = None
            return
        if transfer.purpose == "climate":
            if not self._live_request() or transfer.climate_desired is None:
                return
            desired = dict(transfer.climate_desired)
            self._request = None
            state = {
                "version": 1,
                "codebook_id": candidate["id"],
                "desired": desired,
                "estimated": dict(desired),
                "pending": False,
                "requested": None,
                "estimate_stale": False,
                "status": "设备传输完成；仅为命令估计，请观察空调实际响应。",
            }
            self._write(state)
        elif transfer.purpose == "saved_test":
            self._write(self._initial(candidate))
        elif transfer.purpose == "saved_off":
            state = self._state(candidate)
            state["desired"]["power"] = state["estimated"]["power"] = False
            state.update(
                pending=False,
                requested=None,
                estimate_stale=False,
                status="已保存关机码传输完成；仅为命令估计，请观察空调。",
            )
            self._write(state)

    async def action(self, patch):
        """Validate one atomic patch and send exactly one complete source state."""
        if (
            not isinstance(patch, dict)
            or not patch
            or set(patch) - {"power", "mode", "temperature", "fan"}
        ):
            raise ValueError("空调操作须包含有效的电源、模式、温度或风速字段")
        self.owner._assert_idle()
        if self._lock:
            raise ValueError("空调操作正在处理中")
        candidate = self._candidate()
        if candidate is None:
            raise ValueError("请先确认保存带完整控制表的空调码库")
        state = self._state(candidate)
        desired = dict(state["desired"])
        if "power" in patch and not isinstance(patch["power"], bool):
            raise ValueError("电源必须为布尔值")
        if "mode" in patch and patch["mode"] not in [
            "off",
            *candidate["control"]["modes"],
        ]:
            raise ValueError("此码库不支持该工作模式")
        if patch.get("power") is True and patch.get("mode") == "off":
            raise ValueError("开机与关机模式冲突")
        if "mode" in patch and patch["mode"] != "off":
            desired["mode"] = patch["mode"]
            desired["power"] = True
        if "power" in patch:
            desired["power"] = patch["power"]
        if patch.get("mode") == "off":
            desired["power"] = False
        temperature_profile = self._temperature(candidate, desired["mode"])
        if "temperature" in patch:
            value = patch["temperature"]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value not in temperature_profile["values"]
                or not math.isfinite(value)
            ):
                raise ValueError(
                    "此码库/模式不支持该精确温度；请选择可用值，不会自动取邻近温度"
                )
            desired["temperature"] = value
        if "fan" in patch:
            desired["fan"] = patch["fan"]
        constraint = self._constraint(candidate, desired["mode"])
        fans = constraint.get("fans") or candidate["control"]["fans"]
        if (
            "fan" not in patch
            and desired["mode"] != state["desired"]["mode"]
            and desired["fan"] not in fans
        ):
            default_fan = candidate["control"]["defaults"]["fan"]
            desired["fan"] = default_fan if default_fan in fans else fans[0]
        if "fixedFan" in constraint:
            if "fan" in patch and desired["fan"] != constraint["fixedFan"]:
                raise ValueError("当前模式自行管理风速，不支持该风档")
            desired["fan"] = constraint["fixedFan"]
        temperature_key = (
            None
            if constraint.get("temperatureApplicable") is False
            else desired["temperature"]
        )
        key = (desired["mode"], temperature_key, desired["fan"])
        if not isinstance(desired["fan"], str) or key not in CONTROL_STATES.get(
            candidate["id"], {}
        ):
            raise ValueError("此码库不支持该模式、温度和风速组合")
        code = CONTROL_STATES[candidate["id"]][key]["code"]
        local_only = (
            not desired["power"]
            and not state["estimated"]["power"]
            and "power" not in patch
            and "mode" not in patch
        )
        future_temperature_only = constraint.get(
            "temperatureApplicable"
        ) is False and set(patch) == {"temperature"}
        if local_only or future_temperature_only:
            state.update(
                desired=desired,
                pending=False,
                requested=None,
                status="已保存待机或下次控温设置；未发送红外，当前状态仍为命令估计。",
            )
            self._write(state)
            return self.snapshot()
        token = object()
        self._lock = token
        request = {
            "desired": desired,
            "codebook_id": candidate["id"],
            "epoch": self.owner._epoch,
            "sent": False,
        }
        self._request = request
        state.update(
            pending=True,
            requested=dict(desired),
            status="正在发送空调指令；完成前保留上次命令估计。",
        )
        self._write(state)
        try:
            await self.owner.transmit(
                code if desired["power"] else candidate["offCode"],
                purpose="climate",
                candidate_id=candidate["id"],
                climate_desired=desired,
            )
        except Exception:
            if self._request is request:
                self._failure("空调指令未完成")
            raise
        finally:
            if self._lock is token:
                self._lock = None
        return self.snapshot()


def _validate_key_name(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > 48
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or value.strip() == "请选择已保存按键"
    ):
        raise ValueError("按键名称须为 1–48 个字符，不能包含控制字符或占位名称")
    return value.strip()


def _validate_learned_stream(raw: bytes) -> None:
    """Require complete bounded FastLZ decoding rather than a valid prefix."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_CAPTURE_BYTES:
        raise ValueError("学习码长度无效")
    expanded = bytearray()
    position = 0

    def take():
        nonlocal position
        if position >= len(raw):
            raise ValueError("学习码压缩流被截断")
        value = raw[position]
        position += 1
        return value

    while position < len(raw):
        header = take()
        kind = header >> 5
        length = (header & 31) + 1 if kind == 0 else kind + 2
        if kind == 7:
            while True:
                extension = take()
                length += extension
                if extension != 255:
                    break
        if len(expanded) + length > MAX_EXPANDED_BYTES:
            raise ValueError("学习码解压后过长")
        if kind == 0:
            for _ in range(length):
                expanded.append(take())
        else:
            distance = ((header & 31) << 8) + take() + 1
            if distance > len(expanded):
                raise ValueError("学习码压缩引用无效")
            for _ in range(length):
                expanded.append(expanded[-distance])
    if len(expanded) < 4 or len(expanded) % 2 or not any(expanded):
        raise ValueError("学习码不包含完整有效的红外时序")


@dataclass
class _KeyCapture:
    identifier: str
    epoch: object
    started_at: float
    seq: int | None = None
    length: int | None = None
    raw: bytearray = field(default_factory=bytearray)
    finish_requested: bool = False
    start_task: Any = None
    tail: Any = None
    timer: Any = None


class _NamedKeys:
    """Single-source learned-key bank backed by local zigpy attributes."""

    def __init__(self, owner):
        self.owner = owner
        self.capture = None
        self._lock = None
        self._tasks = set()
        self._stop_task = None
        self._pending_timer = None
        self._pending_timer_id = None

    def _read(self, attr, default):
        value = self.owner.get(attr)
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("按键库数据无法读取，请检查自定义 quirk 数据") from exc

    def _write(self, attr, value):
        if attr == KEY_PENDING_ATTRIBUTE and value is None and self._pending_timer:
            self._pending_timer.cancel()
            self._pending_timer = self._pending_timer_id = None
        text = (
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if value is not None
            else ""
        )
        if len(text.encode()) > 65534:
            raise ValueError("按键库单条记录超过本地属性容量")
        self.owner._update_attribute(attr, text)

    def _meta(self):
        default = {
            "version": 1,
            "next_id": 1,
            "name": "",
            "selected_id": None,
            "entries": [],
            "status": "填写按键名称（如电视关机），再点击开始按键学习；收到信号后确认保存。",
        }
        meta = self._read(KEY_METADATA_ATTRIBUTE, default)
        if (
            not isinstance(meta, dict)
            or meta.get("version") != 1
            or not isinstance(meta.get("entries"), list)
            or len(meta["entries"]) > MAX_KEYS
        ):
            raise ValueError("按键库格式或条目数无效")
        return meta

    @staticmethod
    def _validated_saved_entry(entry):
        """Trust recovery data only when it is a complete, known named capture."""
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or not entry["id"].isdecimal()
            or int(entry["id"]) < 1
            or entry.get("source") != "validated_named_capture"
            or not isinstance(entry.get("capture_id"), str)
            or not entry["capture_id"]
        ):
            raise ValueError("删除备份的来源或记录格式无效")
        _validate_key_name(entry.get("name"))
        for timestamp_field in ("created_at", "updated_at", "captured_at"):
            value = entry.get(timestamp_field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("删除备份的时间记录无效")
        code = entry.get("code")
        _validate_code(code)
        raw = base64.b64decode(code, validate=True)
        _validate_learned_stream(raw)
        if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("删除备份的完整性校验失败")
        return entry

    def _entries(self, meta, *, repair=False):
        result = []
        recovered = []
        slots, identifiers = set(), set()
        for ref in meta["entries"]:
            slot = ref.get("slot")
            identifier = ref.get("id")
            if (
                not isinstance(slot, int)
                or not 0 <= slot < MAX_KEYS
                or slot in slots
                or not isinstance(identifier, str)
                or not identifier.isdecimal()
                or int(identifier) < 1
                or identifier in identifiers
            ):
                raise ValueError("按键库槽位无效")
            slots.add(slot)
            identifiers.add(identifier)
            entry = self._read(KEY_SLOT_BASE + slot, None)
            if entry is None:
                # Version 1.2 cleared a slot before removing its index. A
                # matching, validated delete backup can supply only that exact
                # already-indexed key; never import unindexed/orphaned slots.
                backup = self._read(KEY_DELETED_ATTRIBUTE, None)
                if isinstance(backup, dict) and backup.get("id") == identifier:
                    entry = dict(self._validated_saved_entry(backup))
                    recovered.append((slot, entry))
            if not isinstance(entry, dict) or entry.get("id") != ref.get("id"):
                raise ValueError("按键库记录与索引不一致")
            _validate_key_name(entry.get("name"))
            result.append((ref, entry))
        if recovered and len({entry["name"] for _, entry in result}) != len(result):
            raise ValueError("删除备份与现有按键名称冲突")
        if repair:
            # Materialize recovery only for an explicit action, before it can
            # overwrite the sole delete backup. Snapshot reads remain read-only.
            for slot, entry in recovered:
                self._write(KEY_SLOT_BASE + slot, entry)
        return result

    def _pending_saved(self, pending, entries=None):
        """Recognize a save committed before its staging record was cleared."""
        if not isinstance(pending, dict):
            return False
        if entries is None:
            entries = self._entries(self._meta())
        return any(
            entry.get("source") == "validated_named_capture"
            and all(
                pending.get(key) is not None and pending[key] == entry.get(key)
                for key in ("capture_id", "sha256", "code")
            )
            for _, entry in entries
        )

    def _notify(self):
        if self.owner._active:
            revision = int(self.owner.get(KEY_REVISION_ATTRIBUTE, 0) or 0)
            self.owner._update_attribute(
                KEY_REVISION_ATTRIBUTE, (revision + 1) % 0x100000000
            )

    def _commit(self, meta, status):
        meta["status"] = _status_text(status)
        self._write(KEY_METADATA_ATTRIBUTE, meta)
        self._notify()

    def _pending(self):
        pending = self._read(KEY_PENDING_ATTRIBUTE, None)
        if (
            not isinstance(pending, dict)
            or pending.get("validated") is not True
            or not isinstance(pending.get("capture_id"), str)
            or not pending["capture_id"]
        ):
            return None
        now = time.time()
        captured = pending.get("captured_at")
        if (
            not isinstance(captured, (float, int))
            or not 0 <= now - captured < KEY_PENDING_TTL
        ):
            return None
        try:
            code = pending["code"]
            _validate_code(code)
            raw = base64.b64decode(code, validate=True)
            _validate_learned_stream(raw)
            if hashlib.sha256(raw).hexdigest() != pending.get("sha256"):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        return None if self._pending_saved(pending) else pending

    def _arm_pending_expiry(self, pending):
        if (
            not pending
            or not self.owner._active
            or self._pending_timer_id == pending["capture_id"]
        ):
            return
        if self._pending_timer:
            self._pending_timer.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._pending_timer_id = pending["capture_id"]

        def expire():
            self._pending_timer = None
            self._pending_timer_id = None
            if not self.owner._active:
                return
            current = self._read(KEY_PENDING_ATTRIBUTE, None)
            if (
                current
                and current.get("capture_id") == pending["capture_id"]
                and not self._pending()
            ):
                self._write(KEY_PENDING_ATTRIBUTE, None)
                self._commit(
                    self._meta(),
                    "待保存的新码已超过 10 分钟，请重新学习；已保存按键不变。",
                )

        delay = max(0, pending["captured_at"] + KEY_PENDING_TTL - time.time())
        self._pending_timer = loop.call_later(delay, expire)

    def snapshot(self):
        """Return UI metadata only; never expose captured or stored IR payloads."""
        meta = self._meta()
        entries = self._entries(meta)
        pending = self._pending()
        self._arm_pending_expiry(pending)
        raw_pending = self._read(KEY_PENDING_ATTRIBUTE, None)
        status = meta["status"]
        if not self.owner._active:
            status = "此设备对象已停用，等待绑定当前 ZHA 设备。"
        elif raw_pending and not pending:
            status = (
                "本次学习码已保存；无须重复保存。"
                if self._pending_saved(raw_pending, entries)
                else "待保存结果已失效，请重新学习；已保存按键不变。"
            )
        elif any(
            self._read(KEY_SLOT_BASE + ref["slot"], None) is None for ref, _ in entries
        ):
            status = "上次删除未完成；已保留原按键，可重新删除或继续使用。"
        elif not self.capture and status.startswith("正在学习"):
            status = "上次未完成学习已失效，请重新开始；没有导入旧学习码。"
        selected = any(entry["id"] == meta["selected_id"] for _, entry in entries)
        deleted = self._read(KEY_DELETED_ATTRIBUTE, None)
        can_undo = bool(
            isinstance(deleted, dict)
            and deleted.get("id")
            and deleted.get("name")
            and len(entries) < MAX_KEYS
            and not any(
                entry["id"] == deleted["id"] or entry["name"] == deleted["name"]
                for _, entry in entries
            )
        )
        # Relevance is independent of short-lived busy/active flags. The backend
        # still validates every action, including calls through stale HA entities.
        relevant_actions = ["learn"]
        if (
            self.capture
            or self.owner.learning
            or self.owner._learn_pending
            or meta.get("stop_required")
        ):
            relevant_actions.append("stop")
        if pending and len(entries) < MAX_KEYS:
            relevant_actions.append("save")
        if selected:
            relevant_actions.extend(("send", "rename", "delete"))
            if pending:
                relevant_actions.append("update")
        if can_undo:
            relevant_actions.append("undo_delete")
        return {
            "version": 1,
            "revision": int(self.owner.get(KEY_REVISION_ATTRIBUTE, 0) or 0),
            "name": meta["name"],
            "selected_id": meta["selected_id"],
            "keys": [
                {key: entry[key] for key in ("id", "name", "created_at", "updated_at")}
                for _, entry in entries
            ],
            "count": len(entries),
            "status": status,
            "learning": self.capture is not None,
            "busy": bool(
                self.capture
                or self.owner.transfer
                or self.owner.learning
                or self.owner._learn_pending
                or self._lock
            ),
            "pending_valid": bool(pending and self.owner._active),
            "pending_expires_at": pending["captured_at"] + KEY_PENDING_TTL
            if pending
            else None,
            "can_undo": can_undo,
            "relevant_actions": relevant_actions,
        }

    def _task(self, coroutine):
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _current(self, capture):
        return (
            self.owner._active
            and self.capture is capture
            and self.owner._epoch is capture.epoch
        )

    def _drop_capture(self, capture):
        if self.capture is not capture:
            return
        if capture.timer:
            capture.timer.cancel()
        self.capture = None
        self.owner.learning = False
        self.owner.learn_seq = None
        current = asyncio.current_task()
        if capture.tail and capture.tail is not current and not capture.tail.done():
            capture.tail.cancel()

    async def abort_for_other(self, clear_pending=False):
        """Invalidate named learning before a different explicit IR operation."""
        epoch = self.owner._epoch
        capture = self.capture
        if capture:
            self._drop_capture(capture)
            clear_pending = True
        if clear_pending:
            self._write(KEY_PENDING_ATTRIBUTE, None)
            self._commit(self._meta(), "本次命名学习已取消；已保存按键不变。")
        if (
            capture
            and capture.start_task
            and capture.start_task is not asyncio.current_task()
        ):
            try:
                await asyncio.shield(capture.start_task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                pass
        if self._stop_task and self._stop_task is not asyncio.current_task():
            try:
                await asyncio.shield(self._stop_task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                pass
        if not self.owner._active or self.owner._epoch is not epoch:
            raise ValueError("按键操作所属的 ZHA 绑定已失效")

    async def _stop_radio(self, epoch):
        if not self.owner._active or self.owner._epoch is not epoch:
            return
        try:
            _check_reply(
                await ZosungIRControl.command(
                    self.owner.endpoint.zosung_ircontrol, 1, on_off=False
                )
            )
        except Exception:
            if self.owner._active and self.owner._epoch is epoch:
                meta = self._meta()
                meta["stop_required"] = True
                self._commit(
                    meta,
                    "停止学习命令失败；本次学习已作废，请检查设备在线后再次停止学习。",
                )
        else:
            if self.owner._active and self.owner._epoch is epoch:
                meta = self._meta()
                meta["stop_required"] = False
                self._write(KEY_METADATA_ATTRIBUTE, meta)
                self._notify()

    def _timeout(self, capture):
        if not self._current(capture):
            return
        self._drop_capture(capture)
        self._write(KEY_PENDING_ATTRIBUTE, None)
        self._commit(self._meta(), "学习超时，没有保存新码；正在退出学习。")
        self._stop_task = self._task(self._stop_radio(capture.epoch))

    async def _start(self):
        _validate_key_name(self._meta()["name"])
        await self.abort_for_other(clear_pending=True)
        self.owner._assert_idle()
        capture = _KeyCapture(str(uuid4()), self.owner._epoch, time.time())
        self.capture = capture
        token = object()
        self.owner._learn_pending = token
        capture.timer = asyncio.get_running_loop().call_later(
            KEY_LEARN_TIMEOUT, self._timeout, capture
        )
        self._commit(
            self._meta(),
            "正在学习新按键（60 秒）；请将原遥控器对准红外盒按一次，收到信号后确认保存。",
        )

        async def start_command():
            try:
                result = _check_reply(
                    await ZosungIRControl.command(
                        self.owner.endpoint.zosung_ircontrol, 1, on_off=True
                    )
                )
                if self._current(capture):
                    self.owner.learning = True
                    self.owner.learn_seq = None
                    self._notify()
                return result
            except Exception:
                if self._current(capture):
                    self._drop_capture(capture)
                    self._write(KEY_PENDING_ATTRIBUTE, None)
                    self._commit(
                        self._meta(), "启动学习失败，旧待保存码已清除；请重试。"
                    )
                raise
            except asyncio.CancelledError:
                if self._current(capture):
                    self._drop_capture(capture)
                    self._write(KEY_PENDING_ATTRIBUTE, None)
                    self._commit(self._meta(), "启动学习已取消；没有保存新码。")
                    self._stop_task = self._task(self._stop_radio(capture.epoch))
                raise
            finally:
                if self.owner._learn_pending is token:
                    self.owner._learn_pending = False

        capture.start_task = self._task(start_command())
        await capture.start_task

    def handle_frame(self, header, args, addressing=None):
        """Queue this capture's frames behind start and preceding radio ACKs."""
        capture = self.capture
        if not capture or header.command_id not in (0, 3, 5):
            return
        previous = capture.tail

        async def process():
            try:
                if previous:
                    await asyncio.shield(previous)
                if capture.start_task:
                    await asyncio.shield(capture.start_task)
                if self._current(capture):
                    await self._process_frame(capture, header, args, addressing)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self._current(capture):
                    self._drop_capture(capture)
                    self._write(KEY_PENDING_ATTRIBUTE, None)
                    self._commit(
                        self._meta(), f"学习失败：{str(exc)[:70]}；没有保存新码。"
                    )
                    self._stop_task = self._task(self._stop_radio(capture.epoch))

        capture.tail = self._task(process())

    async def _process_frame(self, capture, header, args, addressing):
        transmit = self.owner.endpoint.zosung_irtransmit
        command_id = header.command_id
        if command_id == 0:
            if capture.seq is not None:
                return
            if not 0 <= args.seq <= 65535 or not 0 < args.length <= MAX_CAPTURE_BYTES:
                raise ValueError("学习帧头长度或序号无效")
            capture.seq, capture.length = int(args.seq), int(args.length)
        elif capture.seq is None or args.seq != capture.seq:
            return
        elif command_id == 3:
            if (
                args.position != len(capture.raw)
                or sum(args.msgpart) % 256 != args.msgpartcrc
            ):
                return
            if not args.msgpart or args.position + len(args.msgpart) > capture.length:
                raise ValueError("学习分片为空或超过声明长度")
        elif command_id == 5:
            if not capture.finish_requested or len(capture.raw) != capture.length:
                raise ValueError("本次学习尚未完整接收")
            raw = bytes(capture.raw)
            _validate_learned_stream(raw)
            _check_reply(
                await ZosungIRControl.command(
                    self.owner.endpoint.zosung_ircontrol, 1, on_off=False
                )
            )
            if not self._current(capture):
                return
            now = time.time()
            code = base64.b64encode(raw).decode()
            pending = {
                "validated": True,
                "capture_id": capture.identifier,
                "started_at": capture.started_at,
                "captured_at": now,
                "seq": capture.seq,
                "code": code,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            self._drop_capture(capture)
            self.owner.endpoint.device.last_learned_ir_code = code
            self.owner._climate.invalidate_estimate(
                "已学习新的红外信号；原遥控器可能改变空调，原估计需重新确认。"
            )
            self._write(KEY_PENDING_ATTRIBUTE, pending)
            self._arm_pending_expiry(pending)
            meta = self._meta()
            meta["stop_required"] = False
            self._commit(
                meta,
                f"收到完整新码（{len(raw)} 字节）；请确认来源和名称，10 分钟内保存或更新。",
            )
            return
        # Reuse upstream packet handling and schemas, but await its generated
        # commands in order. A final 05 cannot race the last 03's ACK.
        commands = []
        transmit._capture_task_sink = commands
        try:
            ZosungIRTransmit.handle_cluster_request(
                transmit, header, args, dst_addressing=addressing
            )
        finally:
            transmit._capture_task_sink = None
        try:
            for coroutine in commands:
                if not self._current(capture):
                    return
                _check_reply(await coroutine)
            if not self._current(capture):
                return
            if command_id == 3:
                capture.raw.extend(args.msgpart)
                capture.finish_requested = len(capture.raw) == capture.length
        finally:
            for coroutine in commands:
                coroutine.close()

    async def action(self, action, value=None):
        """Apply one explicit key operation; IDs never follow mutable names."""
        if not self.owner._active:
            raise ValueError("ZHA 设备对象已失效，请等待重新绑定")
        if action == "stop":
            epoch = self.owner._epoch
            try:
                await self.owner.learn(False)
            except Exception:
                if self.owner._active and self.owner._epoch is epoch:
                    meta = self._meta()
                    meta["stop_required"] = True
                    self._commit(
                        meta, "停止学习命令失败；请检查设备在线后再次停止学习。"
                    )
                raise
            meta = self._meta()
            meta["stop_required"] = False
            self._commit(meta, "已停止学习；已保存按键不变。")
            return self.snapshot()
        if self._lock:
            raise ValueError("按键操作正在处理中")
        self.owner._assert_idle()
        if self.capture or self.owner.learning:
            raise ValueError("红外正在学习，请先完成或停止学习")
        token = object()
        self._lock = token
        try:
            meta = self._meta()
            entries = self._entries(meta, repair=True)
            if self._pending_saved(self._read(KEY_PENDING_ATTRIBUTE, None), entries):
                self._write(KEY_PENDING_ATTRIBUTE, None)
            selected_id = (
                str(value)
                if action == "send" and value is not None
                else meta["selected_id"]
            )
            selected = next(
                ((ref, entry) for ref, entry in entries if entry["id"] == selected_id),
                None,
            )
            now = time.time()
            if action == "name":
                # An empty editable draft is valid; learning/saving/renaming
                # still require a real name and cannot create a blank key.
                meta["name"] = "" if value == "" else _validate_key_name(value)
                self._commit(
                    meta,
                    "名称已设置；可以开始学习或重命名所选按键。"
                    if meta["name"]
                    else "请填写按键名称（如电视关机），再开始学习或保存新按键。",
                )
            elif action in ("selected", "select"):
                value = str(value) if value is not None else None
                if value is not None and not any(
                    entry["id"] == value for _, entry in entries
                ):
                    raise ValueError("所选按键不存在")
                meta["selected_id"] = value
                self._commit(meta, "已选择按键；选择本身不会发送红外。")
            elif action == "learn":
                await self._start()
            elif action in ("save", "update"):
                pending = self._pending()
                if pending is None:
                    raise ValueError("没有本次完整且未过期的捕获，请重新学习")
                if action == "save":
                    name = _validate_key_name(meta["name"])
                    if any(entry["name"] == name for _, entry in entries):
                        raise ValueError("已存在同名按键；请改名或使用更新操作")
                    if len(entries) >= MAX_KEYS:
                        raise ValueError("最多保存 32 个按键")
                    used = {ref["slot"] for ref, _ in entries}
                    slot = next(index for index in range(MAX_KEYS) if index not in used)
                    identifier = str(meta["next_id"])
                    meta["next_id"] += 1
                    entry = {"id": identifier, "name": name, "created_at": now}
                    meta["entries"].append({"slot": slot, "id": identifier})
                else:
                    if selected is None:
                        raise ValueError("请先选择需要更新的按键")
                    ref, entry = selected
                    slot = ref["slot"]
                    identifier = entry["id"]
                entry.update(
                    {
                        "code": pending["code"],
                        "sha256": pending["sha256"],
                        "capture_id": pending["capture_id"],
                        "captured_at": pending["captured_at"],
                        "updated_at": now,
                        "source": "validated_named_capture",
                    }
                )
                self._write(KEY_SLOT_BASE + slot, entry)
                meta["selected_id"] = identifier
                self._commit(
                    meta,
                    f"已保存“{entry['name']}”；按钮可发送此码，未验证家电实际响应。",
                )
                # zigpy commits each attribute separately. Keep the recoverable
                # capture until both its slot and index have been committed.
                self._write(KEY_PENDING_ATTRIBUTE, None)
            elif action == "rename":
                if selected is None:
                    raise ValueError("请先选择需要重命名的按键")
                ref, entry = selected
                name = _validate_key_name(meta["name"])
                if any(
                    other["name"] == name and other["id"] != entry["id"]
                    for _, other in entries
                ):
                    raise ValueError("已存在同名按键")
                entry.update(name=name, updated_at=now)
                self._write(KEY_SLOT_BASE + ref["slot"], entry)
                self._commit(meta, "已重命名；按钮 ID 和编码保持不变。")
            elif action == "delete":
                if selected is None:
                    raise ValueError("请先选择需要删除的按键")
                ref, entry = selected
                self._write(KEY_DELETED_ATTRIBUTE, entry)
                meta["entries"].remove(ref)
                meta["selected_id"] = None
                self._commit(meta, "已删除所选按键；可以撤销最近一次删除。")
                self._write(KEY_SLOT_BASE + ref["slot"], None)
            elif action == "undo_delete":
                entry = self._read(KEY_DELETED_ATTRIBUTE, None)
                if not entry:
                    raise ValueError("没有可撤销的删除")
                self._validated_saved_entry(entry)
                if len(entries) >= MAX_KEYS or any(
                    other["name"] == entry["name"] or other["id"] == entry["id"]
                    for _, other in entries
                ):
                    raise ValueError("容量或名称冲突，无法撤销删除")
                used = {ref["slot"] for ref, _ in entries}
                slot = next(index for index in range(MAX_KEYS) if index not in used)
                self._write(KEY_SLOT_BASE + slot, entry)
                meta["entries"].append({"slot": slot, "id": entry["id"]})
                meta["selected_id"] = entry["id"]
                self._commit(meta, "已恢复最近删除的按键及原按钮 ID。")
                self._write(KEY_DELETED_ATTRIBUTE, None)
            elif action == "send":
                if selected is None:
                    raise ValueError("请先选择有效的已保存按键")
                _, entry = selected
                raw = base64.b64decode(entry["code"], validate=True)
                _validate_learned_stream(raw)
                if (
                    entry.get("source") != "validated_named_capture"
                    or entry.get("sha256") != hashlib.sha256(raw).hexdigest()
                ):
                    raise ValueError("已保存按键的来源或完整性校验失败")
                await self.owner.transmit(entry["code"], purpose="named_key")
                self._commit(
                    self._meta(), f"正在发送“{entry['name']}”；请观察家电实际响应。"
                )
            else:
                raise ValueError("不支持的按键操作")
        finally:
            if self._lock is token:
                self._lock = None
                self._notify()
        return self.snapshot()

    def deactivate(self):
        """Cancel software work without transmitting or deleting persistent data."""
        if self.capture:
            self._drop_capture(self.capture)
        if self._pending_timer:
            self._pending_timer.cancel()
        self._pending_timer = self._pending_timer_id = None
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._lock = None


class IRMatchCluster(LocalDataCluster):
    """Local-only controls; persistence uses zigpy's normal attribute events."""

    cluster_id = MATCH_CLUSTER_ID
    ep_attribute = "ir_match"
    name = "IR quick match"

    class AttributeDefs(BaseAttributeDefs):
        """Define local attributes stored by the normal zigpy attribute cache."""

        selected_brand: Final = foundation.ZCLAttributeDef(
            id=0, type=Brand, access="rw", manufacturer_code=None
        )
        saved_codebook: Final = foundation.ZCLAttributeDef(
            id=1, type=t.CharacterString, access="r", manufacturer_code=None
        )
        transfer_sequence: Final = foundation.ZCLAttributeDef(
            id=2, type=t.uint16_t, access="r", manufacturer_code=None
        )
        match_status: Final = foundation.ZCLAttributeDef(
            id=3, type=t.CharacterString, access="r", manufacturer_code=None
        )
        current_candidate: Final = foundation.ZCLAttributeDef(
            id=4, type=t.CharacterString, access="r", manufacturer_code=None
        )
        key_revision: Final = foundation.ZCLAttributeDef(
            id=KEY_REVISION_ATTRIBUTE,
            type=t.uint32_t,
            access="r",
            manufacturer_code=None,
        )
        key_metadata: Final = foundation.ZCLAttributeDef(
            id=KEY_METADATA_ATTRIBUTE,
            type=t.LongCharacterString,
            access="r",
            manufacturer_code=None,
        )
        key_pending: Final = foundation.ZCLAttributeDef(
            id=KEY_PENDING_ATTRIBUTE,
            type=t.LongCharacterString,
            access="r",
            manufacturer_code=None,
        )
        key_deleted: Final = foundation.ZCLAttributeDef(
            id=KEY_DELETED_ATTRIBUTE,
            type=t.LongCharacterString,
            access="r",
            manufacturer_code=None,
        )
        climate_state: Final = foundation.ZCLAttributeDef(
            id=CLIMATE_STATE_ATTRIBUTE,
            type=t.LongCharacterString,
            access="r",
            manufacturer_code=None,
        )
        climate_revision: Final = foundation.ZCLAttributeDef(
            id=CLIMATE_REVISION_ATTRIBUTE,
            type=t.uint32_t,
            access="r",
            manufacturer_code=None,
        )
        for _slot in range(MAX_KEYS):
            locals()[f"key_slot_{_slot:02d}"] = foundation.ZCLAttributeDef(
                id=KEY_SLOT_BASE + _slot,
                type=t.LongCharacterString,
                access="r",
                manufacturer_code=None,
            )
        del _slot

    class ServerCommandDefs(BaseCommandDefs):
        """Define local UI actions that never serialize on the virtual cluster."""

        match_start: Final = foundation.ZCLCommandDef(
            id=0, schema={}, manufacturer_code=None
        )
        match_next: Final = foundation.ZCLCommandDef(
            id=1, schema={}, manufacturer_code=None
        )
        match_retry: Final = foundation.ZCLCommandDef(
            id=2, schema={}, manufacturer_code=None
        )
        match_confirm: Final = foundation.ZCLCommandDef(
            id=3, schema={}, manufacturer_code=None
        )
        match_cancel: Final = foundation.ZCLCommandDef(
            id=4, schema={}, manufacturer_code=None
        )
        saved_test: Final = foundation.ZCLCommandDef(
            id=5, schema={}, manufacturer_code=None
        )
        saved_off: Final = foundation.ZCLCommandDef(
            id=6, schema={}, manufacturer_code=None
        )

    _DEFAULT_VALUES = {
        0: Brand(0),
        1: "",
        2: 0,
        3: "请选择空调品牌，再开始逐套测试。",
        4: "",
    }

    def __init__(self, *args, **kwargs):
        """Initialize transient workflow state independently of persisted attributes."""
        super().__init__(*args, **kwargs)
        self.transfer: _Transfer | None = None
        self.candidate_id: str | None = None
        self.ready_id: str | None = None
        self.learning = False
        self.learn_seq: int | None = None
        self._status: str | None = None
        self._learn_pending = False
        self._active = True
        self._epoch = object()
        self._keys = _NamedKeys(self)
        self._climate = _ClimateControl(self)

    def climate_snapshot(self):
        """Return the confirmed codebook's controls and command-estimate state."""
        return self._climate.snapshot()

    async def climate_action(self, patch):
        """Apply one atomic power/mode/temperature/fan patch through shared IR."""
        return await self._climate.action(patch)

    def key_snapshot(self):
        """Return the single-source learned-key UI state without IR payloads."""
        return self._keys.snapshot()

    def snapshot(self):
        """Alias the learned-key snapshot for companion integration consumers."""
        return self.key_snapshot()

    async def key_action(self, action, value=None):
        """Execute a named-key operation through the shared transport guard."""
        return await self._keys.action(action, value)

    def deactivate(self):
        """Invalidate this runtime object without sending anything to hardware."""
        self._active = False
        self._epoch = object()
        if self.transfer:
            self._release(self.transfer)
        self.learning = False
        self.learn_seq = None
        self._learn_pending = False
        self._keys.deactivate()
        self._climate.deactivate()

    def invalidate(self):
        """Alias lifecycle invalidation for companion integration rebinds."""
        self.deactivate()

    def activate(self):
        """Enable a freshly verified binding without restoring transient work."""
        if not self._active:
            self._epoch = object()
            self._active = True

    def get(self, key, default=None):
        """Read persistent values while suppressing stale transient state after reload."""
        try:
            attr_id = self.find_attribute(key).id
        except KeyError:
            return default
        if attr_id == 3:
            if self._status is not None:
                return self._status
            saved = super().get("saved_codebook", "")
            if saved:
                return _status_text(
                    f"已恢复保存码库 {saved}；可复测或关机，新匹配需要重新测试。"
                )
            return "请选择空调品牌，再开始逐套测试；尚未确认匹配。"
        if attr_id == 4:
            return self.candidate_id or ""
        return super().get(key, default)

    async def read_attributes_raw(self, attributes, manufacturer=None, **kwargs):
        # Cache replay happens after device construction. Recompute transient
        # display values here rather than restoring stale 'ready to confirm'.
        """Serve virtual attributes locally without sending Zigbee read requests."""
        for attr_id in attributes:
            if attr_id in (3, 4):
                self._update_attribute(attr_id, self.get(attr_id))
        return await super().read_attributes_raw(attributes, manufacturer, **kwargs)

    def _set_status(self, text: str) -> None:
        self._status = _status_text(text)
        self._update_attribute(3, self._status)
        self._update_attribute(4, self.candidate_id or "")
        self._keys._notify()

    def _assert_idle(self) -> None:
        if not self._active:
            raise ValueError("ZHA 设备对象已失效，请等待重新绑定")
        if self.transfer is not None or self._learn_pending:
            raise ValueError("红外传输尚未结束，请等待当前操作完成")

    async def write_attributes(self, attributes, **kwargs):
        """Select a valid brand locally and leave the confirmed codebook unchanged."""
        self._assert_idle()
        if len(attributes) != 1:
            raise ValueError("每次只能选择一个空调品牌")
        key, value = next(iter(attributes.items()))
        if self.find_attribute(key).id != 0 or int(value) not in {0, *BRANDS_BY_TOKEN}:
            raise ValueError("请选择列表中的空调品牌；其他属性只读")
        self._update_attribute(0, Brand(value))
        self.candidate_id = self.ready_id = None
        bid = BRANDS_BY_TOKEN.get(int(value))
        if bid:
            count = sum(item["brandId"] == bid for item in CANDIDATES.values())
            self._set_status(
                f"已选择 {BRANDS[bid]['label']}，共 {count} 套；按开始匹配测试。已保存码库不变。"
            )
        else:
            self._set_status("请选择空调品牌；已保存码库不变。")
        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]

    async def command(self, command_id, *args, **kwargs):
        """Execute one explicit workflow action with confirmation and busy checks."""
        if command_id not in self.server_commands:
            raise ValueError("不支持的红外匹配操作")
        if command_id == 4:
            if self.transfer and self.transfer.purpose == "match":
                self.transfer.cancelled = True
            self.candidate_id = self.ready_id = None
            self._set_status("已取消匹配；已发出的测试不能撤回，已保存码库不变。")
            return None
        self._assert_idle()
        if command_id == 3:
            if not self.candidate_id or self.ready_id != self.candidate_id:
                raise ValueError(
                    "请先测试当前候选并等待传输完成，再确认空调响应是否正确"
                )
            self._update_attribute(1, self.candidate_id)
            self._climate.reset(CANDIDATES[self.candidate_id])
            self._set_status(
                f"用户已确认并保存 {self.candidate_id}；可使用已保存码复测或关机。"
            )
            return None
        if command_id in (5, 6):
            candidate = CANDIDATES.get(self.get("saved_codebook"))
            if candidate is None:
                raise ValueError("尚无可用的已确认码库，请先完成一次匹配")
            purpose = "saved_off" if command_id == 6 else "saved_test"
        else:
            bid = BRANDS_BY_TOKEN.get(int(self.get("selected_brand")))
            candidates = [
                item for item in CANDIDATES.values() if item["brandId"] == bid
            ]
            if not candidates:
                raise ValueError("请先选择空调品牌")
            if command_id == 0:
                candidate = candidates[0]
            else:
                index = next(
                    (
                        i
                        for i, item in enumerate(candidates)
                        if item["id"] == self.candidate_id
                    ),
                    None,
                )
                if index is None:
                    raise ValueError("请先按开始匹配")
                if command_id == 1 and index + 1 == len(candidates):
                    self._set_status(
                        "已到最后一套，不会自动循环发码；可重试、确认或取消。"
                    )
                    return None
                candidate = candidates[index + (command_id == 1)]
            self.candidate_id = candidate["id"]
            purpose = "match"
        self.ready_id = None
        code = (
            candidate["offCode"]
            if purpose == "saved_off"
            else candidate["test"]["code"]
        )
        await self.transmit(code, purpose, candidate["id"])

    async def learn(self, enabled: bool):
        """Serialize learning commands against outgoing IR operations."""
        if not self._active:
            raise ValueError("ZHA 设备对象已失效，请等待重新绑定")
        await self._keys.abort_for_other(clear_pending=True)
        self._assert_idle()
        self.ready_id = None
        control = self.endpoint.zosung_ircontrol
        token = object()
        epoch = self._epoch
        self._learn_pending = token
        try:
            result = _check_reply(
                await ZosungIRControl.command(control, 1, on_off=enabled)
            )
        finally:
            if self._learn_pending is token:
                self._learn_pending = False
        if not self._active or self._epoch is not epoch:
            raise ValueError("学习操作所属的 ZHA 绑定已失效")
        self.learning = enabled
        self.learn_seq = None
        self._set_status(
            "正在学习红外；请对准发射原遥控器。"
            if enabled
            else "已停止学习；已保存码库不变。"
        )
        return result

    async def transmit(
        self, code: str, purpose="manual", candidate_id=None, *, climate_desired=None
    ):
        """Reserve one transfer, stop learning, then use upstream Zosung sending."""
        if not self._active:
            raise ValueError("ZHA 设备对象已失效，请等待重新绑定")
        await self._keys.abort_for_other()
        self._assert_idle()
        _validate_code(code)
        self.ready_id = None
        transfer = _Transfer(
            purpose,
            candidate_id,
            climate_desired=dict(climate_desired) if climate_desired else None,
        )
        self.transfer = transfer  # Lock before the first await.
        transfer.timer = asyncio.get_running_loop().call_later(
            TRANSFER_TIMEOUT,
            self.fail,
            transfer,
            "红外传输超时；请检查空调后重试，未确认匹配。",
        )
        candidate = CANDIDATES.get(candidate_id)
        description = _description(candidate) if candidate else "手动红外码"
        self._set_status(
            f"{description}；正在发送{'关机码' if purpose == 'saved_off' else '测试码'}，需观察空调。"
        )
        try:
            _check_reply(
                await ZosungIRControl.command(
                    self.endpoint.zosung_ircontrol, 1, on_off=False
                )
            )
            if self.transfer is not transfer:
                raise ValueError("红外操作已取消或过期；不会继续发送")
            if transfer.cancelled:
                self._release(transfer)
                return
            self.learning = False
            self.learn_seq = None
            self._climate.begin_wire(transfer)
            await ZosungIRControl.command(self.endpoint.zosung_ircontrol, 2, code=code)
        except Exception:
            self.fail(transfer, "红外发送失败；请检查设备后重试，已保存码库不变。")
            raise

    def fail(self, transfer: _Transfer, message: str) -> None:
        """Release the matching transfer without authorizing confirmation."""
        if self.transfer is not transfer:
            return
        self._release(transfer)
        self._climate.failed(transfer, message)
        self.ready_id = None
        self._set_status(message)
        if transfer.purpose == "named_key":
            self._keys._commit(self._keys._meta(), "按键发送失败；未取得家电实际反馈。")

    def _release(self, transfer):
        if transfer.timer:
            transfer.timer.cancel()
        self.endpoint.device.ir_msg_to_send.pop(transfer.seq, None)
        self.transfer = None

    def complete(self, transfer):
        """Mark a transmitted candidate ready for explicit user confirmation."""
        if self.transfer is not transfer:
            return
        self._release(transfer)
        self._climate.completed(transfer)
        if transfer.purpose == "named_key":
            self._keys._commit(
                self._keys._meta(), "命名按键传输完成；请观察家电实际响应。"
            )
        if transfer.cancelled:
            return  # Retain cancellation and never make this candidate confirmable.
        if transfer.purpose == "match" and transfer.candidate_id == self.candidate_id:
            self.ready_id = transfer.candidate_id
            self._set_status(
                f"{_description(CANDIDATES[self.candidate_id])}；传输完成。请观察空调后确认或试下一套。"
            )
        else:
            self._set_status("红外传输完成；需观察空调实际响应，已保存码库不变。")


def _matcher(device) -> IRMatchCluster | None:
    return device.endpoints[1].in_clusters.get(MATCH_CLUSTER_ID)


class GuardedIRControl(ZosungIRControl):
    """Keep original learning/send commands and route them through the busy lock."""

    async def command(self, command_id, *args, **kwargs):
        """Route learning and sending through the shared workflow lock."""
        matcher = _matcher(self.endpoint.device)
        if matcher is not None and command_id == 1:
            return await matcher.learn(bool(kwargs["on_off"]))
        if matcher is not None and command_id == 2:
            return await matcher.transmit(kwargs["code"])
        return await super().command(command_id, *args, **kwargs)


class GuardedIRTransmit(ZosungIRTransmit):
    """Observe upstream tasks and sender completion without duplicating encoding."""

    _chunk_context = None

    async def command(self, command_id, *args, **kwargs):
        """Report asynchronous sender failures back to the active workflow."""
        matcher = _matcher(self.endpoint.device)
        if matcher is not None and not matcher._active:
            raise ValueError("此 ZHA 传输对象已失效")
        transfer = matcher.transfer if matcher else None
        if (
            matcher is not None
            and command_id == 0
            and (transfer is None or transfer.seq != kwargs.get("seq"))
        ):
            # Upstream queues the header coroutine. A rebind can invalidate its
            # original transfer before this coroutine begins running.
            raise ValueError("红外发送帧头已过期，不会继续发送")
        try:
            return _check_reply(await super().command(command_id, *args, **kwargs))
        except Exception:
            if transfer:
                matcher.fail(transfer, "红外传输失败；未确认匹配，已保存码库不变。")
            raise

    def create_catching_task(self, target, *args, **kwargs):
        """Observe upstream fragment completion and failures for this transfer only."""
        sink = getattr(self, "_capture_task_sink", None)
        if sink is not None:
            sink.append(target)
            return None
        matcher = _matcher(self.endpoint.device)
        transfer = matcher.transfer if matcher else None
        epoch = matcher._epoch if matcher else None
        context = self._chunk_context

        async def observed():
            try:
                if matcher and (not matcher._active or matcher._epoch is not epoch):
                    target.close()
                    return None
                result = _check_reply(await target)
                if context and matcher.transfer is transfer:
                    transfer.chunks[context[0]] = context[1]
                    self._finish_when_ready(transfer)
                return result
            except Exception:
                if transfer:
                    matcher.fail(
                        transfer, "红外分包传输失败；未确认匹配，已保存码库不变。"
                    )
                raise

        return super().create_catching_task(observed(), *args, **kwargs)

    def _finish_when_ready(self, transfer):
        matcher = _matcher(self.endpoint.device)
        if (
            matcher.transfer is not transfer
            or not transfer.completion_received
            or transfer.finishing
        ):
            return
        message = self.endpoint.device.ir_msg_to_send.get(transfer.seq, "")
        covered = 0
        for position, end in sorted(transfer.chunks.items()):
            if position > covered:
                break
            covered = max(covered, end)
        if not message or covered < len(message):
            return
        transfer.finishing = True

        async def finish():
            _check_reply(
                await super(GuardedIRTransmit, self).command(
                    5, seq=transfer.seq, zero=0, expect_reply=False
                )
            )
            matcher.complete(transfer)

        self.create_catching_task(finish())

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None):
        """Reject stale frames and observe validated upstream transfer completion."""
        matcher = _matcher(self.endpoint.device)
        if matcher is None:
            return super().handle_cluster_request(
                hdr, args, dst_addressing=dst_addressing
            )
        if not matcher._active:
            return
        if matcher._keys.capture is not None:
            matcher._keys.handle_frame(hdr, args, dst_addressing)
            return
        transfer = matcher.transfer
        if hdr.command_id in (1, 2, 4):
            if not transfer or transfer.seq is None or args.seq != transfer.seq:
                return
            message = self.endpoint.device.ir_msg_to_send.get(transfer.seq, "")
            if hdr.command_id == 2:
                if not 0 <= args.position < len(message) or not 0 < args.maxlen <= 128:
                    return
                self._chunk_context = (
                    args.position,
                    min(len(message), args.position + args.maxlen),
                )
            elif hdr.command_id == 4:
                transfer.completion_received = True
                self._finish_when_ready(transfer)
                return
        elif hdr.command_id in (0, 3, 5):
            if transfer is not None or not matcher.learning:
                return
            if hdr.command_id == 0:
                if not 0 < args.length <= 16384:
                    return
                matcher.learn_seq = args.seq
            elif args.seq != matcher.learn_seq:
                return
            elif hdr.command_id == 3:
                if (
                    args.position != len(self.ir_msg)
                    or not args.msgpart
                    or args.position + len(args.msgpart) > self.msg_length
                    or sum(args.msgpart) % 256 != args.msgpartcrc
                ):
                    return
            elif hdr.command_id == 5 and (
                not self.msg_length or len(self.ir_msg) != self.msg_length
            ):
                return
            elif hdr.command_id == 5:
                matcher._climate.invalidate_estimate(
                    "已收到新的学习信号；原遥控器可能改变空调，原估计需重新确认。"
                )
        try:
            return super().handle_cluster_request(
                hdr, args, dst_addressing=dst_addressing
            )
        finally:
            self._chunk_context = None


def has_zosung_server_clusters(device: Device) -> bool:
    """Require the actual endpoint 1 transport without guessing its full signature."""
    endpoint = device.endpoints.get(1)
    return (
        endpoint is not None
        and endpoint.profile_id == zha.PROFILE_ID
        and {ZosungIRControl.cluster_id, ZosungIRTransmit.cluster_id}
        <= endpoint.in_clusters.keys()
    )


class ZemismartTS1201IR(CustomZigpyDevice):
    """Provide the per-device state expected by the upstream Zosung clusters."""

    def __init__(self, *args, **kwargs):
        """Initialize the per-device state required by the upstream transport."""
        self.seq = 0
        self.ir_msg_to_send: dict[int, str] = {}
        self.last_learned_ir_code = ""
        super().__init__(*args, **kwargs)

    def next_seq(self) -> int:
        """Use the same unsigned 16-bit sequence as upstream ZosungIRBlaster."""
        matcher = _matcher(self)
        previous = int(matcher.get("transfer_sequence")) if matcher else self.seq
        self.seq = (previous + 1) % 0x10000
        if matcher:
            matcher._update_attribute(2, self.seq)
            if matcher.transfer and matcher.transfer.seq is None:
                matcher.transfer.seq = self.seq
        return self.seq


_builder = (
    QuirkBuilder(MANUFACTURER, MODEL)
    .filter(has_zosung_server_clusters)
    .zigpy_device_class(ZemismartTS1201IR)
    .replaces(GuardedIRControl, endpoint_id=1)
    .replaces(GuardedIRTransmit, endpoint_id=1)
    .adds(IRMatchCluster, endpoint_id=1)
    .command_button(
        command_name="IRLearn",
        cluster_id=ZosungIRControl.cluster_id,
        command_kwargs={"on_off": True},
        unique_id_suffix="learn_ir_code",
        translation_key="learn_ir_code",
        fallback_name="Learn IR code",
    )
    .command_button(
        command_name="IRLearn",
        cluster_id=ZosungIRControl.cluster_id,
        command_kwargs={"on_off": False},
        unique_id_suffix="stop_ir_learning",
        translation_key="stop_ir_learning",
        fallback_name="Stop IR learning",
    )
)

if CODEBOOKS:
    _builder.enum(
        attribute_name="selected_brand",
        enum_class=Brand,
        cluster_id=MATCH_CLUSTER_ID,
        translation_key="ac_brand",
        fallback_name="空调品牌",
    )
    for name, label in [
        ("match_start", "开始匹配"),
        ("match_next", "下一套码"),
        ("match_retry", "重试当前码"),
        ("match_confirm", "确认匹配成功"),
        ("match_cancel", "取消匹配"),
        ("saved_test", "测试已保存码"),
        ("saved_off", "关闭已匹配空调"),
    ]:
        _builder.command_button(
            command_name=name,
            cluster_id=MATCH_CLUSTER_ID,
            translation_key=name,
            fallback_name=label,
            unique_id_suffix=name,
        )
    for name, label in [
        ("match_status", "匹配状态"),
        ("current_candidate", "当前候选码库"),
        ("saved_codebook", "已保存码库"),
    ]:
        _builder.sensor(
            attribute_name=name,
            cluster_id=MATCH_CLUSTER_ID,
            translation_key=name,
            fallback_name=label,
            unique_id_suffix=name,
        )

QUIRK = _builder.add_to_registry()
