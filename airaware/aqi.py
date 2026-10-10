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

CATEGORIES = [  # upper bound, name, colour: CPCB's hues, softened so text and maps stay readable on screen
    (50, "Good", "#2f9e5b"),
    (100, "Satisfactory", "#8cb83a"),
    (200, "Moderate", "#e0b411"),
    (300, "Poor", "#e57a2b"),
    (400, "Very Poor", "#cf4130"),
    (math.inf, "Severe", "#8e1f2f"),
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
    # The category of the number people see: AQI is reported as a whole number (half up, as the browser rounds), so
    # a forecast of 100.4 shows as 100 and must read Satisfactory, not Moderate.
    if math.isfinite(value):
        value = math.floor(value + 0.5)
    for upper, name, colour in CATEGORIES:
        if value <= upper:
            return name, colour
    return CATEGORIES[-1][1:]


ADVICE = {  # plain-language health advice per category, following the spirit of CPCB's health statements
    "Good": "Air is clean. A good day to be outdoors.",
    "Satisfactory": "Fine for almost everyone. People who are very sensitive may notice slight breathing discomfort.",
    "Moderate": "Children, older adults and people with asthma, lung or heart disease should cut down long or hard outdoor exercise.",
    "Poor": "Most people may feel uncomfortable after long exposure. Sensitive groups should avoid outdoor exercise; wear a mask in traffic.",
    "Very Poor": "Everyone should limit time outdoors. Sensitive groups should stay indoors and keep activity light.",
    "Severe": "Avoid outdoor activity, keep windows shut, and get medical help for any breathing trouble.",
}


HEALTH_GROUPS = {  # what a user can tick in their profile
    "asthma": "Asthma or other lung disease",
    "heart": "Heart disease",
    "child": "Young children",
    "elderly": "Aged 65 or over",
    "pregnant": "Pregnant",
    "outdoor": "Works or exercises outdoors",
}
SENSITIVE = {"asthma", "heart", "child", "elderly", "pregnant"}


# AQI up to which each kind of person is "ok", then "caution"; above the second number, "avoid".
LEVELS = {"general": (200, 300), "outdoor": (100, 300), "sensitive": (100, 200)}


def personal_advice(value: float, groups: list[str] | set[str] = ()) -> dict:
    """Advice for one person: sensitive groups are warned one category earlier, outdoor workers get exposure tips.

    Returns a level ("ok", "caution" or "avoid") for colour-coding and a sentence to show.
    """
    groups = set(groups)
    who = "sensitive" if SENSITIVE & groups else "outdoor" if "outdoor" in groups else "general"
    ok, caution = LEVELS[who]
    level = "ok" if value <= ok else "caution" if value <= caution else "avoid"
    name = category(value)[0]
    text = ADVICE[name]
    if who == "sensitive" and 100 < value <= 200:
        text = "For you this is a day to take care: keep outdoor exercise short and light, and carry any inhaler or medicine you use."
    if "outdoor" in groups and value > 100:
        text += " Working or training outside: go early afternoon when the air is usually cleanest, and wear an N95 near traffic."
    return {"level": level, "category": name, "text": text}
