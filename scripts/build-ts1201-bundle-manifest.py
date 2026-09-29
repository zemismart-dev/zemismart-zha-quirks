#!/usr/bin/env python3
"""Build the delivery manifest after copying final TS1201 files into a bundle."""

import argparse
import importlib.util
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "ts1201_install", Path(__file__).with_name("ts1201-install.py")
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    manifest = installer.build_manifest(args.bundle_dir)
    path = args.bundle_dir / installer.MANIFEST
    installer._write_atomic(path, installer._encode(manifest))
    print(
        f"Created {path.name}: {len(manifest['files'])} files, component {manifest['component_version']}"
    )


if __name__ == "__main__":
    main()
