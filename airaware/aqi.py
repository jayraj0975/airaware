"""India's National Air Quality Index (CPCB, 2014) for particulate matter.

CPCB's AQI is the worst pollutant sub-index. AirAware uses PM2.5 and PM10 only: they set the AQI on almost
every day in Pune and Mumbai, and the archived gas readings are too inconsistent to trust (see README)."""

import math

# 24-hour average concentration breakpoints in µg/m³, matching the INDEX breakpoints below.
# The open top band ("Severe") is extended to 500 the way most CPCB calculators do.
BREAKPOINTS = {
    "pm2_5": [0, 30, 60, 90, 120, 250, 380],
    "pm10": [0, 50, 100, 250, 350, 430, 510],
}
INDEX = [0, 50, 100, 200, 300, 400, 500]

CATEGORIES = [  # upper bound, name, colour used by CPCB
    (50, "Good", "#00b050"),
    (100, "Satisfactory", "#92d050"),
    (200, "Moderate", "#ffff00"),
    (300, "Poor", "#ff9900"),
    (400, "Very Poor", "#ff0000"),
    (math.inf, "Severe", "#c00000"),
]


def sub_index(pollutant: str, conc: float) -> float:
    """Linear interpolation inside the CPCB band that holds `conc`; capped at 500."""
    if conc is None or math.isnan(conc):
        return math.nan
    bp = BREAKPOINTS[pollutant]
    for i in range(1, len(bp)):
        if conc <= bp[i]:
            return INDEX[i - 1] + (conc - bp[i - 1]) * (INDEX[i] - INDEX[i - 1]) / (bp[i] - bp[i - 1])
    return 500.0


def category(value: float) -> tuple[str, str]:
    for upper, name, colour in CATEGORIES:
        if value <= upper:
            return name, colour
    return CATEGORIES[-1][1:]
