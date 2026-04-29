from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ArchiveQueryRow(TypedDict, total=False):
    obs_publisher_did: str
    project_code: str
    target_name: str
    t_min: float
    t_max: float
    t_exptime: float
    instrument_name: str
    configuration: str
    dataproduct_type: str
    freq_min: float
    freq_max: float
    em_min: float
    em_max: float
    s_ra: float
    s_dec: float
    access_estsize: float
    access_url: str
    access_format: str
    proprietary_status: str
    pol_states: str
    calib_level: int
    num_antennas: int
    max_uv_dist: float
    spw_names: str
    center_frequencies: str
    bandwidths: str
    nums_channels: str
    spectral_resolutions: str
    aggregate_bandwidth: float


class ArchiveExecutionBlock(TypedDict, total=False):
    sdm_id: str
    project_code: str
    obs_start: str
    obs_stop: float
    cal_status: str
    band_code: str
    num_antennas: int
    configuration: str
    instrument_name: str
    alma_ous_id: Optional[str]
    legacy_id: Optional[str]
    access_estsize: float
    cals: List[Dict[str, Any]]
    configurations: List[Dict[str, Any]]
    scan_rows: List[Dict[str, Any]]


class ArchiveDetailsContainer(TypedDict, total=False):
    dataset_title: str
    execution_blocks: List[ArchiveExecutionBlock]


class ArchiveDetailsPayload(TypedDict, total=False):
    details: ArchiveDetailsContainer


class ManifestEntry(TypedDict, total=False):
    project_code: str
    obs_id: str
    date: str
    viewer_url: str
    estimated_size_gb: float
    band_codes: List[str]
    array_configs: List[str]
    targets: List[str]
    request_status: str
    request_submitted_at: Optional[str]
    request_finished_at: Optional[str]
    download_command: str
    download_attempts: int
    download_root: Optional[str]
    row: Dict[str, Any]
    details: Dict[str, Any]
    detail_summary: Dict[str, Any]
    last_error: Optional[str]


class ManifestDocument(TypedDict, total=False):
    version: int
    created_at: str
    source: Dict[str, Any]
    entries: List[ManifestEntry]
