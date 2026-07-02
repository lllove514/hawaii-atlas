"""Reef Heat Atlas — shared configuration.

Single source of truth for every script. Edit the years / bounding box here and
the whole pipeline follows.
"""
import os

# ---------------------------------------------------------------------------
# Data source
# ---------------------------------------------------------------------------
# NOAA Coral Reef Watch CoralTemp 5km daily SST, served by the PacIOOS ERDDAP
# (University of Hawaii). Discovered via the CoastWatch ERDDAP entry point
# (coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW), which 302-redirects here.
# We hit PacIOOS directly because it is verified to return cropped NetCDF and is
# the Hawaii-local mirror. Variables used: CRW_SST, CRW_HOTSPOT, CRW_DHW.
ENDPOINT = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap/dhw_5km"
SOURCE_LABEL = "NOAA Coral Reef Watch CoralTemp 5km daily (PacIOOS ERDDAP: dhw_5km)"

# ---------------------------------------------------------------------------
# Time range (inclusive). CRW 5km daily begins 1985-04-01.
# ---------------------------------------------------------------------------
START_YEAR = 1985
END_YEAR = 2026

# ---------------------------------------------------------------------------
# Hawaiian Islands crop. Longitudes in -180..180 to match the dataset grid.
# ---------------------------------------------------------------------------
LAT_MIN, LAT_MAX = 18.0, 23.0
LON_MIN, LON_MAX = -161.5, -154.0

# ---------------------------------------------------------------------------
# Bleaching algorithm (standard CRW)
# ---------------------------------------------------------------------------
DHW_WINDOW_DAYS = 84        # trailing 12 weeks
HOTSPOT_THRESHOLD = 1.0     # degC; only HotSpots >= this count toward DHW
DHW_SIGNIFICANT = 4.0       # degC-weeks: significant bleaching likely
DHW_SEVERE = 8.0            # degC-weeks: severe bleaching + mortality likely

# Plausible SST envelope for Hawaiian reef waters, used by sanity asserts.
SST_MIN_PLAUSIBLE, SST_MAX_PLAUSIBLE = 15.0, 32.0

# ---------------------------------------------------------------------------
# Web payload
# ---------------------------------------------------------------------------
WEB_STRIDE_DAYS = 7         # temporal downsample for the browser (weekly)

# ---------------------------------------------------------------------------
# Paths (absolute, anchored at repo root so scripts run from anywhere)
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
PROC_DIR = os.path.join(ROOT, "processed")
WEB_DATA_DIR = os.path.join(ROOT, "..", "..", "data", "reef-heat-atlas")
QA_PATH = os.path.join(ROOT, "QA.md")

MMM_PATH = os.path.join(RAW_DIR, "mmm.nc")


def year_sst_path(year):
    return os.path.join(RAW_DIR, "sst_%d.nc" % year)
