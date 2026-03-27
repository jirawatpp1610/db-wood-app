import streamlit as st
import pandas as pd
import plotly.express as px
from core_engine import load_real_data, load_raw_master, pragmatic_forecast_and_score
from auth import require_auth

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Customer Analysis", page_icon="👤", layout="wide")
require_auth()
st.title("👤 เจาะลึกพฤติกรรมและแผนปฏิบัติการ")

# =========================================================
# LOAD DATA (จาก Supabase ผ่าน core_engine cache)
# =========================================================
_, daily_raw = load_real_data()

if daily_raw.empty:
    st.warning("⚠️ ยังไม่มีข้อมูลในระบบ กรุณาไปที่หน้า **Update** เพื่ออัพโหลดไฟล์ข้อมูลก่อน")
    st.stop()

# =========================================================
# CUSTOMER SELECTION & HISTORY
# =========================================================
selected = st.selectbox("เลือกรายชื่อลูกค้า", sorted(daily_raw["customer"].unique()))
df_c = daily_raw[daily_raw["customer"] == selected].sort_values("date")

st.subheader(f"📈 ประวัติการจัดส่งจริง: {selected}")
fig1 = px.bar(df_c, x="date", y="ton", text="ton", title="ปริมาณการส่งไม้รายวัน (ตัน)")
fig1.update_traces(texttemplate="%{text:.1f}", textposition="outside")
st.plotly_chart(fig1, width="stretch")

# --- วันที่มาส่งล่าสุด ---
last_delivery_date = df_c["date"].max()
days_since = (pd.Timestamp.today().normalize() - last_delivery_date).days
thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
last_date_str = f"{last_delivery_date.day} {thai_months[last_delivery_date.month]} {last_delivery_date.year + 543}"

if days_since == 0:
    st.caption(f"📦 มาส่งล่าสุด: **{last_date_str}** (วันนี้)")
elif days_since == 1:
    st.caption(f"📦 มาส่งล่าสุด: **{last_date_str}** (เมื่อวาน)")
else:
    st.caption(f"📦 มาส่งล่าสุด: **{last_date_str}** ({days_since} วันที่แล้ว)")

# =========================================================
# ประเภทรถและตันเฉลี่ยต่อเที่ยว
# ดึงจาก raw_master เพราะ daily_raw aggregate แล้ว ไม่มี ประเภทรถ
# =========================================================
st.subheader("🚛 ประเภทรถและตันเฉลี่ยต่อเที่ยว")

raw_master = load_raw_master()
if not raw_master.empty:
    cust_raw = raw_master[raw_master["ชื่อลูกค้า"] == selected].copy()
    cust_raw["ประเภทรถ"] = cust_raw["ประเภทรถ"].fillna("ไม่ระบุ").astype(str).str.strip()
    cust_raw = cust_raw[cust_raw["ประเภทรถ"] != ""]

    if not cust_raw.empty:
        ton_col = "น้ำหนักสุทธิ(TON)"
        if ton_col not in cust_raw.columns:
            st.caption("ไม่พบคอลัมน์น้ำหนักในข้อมูลดิบ")
        else:
            truck_stats = (
                cust_raw.groupby("ประเภทรถ")[ton_col]
                .agg(["count", "sum"])
                .reset_index()
            )
            truck_stats.columns = ["ประเภทรถ", "จำนวนเที่ยว", "ตันรวม"]
            truck_stats["ตันเฉลี่ยต่อเที่ยว"] = truck_stats["ตันรวม"] / truck_stats["จำนวนเที่ยว"]
            truck_stats = truck_stats.sort_values("จำนวนเที่ยว", ascending=False).reset_index(drop=True)

            cols = st.columns(min(len(truck_stats), 4))
            for i, row in truck_stats.iterrows():
                with cols[i % len(cols)]:
                    st.metric(
                        label=f"🚚 {row['ประเภทรถ']}",
                        value=f"{row['ตันเฉลี่ยต่อเที่ยว']:.2f} ตัน/เที่ยว",
                        delta=f"{int(row['จำนวนเที่ยว'])} เที่ยว รวม {row['ตันรวม']:.1f} ตัน",
                        delta_color="off",
                    )
    else:
        st.caption("ไม่มีข้อมูลประเภทรถของลูกค้ารายนี้")

st.markdown("---")

# =========================================================
# FORECAST & ACTION PANEL
# =========================================================

# ถ้าขาดส่งเกิน 7 วัน → ไม่พยากรณ์ แสดง alert แทน
OVERDUE_DAYS = 7
if days_since > OVERDUE_DAYS:
    st.subheader("⚠️ แผนปฏิบัติการสัปดาห์หน้า (Action Panel)")
    st.error(
        f"🚨 ลูกค้าขาดส่งมาแล้ว **{days_since} วัน** (เกินกำหนด {OVERDUE_DAYS} วัน) "
        f"— ไม่สามารถพยากรณ์ได้เนื่องจากพฤติกรรมผิดปกติ → **ควรติดต่อลูกค้าโดยด่วน**"
    )
    st.stop()

result = pragmatic_forecast_and_score(df_c)

if result["status"] == "success":
    weekly_total = result["expected_7d_ton"]

    avg_gap_days          = result["avg_gap"]
    std_gap_days          = result["std_gap"]
    avg_ton_per_trip      = result["avg_ton"]       # all-time mean (baseline)
    ewma_ton              = result["ewma_ton"]       # recency-weighted (ใช้ forecast)
    trend_label           = result["trend_label"]
    trend_factor          = result["trend_factor"]
    has_weekday_pattern   = result["has_weekday_pattern"]
    trips_per_week        = 7.0 / max(avg_gap_days, 0.5)
    historical_weekly_avg = avg_ton_per_trip * trips_per_week

    _trend_icon = {"rising": "📈", "falling": "📉", "stable": "➡️"}[trend_label]
    _trend_th   = {"rising": "เพิ่มขึ้น", "falling": "ลดลง", "stable": "คงที่"}[trend_label]

    st.subheader("⚠️ แผนปฏิบัติการสัปดาห์หน้า (Action Panel)")

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "📦 คาดการณ์ 7 วันข้างหน้า",
        f"{weekly_total:.1f} ตัน",
        help="คำนวณด้วย Gaussian Renewal Process โดยใช้ EWMA ton และ days since last delivery",
    )
    m2.metric(
        f"{_trend_icon} แนวโน้ม Volume",
        _trend_th,
        delta=f"{(trend_factor - 1) * 100:+.0f}% vs ค่าเฉลี่ยทั้งหมด",
        delta_color="normal",
        help="เปรียบ 30 วันล่าสุด vs ค่าเฉลี่ยทั้งหมด",
    )
    m3.metric(
        "🕐 ตันเฉลี่ยล่าสุด (EWMA)",
        f"{ewma_ton:.1f} ตัน/ครั้ง",
        delta=f"{ewma_ton - avg_ton_per_trip:+.1f} vs ค่าเฉลี่ยทั้งหมด",
        delta_color="normal",
        help="Exponential Weighted Moving Average (span=10) — ให้น้ำหนักข้อมูลล่าสุดมากกว่า",
    )

    if weekly_total > historical_weekly_avg * 1.5:
        st.error(
            f"🔥 สัปดาห์หน้าของเข้าเยอะผิดปกติ! (คาดการณ์ {weekly_total:.1f} ตัน vs ปกติ {historical_weekly_avg:.1f} ตัน)"
            f" → เตรียมเงินสดล่วงหน้า"
        )
    elif weekly_total < historical_weekly_avg * 0.7:
        st.warning(
            f"⚠️ Supply มีแนวโน้มลดลงอย่างมีนัยสำคัญ (คาดการณ์ {weekly_total:.1f} ตัน vs ปกติ {historical_weekly_avg:.1f} ตัน)"
            f" → เสี่ยงของขาด ควรติดต่อลูกค้าด่วน"
        )
    else:
        st.success(f"✅ ปริมาณไม้เข้าสู่สภาวะปกติ (ระดับ {weekly_total:.1f} ตัน/สัปดาห์)")

    weekday_note = " · มี weekday pattern" if has_weekday_pattern else ""
    st.caption(
        f"📐 baseline: {historical_weekly_avg:.1f} ตัน/สัปดาห์"
        f" · avg gap {avg_gap_days:.1f} ± {std_gap_days:.1f} วัน"
        f" · {avg_ton_per_trip:.1f} ตัน/ครั้ง (all-time){weekday_note}"
    )

    st.metric(
        "⭐️ คะแนนความสำคัญลูกค้า (Priority Score)",
        f"{result['priority_score']:.2f}",
        help="คำนวณจาก: ปริมาณคาดหวัง × ความถี่ (30d) × ความสม่ำเสมอ × แนวโน้ม volume",
    )

else:
    st.info("ℹ️ ลูกค้ารายนี้มีประวัติการส่งไม้น้อยกว่า 2 ครั้ง ยังไม่สามารถคำนวณพฤติกรรมล่วงหน้าได้")
