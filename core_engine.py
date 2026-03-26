"""
core_engine.py
--------------
1. DATA INGESTION  — โหลด master.parquet จาก Supabase Storage
2. FORECAST ENGINE — พยากรณ์ปริมาณและจัดลำดับความสำคัญลูกค้า
"""

import pandas as pd
import streamlit as st


# =========================================================
# 1. DATA INGESTION (โหลดจาก Supabase Storage)
# =========================================================
@st.cache_data(ttl=300)   # refresh cache ทุก 5 นาที
def load_real_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    คืน (daily_full, daily_raw)
    - daily_raw  : ข้อมูลรายวันต่อลูกค้า (มีเฉพาะวันที่มีการมาส่ง)
    - daily_full : เติม 0 ในวันที่ไม่มีการมาส่ง (ใช้วาดกราฟ)
    """
    from storage_utils import download_master

    df = download_master()

    if df.empty:
        empty = pd.DataFrame(
            columns=["customer", "date", "ton", "trips", "arrived"]
        )
        return empty, empty

    # ---- แปลง timestamp และเรียงลำดับวันที่ ----
    df["date"] = pd.to_datetime(df["วัน/เวลาชั่งเข้า"]).dt.normalize()
    df = df.sort_values("date")  # แก้ปัญหาข้อมูลไม่เรียงลำดับ

    df.rename(
        columns={
            "ชื่อลูกค้า": "customer",
            "น้ำหนักสุทธิ(TON)": "ton",
            "ประเภทลูกค้า": "cust_type",
            "ทะเบียนหัว": "plate",
        },
        inplace=True,
    )

    # ---- Aggregate รายวัน ต่อลูกค้า ----
    daily = (
        df.groupby(["customer", "date"])
        .agg(ton=("ton", "sum"), trips=("ton", "count"))
        .reset_index()
    )
    daily["arrived"] = 1

    # ---- เติม 0 ในวันที่ไม่มีข้อมูล (สำหรับ time-series chart) ----
    all_dates = pd.date_range(daily["date"].min(), daily["date"].max())
    customers = daily["customer"].unique()
    full_index = pd.MultiIndex.from_product(
        [customers, all_dates], names=["customer", "date"]
    )
    daily_full = (
        daily.set_index(["customer", "date"])
        .reindex(full_index)
        .fillna({"ton": 0, "trips": 0, "arrived": 0})
        .reset_index()
    )

    return daily_full, daily


# =========================================================
# 2. CORE FORECAST ENGINE
# =========================================================
def pragmatic_forecast_and_score(df_c: pd.DataFrame) -> dict:
    """
    รับ df_c = DataFrame ของลูกค้าคนเดียว (daily_raw)
    คืน dict: expected_7d_ton, priority_score, forecast_daily, status
    """
    if len(df_c) < 2:
        return {
            "expected_7d_ton": 0.0,
            "priority_score": 0.0,
            "forecast_daily": [],
            "status": "not_enough_data",
        }

    df_c = df_c.sort_values("date").copy()
    time_deltas = df_c["date"].diff().dt.days.dropna()

    avg_gap = time_deltas.mean()
    std_gap = time_deltas.std() if len(time_deltas) > 1 else 0.0
    avg_ton = df_c["ton"].mean()

    prob_per_day = 1.0 / avg_gap if avg_gap > 0 else 0.0

    base_date = df_c["date"].max()
    forecast_daily = [
        {
            "date": base_date + pd.Timedelta(days=i),
            "prob": prob_per_day,
            "expected_ton": prob_per_day * avg_ton,
        }
        for i in range(1, 8)
    ]
    expected_7d_ton = sum(d["expected_ton"] for d in forecast_daily)

    cutoff_30d = base_date - pd.Timedelta(days=30)
    freq_30d = len(df_c[df_c["date"] >= cutoff_30d])

    cv_gap = (std_gap / avg_gap) if avg_gap > 0 else 1.0
    consistency_index = 1.0 / (cv_gap + 1.0)

    score = expected_7d_ton * freq_30d * consistency_index

    return {
        "expected_7d_ton": expected_7d_ton,
        "priority_score": score,
        "forecast_daily": forecast_daily,
        "avg_gap": avg_gap,
        "status": "success",
    }
