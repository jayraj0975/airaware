"""AirAware GUI: `streamlit run app.py`."""

import pandas as pd
import streamlit as st

from airaware.aqi import CATEGORIES, category
from airaware.data import STATIONS, load
from airaware.model import FEATURES, TEST_FROM, train

NAMES = {
    "aqi": "Today's AQI", "aqi_lag1": "Yesterday's AQI", "aqi_lag2": "AQI two days ago", "aqi_7d": "Last 7 days' average AQI",
    "pm25": "Today's PM2.5", "pm10": "Today's PM10", "temp": "Today's temperature", "humidity": "Today's humidity",
    "rain": "Today's rain", "wind": "Today's wind speed", "wind_u": "Today's east-west wind", "wind_v": "Today's north-south wind",
    "pressure": "Today's air pressure", "blh": "Today's mixing height", "doy_sin": "Season (sine)", "doy_cos": "Season (cosine)",
    "weekday": "Day of week", "diwali": "Diwali week", "mumbai": "City",
    "temp_next": "Tomorrow's temperature", "humidity_next": "Tomorrow's humidity", "rain_next": "Tomorrow's rain",
    "wind_next": "Tomorrow's wind speed", "wind_u_next": "Tomorrow's east-west wind", "wind_v_next": "Tomorrow's north-south wind",
    "pressure_next": "Tomorrow's air pressure", "blh_next": "Tomorrow's mixing height",
}
ORDER = [c[1] for c in CATEGORIES]

st.set_page_config(page_title="AirAware", page_icon="🌫️", layout="wide")


@st.cache_data
def daily() -> pd.DataFrame:
    return load()


@st.cache_resource
def result():
    return train(daily())


def badge(label: str, value: float) -> str:
    name, colour = category(value)
    return (f"<div style='background:{colour};color:#111;border-radius:12px;padding:14px 18px;text-align:center'>"
            f"<div style='font-size:0.9rem'>{label}</div><div style='font-size:2.4rem;font-weight:700'>{value:.0f}</div>"
            f"<div style='font-weight:600'>{name}</div></div>")


d, r = daily(), result()
st.title("🌫️ AirAware")
st.caption("Tomorrow's air quality for Pune and Mumbai, from government monitoring stations and the weather forecast.")
city = st.sidebar.radio("City", ["Pune", "Mumbai"])
st.sidebar.markdown(f"**{len(set(STATIONS[city].values()))} CPCB stations** averaged into one city AQI.")
st.sidebar.markdown("AQI uses CPCB's PM2.5 and PM10 sub-indices. Data: OpenAQ archive of CPCB readings; weather: ERA5 via Open-Meteo.")

forecast, explore, model = st.tabs(["Forecast", "Explore the data", "How good is it?"])

with forecast:
    rows = r.test[r.test["city"] == city].set_index("date")
    day = st.select_slider("Forecast made on the evening of", options=list(rows.index.date), value=rows.index[-1].date(),
                           format_func=lambda x: x.strftime("%a %d %b %Y"))
    row = rows.loc[pd.Timestamp(day)]
    st.caption(f"Pick any day from {rows.index[0]:%d %b %Y} onwards. Each forecast comes from a model trained only on earlier "
               "months, so this replays what AirAware would really have said that evening.")

    st.subheader("What if tomorrow's weather were different?")
    c1, c2, c3, c4 = st.columns(4)
    x = row[FEATURES].astype(float).copy()
    x["temp_next"] = c1.slider("Temperature tomorrow (°C)", 10.0, 40.0, float(round(x["temp_next"], 1)), 0.5,
                               help="The model's strongest weather input: a warmer day than today usually pushes the forecast up.")
    x["humidity_next"] = c2.slider("Humidity tomorrow (%)", 10.0, 100.0, float(round(x["humidity_next"])), 1.0)
    x["rain_next"] = c3.slider("Rain tomorrow (mm)", 0.0, 100.0, float(round(x["rain_next"], 1)), 0.5)
    x["wind_next"] = c4.slider("Wind tomorrow (km/h)", 0.0, 40.0, float(round(x["wind_next"], 1)), 0.5)
    pred = float(r.model_for(pd.Timestamp(day)).predict(x.to_frame().T)[0])
    base = float(row["predicted"])

    a, b, c = st.columns(3)
    a.markdown(badge(f"Today ({day:%d %b})", row["aqi"]), unsafe_allow_html=True)
    b.markdown(badge("AirAware's forecast for tomorrow", pred), unsafe_allow_html=True)
    if pd.notna(row["target"]):
        c.markdown(badge("What actually happened", row["target"]), unsafe_allow_html=True)
    if abs(pred - base) >= 0.5:
        st.info(f"With your weather the forecast moves from {base:.0f} to {pred:.0f} ({pred - base:+.0f}).")

with explore:
    ok = d.dropna(subset=["aqi"])
    st.subheader("Daily AQI")
    st.line_chart(d.pivot(index="date", columns="city", values="aqi"), y_label="AQI")  # gaps stay gaps
    st.caption("The gap in 2023-24 is missing in the OpenAQ archive, not clean air.")

    left, right = st.columns(2)
    with left:
        st.subheader("Average AQI by month")
        m = ok.assign(month=ok["date"].dt.month).groupby(["month", "city"])["aqi"].mean().unstack()
        m.index = pd.to_datetime(m.index, format="%m").strftime("%b")
        st.bar_chart(m, stack=False, y_label="AQI", sort=False)
        st.caption("Monsoon rain washes the air clean (June to September); calm, dry winters trap dust and smoke.")
    with right:
        st.subheader("Share of days in each category")
        share = ok.assign(cat=ok["aqi"].map(lambda v: category(v)[0])).groupby("city")["cat"].value_counts(normalize=True).unstack(0)
        st.bar_chart((share.reindex(ORDER).fillna(0) * 100).round(1), stack=False, y_label="% of days", sort=False)

    st.subheader("Weather against air quality")
    w = st.selectbox("Weather variable", ["blh", "rain", "wind", "humidity", "temp"], format_func=lambda k: NAMES[k].replace("Today's ", "").capitalize())
    st.scatter_chart(ok[ok["city"] == city], x=w, y="aqi", y_label="AQI", x_label=NAMES[w].replace("Today's ", "").capitalize())

    st.subheader("Data coverage")
    cov = ok.groupby([ok["date"].dt.year.rename("year"), "city"]).size().unstack()
    st.dataframe(cov.rename_axis(None).T, use_container_width=True)
    st.caption("City-days with an AQI. A day counts when at least two stations had 16+ valid hours.")

with model:
    st.subheader("AirAware against simple baselines")
    t = r.table[r.table["City"].isin(["Both", city])]
    st.dataframe(t.pivot(index="Method", columns="City", values=["MAE", "Category accuracy", "Poor-day recall"]).round(2), use_container_width=True)
    st.caption(f"Walk-forward test from {TEST_FROM:%B %Y}: at the start of each month every method is retrained on everything "
               "before it, then forecasts that month. MAE = average error in AQI points. "
               "Poor-day recall = share of days that were actually Poor or worse (AQI > 200) that the method also called Poor or worse.")

    st.subheader(f"Forecast against reality, {city}")
    st.line_chart(rows[["target", "predicted", "persistence"]].rename(columns={
        "target": "Actual", "predicted": "AirAware", "persistence": "Tomorrow = today"}).set_index(rows.index + pd.Timedelta(days=1)))

    st.subheader("What the model relies on")
    imp = r.importance.head(10).rename(index=NAMES)
    st.bar_chart(imp, horizontal=True, x_label="AQI points of error added when this input is shuffled", sort=False)
