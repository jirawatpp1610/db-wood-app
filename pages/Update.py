"""
pages/Update.py
---------------
หน้าอัพโหลดไฟล์ .xls เพื่ออัพเดทข้อมูลเข้า Supabase Storage
Flow: upload .xls → แสดง preview → ยืนยัน → union + dedup → push master.parquet
"""

import streamlit as st
import pandas as pd
from storage_utils import download_master, upload_master
from auth import require_auth
from core_engine import load_real_data

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(page_title="Update Data", page_icon="📤", layout="wide")
require_auth()
st.title("📤 อัพเดทข้อมูลดิบ (Upload .xls)")

# =========================================================
# คอลัมน์ที่ต้องมีในไฟล์ .xls (Validation)
# =========================================================
REQUIRED_COLS = [
    "วัน/เวลาชั่งเข้า",
    "ชื่อลูกค้า",
    "น้ำหนักสุทธิ(TON)",
    "ประเภทลูกค้า",
    "ทะเบียนหัว",
]
DEDUP_KEYS = ["วัน/เวลาชั่งเข้า", "ทะเบียนหัว"]

# =========================================================
# STEP 1: อัพโหลดไฟล์
# =========================================================
st.markdown("### 1️⃣ เลือกไฟล์ .xls ที่ต้องการนำเข้า")
st.caption("รองรับไฟล์ .xls และ .xlsx — ข้อมูลซ้ำกันจะถูกตัดออกโดยอัตโนมัติ (key: วัน/เวลาชั่งเข้า + ทะเบียนหัว)")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

uploaded_file = st.file_uploader(
    label="เลือกไฟล์ Excel",
    type=["xls", "xlsx"],
    label_visibility="collapsed",
)

if uploaded_file is None:
    st.info("⬆️ กรุณาเลือกไฟล์ .xls หรือ .xlsx เพื่อเริ่มต้น")
    st.stop()

if uploaded_file.size > MAX_UPLOAD_BYTES:
    st.error(f"❌ ไฟล์ใหญ่เกินไป ({uploaded_file.size / 1024 / 1024:.1f} MB) — รองรับสูงสุด {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    st.stop()

# =========================================================
# STEP 2: อ่านไฟล์และ Validate
# =========================================================
def _read_xls_file(f) -> pd.DataFrame:
    """
    อ่านไฟล์ .xls/.xlsx โดยรองรับ 2 กรณี:
    1. Excel binary จริง (BIFF)  -> ใช้ pd.read_excel()
    2. HTML ที่บันทึกเป็น .xls   -> ใช้ pd.read_html() (พบบ่อยใน WMS export)
    """
    import io as _io

    header = f.read(1024)
    f.seek(0)
    is_html = header.lstrip()[:1] == b"<"

    if is_html:
        # WMS ไทยส่วนใหญ่ใช้ TIS-620 / Windows-874
        import chardet as _chardet
        raw_bytes = f.read()
        detected = _chardet.detect(raw_bytes[:4096])
        encoding = detected.get("encoding") or "tis-620"

        html_str = raw_bytes.decode(encoding, errors="replace")
        tables = pd.read_html(_io.StringIO(html_str), header=0, flavor="bs4")
        if not tables:
            raise ValueError("ไม่พบตารางข้อมูลในไฟล์ HTML")
        # เลือกตารางที่ใหญ่ที่สุด (กรณีมีหลาย table ในหน้า)
        return max(tables, key=len)
    else:
        engine = "xlrd" if f.name.endswith(".xls") else "openpyxl"
        return pd.read_excel(f, engine=engine)

try:
    new_df = _read_xls_file(uploaded_file)
except Exception as e:
    st.error(f"❌ ไม่สามารถอ่านไฟล์ได้: {e}")
    st.stop()

# ตรวจว่ามีคอลัมน์ครบไหม
missing_cols = [c for c in REQUIRED_COLS if c not in new_df.columns]
if missing_cols:
    st.error(f"❌ ไฟล์ขาดคอลัมน์: {missing_cols}")
    st.caption(f"คอลัมน์ที่พบในไฟล์: {new_df.columns.tolist()}")
    st.stop()

# =========================================================
# STEP 3: Preview
# =========================================================
st.markdown("### 2️⃣ ตรวจสอบข้อมูลก่อนนำเข้า")

col_info1, col_info2, col_info3 = st.columns(3)
col_info1.metric("จำนวนแถวในไฟล์ใหม่", f"{len(new_df):,} รายการ")
col_info2.metric(
    "ช่วงวันที่",
    f"{pd.to_datetime(new_df['วัน/เวลาชั่งเข้า']).dt.date.min()} → {pd.to_datetime(new_df['วัน/เวลาชั่งเข้า']).dt.date.max()}",
)
col_info3.metric("จำนวนลูกค้าในไฟล์ใหม่", f"{new_df['ชื่อลูกค้า'].nunique():,} ราย")

with st.expander("🔍 ดูตัวอย่างข้อมูล 10 แถวแรก"):
    st.dataframe(new_df.head(10), use_container_width=True, hide_index=True)

# =========================================================
# STEP 4: ดาวน์โหลด Master และ Preview ผลหลัง Union
# =========================================================
st.markdown("### 3️⃣ ผลลัพธ์หลัง Union + Dedup")

with st.spinner("⏳ กำลังโหลด master.parquet จาก Supabase..."):
    master_df = download_master()

# --- แสดงสถานะ Master ปัจจุบัน ---
if master_df.empty:
    st.warning("⚠️ ยังไม่มีไฟล์ master.parquet บน Supabase — จะสร้างไฟล์ใหม่")
    master_rows = 0
else:
    master_rows = len(master_df)
    st.success(f"✅ master.parquet ปัจจุบัน: {master_rows:,} รายการ")

# ---- Smart Upsert Logic ----
# key = วัน/เวลาชั่งเข้า + ทะเบียนหัว
# กรณี 1: key ซ้ำ + ทุก column เหมือนกัน  → ข้ามไม่ทำอะไร (true duplicate)
# กรณี 2: key ซ้ำ + บาง column ต่างกัน    → ลบ master ทิ้ง ใช้ข้อมูลใหม่แทน

# init preview_df กรณี master ว่าง (ป้องกัน NameError)
preview_df = new_df.copy()
updated_records = 0
before_dedup = len(master_df) + len(new_df)  # จำนวนก่อน upsert

if not master_df.empty:
    # Normalize timestamp ให้ตรงกันก่อน compare (ป้องกัน type mismatch)
    master_df = master_df.copy()
    new_df    = new_df.copy()
    master_df["วัน/เวลาชั่งเข้า"] = pd.to_datetime(master_df["วัน/เวลาชั่งเข้า"])
    new_df["วัน/เวลาชั่งเข้า"]    = pd.to_datetime(new_df["วัน/เวลาชั่งเข้า"])
    master_df["ทะเบียนหัว"] = master_df["ทะเบียนหัว"].astype(str).str.strip()
    new_df["ทะเบียนหัว"]    = new_df["ทะเบียนหัว"].astype(str).str.strip()

    new_keys    = new_df.set_index(DEDUP_KEYS).index
    master_keys = master_df.set_index(DEDUP_KEYS).index

    # หา key ที่ซ้ำกัน
    overlapping_keys = new_keys.intersection(master_keys)

    if len(overlapping_keys) > 0:
        # ดึงเฉพาะแถวที่ key ซ้ำจากทั้งสองฝั่ง
        master_overlap = master_df.set_index(DEDUP_KEYS).loc[overlapping_keys].reset_index()
        new_overlap    = new_df.set_index(DEDUP_KEYS).loc[overlapping_keys].reset_index()

        # เรียง columns ให้ตรงกันก่อนเปรียบเทียบ
        common_cols = [c for c in master_overlap.columns if c in new_overlap.columns]
        master_overlap = master_overlap[common_cols].sort_values(DEDUP_KEYS).reset_index(drop=True)
        new_overlap    = new_overlap[common_cols].sort_values(DEDUP_KEYS).reset_index(drop=True)

        # หา key ที่ข้อมูลต่างกันจริงๆ (ไม่ใช่ true duplicate)
        try:
            diff_mask = ~master_overlap.fillna("__NA__").eq(new_overlap.fillna("__NA__")).all(axis=1)
            keys_to_replace = master_overlap[diff_mask].set_index(DEDUP_KEYS).index
        except Exception:
            # fallback: ถ้า compare ไม่ได้ ให้ใช้ new ทั้งหมดที่ key ซ้ำ
            keys_to_replace = overlapping_keys

        # ลบแถว master ที่ต้องถูกแทนที่ออก
        if len(keys_to_replace) > 0:
            drop_mask = master_df.set_index(DEDUP_KEYS).index.isin(keys_to_replace)
            master_df_clean = master_df[~drop_mask]
            updated_records = int(drop_mask.sum())
        else:
            master_df_clean = master_df
            updated_records = 0

        # สร้าง preview ใหม่: master ที่ clean แล้ว + new_df ทั้งหมด แล้ว dedup true duplicate
        preview_df = pd.concat([master_df_clean, new_df], ignore_index=True)
    else:
        preview_df = pd.concat([master_df, new_df], ignore_index=True)
        updated_records = 0

    # re-normalize หลัง concat ใหม่
    preview_df["วัน/เวลาชั่งเข้า"] = pd.to_datetime(preview_df["วัน/เวลาชั่งเข้า"])
    _SKIP_COLS2 = {"วัน/เวลาชั่งเข้า", "ทะเบียนหัว", "ชื่อลูกค้า", "ประเภทลูกค้า", "ประเภทรถ"}
    for _col in preview_df.select_dtypes(include="object").columns:
        if _col not in _SKIP_COLS2:
            preview_df[_col] = pd.to_numeric(preview_df[_col], errors="coerce")

# ตัด true duplicate (key + ทุก column เหมือนกันจริงๆ) ออก
preview_df = (
    preview_df
    .drop_duplicates(subset=DEDUP_KEYS, keep="last")  # keep="last" = new_df ชนะ
    .sort_values("วัน/เวลาชั่งเข้า")
    .reset_index(drop=True)
)
after_dedup = len(preview_df)
duplicates_removed = before_dedup - after_dedup
new_records_added = after_dedup - master_rows

col_r1, col_r2, col_r3, col_r4 = st.columns(4)
col_r1.metric("รายการทั้งหมดหลัง Union", f"{after_dedup:,} รายการ")
col_r2.metric("รายการซ้ำที่ตัดออก", f"{duplicates_removed:,} รายการ", delta_color="off")
col_r3.metric(
    "รายการใหม่ที่เพิ่มเข้า",
    f"{new_records_added:,} รายการ",
    delta=f"+{new_records_added}" if new_records_added > 0 else "0",
)
col_r4.metric(
    "รายการที่อัพเดทข้อมูล",
    f"{updated_records:,} รายการ",
    delta=f"↺ {updated_records}" if updated_records > 0 else "0",
    delta_color="normal",
)

# =========================================================
# STEP 5: ยืนยันการบันทึก
# =========================================================
st.markdown("### 4️⃣ ยืนยันการบันทึก")

has_changes = new_records_added > 0 or updated_records > 0

if not has_changes:
    st.warning("⚠️ ไฟล์ที่อัพโหลดมีข้อมูลซ้ำกับ Master ทั้งหมด — ไม่มีข้อมูลใหม่ที่จะเพิ่ม")
elif updated_records > 0 and new_records_added == 0:
    st.info(f"↺ พบข้อมูลที่ต้องอัพเดท {updated_records:,} รายการ (เช่น น้ำหนักสุทธิที่เปลี่ยนแปลง)")

confirm_col, _ = st.columns([1, 3])
with confirm_col:
    save_btn = st.button(
        label="💾 บันทึกและอัพโหลดไปยัง Supabase",
        type="primary",
        disabled=(not has_changes),
        use_container_width=True,
    )

if save_btn:
    with st.spinner("⏳ กำลังอัพโหลด master.parquet ไปยัง Supabase..."):
        try:
            upload_master(preview_df)
            # Clear ทุก cache พร้อมกัน → ทุกหน้าโหลดข้อมูลใหม่ทันที
            st.cache_data.clear()
            st.success(
                f"✅ อัพโหลดสำเร็จ! master.parquet อัพเดทเป็น {after_dedup:,} รายการ "
                f"(เพิ่มใหม่ {new_records_added:,} | อัพเดท {updated_records:,} รายการ)"
            )
            st.balloons()
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดในการอัพโหลด: {e}")
