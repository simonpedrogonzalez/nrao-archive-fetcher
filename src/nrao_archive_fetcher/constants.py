from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


TAP_URL = "https://data-query.nrao.edu/tap"
NRAO_DETAILS_API = "https://data.nrao.edu/archive-service/restapi_product_details_view"
DEFAULT_QUERY_LIMIT = 10


@dataclass(frozen=True)
class TimeSpan:
    start_mjd: Optional[float] = None
    end_mjd: Optional[float] = None


class TIMESPANS:
    FROM_2012 = TimeSpan(start_mjd=55927.0, end_mjd=None)
    FROM_2016_SEP = TimeSpan(start_mjd=57632.0, end_mjd=None)


class PROPRIETARY:
    PUBLIC = "PUBLIC"
    PROPRIETARY = "PROPRIETARY"
    PRIVATE = "PRIVATE"
    UNKNOWN = "UNKNOWN"

    @staticmethod
    def any_public():
        return ["PUBLIC"]


class INSTRUMENTS:
    VLA = "VLA"
    EVLA = "EVLA"
    ALMA = "ALMA"
    GBT = "GBT"
    VLBA = "VLBA"
    GMVA = "GMVA"

    @staticmethod
    def VLA_VARIANTS():
        return ["VLA", "EVLA"]


class DATAPRODS:
    VISIBILITY = "visibility"
    IMAGE = "image"


class CONFIGS:
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    ALL = ["A", "B", "C", "D"]


@dataclass(frozen=True)
class Band:
    key: str
    f_lo_hz: float
    f_hi_hz: float
    label: str


class BANDS:
    L = Band("L", 1e9, 2e9, "~20cm")
    S = Band("S", 2e9, 4e9, "~13cm")
    C = Band("C", 4e9, 8e9, "~6cm")
    X = Band("X", 8e9, 12e9, "~3.7cm")
    KU = Band("KU", 12e9, 18e9, "~2cm")
    K = Band("K", 18e9, 26.5e9, "~1.3cm")
    KA = Band("KA", 26.5e9, 40e9, "~9mm")
    Q = Band("Q", 40e9, 50e9, "~7mm")

    _BY_KEY = {
        L.key: L,
        S.key: S,
        C.key: C,
        X.key: X,
        KU.key: KU,
        K.key: K,
        KA.key: KA,
        Q.key: Q,
    }

    @classmethod
    def get(cls, value):
        text = str(value).strip().upper().replace(" ", "")
        if text in cls._BY_KEY:
            return cls._BY_KEY[text]

        wl = str(value).strip().lower().replace(" ", "")
        if wl.endswith("cm"):
            cm = float(wl[:-2])
            if 15 <= cm <= 30:
                return cls.L
            if 9 <= cm <= 15:
                return cls.S
            if 4.5 <= cm <= 7.5:
                return cls.C
            if 3.0 <= cm <= 4.5:
                return cls.X
            if 1.6 <= cm <= 2.6:
                return cls.KU
            if 1.0 <= cm <= 1.6:
                return cls.K
        if wl.endswith("mm"):
            mm = float(wl[:-2])
            if 8 <= mm <= 12:
                return cls.KA
            if 6 <= mm <= 8:
                return cls.Q
        raise ValueError("Could not infer band from %r" % (value,))


class COLS:
    obs_publisher_did = "obs_publisher_did"
    project_code = "project_code"
    target_name = "target_name"
    t_min = "t_min"
    t_max = "t_max"
    t_exptime = "t_exptime"
    instrument_name = "instrument_name"
    configuration = "configuration"
    dataproduct_type = "dataproduct_type"
    freq_min = "freq_min"
    freq_max = "freq_max"
    em_min = "em_min"
    em_max = "em_max"
    s_ra = "s_ra"
    s_dec = "s_dec"
    access_estsize = "access_estsize"
    access_url = "access_url"
    access_format = "access_format"
    proprietary_status = "proprietary_status"
    pol_states = "pol_states"
    calib_level = "calib_level"
    num_antennas = "num_antennas"
    max_uv_dist = "max_uv_dist"
    spw_names = "spw_names"
    center_frequencies = "center_frequencies"
    bandwidths = "bandwidths"
    nums_channels = "nums_channels"
    spectral_resolutions = "spectral_resolutions"
    aggregate_bandwidth = "aggregate_bandwidth"


KNOWN_QUERY_COLUMNS = [
    COLS.obs_publisher_did,
    COLS.project_code,
    COLS.target_name,
    COLS.t_min,
    COLS.t_max,
    COLS.t_exptime,
    COLS.instrument_name,
    COLS.configuration,
    COLS.dataproduct_type,
    COLS.freq_min,
    COLS.freq_max,
    COLS.em_min,
    COLS.em_max,
    COLS.s_ra,
    COLS.s_dec,
    COLS.access_estsize,
    COLS.access_url,
    COLS.access_format,
    COLS.proprietary_status,
    COLS.pol_states,
    COLS.calib_level,
    COLS.num_antennas,
    COLS.max_uv_dist,
    COLS.spw_names,
    COLS.center_frequencies,
    COLS.bandwidths,
    COLS.nums_channels,
    COLS.spectral_resolutions,
    COLS.aggregate_bandwidth,
]
