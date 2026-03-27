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

            # --- แยกตามทะเบียน (หัว + หาง) ---
            if "ทะเบียนหัว" in cust_raw.columns:
                tmp = cust_raw.copy()
                tail = tmp.get("ทะเบียนหาง", pd.Series("", index=tmp.index))
                tmp["ทะเบียน"] = tmp["ทะเบียนหัว"].fillna("").astype(str).str.strip()
                tail_clean = tail.fillna("").astype(str).str.strip()
                tmp["ทะเบียน"] = tmp.apply(
                    lambda r: r["ทะเบียน"] + " + " + tail_clean[r.name]
                    if tail_clean[r.name] != "" else r["ทะเบียน"],
                    axis=1,
                )

                plate_stats = (
                    tmp.groupby(["ทะเบียน", "ประเภทรถ"])[ton_col]
                    .agg(["count", "sum"])
                    .reset_index()
                )
                plate_stats.columns = ["ทะเบียน", "ประเภทรถ", "จำนวนเที่ยว", "ตันรวม"]
                plate_stats["ตันเฉลี่ยต่อเที่ยว"] = (
                    plate_stats["ตันรวม"] / plate_stats["จำนวนเที่ยว"]
                ).round(2)
                plate_stats["ตันรวม"] = plate_stats["ตันรวม"].round(2)
                plate_stats = plate_stats.sort_values("จำนวนเที่ยว", ascending=False).reset_index(drop=True)

                st.markdown("**รายละเอียดแยกตามทะเบียน**")
                st.dataframe(
                    plate_stats,
                    width="stretch",
                    hide_index=True,
                    column_order=["ทะเบียน", "ประเภทรถ", "จำนวนเที่ยว", "ตันรวม", "ตันเฉลี่ยต่อเที่ยว"],
                )
    else:
        st.caption("ไม่มีข้อมูลประเภทรถของลูกค้ารายนี้")

st.markdown("---")

# =========================================================
# FORECAST & ACTION PANEL
# =========================================================

# ถ้าขาดส่งเกิน 7 วัน → ไม่พยากรณ์ แสดง alert แทน
OVERDUE_DAYS = 10
if days_since > OVERDUE_DAYS:
    st.subheader("⚠️ Action Panel")
    st.error(
        f"🚨 ลูกค้าขาดส่งมาแล้ว **{days_since} วัน** (เกินกำหนด {OVERDUE_DAYS} วัน) "
        f"— ไม่สามารถพยากรณ์ได้เนื่องจากพฤติกรรมผิดปกติ → **ควรติดต่อลูกค้าโดยด่วน**"
    )
    st.stop()

result = pragmatic_forecast_and_score(df_c)

if result["status"] == "success":
    weekly_total         = result["expected_7d_ton"]
    avg_gap_days         = result["avg_gap"]
    std_gap_days         = result["std_gap"]
    avg_ton_per_trip     = result["avg_ton"]
    ewma_ton             = result["ewma_ton"]
    trend_label          = result["trend_label"]
    trend_factor         = result["trend_factor"]
    has_weekday_pattern  = result["has_weekday_pattern"]
    p_deliv              = result["p_delivery_7d"]
    hist_p               = result["historical_p_weekly"]

    _trend_icon = {"rising": "📈", "falling": "📉", "stable": "➡️"}[trend_label]
    _trend_th   = {"rising": "เพิ่มขึ้น", "falling": "ลดลง", "stable": "คงที่"}[trend_label]

    st.subheader("⚠️ แผนปฏิบัติการสัปดาห์หน้า (Action Panel)")

    # ความถี่ 30 วันย้อนหลัง
    cutoff_30d = last_delivery_date - pd.Timedelta(days=30)
    df_30d = df_c[df_c["date"] >= cutoff_30d].sort_values("date")
    gaps_30d = df_30d["date"].diff().dt.days.dropna()
    if len(gaps_30d) >= 2:
        g_avg = round(gaps_30d.mean())
        g_std = round(gaps_30d.std())
        g_lo, g_hi = max(1, g_avg - g_std), g_avg + g_std
        freq_label = f"{g_lo}–{g_hi} วัน/ครั้ง" if g_lo != g_hi else f"{g_lo} วัน/ครั้ง"
        freq_delta = f"จาก {len(gaps_30d)+1} ครั้ง ใน 30 วัน"
    elif len(gaps_30d) == 1:
        g_avg = round(gaps_30d.iloc[0])
        freq_label = f"{g_avg} วัน/ครั้ง"
        freq_delta = "ข้อมูลน้อย (2 ครั้ง)"
    else:
        freq_label = "ไม่พอข้อมูล"
        freq_delta = "มาน้อยกว่า 2 ครั้งใน 30 วัน"

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "📅 ความถี่ในการมาส่ง",
        freq_label,
        delta=freq_delta,
        delta_color="off",
        help="avg ± S.D. ของช่วงห่างระหว่างเที่ยว คำนวณจาก 30 วันย้อนหลัง",
    )
    m2.metric(
        f"{_trend_icon} แนวโน้ม Volume",
        _trend_th,
        delta=f"{(trend_factor - 1) * 100:+.0f}% vs ค่าเฉลี่ยทั้งหมด",
        delta_color="normal",
        help="เปรียบ 30 วันล่าสุด vs ค่าเฉลี่ยทั้งหมด",
    )
    last10 = df_c["ton"].tail(10)
    last10_avg = round(last10.mean())
    last10_std = round(last10.std()) if len(last10) > 1 else 0
    m3.metric(
        "📦 ถ้ามา คาดว่า",
        f"{last10_avg - last10_std}–{last10_avg + last10_std} ตัน",
        delta=f"{last10_avg - round(avg_ton_per_trip):+d} vs ค่าเฉลี่ยทั้งหมด",
        delta_color="normal",
        help="avg ± S.D. จาก 10 เที่ยวล่าสุด",
    )

    # Alert อิงจาก p_deliv vs hist_p (ไม่ใช่ตันเทียบตัน ซึ่งสับสนเมื่อ std สูง)
    rel = p_deliv / max(hist_p, 0.01)
    if rel > 1.5:
        st.error(
            f"🔥 โอกาสมาสูงกว่าปกติมาก! ({p_deliv*100:.0f}% vs ปกติ {hist_p*100:.0f}%)"
            f" → เตรียมเงินสดล่วงหน้า"
        )
    elif rel < 0.5:
        st.warning(
            f"⚠️ โอกาสมาต่ำกว่าปกติ ({p_deliv*100:.0f}% vs ปกติ {hist_p*100:.0f}%)"
            f" → ควรติดต่อลูกค้า"
        )
    else:
        st.success(
            f"✅ สัปดาห์หน้าเป็นปกติ (โอกาสมา {p_deliv*100:.0f}%"
            f" · คาดการณ์รวม {weekly_total:.1f} ตัน)"
        )

    weekday_note = " · มี weekday pattern" if has_weekday_pattern else ""
    st.caption(
        f"📐 avg gap {avg_gap_days:.1f} ± {std_gap_days:.1f} วัน"
        f" · {avg_ton_per_trip:.1f} ตัน/ครั้ง (all-time){weekday_note}"
    )

    st.metric(
        "⭐️ คะแนนความสำคัญลูกค้า (Priority Score)",
        f"{result['priority_score']:.2f}",
        help="คำนวณจาก: ปริมาณคาดหวัง × ความถี่ (30d) × ความสม่ำเสมอ × แนวโน้ม volume",
    )

else:
    st.info("ℹ️ ลูกค้ารายนี้มีประวัติการส่งไม้น้อยกว่า 2 ครั้ง ยังไม่สามารถคำนวณพฤติกรรมล่วงหน้าได้")
