#!/usr/bin/env python3
"""Install/roll back the TS1201 pilot files without editing HA configuration.

The default action is a read-only check. Run inside the Home Assistant Python
environment to check its versions; another interpreter cannot verify HA Core.
This checks bundle integrity, not publisher authenticity.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import socket
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MANIFEST = "TS1201_BUNDLE_MANIFEST.json"
BACKUPS = ".ts1201-backups"
LOCK = ".ts1201-install.lock"
GUARD = ".ts1201-install.guard"
BACKUP_ID = r"[0-9]{8}T[0-9]{6}Z_[a-f0-9]{12}"
FINISHED_STATUSES = {"installed", "rolled_back", "failed_restored"}
MAX_BYTES = 16 * 1024 * 1024
VERIFIED_RUNTIME = {
    "python": "3.14.6",
    "homeassistant": "2026.8.0",
    "zha": "2.1.0",
    "zha-quirks": "2.2.0",
    "zigpy": "2.1.0",
}
COMPONENT_FILES = (
    "__init__.py",
    "button.py",
    "climate.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "entity.py",
    "manifest.json",
    "select.py",
    "sensor.py",
    "strings.json",
    "text.py",
    "translations/zh-Hans.json",
)
FILES = {
    "zemismart_ts1201_ir_zha.py": "zha_quirks/zemismart_ts1201_ir_zha.py",
    "data/ts1201-ir-codebooks.json": "zha_quirks/ts1201-ir-codebooks.json",
    "data/ts1201-ir-codebooks-LICENSE.txt": "zha_quirks/ts1201-ir-codebooks-LICENSE.txt",
    **{
        f"custom_components/ts1201_ir/{name}": f"custom_components/ts1201_ir/{name}"
        for name in COMPONENT_FILES
    },
}


class InstallError(Exception):
    """The requested operation cannot be completed safely."""


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(path))


def _safe_path(path: Path, *, directory: bool = False) -> Path:
    """Reject symlinks at every existing level, including the selected root."""
    path = _absolute(path)
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise InstallError(f"拒绝符号链接路径: {part}")
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise InstallError(f"父路径不是目录: {part}")
        if part == path:
            expected = stat.S_ISDIR if directory else stat.S_ISREG
            if not expected(info.st_mode):
                raise InstallError(f"路径类型不符合要求: {part}")
    return path


def _relative(value: object) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise InstallError("清单路径无效")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(p in (".", "..") for p in path.parts)
    ):
        raise InstallError(f"清单路径无效: {value}")
    return value


def _bytes(path: Path) -> bytes:
    _safe_path(path)
    if not path.is_file():
        raise InstallError(f"缺少文件: {path}")
    if path.stat().st_size > MAX_BYTES:
        raise InstallError(f"文件超过大小限制: {path}")
    return path.read_bytes()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _current(path: Path) -> str | None:
    _safe_path(path)
    return _digest(_bytes(path)) if path.exists() else None


def _matches(path: Path, digest: str | None, mode: int | None) -> bool:
    if _current(path) != digest:
        return False
    return digest is None or stat.S_IMODE(path.stat().st_mode) == mode


def _json(path: Path) -> dict:
    try:
        value = json.loads(_bytes(path))
    except (ValueError, UnicodeError) as err:
        raise InstallError(f"JSON 无效: {path}") from err
    if not isinstance(value, dict):
        raise InstallError(f"需要 JSON 对象: {path}")
    return value


def _encode(value: dict) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()


def build_manifest(bundle: Path) -> dict:
    """Used only by the packaging helper, never by installation validation."""
    bundle = _safe_path(bundle, directory=True)
    component = _json(bundle / "custom_components/ts1201_ir/manifest.json")
    if component.get("domain") != "ts1201_ir" or not isinstance(
        component.get("version"), str
    ):
        raise InstallError("集成 domain/version 无效")
    return {
        "schema": 1,
        "product": "ts1201-zha-pilot",
        "component_version": component["version"],
        "verified_runtime": VERIFIED_RUNTIME,
        "files": [
            {
                "source": source,
                "destination": destination,
                "sha256": _digest(_bytes(bundle / source)),
            }
            for source, destination in sorted(FILES.items())
        ],
    }


def validate_bundle(bundle: Path) -> tuple[dict, dict[str, bytes]]:
    bundle = _safe_path(bundle, directory=True)
    manifest = _json(bundle / MANIFEST)
    if (
        manifest.get("schema") != 1
        or manifest.get("product") != "ts1201-zha-pilot"
        or manifest.get("verified_runtime") != VERIFIED_RUNTIME
    ):
        raise InstallError("不支持此安装清单或运行环境基线")
    records = manifest.get("files")
    if not isinstance(records, list) or len(records) != len(FILES):
        raise InstallError("安装清单不完整")
    payload = {}
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise InstallError("安装清单记录无效")
        source = _relative(record.get("source"))
        destination = _relative(record.get("destination"))
        if source in seen or FILES.get(source) != destination:
            raise InstallError(f"安装清单包含未授权或重复路径: {source}")
        seen.add(source)
        content = _bytes(bundle / source)
        if _digest(content) != record.get("sha256"):
            raise InstallError(f"安装包校验失败: {source}")
        payload[destination] = content
    try:
        component = json.loads(payload["custom_components/ts1201_ir/manifest.json"])
    except (ValueError, UnicodeError) as err:
        raise InstallError("集成 manifest.json 无效") from err
    if (
        not isinstance(component, dict)
        or component.get("domain") != "ts1201_ir"
        or not isinstance(component.get("version"), str)
        or component.get("version") != manifest.get("component_version")
    ):
        raise InstallError("集成版本与安装清单不一致")
    return manifest, payload


def runtime_versions() -> dict[str, str | None]:
    result = {"python": ".".join(map(str, sys.version_info[:3]))}
    for name in VERIFIED_RUNTIME:
        if name == "python":
            continue
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def _config_root(config: Path) -> Path:
    config = _safe_path(config, directory=True)
    if not config.is_dir():
        raise InstallError("--config-dir 必须是已存在的 Home Assistant 配置目录")
    marker = _safe_path(config / "configuration.yaml")
    if not marker.is_file():
        raise InstallError(
            "配置目录中缺少 configuration.yaml；不会自动创建或读取其内容"
        )
    _safe_path(config / BACKUPS, directory=True)
    _safe_path(config / LOCK, directory=True)
    _safe_path(config / GUARD)
    return config


def _transactions(config: Path) -> list[dict]:
    """Report incomplete journals without treating their files as a new baseline."""
    root = config / BACKUPS
    if not root.exists():
        return []
    pending = []
    for directory in sorted(root.iterdir()):
        if not re.fullmatch(BACKUP_ID, directory.name):
            continue
        _safe_path(directory, directory=True)
        path = directory / "transaction.json"
        if not path.exists():
            # All backup copies are written before the journal and any targets.
            continue
        try:
            journal = _json(path)
            status = journal.get("status", "unknown")
            if isinstance(status, str) and status in FINISHED_STATUSES:
                continue
            pending.append({"backup_id": directory.name, "status": status})
        except (InstallError, OSError) as err:
            pending.append(
                {"backup_id": directory.name, "status": "unreadable", "error": str(err)}
            )
    return pending


def _lock_state(config: Path) -> dict:
    lock = config / LOCK
    if not lock.exists():
        return {"state": "absent"}
    owner_path = lock / "owner.json"
    if not owner_path.exists():
        return {"state": "legacy_or_incomplete", "recovery_requires_confirmation": True}
    try:
        owner = _json(owner_path)
        if (
            owner.get("schema") != 1
            or type(owner.get("pid")) is not int
            or owner["pid"] <= 0
            or not isinstance(owner.get("hostname"), str)
        ):
            raise InstallError("锁归属记录无效")
        state = "unknown_host"
        if owner["hostname"] == socket.gethostname():
            try:
                os.kill(owner["pid"], 0)
                state = "active_or_pid_reused"
            except ProcessLookupError:
                state = "stale"
            except PermissionError:
                state = "active_or_inaccessible"
        return {"state": state, "owner": owner}
    except (InstallError, OSError) as err:
        return {"state": "unreadable", "error": str(err)}


def preflight(
    config: Path,
    bundle: Path,
    *,
    allow_unverified: bool = False,
    runtime: dict | None = None,
) -> tuple[dict, dict[str, bytes]]:
    config = _config_root(config)
    manifest, payload = validate_bundle(bundle)
    runtime = runtime_versions() if runtime is None else runtime
    mismatches = {
        name: {"expected": expected, "observed": runtime.get(name)}
        for name, expected in VERIFIED_RUNTIME.items()
        if runtime.get(name) != expected
    }
    if mismatches and not allow_unverified:
        raise InstallError(
            "当前 Python 进程不是已验证的 HA 运行环境: "
            + json.dumps(mismatches, ensure_ascii=False)
            + "。请在 HA Core Python 环境检查；SSH 插件的 Python 不能代表 HA Core。"
            "明确接受未验证版本时可使用 --allow-unverified-runtime。"
        )
    changes = []
    unchanged = []
    for destination, content in payload.items():
        current = _current(config / destination)
        (unchanged if current == _digest(content) else changes).append(destination)
    installed_path = config / "custom_components/ts1201_ir/manifest.json"
    installed_version = (
        _json(installed_path).get("version") if installed_path.exists() else None
    )
    unknown_files = []
    component_dir = config / "custom_components/ts1201_ir"
    if component_dir.exists():
        for current_dir, directories, filenames in os.walk(
            component_dir, followlinks=False
        ):
            directories[:] = [name for name in directories if name != "__pycache__"]
            for filename in filenames:
                relative = (Path(current_dir) / filename).relative_to(config).as_posix()
                if relative not in FILES.values() and not filename.endswith(".pyc"):
                    unknown_files.append(relative)
    pending = _transactions(config)
    lock = _lock_state(config)
    return {
        "action": "check",
        "component_version": manifest["component_version"],
        "installed_component_version": installed_version,
        "unmanaged_component_files_preserved": sorted(unknown_files),
        "config_dir": str(config),
        "runtime_scope": "installer_python_process_only",
        "runtime": runtime,
        "runtime_verified": not mismatches,
        "runtime_mismatches": mismatches,
        "changes": changes,
        "unchanged": unchanged,
        "pending_transactions": pending,
        "install_blocked_by_pending_transaction": bool(pending),
        "lock": lock,
        "notes": [
            "仅检查此 Python 进程的依赖版本，不能证明正在运行的 HA 服务使用同一环境。",
            "安装程序不修改 configuration.yaml、.storage、zigbee.db 或其他设备适配文件。",
            "安装后需检查 ZHA custom_quirks_path 设置并重启 HA Core；本工具不会重启或发射红外。",
            "代码备份不包含已学习按键；升级前另行创建完整 Home Assistant 备份。",
            "存在未完成事务时先 recover --config-dir <配置目录> --backup-id <原备份 ID>，不要直接重新安装。",
        ],
    }, payload


def _write_atomic(path: Path, content: bytes, mode: int = 0o644) -> None:
    _safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".ts1201-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        _safe_path(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _clear_stale_lock(config: Path, *, confirm_legacy: bool) -> None:
    state = _lock_state(config)
    if state["state"] == "absent":
        return
    if state["state"] != "stale" and not (
        state["state"] == "legacy_or_incomplete" and confirm_legacy
    ):
        raise InstallError(
            "不能清理安装/回滚锁: "
            + json.dumps(state, ensure_ascii=False)
            + "。活进程、未知主机或损坏归属记录不会被覆盖；"
            "旧版空锁仅在确认原操作已结束后使用 --confirm-legacy-stale-lock。"
        )
    lock = config / LOCK
    children = list(lock.iterdir())
    for child in children:
        if child.name != "owner.json" and not re.fullmatch(
            r"\.ts1201-[a-z0-9_]{8}", child.name
        ):
            raise InstallError("锁目录包含未知文件，拒绝清理")
        _safe_path(child)
    # An atomic owner.json update can leave its temporary file after SIGKILL.
    for child in children:
        if child.name != "owner.json":
            child.unlink()
    owner = lock / "owner.json"
    if owner.exists():
        _safe_path(owner)
        owner.unlink()
    lock.rmdir()


@contextmanager
def _locked(
    config: Path,
    *,
    action: str,
    backup_id: str | None = None,
    recover_stale: bool = False,
    confirm_legacy: bool = False,
):
    # Keep this inode: unlinking it would let a second process lock a new inode.
    guard = _safe_path(config / GUARD)
    descriptor = os.open(guard, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as err:
            raise InstallError("已有进行中的安装/回滚/恢复操作，不能清理活锁") from err
        with _directory_lock(
            config,
            action=action,
            backup_id=backup_id,
            recover_stale=recover_stale,
            confirm_legacy=confirm_legacy,
        ) as owner:
            yield owner
    finally:
        os.close(descriptor)


@contextmanager
def _directory_lock(config: Path, **options):
    lock = _safe_path(config / LOCK, directory=True)
    if options["recover_stale"]:
        _clear_stale_lock(config, confirm_legacy=options["confirm_legacy"])
    try:
        lock.mkdir()
    except FileExistsError as err:
        raise InstallError(
            "已有安装/回滚锁；先运行 check 查看归属，再用 recover 恢复原事务"
        ) from err
    owner = {
        "schema": 1,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "action": options["action"],
        "backup_id": options["backup_id"],
    }
    try:
        _write_atomic(lock / "owner.json", _encode(owner), 0o600)
        yield owner
    finally:
        owner_path = lock / "owner.json"
        if owner_path.exists():
            owner_path.unlink()
        lock.rmdir()


def _restore_entry(config: Path, backup: Path, entry: dict) -> None:
    target = config / entry["destination"]
    if entry["before_sha256"] is None:
        _safe_path(target)
        if target.exists():
            target.unlink()
    else:
        original = _bytes(backup / "files" / entry["destination"])
        if _digest(original) != entry["before_sha256"]:
            raise InstallError(f"备份校验失败: {entry['destination']}")
        _write_atomic(target, original, entry["before_mode"])


def _entry_state(config: Path, entry: dict) -> str:
    target = config / entry["destination"]
    if _matches(target, entry["before_sha256"], entry["before_mode"]):
        return "before"
    if _matches(target, entry["after_sha256"], entry["after_mode"]):
        return "after"
    return "conflict"


def _recover_entries(config: Path, backup: Path, entries: list[dict]) -> list[str]:
    """Recover by observed state, including an interrupted atomic replacement."""
    errors = []
    for entry in reversed(entries):
        try:
            state = _entry_state(config, entry)
            if state == "before":
                continue
            if state != "after":
                raise InstallError("文件内容或权限已被其他进程修改，拒绝覆盖")
            _restore_entry(config, backup, entry)
        except (InstallError, OSError, KeyboardInterrupt) as err:
            # The restore itself may have completed before an exception arrived.
            try:
                restored = _entry_state(config, entry) == "before"
            except (InstallError, OSError):
                restored = False
            if not restored:
                errors.append(f"{entry['destination']}: {err}")
    # Never advertise successful recovery based solely on attempted operations.
    for entry in entries:
        try:
            if _entry_state(config, entry) != "before":
                errors.append(f"{entry['destination']}: 恢复后的内容或权限不匹配")
        except (InstallError, OSError) as err:
            errors.append(f"{entry['destination']}: 无法验证恢复结果: {err}")
    return errors


def install(
    config: Path,
    bundle: Path,
    *,
    allow_unverified: bool = False,
    runtime: dict | None = None,
) -> dict:
    config = _config_root(config)
    with _locked(config, action="install") as owner:
        report, payload = preflight(
            config, bundle, allow_unverified=allow_unverified, runtime=runtime
        )
        if report["pending_transactions"]:
            raise InstallError(
                "存在未完成事务，不能以当前文件建立新备份基线；先 recover --backup-id <原备份 ID>: "
                + json.dumps(report["pending_transactions"], ensure_ascii=False)
            )
        if not report["changes"]:
            return {
                **report,
                "action": "install",
                "status": "already_installed",
                "backup_id": None,
            }
        backup_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")
            + uuid.uuid4().hex[:12]
        )
        backup = config / BACKUPS / backup_id
        _safe_path(backup, directory=True)
        backup.mkdir(parents=True)
        entries = []
        for destination in report["changes"]:
            target = config / destination
            before = _current(target)
            mode = stat.S_IMODE(target.stat().st_mode) if before is not None else None
            if before is not None:
                content = _bytes(target)
                if _digest(content) != before:
                    raise InstallError(f"备份期间文件发生变化: {destination}")
                _write_atomic(backup / "files" / destination, content, mode)
            entries.append(
                {
                    "destination": destination,
                    "before_sha256": before,
                    "before_mode": mode,
                    "after_sha256": _digest(payload[destination]),
                    "after_mode": mode if mode is not None else 0o644,
                }
            )
        journal = {
            "schema": 1,
            "product": "ts1201-zha-pilot",
            "backup_id": backup_id,
            "component_version": report["component_version"],
            "status": "installing",
            "entries": entries,
        }
        _write_atomic(backup / "transaction.json", _encode(journal), 0o600)
        owner["backup_id"] = backup_id
        _write_atomic(config / LOCK / "owner.json", _encode(owner), 0o600)
        try:
            for entry in entries:
                target = config / entry["destination"]
                if not _matches(target, entry["before_sha256"], entry["before_mode"]):
                    raise InstallError(f"安装期间文件发生变化: {entry['destination']}")
                _write_atomic(
                    target, payload[entry["destination"]], entry["after_mode"]
                )
            journal["status"] = "installed"
            _write_atomic(backup / "transaction.json", _encode(journal), 0o600)
        except BaseException as err:
            recovery_errors = _recover_entries(config, backup, entries)
            journal["status"] = (
                "recovery_failed" if recovery_errors else "failed_restored"
            )
            journal["recovery_errors"] = recovery_errors
            try:
                _write_atomic(backup / "transaction.json", _encode(journal), 0o600)
            except (InstallError, OSError) as journal_err:
                recovery_errors.append(f"transaction.json: {journal_err}")
            raise InstallError(
                f"安装失败: {err}; 自动恢复: {recovery_errors or '成功'}; 备份: {backup_id}"
            ) from err
    return {
        **report,
        "action": "install",
        "status": "installed_restart_required",
        "backup_id": backup_id,
    }


def _backup(config: Path, backup_id: str) -> tuple[Path, dict]:
    if not re.fullmatch(BACKUP_ID, backup_id):
        raise InstallError("备份 ID 无效")
    backup = _safe_path(config / BACKUPS / backup_id, directory=True)
    journal = _json(backup / "transaction.json")
    if (
        journal.get("schema") != 1
        or journal.get("product") != "ts1201-zha-pilot"
        or journal.get("backup_id") != backup_id
        or not isinstance(journal.get("entries"), list)
    ):
        raise InstallError("备份事务清单无效")
    seen = set()
    for entry in journal["entries"]:
        if not isinstance(entry, dict):
            raise InstallError("备份事务记录无效")
        destination = _relative(entry.get("destination"))
        if destination not in FILES.values() or destination in seen:
            raise InstallError("备份清单包含未授权或重复路径")
        seen.add(destination)
        for field in ("before_sha256", "after_sha256"):
            value = entry.get(field)
            if field == "before_sha256" and value is None:
                continue
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                raise InstallError("备份哈希无效")
        if (
            type(entry.get("after_mode")) is not int
            or not 0 <= entry["after_mode"] <= 0o7777
        ):
            raise InstallError("安装文件权限无效")
        if entry["before_sha256"] is not None:
            mode = entry.get("before_mode")
            if type(mode) is not int or not 0 <= mode <= 0o7777:
                raise InstallError("备份文件权限无效")
            if (
                _digest(_bytes(backup / "files" / destination))
                != entry["before_sha256"]
            ):
                raise InstallError(f"备份校验失败: {destination}")
    return backup, journal


def _rollback_locked(config: Path, backup_id: str) -> dict:
    backup, journal = _backup(config, backup_id)
    entries = journal["entries"]
    restore = []
    for entry in entries:
        state = _entry_state(config, entry)
        if state == "before":
            continue  # Idempotent retry after an interrupted rollback.
        if state != "after":
            raise InstallError(
                f"安装后文件已修改，回滚已停止且未写入: {entry['destination']}"
            )
        restore.append(entry)
    journal["status"] = "rolling_back"
    _write_atomic(backup / "transaction.json", _encode(journal), 0o600)
    errors = _recover_entries(config, backup, entries)
    if errors:
        raise InstallError(
            f"回滚尚未完成: {errors}。不要重启 HA；解决文件写入问题后使用同一备份 ID 重试: {backup_id}"
        )
    journal["status"] = "rolled_back"
    _write_atomic(backup / "transaction.json", _encode(journal), 0o600)
    return {
        "action": "rollback",
        "status": "rolled_back_restart_required",
        "backup_id": backup_id,
        "restored_files": len(restore),
        "notes": ["已学习按键和 HA 配置未被修改。代码回滚后需要重启 HA Core。"],
    }


def rollback(config: Path, backup_id: str) -> dict:
    config = _config_root(config)
    with _locked(config, action="rollback", backup_id=backup_id):
        return _rollback_locked(config, backup_id)


def recover(
    config: Path,
    backup_id: str | None = None,
    *,
    confirm_legacy: bool = False,
) -> dict:
    config = _config_root(config)
    with _locked(
        config,
        action="recover",
        backup_id=backup_id,
        recover_stale=True,
        confirm_legacy=confirm_legacy,
    ):
        if backup_id:
            return {**_rollback_locked(config, backup_id), "action": "recover"}
        pending = _transactions(config)
        if pending:
            raise InstallError(
                "恢复未完成事务需要 --backup-id: "
                + json.dumps(pending, ensure_ascii=False)
            )
        return {
            "action": "recover",
            "status": "stale_lock_cleared_no_files_restored",
            "notes": ["只清理遗留锁，未恢复代码；需要回滚时指定原备份 ID。"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        choices=("check", "install", "rollback", "recover"),
        default="check",
    )
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument(
        "--bundle-dir", type=Path, default=Path(__file__).absolute().parent.parent
    )
    parser.add_argument("--allow-unverified-runtime", action="store_true")
    parser.add_argument("--backup-id")
    parser.add_argument("--confirm-legacy-stale-lock", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.confirm_legacy_stale_lock and args.action != "recover":
            parser.error("--confirm-legacy-stale-lock is only valid with recover")
        if args.action == "recover":
            result = recover(
                args.config_dir,
                args.backup_id,
                confirm_legacy=args.confirm_legacy_stale_lock,
            )
        elif args.action == "rollback":
            if not args.backup_id:
                parser.error("rollback requires --backup-id")
            result = rollback(args.config_dir, args.backup_id)
        elif args.action == "install":
            result = install(
                args.config_dir,
                args.bundle_dir,
                allow_unverified=args.allow_unverified_runtime,
            )
        else:
            result, _ = preflight(
                args.config_dir,
                args.bundle_dir,
                allow_unverified=args.allow_unverified_runtime,
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (InstallError, OSError) as err:
        print(f"TS1201: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
