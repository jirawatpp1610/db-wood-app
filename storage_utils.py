"""
storage_utils.py
----------------
Helper สำหรับติดต่อ Supabase Storage
- download_master()  : ดาวน์โหลด master.parquet → pd.DataFrame
- upload_master(df)  : อัพโหลด / overwrite master.parquet
"""

import io
import streamlit as st
import pandas as pd
from supabase import create_client, Client

MASTER_FILENAME = "master.parquet"


# =========================================================
# AUTH (cache ตลอด session)
# =========================================================
@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["service_role_key"]
    return create_client(url, key)


# =========================================================
# PUBLIC: DOWNLOAD
# =========================================================
def download_master() -> pd.DataFrame:
    """
    ดาวน์โหลด master.parquet จาก Supabase Storage
    คืน pd.DataFrame ว่างถ้ายังไม่มีไฟล์
    """
    try:
        client = get_supabase_client()
        bucket = st.secrets["supabase"]["bucket"]

        data = client.storage.from_(bucket).download(MASTER_FILENAME)
        return pd.read_parquet(io.BytesIO(data))

    except Exception as e:
        # ไฟล์ยังไม่มี หรือ error อื่น → คืน DataFrame ว่าง
        err_str = str(e).lower()
        if "not found" in err_str or "404" in err_str or "object not found" in err_str:
            return pd.DataFrame()
        st.warning(f"⚠️ download_master error: {e}")
        return pd.DataFrame()


# =========================================================
# PUBLIC: UPLOAD (create หรือ overwrite อัตโนมัติ)
# =========================================================
def upload_master(df: pd.DataFrame) -> None:
    """
    บันทึก DataFrame กลับ Supabase Storage เป็น master.parquet
    ใช้ upsert=True → สร้างใหม่หรือ overwrite อัตโนมัติ (atomic, 1 API call)
    """
    client = get_supabase_client()
    bucket = st.secrets["supabase"]["bucket"]

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)
    file_bytes = buffer.read()

    client.storage.from_(bucket).upload(
        path=MASTER_FILENAME,
        file=file_bytes,
        file_options={
            "content-type": "application/octet-stream",
            "upsert": "true",
        },
    )
