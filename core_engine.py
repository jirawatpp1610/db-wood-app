"""
core_engine.py
--------------
1. DATA INGESTION — โหลด master.parquet จาก Supabase Storage
2. FORECAST ENGINE — พยากรณ์ปริมาณและจัดลำดับความสำคัญลูกค้า
"""

import pandas as pd
import streamlit as st


# =========================================================
# 1a. RAW MASTER CACHE (shared across all pages)
# =========================================================

@st.cache_data(ttl=300)  # refresh cache ทุก 5 นาที
def load_raw_master() -> pd.DataFrame:
    """
    คืน raw master DataFrame ตรงจาก Supabase (ยังไม่ aggregate)

    FIX [High #1 & #2]: ทุกหน้าที่ต้องการ raw data ควรใช้ฟังก์ชันนี้
    แทนการเรียก download_master() ตรงๆ เพื่อให้ share cache เดียวกัน
    และลด Supabase API calls จาก 4 ครั้ง → 1 ครั้งต่อ TTL window
    """
    from storage_utils import download_master
    return download_master()


# =========================================================
# 1b. DATA INGESTION (aggregate สำหรับ dashboard)
# =========================================================

@st.cache_data(ttl=300)  # refresh cache ทุก 5 นาที
def load_real_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    คืน (daily_full, daily_raw)
    - daily_raw : ข้อมูลรายวันต่อลูกค้า (มีเฉพาะวันที่มีการมาส่ง)
    - daily_full: เติม 0 ในวันที่ไม่มีการมาส่ง (ใช้วาดกราฟ)

    หมายเหตุ: ฟังก์ชันนี้เรียก download_master() ภายใน cache ของตัวเอง
    ส่วน load_raw_master() เป็น cache entry แยก — ทั้งคู่มี TTL=300
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
    df = df.sort_values("date")

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
# 2. CORE FORECAST ENGINE (v2 — Gaussian Renewal Process)
# =========================================================

def pragmatic_forecast_and_score(df_c: pd.DataFrame) -> dict:
    """
    Forecast Engine v2: Gaussian Renewal Process

    เดิม (v1): prob_per_day = 1/avg_gap (uniform ทุกวัน)
    ──────────────────────────────────────────────────────
    ปัญหา: ไม่สนใจว่าลูกค้ามาครั้งล่าสุดเมื่อกี่วัน
    ถ้า avg_gap=7 วัน และผ่านมา 6 วันแล้ว → ควรมีโอกาสมาสูงมากวันพรุ่งนี้
    แต่ v1 ให้ prob เท่ากันทุกวัน

    ใหม่ (v2): Gaussian Renewal Process
    ──────────────────────────────────────────────────────
    P(มาวันที่ i จากนี้) ≈ N(days_since_last + i ; avg_gap, std_gap)
    → ความน่าจะเป็นสูงสุดเมื่อ days_since_last + i ≈ avg_gap
    → std_gap ควบคุมความกว้างของ distribution (ยิ่งไม่สม่ำเสมอ ยิ่งแผ่กว้าง)

    เพิ่มเติม:
    - EWMA ton (span=10): ให้น้ำหนักข้อมูลล่าสุดมากกว่า simple mean
    - Weekday pattern: boost วันที่ลูกค้ามักมาส่งจริง
    - Volume trend: เปรียบ 30d avg vs ทั้งหมด → ปรับ priority score
    """
    import math

    if len(df_c) < 2:
        return {
            "expected_7d_ton": 0.0,
            "priority_score": 0.0,
            "forecast_daily": [],
            "avg_gap": 0.0,
            "avg_ton": 0.0,
            "status": "not_enough_data",
        }

    df_c = df_c.sort_values("date").copy()
    today = pd.Timestamp.today().normalize()
    base_date = df_c["date"].max()

    # ── 1. Gap statistics ──────────────────────────────────────────────
    time_deltas = df_c["date"].diff().dt.days.dropna()
    avg_gap = float(time_deltas.mean())
    # std ขั้นต่ำ 1 วัน — ป้องกัน std=0 เช่น ลูกค้ามาตรงเป๊ะทุกวัน
    std_gap = float(time_deltas.std()) if len(time_deltas) > 1 else avg_gap * 0.3
    std_gap = max(std_gap, 1.0)

    # ── 2. Ton: EWMA (recency-weighted) + simple mean (historical baseline) ──
    span     = min(len(df_c), 10)
    ewma_ton = float(df_c["ton"].ewm(span=span, adjust=True).mean().iloc[-1])
    avg_ton  = float(df_c["ton"].mean())

    # ── 3. Volume trend (30d vs all-time) ─────────────────────────────
    cutoff_30d    = base_date - pd.Timedelta(days=30)
    recent_df     = df_c[df_c["date"] >= cutoff_30d]
    recent_avg    = float(recent_df["ton"].mean()) if len(recent_df) >= 2 else avg_ton
    trend_factor  = recent_avg / avg_ton if avg_ton > 0 else 1.0
    trend_factor  = max(0.5, min(trend_factor, 2.0))  # clamp ไม่ให้สุดโต่ง

    if trend_factor >= 1.15:
        trend_label = "rising"
    elif trend_factor <= 0.85:
        trend_label = "falling"
    else:
        trend_label = "stable"

    # ── 4. Weekday pattern detection ──────────────────────────────────
    # ถ้าวันเดียวคิดเป็น ≥40% ของการส่งทั้งหมด (และมีข้อมูล ≥6 ครั้ง) → มี pattern
    weekday_counts = df_c["date"].dt.dayofweek.value_counts()
    top_day_ratio  = float(weekday_counts.iloc[0]) / len(df_c)
    has_weekday_pattern = (top_day_ratio >= 0.40) and (len(df_c) >= 6)
    weekday_freq   = (weekday_counts / len(df_c)).to_dict()  # {0: 0.4, 2: 0.3, ...}

    # ── 5. Gaussian Renewal Process — forecast 7 วันข้างหน้า ──────────
    days_since = max((today - base_date).days, 0)

    def _gauss_pdf(x: float, mu: float, sigma: float) -> float:
        return (
            (1.0 / (sigma * math.sqrt(2 * math.pi)))
            * math.exp(-0.5 * ((x - mu) / sigma) ** 2)
        )

    forecast_daily = []
    for i in range(1, 8):
        days_from_last = days_since + i          # วันนับจากครั้งล่าสุด
        prob = _gauss_pdf(days_from_last, avg_gap, std_gap)

        # Weekday boost: ถ้ามี pattern → ปรับน้ำหนักตามวันในสัปดาห์
        if has_weekday_pattern:
            wd = (today + pd.Timedelta(days=i)).dayofweek
            prob *= (1.0 + weekday_freq.get(wd, 0.0))

        forecast_daily.append({
            "date": today + pd.Timedelta(days=i),
            "prob": min(prob * avg_gap, 1.0),    # scale ให้อ่านง่าย (0–1)
            "expected_ton": prob * ewma_ton,
        })

    expected_7d_ton = sum(d["expected_ton"] for d in forecast_daily)

    # ── 6. Priority score ──────────────────────────────────────────────
    # v1: score = expected_7d_ton × freq_30d × consistency
    # v2: เพิ่ม trend_factor — ลูกค้าที่ volume กำลังเพิ่มขึ้นควรมี score สูงขึ้นด้วย
    freq_30d          = len(df_c[df_c["date"] >= cutoff_30d])
    cv_gap            = std_gap / avg_gap if avg_gap > 0 else 1.0
    consistency_index = 1.0 / (cv_gap + 1.0)
    score             = expected_7d_ton * freq_30d * consistency_index * trend_factor

    return {
        "expected_7d_ton":      expected_7d_ton,
        "priority_score":       score,
        "forecast_daily":       forecast_daily,
        "avg_gap":              avg_gap,
        "std_gap":              std_gap,
        "avg_ton":              avg_ton,
        "ewma_ton":             ewma_ton,
        "trend_factor":         trend_factor,
        "trend_label":          trend_label,
        "has_weekday_pattern":  has_weekday_pattern,
        "status":               "success",
    }
