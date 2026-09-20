from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


VIEWER_RE = re.compile(r"/(?:productViewer|productviewer)/([^/?#]+)")


def obs_id_from_url(url):
    match = VIEWER_RE.search(str(url or ""))
    return match.group(1) if match else None


def project_code_from_obs_id(obs_id):
    return re.split(r"(?:\.sb|_sb)", obs_id, maxsplit=1, flags=re.IGNORECASE)[0]


def find_historical_ms(row, extracted_root):
    calibrator_id = str(row.get("name") or "").strip()
    expected = Path(extracted_root) / calibrator_id / calibrator_id / (calibrator_id + ".ms")
    if expected.is_dir():
        return expected.resolve()
    recorded = Path(str(row.get("extracted_ms") or ""))
    if recorded.is_dir() and recorded.name == calibrator_id + ".ms":
        return recorded.resolve()
    candidates = sorted(
        path for path in (Path(extracted_root) / calibrator_id).glob("**/%s.ms" % calibrator_id)
        if path.is_dir()
    )
    return candidates[0].resolve() if candidates else None


def build_inventory(csv_path, extracted_root):
    inventory = {}
    with Path(csv_path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            calibrator_id = str(row.get("name") or "").strip()
            if not calibrator_id or calibrator_id == "z":
                continue
            extracted_ms = find_historical_ms(row, extracted_root)
            if extracted_ms is None:
                continue
            obs_id = obs_id_from_url(row.get("access_url"))
            if not obs_id:
                raise ValueError("Downloaded calibrator %s has no obs_id" % calibrator_id)
            metadata = {
                "project_code": project_code_from_obs_id(obs_id),
                "calibrator_id": calibrator_id,
                "gain_calibrator_name": str(row.get("gain_calibrator_name") or "").strip(),
                "historical_extracted_path": str(extracted_ms),
                "calibrator_ids": [calibrator_id],
                "gain_calibrator_names": [str(row.get("gain_calibrator_name") or "").strip()],
                "historical_extracted_paths": [str(extracted_ms)],
            }
            if obs_id not in inventory:
                inventory[obs_id] = metadata
                continue
            existing = inventory[obs_id]
            existing["calibrator_ids"] = sorted(set(existing["calibrator_ids"] + metadata["calibrator_ids"]))
            existing["gain_calibrator_names"] = sorted(
                name for name in set(existing["gain_calibrator_names"] + metadata["gain_calibrator_names"]) if name
            )
            existing["historical_extracted_paths"] = sorted(
                set(existing["historical_extracted_paths"] + metadata["historical_extracted_paths"])
            )
            existing["calibrator_id"] = existing["calibrator_ids"][0]
            existing["gain_calibrator_name"] = (
                existing["gain_calibrator_names"][0] if existing["gain_calibrator_names"] else ""
            )
            existing["historical_extracted_path"] = existing["historical_extracted_paths"][0]
    return dict(sorted(inventory.items()))


def _frozenset_lines(name, values):
    lines = [name + " = frozenset({"]
    lines.extend("    %r," % value for value in sorted(values))
    lines.append("})")
    return lines


def render_inventory(inventory, csv_path, extracted_root):
    lines = [
        '"""Generated downloaded-inventory snapshot; do not edit by hand."""',
        "",
        "# Source CSV: %s" % Path(csv_path).resolve(),
        "# Reconciled extracted root: %s" % Path(extracted_root).resolve(),
        "",
    ]
    lines.extend(_frozenset_lines("ALREADY_DOWNLOADED_OBS_IDS", inventory))
    lines.append("")
    lines.extend(
        _frozenset_lines(
            "ALREADY_DOWNLOADED_CALIBRATOR_IDS",
            (
                calibrator_id
                for metadata in inventory.values()
                for calibrator_id in metadata["calibrator_ids"]
            ),
        )
    )
    lines.append("")
    lines.extend(
        _frozenset_lines(
            "ALREADY_DOWNLOADED_GAIN_FIELDS",
            (
                name
                for metadata in inventory.values()
                for name in metadata["gain_calibrator_names"]
                if name
            ),
        )
    )
    lines.extend(["", "DOWNLOADED_BY_OBS_ID = {"])
    for obs_id, metadata in inventory.items():
        lines.append("    %r: {" % obs_id)
        for key in (
            "project_code",
            "calibrator_id",
            "gain_calibrator_name",
            "historical_extracted_path",
            "calibrator_ids",
            "gain_calibrator_names",
            "historical_extracted_paths",
        ):
            lines.append("        %r: %r," % (key, metadata[key]))
        lines.append("    },")
    lines.extend(["}", ""])
    return "\n".join(lines)


def generate_inventory(csv_path, extracted_root, output_path):
    inventory = build_inventory(csv_path, extracted_root)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_inventory(inventory, csv_path, extracted_root))
    return inventory


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("small_selection_csv")
    parser.add_argument("extracted_root")
    parser.add_argument(
        "--output",
        default=Path(__file__).with_name("downloaded_inventory.py"),
        type=Path,
    )
    args = parser.parse_args(argv)
    inventory = generate_inventory(args.small_selection_csv, args.extracted_root, args.output)
    print("Wrote %d downloaded observations to %s" % (len(inventory), args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
