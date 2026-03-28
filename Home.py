import streamlit as st
import pandas as pd
import plotly.express as px
import pytz
from core_engine import load_real_data, load_raw_master, pragmatic_forecast_and_score
from auth import require_auth

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Supply Overview", page_icon="🏠", layout="wide")
require_auth()
st.title("📊 ภาพรวม: โรงชิพจัตุรัส")

# =========================================================
# LOAD DATA (จาก Supabase ผ่าน core_engine)
# =========================================================
daily_full, daily_raw = load_real_data()

if daily_raw.empty:
    st.warning("⚠️ ยังไม่มีข้อมูลในระบบ กรุณาไปที่หน้า **Update** เพื่ออัพโหลดไฟล์ข้อมูลก่อน")
    st.stop()

# =========================================================
# FIX [High #1]: โหลด raw_master ผ่าน shared cache
# แทนการเรียก download_master() ภายใน expander ซ้ำ 2 ครั้ง
# =========================================================
raw_master = load_raw_master()
if not raw_master.empty:
    raw_master = raw_master.copy()
    raw_master["datetime"] = pd.to_datetime(raw_master["วัน/เวลาชั่งเข้า"])
    raw_master["date_only"] = raw_master["datetime"].dt.normalize()

# =========================================================
# TODAY'S SNAPSHOT (เวลาจริงประเทศไทย)
# =========================================================
tz_th = pytz.timezone("Asia/Bangkok")
real_today_th = pd.Timestamp.now(tz=tz_th).normalize().tz_localize(None)
yesterday_real = real_today_th - pd.Timedelta(days=1)

thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

def fmt_date(d):
    return f"{d.day} {thai_months[d.month]} {d.year + 543}"


df_today = daily_raw[daily_raw["date"] == real_today_th]
vol_today   = df_today["ton"].sum()    if not df_today.empty else 0.0
cust_today  = df_today["customer"].nunique() if not df_today.empty else 0
trips_today = df_today["trips"].sum()  if not df_today.empty else 0

today_str = fmt_date(real_today_th.date())
st.subheader(f"🟢 สรุปยอดวันนี้ ({today_str})")
t_col1, t_col2, t_col3 = st.columns(3)
t_col1.metric("จำนวนเที่ยวรถวันนี้",  f"{trips_today:,.0f} เที่ยว")
t_col2.metric("จำนวนลูกค้าวันนี้",   f"{cust_today:,.0f} ราย")
t_col3.metric("ปริมาณไม้วันนี้",     f"{vol_today:,.1f} ตัน")

with st.expander("🔍 คลิกเพื่อดูรายละเอียดลูกค้าวันนี้"):
    # FIX [High #1]: ใช้ raw_master ที่ cache ไว้แล้วแทน download_master() ใหม่
    if raw_master.empty:
        st.info("ไม่มีข้อมูลในระบบ")
    else:
        try:
            today_raw_data = raw_master[raw_master["date_only"] == real_today_th].copy()
            if not today_raw_data.empty:
                detail_today = today_raw_data.groupby("ชื่อลูกค้า").agg({
                    "datetime":            lambda x: ", ".join(x.dt.strftime("%H:%M")),
                    "ประเภทลูกค้า":       "first",
                    "ประเภทรถ":           lambda x: ", ".join(x.dropna().astype(str).unique()),
                    "น้ำหนักสุทธิ(TON)": ["count", "sum"],
                }).reset_index()
                detail_today.columns = ["ชื่อ", "เวลา", "ประเภทลูกค้า", "ประเภทรถ", "จำนวนเที่ยว", "จำนวนตัน"]
                detail_today["ตันเฉลี่ยต่อเที่ยว"] = detail_today["จำนวนตัน"] / detail_today["จำนวนเที่ยว"]
                detail_today = detail_today[["เวลา", "ชื่อ", "ประเภทลูกค้า", "ประเภทรถ", "จำนวนเที่ยว", "จำนวนตัน", "ตันเฉลี่ยต่อเที่ยว"]]
                st.dataframe(
                    detail_today.style.format({"จำนวนตัน": "{:,.2f}", "ตันเฉลี่ยต่อเที่ยว": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("ยังไม่มีบันทึกข้อมูลการรับไม้วันนี้")
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {e}")

st.markdown("---")

# =========================================================
# YESTERDAY'S SNAPSHOT
# =========================================================
df_yesterday   = daily_raw[daily_raw["date"] == yesterday_real]
vol_yesterday  = df_yesterday["ton"].sum()    if not df_yesterday.empty else 0.0
cust_yesterday = df_yesterday["customer"].nunique() if not df_yesterday.empty else 0
trips_yesterday= df_yesterday["trips"].sum()  if not df_yesterday.empty else 0

date_str = fmt_date(yesterday_real.date())
st.subheader(f"📅 สรุปยอดเมื่อวาน ({date_str})")
y_col1, y_col2, y_col3 = st.columns(3)
y_col1.metric("จำนวนเที่ยวรถที่เข้าเมื่อวาน",  f"{trips_yesterday:,.0f} เที่ยว")
y_col2.metric("จำนวนลูกค้าเมื่อวาน",           f"{cust_yesterday:,.0f} ราย")
y_col3.metric("ปริมาณไม้ที่ซื้อได้เมื่อวาน",   f"{vol_yesterday:,.1f} ตัน")

with st.expander("🔍 คลิกเพื่อดูรายละเอียดและรายชื่อลูกค้าที่มาส่งเมื่อวาน (Drill-down)"):
    # FIX [High #1]: ใช้ raw_master ที่ cache ไว้แล้วแทน download_master() ใหม่
    if raw_master.empty:
        st.info("ไม่มีข้อมูลในระบบ")
    else:
        try:
            yest_raw_data = raw_master[raw_master["date_only"] == yesterday_real].copy()
            if not yest_raw_data.empty:
                detail_df = yest_raw_data.groupby("ชื่อลูกค้า").agg({
                    "datetime":            lambda x: ", ".join(x.dt.strftime("%H:%M")),
                    "ประเภทลูกค้า":       "first",
                    "ประเภทรถ":           lambda x: ", ".join(x.dropna().astype(str).unique()),
                    "น้ำหนักสุทธิ(TON)": ["count", "sum"],
                }).reset_index()
                detail_df.columns = ["ชื่อ", "เวลา", "ประเภทลูกค้า", "ประเภทรถ", "จำนวนเที่ยว", "จำนวนตัน"]
                detail_df["ตันเฉลี่ยต่อเที่ยว"] = detail_df["จำนวนตัน"] / detail_df["จำนวนเที่ยว"]
                detail_df = detail_df[["เวลา", "ชื่อ", "ประเภทลูกค้า", "ประเภทรถ", "จำนวนเที่ยว", "จำนวนตัน", "ตันเฉลี่ยต่อเที่ยว"]]
                st.dataframe(
                    detail_df.style.format({"จำนวนตัน": "{:,.2f}", "ตันเฉลี่ยต่อเที่ยว": "{:,.2f}"}),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("ไม่มีบันทึกข้อมูลการรับไม้ของเมื่อวาน")
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการประมวลผลตาราง: {e}")

# =========================================================
# THIS WEEK & LAST WEEK OVERVIEW (เริ่มต้นสัปดาห์ = วันจันทร์)
# =========================================================
this_week_start = real_today_th - pd.Timedelta(days=real_today_th.weekday())
this_week_data  = daily_full[daily_full["date"] >= this_week_start]

prev_week_start_dt = this_week_start - pd.Timedelta(days=7)
prev_week_end_dt   = this_week_start - pd.Timedelta(days=1)
prev_week_data = daily_full[
    (daily_full["date"] >= prev_week_start_dt) & (daily_full["date"] <= prev_week_end_dt)
]

def fmt_range(start, end):
    return f"{fmt_date(start.date())} – {fmt_date(end.date())}"

# --- สัปดาห์นี้ ---
st.markdown("---")
st.subheader(f"🗓️ ภาพรวมของสัปดาห์นี้ ({fmt_range(this_week_start, real_today_th)})")
col1, col2, col3, col4 = st.columns(4)
col1.metric("ปริมาณรับไม้สัปดาห์นี้",    f"{this_week_data['ton'].sum():,.2f} ตัน")
col2.metric("จำนวนเที่ยวสัปดาห์นี้",     f"{this_week_data['trips'].sum():,.0f} เที่ยว")
col3.metric("จำนวนลูกค้าที่ Active",      f"{this_week_data[this_week_data['arrived']==1]['customer'].nunique()} ราย")
col4.metric(
    "ไม้เข้าเฉลี่ยต่อวัน",
    f"{this_week_data.groupby('date')['ton'].sum().mean():,.2f} ตัน"
    if not this_week_data.empty else "0.0 ตัน",
)

st.markdown("---")

# --- สัปดาห์ก่อน ---
st.subheader(f"📆 ภาพรวมของสัปดาห์ก่อน ({fmt_range(prev_week_start_dt, prev_week_end_dt)})")
p_col1, p_col2, p_col3, p_col4 = st.columns(4)
p_col1.metric("ปริมาณรับไม้สัปดาห์ก่อน",  f"{prev_week_data['ton'].sum():,.2f} ตัน")
p_col2.metric("จำนวนเที่ยวสัปดาห์ก่อน",   f"{prev_week_data['trips'].sum():,.0f} เที่ยว")
p_col3.metric("จำนวนลูกค้าที่ Active",     f"{prev_week_data[prev_week_data['arrived']==1]['customer'].nunique()} ราย")
p_col4.metric(
    "ไม้เข้าเฉลี่ยต่อวัน",
    f"{prev_week_data.groupby('date')['ton'].sum().mean():,.2f} ตัน"
    if not prev_week_data.empty else "0.0 ตัน",
)

st.markdown("---")

# =========================================================
# TIME-SERIES CHART
# =========================================================
supply = daily_full.groupby("date")["ton"].sum().reset_index()

chart_end           = supply["date"].max()
chart_start_default = chart_end - pd.DateOffset(months=2)

fig = px.line(
    supply, x="date", y="ton",
    title="แนวโน้มปริมาณวัตถุดิบรายวัน (Raw Volume Time-Series)",
)

# --- เส้น Monday (เบา, dash) ---
mondays = pd.date_range(start=supply["date"].min(), end=supply["date"].max(), freq="W-MON")
for monday in mondays:
    fig.add_vline(x=monday, line_width=1, line_dash="dash", line_color="rgba(180,180,180,0.4)")

# --- เส้นแบ่งเดือน (เข้ม, solid) + annotation ชื่อเดือน ---
thai_months_short = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                     "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

month_starts = pd.date_range(
    start=supply["date"].min().to_period("M").to_timestamp(),
    end=supply["date"].max(),
    freq="MS",
)

y_max = supply["ton"].max() if not supply.empty else 1.0

for ms in month_starts:
    if ms <= supply["date"].min():
        continue
    fig.add_vline(
        x=ms,
        line_width=2,
        line_dash="solid",
        line_color="rgba(60,60,60,0.55)",
    )
    label = f"{thai_months_short[ms.month]} {str(ms.year + 543)[2:]}"
    fig.add_annotation(
        x=ms,
        y=y_max,
        text=label,
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font=dict(size=11, color="rgba(60,60,60,0.8)"),
        bgcolor="rgba(255,255,255,0.6)",
        borderpad=2,
        xshift=4,
    )

# --- x-axis: tick รายสัปดาห์ ---
fig.update_xaxes(
    tickmode="array",
    tickvals=mondays,
    tickformat="%d/%m",
    range=[chart_start_default, chart_end],
    tickangle=-45,
)
fig.update_layout(margin=dict(t=60))

st.plotly_chart(fig, width="stretch")

# =========================================================
# ภาพรวมของเดือนนี้
# =========================================================
month_start = real_today_th.replace(day=1)
month_data_full = daily_full[daily_full["date"] >= month_start]
month_data_raw  = daily_raw[daily_raw["date"] >= month_start]

thai_month_name = thai_months[real_today_th.month]
st.subheader(f"📅 ภาพรวมของเดือน {thai_month_name} {real_today_th.year + 543}")
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric("ปริมาณรับไม้เดือนนี้",   f"{month_data_full['ton'].sum():,.2f} ตัน")
m_col2.metric("จำนวนเที่ยวเดือนนี้",    f"{month_data_full['trips'].sum():,.0f} เที่ยว")
m_col3.metric("จำนวนลูกค้าที่มาขาย",   f"{month_data_raw['customer'].nunique():,} ราย")
m_col4.metric(
    "ไม้เข้าเฉลี่ยต่อวัน",
    f"{month_data_full.groupby('date')['ton'].sum().mean():,.2f} ตัน"
    if not month_data_full.empty else "0.0 ตัน",
)

st.markdown("---")

# =========================================================
# TABLES: Top Volume + Top 5 Priority
# =========================================================
latest_date       = daily_full["date"].max()
current_week_start= latest_date - pd.Timedelta(days=latest_date.weekday())
prev_week_start   = current_week_start - pd.Timedelta(days=7)
prev_week_end     = current_week_start - pd.Timedelta(days=1)

prev_week_raw = daily_raw[
    (daily_raw["date"] >= prev_week_start) & (daily_raw["date"] <= prev_week_end)
]

col_t1, col_t2 = st.columns(2)

with col_t1:
    st.subheader("🏆 ลูกค้ารายใหญ่สัปดาห์ก่อนหน้า (Top Volume)")
    top_prev = (
        prev_week_raw.groupby("customer")["ton"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    top_prev.columns = ["ชื่อลูกค้า", "ปริมาณส่งรวม (ตัน)"]
    st.dataframe(top_prev[top_prev["ปริมาณส่งรวม (ตัน)"] > 0], width="stretch")

with col_t2:
    month_start = real_today_th.replace(day=1)
    month_raw = daily_raw[daily_raw["date"] >= month_start]
    thai_month_name = thai_months[real_today_th.month]
    st.subheader(f"📋 รายชื่อลูกค้าที่มาขายในเดือน {thai_month_name} {real_today_th.year + 543}")
    if not month_raw.empty:
        month_summary = (
            month_raw.groupby("customer")["date"]
            .nunique()
            .reset_index()
            .rename(columns={"customer": "ชื่อลูกค้า", "date": "จำนวนวันที่มา (วัน)"})
            .sort_values("จำนวนวันที่มา (วัน)", ascending=False)
            .reset_index(drop=True)
        )
        month_summary.index = month_summary.index + 1
        st.dataframe(month_summary, width="stretch")
    else:
        st.info("ยังไม่มีข้อมูลลูกค้าในเดือนนี้")

st.markdown("---")

# =========================================================
# ลูกค้าที่หายไปจากสัปดาห์ก่อน
# =========================================================
st.subheader(f"⚠️ ลูกค้าที่หายไปจากสัปดาห์ก่อน")
st.caption(f"มาส่งในช่วง {fmt_range(prev_week_start_dt, prev_week_end_dt)} แต่ยังไม่มาในสัปดาห์นี้ ({fmt_range(this_week_start, real_today_th)})")

prev_week_raw_customers = daily_raw[
    (daily_raw["date"] >= prev_week_start_dt) & (daily_raw["date"] <= prev_week_end_dt)
]
this_week_raw_customers = daily_raw[daily_raw["date"] >= this_week_start]

cust_prev_week = set(prev_week_raw_customers["customer"].unique())
cust_this_week = set(this_week_raw_customers["customer"].unique())
missing_customers = cust_prev_week - cust_this_week

if missing_customers:
    missing_summary = (
        prev_week_raw_customers[prev_week_raw_customers["customer"].isin(missing_customers)]
        .groupby("customer")
        .agg(
            ปริมาณส่งสัปดาห์ก่อน=("ton", "sum"),
            จำนวนเที่ยวสัปดาห์ก่อน=("trips", "sum"),
        )
        .sort_values("ปริมาณส่งสัปดาห์ก่อน", ascending=False)
        .reset_index()
    )
    missing_summary.columns = ["ชื่อลูกค้า", "ปริมาณส่งสัปดาห์ก่อน (ตัน)", "จำนวนเที่ยวสัปดาห์ก่อน"]
    st.dataframe(
        missing_summary.style.format({"ปริมาณส่งสัปดาห์ก่อน (ตัน)": "{:,.2f}"}),
        width="stretch",
        hide_index=True,
    )
    st.info(f"พบลูกค้าที่หายไป {len(missing_customers)} ราย")
else:
    st.success("ลูกค้าทุกรายจากสัปดาห์ก่อนมาส่งไม้แล้วในสัปดาห์นี้ ✅")
