from __future__ import annotations

import json
import re
from pathlib import Path


FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
FIT_RE = re.compile(
    r"(?P<field>\S+)\s+(?P<band>[A-Za-z]+)\s+fitted spectral index\s*&\s*SNR\s*=\s*"
    r"(?P<spix>%s)\s+(?P<snr>%s)" % (FLOAT_RE, FLOAT_RE),
    re.IGNORECASE,
)


def _argument(text, name, pattern):
    match = re.search(r"\b%s\s*=\s*%s" % (re.escape(name), pattern), text, re.IGNORECASE)
    return match.group(1) if match else None


def _candidate_files(download_root):
    root = Path(download_root)
    paths = []
    paths.extend(sorted(root.glob("**/stage*/casapy.log")))
    paths.extend(sorted(root.glob("**/stage*/*.log")))
    paths.extend(sorted(root.glob("**/stage*/*.html")))
    paths.extend(sorted(root.glob("**/weblog*/**/*.log")))
    paths.extend(sorted(root.glob("**/weblog*/**/*.html")))
    paths.extend(sorted(root.glob("**/casa_commands.log")))
    seen = set()
    for path in paths:
        resolved = str(path.resolve())
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            yield path


def _source_stage(path):
    for parent in (path,) + tuple(path.parents):
        if re.fullmatch(r"stage\d+", parent.name, re.IGNORECASE):
            return parent.name
    return "top-level"


def parse_flux_text(text, gain_calibrator_name, source_file="", band=None):
    lines = text.splitlines()
    fits = []
    for line in lines:
        match = FIT_RE.search(line)
        if match and match.group("field") == gain_calibrator_name:
            fits.append(match.groupdict())

    for line in lines:
        if "setjy(" not in line.lower() or gain_calibrator_name not in line:
            continue
        field = _argument(line, "field", r"['\"]([^'\"]+)['\"]")
        if field != gain_calibrator_name:
            continue
        flux = _argument(line, "fluxdensity", r"\[\s*(%s)" % FLOAT_RE)
        spix = _argument(line, "spix", r"(%s)" % FLOAT_RE)
        reffreq = _argument(line, "reffreq", r"['\"]\s*(%s)\s*([GMK]?Hz)['\"]" % FLOAT_RE)
        reffreq_match = re.search(
            r"\breffreq\s*=\s*['\"]\s*(%s)\s*([GMK]?Hz)['\"]" % FLOAT_RE,
            line,
            re.IGNORECASE,
        )
        if flux is None or spix is None or reffreq_match is None:
            continue
        value = float(reffreq_match.group(1))
        unit = reffreq_match.group(2).lower()
        scale = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}[unit]
        fit = fits[-1] if fits else {}
        return {
            "status": "available",
            "gain_calibrator_name": gain_calibrator_name,
            "band": fit.get("band") or band,
            "stokes_i_jy": float(flux),
            "reference_frequency_ghz": value * scale,
            "spectral_index": float(spix),
            "fit_snr": float(fit["snr"]) if fit.get("snr") else None,
            "source_stage": _source_stage(Path(source_file)) if source_file else None,
            "source_file": str(source_file),
            "source_text": line.strip(),
        }
    return None


def find_flux_estimate(download_root, gain_calibrator_name, band=None):
    for path in _candidate_files(download_root):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        result = parse_flux_text(text, gain_calibrator_name, source_file=path, band=band)
        if result is not None:
            return result
    return {
        "status": "unavailable",
        "gain_calibrator_name": gain_calibrator_name,
        "band": band,
        "stokes_i_jy": None,
        "reference_frequency_ghz": None,
        "spectral_index": None,
        "fit_snr": None,
        "source_stage": None,
        "source_file": None,
        "source_text": None,
    }


def write_flux_estimate(result, path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
