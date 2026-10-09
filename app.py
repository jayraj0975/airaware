"""AirAware GUI: `streamlit run app.py`."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from airaware.aqi import ADVICE, CATEGORIES, category
from airaware.data import STATIONS, build, load, load_stations, save
from airaware.model import AIRAWARE, FEATURES, PERSISTENCE, TEST_FROM, explain, forecast_now, train

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
DAY = pd.Timedelta(days=1)

st.set_page_config(page_title="AirAware", page_icon="🌫️", layout="wide")


@st.cache_data
def daily() -> pd.DataFrame:
    return load()


@st.cache_data
def stations() -> pd.DataFrame:
    return load_stations()


@st.cache_resource(show_spinner="Training the forecast models (first load only, about 20 seconds)…")
def result():
    return train(daily())


def badge(label: str, value: float, note: str = "") -> str:
    name, colour = category(value)
    return (f"<div style='background:{colour};color:#111;border-radius:12px;padding:14px 18px;text-align:center'>"
            f"<div style='font-size:0.9rem'>{label}</div><div style='font-size:2.4rem;font-weight:700'>{value:.0f}</div>"
            f"<div style='font-weight:600'>{name}</div><div style='font-size:0.8rem'>{note}</div></div>")


def day_label(day: pd.Timestamp) -> str:
    today = pd.Timestamp(date.today())
    return {today: "Today", today + DAY: "Tomorrow", today - DAY: "Yesterday"}.get(day, f"{day:%a %d %b}")


def category_rules() -> alt.Chart:
    edges = pd.DataFrame({"aqi": [100, 200], "label": ["Satisfactory / Moderate", "Moderate / Poor"]})
    return alt.Chart(edges).mark_rule(strokeDash=[2, 2], color="grey").encode(y="aqi:Q", tooltip="label")


d, r = daily(), result()
now = forecast_now(d, r)

st.title("🌫️ AirAware")
st.caption("Air quality forecasts for Pune and Mumbai, up to a week ahead, from government monitoring stations and the weather forecast.")
city = st.sidebar.radio("City", ["Pune", "Mumbai"])
st.sidebar.markdown(f"**{len(set(STATIONS[city].values()))} CPCB stations** averaged into one city AQI.")
st.sidebar.markdown("AQI uses CPCB's PM2.5 and PM10 sub-indices. Data: OpenAQ archive of CPCB readings; weather: ERA5 and the "
                    "Open-Meteo forecast.")
if st.sidebar.button("Fetch latest data", help="Downloads new station readings and the latest weather forecast (a minute or two)."):
    with st.spinner("Downloading station readings and the weather forecast…"):
        try:
            save(*build())
        except OSError as e:
            st.sidebar.error(f"Could not update, still showing the saved data: {e}")
        else:
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

live, replay, station_tab, explore, model = st.tabs(["Right now", "Replay a day", "Stations", "Explore the data", "How good is it?"])

with live:
    mine = d[(d["city"] == city) & d["aqi"].notna()]
    last = mine.iloc[-1]
    fc = now[now["city"] == city]
    ahead = fc[fc["date"] >= pd.Timestamp(date.today())].head(2)
    if ahead.empty:
        ahead = fc.tail(2)
    st.markdown(f"The latest complete day of station readings is **{last['date']:%A %d %B}**. The public archive runs a few "
                "days behind, so AirAware forecasts forward from that day using the weather forecast.")

    cols = st.columns(1 + len(ahead))
    cols[0].markdown(badge(f"Measured, {last['date']:%d %b}", last["aqi"], f"{last['stations']:.0f} stations reporting"), unsafe_allow_html=True)
    for col, row in zip(cols[1:], ahead.itertuples()):
        col.markdown(badge(f"{day_label(row.date)}, {row.date:%d %b}", row.forecast,
                           f"likely {row.lo:.0f}–{row.hi:.0f} · {row.days_ahead} days after the last reading"), unsafe_allow_html=True)
    worst = ahead.iloc[-1]
    st.info(f"**{day_label(worst['date'])}: {category(worst['forecast'])[0]}.** {ADVICE[category(worst['forecast'])[0]]}  \n"
            f"Chance of a Poor or worse day (AQI above 200): **{worst['p_poor']:.0%}**.")

    st.subheader("The last six weeks and the week ahead")
    hist = mine[mine["date"] > last["date"] - pd.Timedelta(days=42)]
    actual = alt.Chart(hist).mark_line(color="#4c78a8").encode(
        x=alt.X("date:T", title=None), y=alt.Y("aqi:Q", title="AQI"), tooltip=[alt.Tooltip("date:T"), alt.Tooltip("aqi:Q", format=".0f")])
    band = alt.Chart(fc).mark_area(opacity=0.25, color="#f58518").encode(x="date:T", y="lo:Q", y2="hi:Q")
    line = alt.Chart(fc).mark_line(point=True, strokeDash=[5, 3], color="#f58518").encode(
        x="date:T", y="forecast:Q", tooltip=[alt.Tooltip("date:T"), alt.Tooltip("forecast:Q", format=".0f"),
                                             alt.Tooltip("lo:Q", format=".0f"), alt.Tooltip("hi:Q", format=".0f")])
    st.altair_chart(category_rules() + actual + band + line, use_container_width=True)
    st.caption("Blue: measured. Orange: AirAware's forecast, with the shaded 80% range. On past test days the real AQI "
               "fell inside that range about 86-88% of the time.")

    table = fc.assign(Day=fc["date"].map(lambda t: f"{day_label(t)} ({t:%d %b})"), Category=fc["forecast"].map(lambda v: category(v)[0]),
                      Range=fc["lo"].round().astype(int).astype(str) + "–" + fc["hi"].round().astype(int).astype(str))
    st.dataframe(table[["Day", "days_ahead", "forecast", "Range", "Category", "p_poor"]].round({"forecast": 0}).rename(columns={
        "days_ahead": "Days after last reading", "forecast": "Forecast AQI", "p_poor": "Chance of Poor or worse"}),
        hide_index=True, use_container_width=True,
        column_config={"Chance of Poor or worse": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})

with replay:
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
    m = r.model_for(pd.Timestamp(day))
    xf = x.to_frame().T
    pred = float(m.predict(xf)[0])
    base = float(row["predicted"])
    shift = pred - base

    a, b, c = st.columns(3)
    a.markdown(badge(f"Today ({day:%d %b})", row["aqi"]), unsafe_allow_html=True)
    b.markdown(badge("AirAware's forecast for tomorrow", pred, f"likely {row['lo'] + shift:.0f}–{row['hi'] + shift:.0f}"), unsafe_allow_html=True)
    if pd.notna(row["target"]):
        c.markdown(badge("What actually happened", row["target"]), unsafe_allow_html=True)
    if abs(shift) >= 0.5:
        st.info(f"With your weather the forecast moves from {base:.0f} to {pred:.0f} ({shift:+.0f}).")
    st.caption(f"Health advice for a {category(pred)[0]} day: {ADVICE[category(pred)[0]]}")

    st.subheader("Why this forecast?")
    parts = explain(m, xf).rename(index=NAMES)
    top = parts.reindex(parts.abs().sort_values(ascending=False).index).head(8)
    other = parts.sum() - top.sum()
    base_change = float(m.model_.named_steps["ridge"].intercept_)
    st.markdown(f"AirAware starts from today's AQI (**{row['aqi']:.0f}**), adds the typical day-to-day change "
                f"(**{base_change:+.1f}**), then each input pushes the forecast up or down. These pushes add up exactly to the "
                f"forecast; the other {len(parts) - len(top)} inputs together add **{other:+.1f}**.")
    why = top.rename("AQI points").rename_axis("Input").reset_index()
    st.altair_chart(alt.Chart(why).mark_bar().encode(
        x=alt.X("AQI points:Q"), y=alt.Y("Input:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
        color=alt.condition("datum['AQI points'] > 0", alt.value("#e45756"), alt.value("#54a24b")),
        tooltip=["Input", alt.Tooltip("AQI points:Q", format="+.1f")]), use_container_width=True)
    st.caption("Red pushes the forecast up (worse air), green pulls it down. Inputs are compared with their usual values, "
               "so an ordinary day contributes little.")

with station_tab:
    s = stations()
    s = s[(s["city"] == city) & (s["date"] > s["date"].max() - pd.Timedelta(days=7))].sort_values("date").groupby("station").last().reset_index()
    s["Category"] = s["aqi"].map(lambda v: category(v)[0])
    s["colour"] = s["aqi"].map(lambda v: category(v)[1])
    st.subheader(f"Stations in {city}, latest reading in the past week")
    st.map(s, latitude="lat", longitude="lon", color="colour", size=600, zoom=10.5 if city == "Pune" else 10)
    st.dataframe(s.sort_values("aqi", ascending=False)[["station", "date", "aqi", "Category", "pm25", "pm10"]].rename(columns={
        "station": "Station", "date": "Day", "aqi": "AQI", "pm25": "PM2.5 (µg/m³)", "pm10": "PM10 (µg/m³)"}).round(0),
        hide_index=True, use_container_width=True, column_config={"Day": st.column_config.DateColumn(format="DD MMM")})
    if len(s) > 1:
        st.caption(f"Across the city, stations differ by up to {s['aqi'].max() - s['aqi'].min():.0f} AQI points this week: "
                   "the city AQI is an average, and your street may be cleaner or dirtier.")

with explore:
    ok = d.dropna(subset=["aqi"])
    st.subheader("Daily AQI")
    st.line_chart(d.pivot(index="date", columns="city", values="aqi"), y_label="AQI")  # gaps stay gaps
    st.caption("The gap in 2023-24 is missing in the OpenAQ archive, not clean air.")

    left, right = st.columns(2)
    with left:
        st.subheader("Average AQI by month")
        mon = ok.assign(month=ok["date"].dt.month).groupby(["month", "city"])["aqi"].mean().unstack()
        mon.index = pd.to_datetime(mon.index, format="%m").strftime("%b")
        st.bar_chart(mon, stack=False, y_label="AQI", sort=False)
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
    st.subheader("Next day: AirAware against simple baselines")
    t = r.table[r.table["City"].isin(["Both", city])]
    st.dataframe(t.pivot(index="Method", columns="City", values=["MAE", "Category accuracy", "Poor-day recall"]).round(2), use_container_width=True)
    st.caption(f"Walk-forward test from {TEST_FROM:%B %Y}: at the start of each month every method is retrained on everything "
               "before it, then forecasts that month. MAE = average error in AQI points. "
               "Poor-day recall = share of days that were actually Poor or worse (AQI > 200) that the method also called Poor or worse.")
    stat, p = r.dm
    verdict = "is statistically significant" if p < 0.05 else "is not statistically significant"
    st.markdown(f"**Is the gain real?** A Diebold-Mariano test of AirAware against \"tomorrow = today\" (absolute error, "
                f"Newey-West variance for autocorrelated days) gives statistic **{stat:.2f}**, p = **{p:.3f}**: the improvement {verdict} "
                "at the 5% level.")

    st.subheader("Further ahead")
    hz = r.horizons.replace({AIRAWARE: "AirAware", PERSISTENCE: "Last reading repeated"})
    st.altair_chart(alt.Chart(hz).mark_line(point=True).encode(
        x=alt.X("Days ahead:O", axis=alt.Axis(labelAngle=0)), y=alt.Y("MAE:Q", title="Average error (AQI points)"), color=alt.Color("Method:N", legend=alt.Legend(orient="bottom")),
        tooltip=["Method", "Days ahead", alt.Tooltip("MAE:Q", format=".1f")]), use_container_width=True)
    cover = hz[hz["Method"] == "AirAware"].set_index("Days ahead")["80% range coverage"]
    st.caption(f"Error grows the further ahead AirAware looks, but it stays below the naive forecast at every step. Its 80% ranges "
               f"contained the real AQI {cover.min():.0%}-{cover.max():.0%} of the time, so they are honest, if slightly cautious.")

    mine = r.test[r.test["city"] == city]
    left, right = st.columns(2)
    with left:
        st.subheader(f"Error by month, {city}")
        month = (mine["date"] + DAY).dt.to_period("M").dt.start_time
        err = pd.DataFrame({"AirAware": (mine["target"] - mine["predicted"]).abs(), "Tomorrow = today": (mine["target"] - mine["persistence"]).abs(),
                            "month": month}).groupby("month").mean()
        err.index = err.index.strftime("%b %y")
        st.bar_chart(err, stack=False, y_label="Average error", sort=False)
        st.caption("Winter months are hardest: the air changes most from day to day.")
    with right:
        st.subheader(f"Categories, {city}")
        cm = pd.crosstab(mine["target"].map(lambda v: category(v)[0]).rename("Actual"),
                         mine["predicted"].map(lambda v: category(v)[0]).rename("Forecast"))
        present = [c for c in ORDER if c in cm.index or c in cm.columns]
        st.dataframe(cm.reindex(index=present, columns=present, fill_value=0), use_container_width=True)
        st.caption("Rows: the category that happened. Columns: the category AirAware forecast. The diagonal is correct.")

    st.subheader(f"Forecast against reality, {city}")
    st.line_chart(rows[["target", "predicted", "persistence"]].rename(columns={
        "target": "Actual", "predicted": "AirAware", "persistence": "Tomorrow = today"}).set_index(rows.index + DAY))

    st.subheader("What the model relies on")
    imp = r.importance.head(10).rename(index=NAMES)
    st.bar_chart(imp, horizontal=True, x_label="AQI points of error added when this input is shuffled", sort=False)

    out = r.test[["city", "date", "aqi", "predicted", "lo", "hi", "p_poor", "persistence", "target"]].assign(date=lambda t: t["date"] + DAY)
    st.download_button("Download every test forecast (CSV)", out.round(2).to_csv(index=False), "airaware_test_forecasts.csv", "text/csv")
