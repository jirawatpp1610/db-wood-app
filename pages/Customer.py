import streamlit as st
import pandas as pd
import plotly.express as px
from core_engine import load_real_data, pragmatic_forecast_and_score
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
st.plotly_chart(fig1, use_container_width=True)

st.markdown("---")

# =========================================================
# FORECAST & ACTION PANEL
# =========================================================
result = pragmatic_forecast_and_score(df_c)

if result["status"] == "success":
    weekly_total = result["expected_7d_ton"]

    lifespan_weeks = (df_c["date"].max() - df_c["date"].min()).days / 7.0
    valid_weeks = max(1.0, lifespan_weeks)
    historical_weekly_avg = df_c["ton"].sum() / valid_weeks

    st.subheader("⚠️ แผนปฏิบัติการสัปดาห์หน้า (Action Panel)")
    st.metric("📦 คาดการณ์ปริมาณไม้ 7 วันข้างหน้า", f"{weekly_total:.1f} ตัน")

    if weekly_total > historical_weekly_avg * 1.5:
        st.error(f"🔥 สัปดาห์หน้าของเข้าเยอะผิดปกติ! (คาดการณ์ {weekly_total:.1f} ตัน) → เตรียมเงินสดล่วงหน้า")
    elif weekly_total < historical_weekly_avg * 0.7:
        st.warning(f"⚠️ Supply มีแนวโน้มลดลงอย่างมีนัยสำคัญ → เสี่ยงของขาด ควรติดต่อลูกค้าด่วน")
    else:
        st.success(f"✅ ปริมาณไม้เข้าสู่สภาวะปกติ (ระดับ {weekly_total:.1f} ตัน/สัปดาห์)")

    st.metric(
        "⭐️ คะแนนความสำคัญลูกค้า (Priority Score)",
        f"{result['priority_score']:.2f}",
        help="คำนวณจาก: ปริมาณคาดหวัง × ความถี่ × ความสม่ำเสมอ (ยิ่งคะแนนสูง ยิ่งควรโทรติดตามเช็คของ)",
    )
else:
    st.info("ℹ️ ลูกค้ารายนี้มีประวัติการส่งไม้น้อยกว่า 2 ครั้ง ยังไม่สามารถคำนวณพฤติกรรมล่วงหน้าได้")
