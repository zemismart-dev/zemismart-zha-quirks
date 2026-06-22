"""Matter User Label writer for screen-switch endpoint names."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, WSMsgType

_LOGGER = logging.getLogger(__name__)

MATTER_SERVER = "core-matter-server"
MATTER_PORT = 5580
RECV_TIMEOUT = 5

USER_LABEL_CLUSTER_ID = 0x0041
LABEL_LIST_ATTRIBUTE_ID = 0x0000


def _matter_node_id_from_device_entry(device_entry: Any) -> int | None:
    """Extract the Matter node id from a HA device registry entry."""

    for domain, identifier in getattr(device_entry, "identifiers", set()):
        if domain != "matter":
            continue

        raw_id = str(identifier)
        if "MatterNodeDevice" not in raw_id:
            continue

        parts = raw_id.split("-")
        if len(parts) < 3:
            continue

        try:
            return int(parts[-2], 16)
        except ValueError:
            _LOGGER.debug("Could not parse Matter node id from identifier=%s", raw_id)

    return None


def _matter_endpoint_from_unique_id(unique_id: str | None) -> int | None:
    """Extract endpoint id from a Matter entity unique id when available."""

    if not unique_id:
        return None

    parts = str(unique_id).split("-")
    try:
        device_marker_index = parts.index("MatterNodeDevice")
    except ValueError:
        return None

    endpoint_index = device_marker_index + 1
    if endpoint_index >= len(parts):
        return None

    try:
        endpoint_id = int(parts[endpoint_index])
    except ValueError:
        return None

    return endpoint_id if endpoint_id > 0 else None


def _matter_endpoint_from_entity_id(entity_id: str) -> int:
    """Fallback endpoint inference for older Matter entity ids."""

    tail = entity_id.rsplit(".", 1)[-1]
    parts = tail.split("_")
    for value in reversed(parts):
        if value.isdigit():
            endpoint_id = int(value)
            return ((endpoint_id - 1) % 4) + 1

    return 1


async def _send_json(ws, message: dict[str, Any]) -> None:
    """Send a JSON command to the Matter Server."""

    _LOGGER.debug(
        "Sending Matter Server message: %s",
        json.dumps(message, ensure_ascii=False),
    )
    await ws.send_json(message)


async def _recv_json(ws, expected_id: str, timeout: int) -> dict[str, Any] | None:
    """Receive the response matching a Matter Server message id."""

    while True:
        try:
            message = await asyncio.wait_for(ws.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timed out waiting for Matter Server response message_id=%s",
                expected_id,
            )
            return None

        if message.type == WSMsgType.TEXT:
            data = json.loads(message.data)
            if str(data.get("message_id")) == expected_id:
                _LOGGER.debug(
                    "Received Matter Server response: %s",
                    json.dumps(data, ensure_ascii=False),
                )
                return data

            _LOGGER.debug(
                "Ignoring non-target Matter Server message: %s",
                json.dumps(data, ensure_ascii=False),
            )
            continue

        if message.type in (WSMsgType.CLOSED, WSMsgType.CLOSE, WSMsgType.ERROR):
            _LOGGER.warning(
                "Matter Server websocket closed while waiting for message_id=%s",
                expected_id,
            )
            return None


async def write_matter_user_label(
    hass,
    *,
    node_id: int,
    endpoint_id: int,
    name: str,
) -> bool:
    """Write a Matter User Label value to one endpoint."""

    attribute_path = (
        f"{endpoint_id}/{USER_LABEL_CLUSTER_ID}/{LABEL_LIST_ATTRIBUTE_ID}"
    )
    label_value = [{"label": "room", "value": str(name)}]
    uri = f"ws://{MATTER_SERVER}:{MATTER_PORT}/ws"

    try:
        async with ClientSession() as session:
            async with session.ws_connect(uri) as ws:
                read_msg_id = f"read_label_node{node_id}_ep{endpoint_id}"
                await _send_json(
                    ws,
                    {
                        "message_id": read_msg_id,
                        "command": "read_attribute",
                        "args": {
                            "node_id": node_id,
                            "attribute_path": attribute_path,
                        },
                    },
                )
                await _recv_json(ws, read_msg_id, RECV_TIMEOUT)

                write_msg_id = f"write_label_node{node_id}_ep{endpoint_id}"
                await _send_json(
                    ws,
                    {
                        "message_id": write_msg_id,
                        "command": "write_attribute",
                        "args": {
                            "node_id": node_id,
                            "attribute_path": attribute_path,
                            "value": label_value,
                        },
                    },
                )
                write_resp = await _recv_json(ws, write_msg_id, RECV_TIMEOUT)
    except (ClientError, TimeoutError, OSError, json.JSONDecodeError) as err:
        _LOGGER.warning(
            "Could not write Matter User Label node=%s endpoint=%s name=%s: %s",
            node_id,
            endpoint_id,
            name,
            err,
        )
        return False

    if write_resp is None:
        return False

    _LOGGER.info(
        "Matter User Label sent: node=%s endpoint=%s name=%s",
        node_id,
        endpoint_id,
        name,
    )
    return True


async def handle_matter_name_update(
    hass,
    entity_id: str,
    device_entry,
    new_name: str,
    *,
    endpoint_id: int | None = None,
    unique_id: str | None = None,
) -> bool:
    """Handle a HA entity-name update by writing a Matter User Label."""

    node_id = _matter_node_id_from_device_entry(device_entry)
    if node_id is None:
        _LOGGER.debug("Device for %s is not a Matter node device", entity_id)
        return False

    resolved_endpoint = (
        endpoint_id
        or _matter_endpoint_from_unique_id(unique_id)
        or _matter_endpoint_from_entity_id(entity_id)
    )

    return await write_matter_user_label(
        hass,
        node_id=node_id,
        endpoint_id=resolved_endpoint,
        name=str(new_name),
    )
