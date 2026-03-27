import streamlit as st
import pandas as pd
from core_engine import load_raw_master   # FIX [High #2]: shared cache แทน load_history_data()
from auth import require_auth

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Historical Data", page_icon="📅", layout="wide")
require_auth()
st.title("📅 ประวัติการรับไม้ย้อนหลัง (Daily History)")

# =========================================================
# LOAD RAW DATA
# FIX [High #2]: ลบ load_history_data() ที่สร้าง cache entry แยกทิ้ง
# ใช้ load_raw_master() จาก core_engine แทน → share cache เดียวกับ Home.py
# ลด Supabase API calls และ memory footprint
# =========================================================
raw_df = load_raw_master()

if raw_df.empty:
    st.warning("⚠️ ยังไม่มีข้อมูลในระบบ กรุณาไปที่หน้า **Update** เพื่ออัพโหลดไฟล์ข้อมูลก่อน")
    st.stop()

raw_df = raw_df.copy()
raw_df["datetime"]  = pd.to_datetime(raw_df["วัน/เวลาชั่งเข้า"])
raw_df["date_only"] = raw_df["datetime"].dt.normalize()
raw_df = raw_df.sort_values("datetime")

# =========================================================
# DATE SELECTOR
# =========================================================
st.markdown("---")
min_date = raw_df["date_only"].min().date()
max_date = raw_df["date_only"].max().date()

col_date, _ = st.columns([2, 2])
with col_date:
    date_range = st.date_input(
        "🗓️ เลือกช่วงวันที่",
        value=(max_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = date_range
elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
    start_date = end_date = date_range[0]
else:
    start_date = end_date = date_range

start_date_pd = pd.to_datetime(start_date)
end_date_pd   = pd.to_datetime(end_date)

day_data = raw_df[
    (raw_df["date_only"] >= start_date_pd) & (raw_df["date_only"] <= end_date_pd)
].copy()

# =========================================================
# KPI METRICS
# =========================================================
thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

def fmt_date(d):
    return f"{d.day} {thai_months[d.month]} {d.year + 543}"


if start_date == end_date:
    date_str        = fmt_date(start_date)
    subheader_label = f"📊 สรุปยอดประจำวันที่ {date_str}"
else:
    date_str        = f"{fmt_date(start_date)} – {fmt_date(end_date)}"
    subheader_label = f"📊 สรุปยอดช่วงวันที่ {date_str}"

st.subheader(subheader_label)

if not day_data.empty:
    vol_total   = day_data["น้ำหนักสุทธิ(TON)"].sum()
    cust_total  = day_data["ชื่อลูกค้า"].nunique()
    trips_total = len(day_data)

    col1, col2, col3 = st.columns(3)
    col1.metric("จำนวนเที่ยวรถที่เข้า (มื้อ)", f"{trips_total:,.0f} เที่ยว")
    col2.metric("จำนวนลูกค้า",                 f"{cust_total:,.0f} ราย")
    col3.metric("ปริมาณไม้ที่ซื้อได้",         f"{vol_total:,.2f} ตัน")

    st.markdown("---")

    # =========================================================
    # DETAILED TABLE
    # =========================================================
    st.subheader("📋 รายละเอียดลูกค้าที่มาส่งไม้")
    try:
        detail_df = day_data.groupby("ชื่อลูกค้า").agg({
            "datetime":            lambda x: ", ".join(x.sort_values().dt.strftime("%H:%M")),
            "ประเภทลูกค้า":       "first",
            "ประเภทรถ":           lambda x: ", ".join(x.dropna().astype(str).unique()),
            "น้ำหนักสุทธิ(TON)": ["count", "sum"],
        }).reset_index()

        detail_df.columns = ["ชื่อ", "เวลา (ชั่งเข้า)", "ประเภทลูกค้า", "ประเภทรถ", "จำนวนเที่ยว", "จำนวนตัน"]
        detail_df["ตันเฉลี่ยต่อเที่ยว"] = detail_df["จำนวนตัน"] / detail_df["จำนวนเที่ยว"]
        detail_df = detail_df[
            ["เวลา (ชั่งเข้า)", "ชื่อ", "ประเภทลูกค้า", "ประเภทรถ", "จำนวนเที่ยว", "จำนวนตัน", "ตันเฉลี่ยต่อเที่ยว"]
        ]
        detail_df = detail_df.sort_values("จำนวนตัน", ascending=False)

        st.dataframe(
            detail_df.style.format({
                "จำนวนตัน":          "{:,.2f}",
                "ตันเฉลี่ยต่อเที่ยว": "{:,.2f}",
            }),
            width="stretch",
            hide_index=True,
        )
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผลตาราง: {e}")

else:
    st.info(f"ไม่มีบันทึกข้อมูลการรับไม้ในช่วงวันที่ {date_str}")
