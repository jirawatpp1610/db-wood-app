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

    หมายเหตุ: ใช้ load_raw_master() แทน download_master() ตรงๆ
    เพื่อให้ทั้งสองฟังก์ชัน share Supabase download เดียวกัน (1 call ต่อ TTL window)
    """
    df = load_raw_master()

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
# 2. CORE FORECAST ENGINE (v3 — Lognormal Renewal Process)
# =========================================================

def pragmatic_forecast_and_score(df_c: pd.DataFrame) -> dict:
    """
    Forecast Engine v3: Lognormal Renewal Process

    ปัญหาของ v2 (Gaussian PDF):
    ──────────────────────────────────────────────────────
    1. Gaussian กำหนดค่าลบได้ → gap ติดลบไม่มีในชีวิตจริง
    2. เมื่อ CV = std/avg > 1 → PDF แบนมาก → expected_ton → 0
       เช่น avg_gap=7.5, std=19.2 → คาดการณ์แค่ 0.4 ตัน
       ทั้งที่ถ้ามาจริงได้ 3+ ตัน

    v3 แก้ด้วย Lognormal + CDF difference:
    ──────────────────────────────────────────────────────
    - Lognormal กำหนดเฉพาะค่าบวก → เหมาะกับ inter-arrival time
    - ใช้ CDF(days_since+7) - CDF(days_since) → P(มาใน 7 วัน) ที่ถูกต้อง
    - expected_7d_ton = P(มา) × EWMA_ton → ตีความง่าย
    - เพิ่ม p_delivery_7d และ historical_p_weekly ใน output
    """
    import math

    if len(df_c) < 2:
        return {
            "expected_7d_ton":     0.0,
            "priority_score":      0.0,
            "forecast_daily":      [],
            "avg_gap":             0.0,
            "avg_ton":             0.0,
            "p_delivery_7d":       0.0,
            "historical_p_weekly": 0.0,
            "status":              "not_enough_data",
        }

    df_c = df_c.sort_values("date").copy()
    today     = pd.Timestamp.today().normalize()
    base_date = df_c["date"].max()

    # ── 1. Gap statistics ──────────────────────────────────────────────
    time_deltas = df_c["date"].diff().dt.days.dropna()
    avg_gap = float(time_deltas.mean())
    std_gap = float(time_deltas.std()) if len(time_deltas) > 1 else avg_gap * 0.3
    std_gap = max(std_gap, 1.0)  # std ขั้นต่ำ 1 วัน

    # ── 2. Ton: EWMA (recency-weighted) + simple mean (historical baseline) ──
    span     = min(len(df_c), 10)
    ewma_ton = float(df_c["ton"].ewm(span=span, adjust=True).mean().iloc[-1])
    avg_ton  = float(df_c["ton"].mean())

    # ── 3. Volume trend (30d vs all-time) ─────────────────────────────
    cutoff_30d   = base_date - pd.Timedelta(days=30)
    recent_df    = df_c[df_c["date"] >= cutoff_30d]
    recent_avg   = float(recent_df["ton"].mean()) if len(recent_df) >= 2 else avg_ton
    trend_factor = max(0.5, min(recent_avg / avg_ton if avg_ton > 0 else 1.0, 2.0))

    if trend_factor >= 1.15:
        trend_label = "rising"
    elif trend_factor <= 0.85:
        trend_label = "falling"
    else:
        trend_label = "stable"

    # ── 4. Weekday pattern detection ──────────────────────────────────
    weekday_counts      = df_c["date"].dt.dayofweek.value_counts()
    top_day_ratio       = float(weekday_counts.iloc[0]) / len(df_c)
    has_weekday_pattern = (top_day_ratio >= 0.40) and (len(df_c) >= 6)
    weekday_freq        = (weekday_counts / len(df_c)).to_dict()

    # ── 5. Lognormal parameters ────────────────────────────────────────
    # แปลง mean/std → Lognormal(μ_ln, σ_ln) ซึ่งกำหนดเฉพาะค่าบวก
    cv2      = (std_gap / avg_gap) ** 2
    sigma_ln = math.sqrt(math.log(1.0 + cv2))
    mu_ln    = math.log(avg_gap) - 0.5 * sigma_ln ** 2

    def _ln_cdf(x: float) -> float:
        if x <= 0:
            return 0.0
        return 0.5 * (1.0 + math.erf((math.log(x) - mu_ln) / (sigma_ln * math.sqrt(2))))

    def _ln_pdf(x: float) -> float:
        if x <= 0:
            return 0.0
        return (math.exp(-0.5 * ((math.log(x) - mu_ln) / sigma_ln) ** 2)
                / (x * sigma_ln * math.sqrt(2 * math.pi)))

    # ── 6. P(delivery in next 7 days) via CDF difference ──────────────
    days_since = max((today - base_date).days, 0)

    # P(T ∈ [days_since, days_since+7]) โดย T ~ Lognormal(μ_ln, σ_ln)
    p_delivery_7d      = max(0.0, _ln_cdf(days_since + 7) - _ln_cdf(max(days_since, 0.001)))
    # historical_p_weekly = baseline P(delivery in first 7 days from a fresh visit)
    historical_p_weekly = _ln_cdf(7.0)

    # ── 7. Expected deliveries (รองรับลูกค้าที่มาบ่อย avg_gap < 7) ───
    # avg_gap >= 7: ส่วนใหญ่ 0–1 ครั้งต่อสัปดาห์ → n = p_delivery_7d
    # avg_gap < 7 : อาจมาหลายครั้ง → scale ด้วย 7/avg_gap
    if avg_gap >= 7:
        n_expected = p_delivery_7d
    else:
        timing_ratio = p_delivery_7d / max(historical_p_weekly, 0.01)
        n_expected   = (7.0 / avg_gap) * timing_ratio

    expected_7d_ton = n_expected * ewma_ton

    # ── 8. Forecast daily: กระจาย probability ด้วย PDF shape + weekday boost ──
    raw_weights = []
    for i in range(1, 8):
        w = _ln_pdf(days_since + i)
        if has_weekday_pattern:
            wd = (today + pd.Timedelta(days=i)).dayofweek
            w *= (1.0 + weekday_freq.get(wd, 0.0))
        raw_weights.append(max(w, 1e-10))

    total_w        = sum(raw_weights)
    forecast_daily = []
    for i, w in enumerate(raw_weights, 1):
        share = w / total_w
        forecast_daily.append({
            "date":         today + pd.Timedelta(days=i),
            "prob":         min(p_delivery_7d * share * 7, 1.0),
            "expected_ton": expected_7d_ton * share,
        })

    # ── 9. Priority score ──────────────────────────────────────────────
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
        "p_delivery_7d":        p_delivery_7d,
        "historical_p_weekly":  historical_p_weekly,
        "status":               "success",
    }
