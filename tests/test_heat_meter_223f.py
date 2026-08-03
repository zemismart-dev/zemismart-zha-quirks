"""Regression tests for the DN15-223F ZHA quirk."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from zha.quirks import ModelInfo
import zhaquirks
from zigpy.quirks.v2.homeassistant.sensor import SensorStateClass


QUIRK_PATH = Path(__file__).parents[1] / "223f.py"
SPEC = importlib.util.spec_from_file_location("heat_meter_223f", QUIRK_PATH)
assert SPEC is not None and SPEC.loader is not None
QUIRK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUIRK)

MODEL_INFO = ModelInfo("_TZE200_jt50ea5d", "TS0601")
ENTRY = next(
    entry
    for entry in zhaquirks.ZHA_DEVICE_REGISTRY
    if MODEL_INFO in entry.device_match.applies_to
)
CLUSTER = next(
    transform.cluster
    for transform in ENTRY.zigpy_transforms
    if hasattr(getattr(transform, "cluster", None), "dp_to_attribute")
)
MAPPINGS = CLUSTER.dp_to_attribute


class HeatMeter223FTest(unittest.TestCase):
    """Validate the supplier DP contract and captured real-device payloads."""

    def test_all_supplier_datapoints_are_mapped(self) -> None:
        self.assertEqual(
            set(MAPPINGS),
            {1, 2, 3, 4, 5, 7, 8, 16, 19, 21, 22, 24},
        )

    def test_captured_read_only_values(self) -> None:
        self.assertEqual(MAPPINGS[1][0].converter(1234), 12340)
        self.assertEqual(
            MAPPINGS[2][0].converter(bytes.fromhex("1a071a0700004fa2")),
            20.386,
        )
        self.assertEqual(
            MAPPINGS[3][0].converter(bytes.fromhex("071f071f000003e8")),
            1.0,
        )
        self.assertEqual(MAPPINGS[5][0].converter(0), "OK")
        self.assertEqual(MAPPINGS[8][0].converter(1234), 12.34)
        self.assertEqual(
            MAPPINGS[16][0].converter(
                bytes.fromhex("3030303030303236303131343031")
            ),
            "00000026011401",
        )
        self.assertEqual(
            MAPPINGS[19][0].converter(bytes.fromhex("00002574")),
            9588,
        )
        self.assertEqual(MAPPINGS[21][0].converter(2469), 24.69)
        self.assertEqual(MAPPINGS[22][0].converter(2473), 24.73)
        self.assertEqual(MAPPINGS[24][0].converter(367), 3.67)

    def test_malformed_raw_values_do_not_become_zero(self) -> None:
        self.assertIsNone(QUIRK.decode_uint32(b"\x00\x01"))
        self.assertIsNone(QUIRK.decode_uint32("not-a-number"))
        self.assertIsNone(QUIRK.decode_raw_volume(b"\x00\x00\x00\x01"))
        self.assertIsNone(QUIRK.decode_hundredths(None))
        self.assertIsNone(QUIRK.decode_meter_id(b"\xff"))

    def test_fault_bitmap_preserves_unknown_bits(self) -> None:
        self.assertEqual(
            QUIRK.decode_faults(0x1001),
            "battery_alarm, transducer_alarm",
        )
        self.assertEqual(QUIRK.decode_faults(0x2000), "unknown_bits_0x2000")
        self.assertEqual(QUIRK.decode_faults("invalid"), "invalid")

    def test_write_datapoint_types_and_report_period_values(self) -> None:
        attributes = CLUSTER.attributes_by_name
        self.assertIs(attributes["report_period"].type, QUIRK.ReportPeriod)
        self.assertEqual(attributes["heat_metering_enabled"].type.__name__, "Bool")
        self.assertEqual(QUIRK.ReportPeriod.Hour_12, 0x06)
        self.assertEqual(QUIRK.ReportPeriod.Hour_24, 0x07)

    def test_daily_and_monthly_entities_have_correct_identity(self) -> None:
        metadata = {
            item.attribute_name: item
            for item in ENTRY.zha_device_factory.quirk_definition.entity_metadata
            if item.attribute_name
            in {"daily_water_consumption", "monthly_water_consumption"}
        }
        self.assertEqual(
            metadata["daily_water_consumption"].unique_id_suffix,
            "daily_water_usage",
        )
        self.assertEqual(
            metadata["monthly_water_consumption"].unique_id_suffix,
            "monthly_water_usage",
        )
        self.assertIs(
            metadata["daily_water_consumption"].state_class,
            SensorStateClass.TOTAL,
        )
        self.assertIs(
            metadata["monthly_water_consumption"].state_class,
            SensorStateClass.TOTAL,
        )


if __name__ == "__main__":
    unittest.main()
