import streamlit as st
import pandas as pd
import numpy as np


st.set_page_config(page_title="Tender Dashboard", layout="wide")

st.title("📊 Tender Optimization — Simple Dashboard")
st.write("A small interactive demo dashboard with sample data. Use the controls in the sidebar to filter the data.")


with st.sidebar:
    st.header("Controls")
    periods = st.slider("Number of days", min_value=7, max_value=180, value=30)
    categories = st.multiselect("Categories", options=["A", "B", "C", "D"], default=["A", "B", "C", "D"])
    seed = st.number_input("Random seed", min_value=0, max_value=9999, value=42)
    show_table = st.checkbox("Show raw data table")
    st.markdown("---")


@st.cache_data
def generate_sample_data(n_days: int, cats: list, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic time series dataset for demo purposes."""
    np.random.seed(int(seed))
    dates = pd.date_range(end=pd.Timestamp.today(), periods=n_days)
    frames = []
    for c in cats:
        base = np.random.uniform(50, 200)
        trend = np.linspace(0, np.random.uniform(0, 50), n_days)
        noise = np.random.normal(scale=10, size=n_days)
        seasonal = 10 * np.sin(np.linspace(0, 3.14 * 2, n_days))
        values = base + trend + noise + seasonal
        frames.append(pd.DataFrame({"date": dates, "category": c, "value": np.round(values, 2)}))
    df = pd.concat(frames, ignore_index=True)
    return df


cats = categories if categories else ["A", "B", "C", "D"]
df = generate_sample_data(periods, cats, seed)

# Aggregate and show top-level metrics
total = df["value"].sum()
avg = df["value"].mean()
last_date = df["date"].max()
last_week = df[df["date"] >= (last_date - pd.Timedelta(days=7))]["value"].sum()

col1, col2, col3 = st.columns(3)
col1.metric("Total value", f"{total:,.0f}")
col2.metric("Average value", f"{avg:,.2f}")
col3.metric("Last 7 days", f"{last_week:,.0f}")

st.markdown("---")

st.subheader("Trend by category")
chart_df = df.pivot_table(index="date", columns="category", values="value", aggfunc="sum").fillna(0)
st.line_chart(chart_df)

st.subheader("Category breakdown")
cat_sum = df.groupby("category")["value"].sum().sort_values(ascending=False)
st.bar_chart(cat_sum)

if show_table:
    st.subheader("Raw data")
    st.dataframe(df)

csv = df.to_csv(index=False).encode("utf-8")
st.download_button("Download sample CSV", data=csv, file_name="sample_data.csv", mime="text/csv")

st.caption("This is synthetic data for demo purposes. Replace the data generation function with your real dataset.")
