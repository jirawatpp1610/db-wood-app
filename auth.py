"""
auth.py
-------
ระบบ password gate พร้อม:
- Rate Limiting : ล็อค 15 นาที หลังกรอกผิด 5 ครั้ง (per IP)
- Session Timeout: หมดอายุอัตโนมัติหลัง 30 นาที ไม่มีกิจกรรม

หมายเหตุด้านสถาปัตยกรรม:
  _ip_store เป็น in-memory dict → รีเซ็ตเมื่อ server restart
  ถ้า deploy บน Streamlit Cloud แบบ multi-process จะไม่ share state ข้าม worker
  หากต้องการ rate limiting ที่ persistent ควรเปลี่ยนไปใช้ Supabase / Redis แทน
"""

import hmac
import time
import threading
import streamlit as st

# =========================================================
# CONFIG
# =========================================================
MAX_ATTEMPTS = 5        # กรอกผิดได้สูงสุดกี่ครั้ง
LOCKOUT_SEC  = 15 * 60  # ล็อคนานกี่วินาที (15 นาที)
SESSION_TTL  = 30 * 60  # session หมดอายุหลังกี่วินาที (30 นาที)

_rl_lock  = threading.Lock()
_ip_store: dict[str, dict] = {}


def _get_client_ip() -> str:
    """ดึง IP จาก request headers

    ลำดับความน่าเชื่อถือ:
    1. cf-connecting-ip  — Cloudflare ตั้งค่าเอง client ปลอมไม่ได้
    2. x-real-ip         — nginx/proxy ตั้งค่าเอง client ปลอมไม่ได้
    3. x-forwarded-for   — ใช้ IP ขวาสุด (เพิ่มโดย trusted proxy)
                           IP ซ้ายสุดอาจถูก client ปลอมได้
    """
    try:
        headers = st.context.headers
        for header in ("cf-connecting-ip", "x-real-ip"):
            val = headers.get(header, "").strip()
            if val:
                return val.split(",")[0].strip()
        xff = headers.get("x-forwarded-for", "").strip()
        if xff:
            return xff.split(",")[-1].strip()
    except Exception:
        pass
    return "unknown"


def _get_ip_state(ip: str) -> dict:
    with _rl_lock:
        if ip not in _ip_store:
            _ip_store[ip] = {"attempts": 0, "lockout_until": 0.0}
        return dict(_ip_store[ip])


def _set_ip_state(ip: str, attempts: int, lockout_until: float) -> None:
    with _rl_lock:
        _ip_store[ip] = {"attempts": attempts, "lockout_until": lockout_until}


# =========================================================
# PUBLIC
# =========================================================

def require_auth() -> None:
    _init_state()

    if st.session_state["authenticated"]:
        idle_sec = time.time() - st.session_state["last_activity"]
        if idle_sec > SESSION_TTL:
            _force_logout("⏱️ Session หมดอายุแล้ว กรุณา Login ใหม่")
        st.session_state["last_activity"] = time.time()
        _show_sidebar_info()
        return

    _show_login_form()
    st.stop()


# =========================================================
# INTERNAL
# =========================================================

def _init_state():
    defaults = {
        "authenticated": False,
        "last_activity": 0.0,
        "login_error": "",
        # fallback rate limiting สำหรับ session ที่ระบุ IP ไม่ได้
        "session_attempts": 0,
        "session_lockout_until": 0.0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _show_login_form():
    col = st.columns([1, 2, 1])[1]
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🔒 โรงชิพจัตุรัส")
        st.markdown("กรุณากรอกรหัสผ่านเพื่อเข้าใช้งาน")
        st.markdown("<br>", unsafe_allow_html=True)

        ip = _get_client_ip()

        # ถ้า IP ระบุไม่ได้ → ใช้ session-based rate limiting แทน IP-based
        ip_known = ip != "unknown"

        if ip_known:
            ip_state  = _get_ip_state(ip)
            now       = time.time()
            remaining = ip_state["lockout_until"] - now

            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                st.error(f"🔐 บัญชีถูกล็อคชั่วคราว กรุณารอ **{mins}:{secs:02d}** นาที")
                st.caption(f"เกิดจากการกรอกรหัสผ่านผิดเกิน {MAX_ATTEMPTS} ครั้ง")
                return

            attempts = ip_state["attempts"]
            if attempts > 0:
                left = MAX_ATTEMPTS - attempts
                st.warning(f"⚠️ กรอกผิดไปแล้ว {attempts} ครั้ง — เหลืออีก {left} ครั้งก่อนถูกล็อค")
        else:
            # IP ระบุไม่ได้ → ใช้ session-based rate limiting แทน
            now = time.time()
            remaining = st.session_state["session_lockout_until"] - now
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                st.error(f"🔐 บัญชีถูกล็อคชั่วคราว กรุณารอ **{mins}:{secs:02d}** นาที")
                st.caption(f"เกิดจากการกรอกรหัสผ่านผิดเกิน {MAX_ATTEMPTS} ครั้ง")
                return
            attempts = st.session_state["session_attempts"]
            if attempts > 0:
                left = MAX_ATTEMPTS - attempts
                st.warning(f"⚠️ กรอกผิดไปแล้ว {attempts} ครั้ง — เหลืออีก {left} ครั้งก่อนถูกล็อค")

        if st.session_state["login_error"]:
            st.error(st.session_state["login_error"])
            st.session_state["login_error"] = ""

        with st.form("login_form"):
            password_input = st.text_input(
                label="รหัสผ่าน",
                type="password",
                placeholder="กรอกรหัสผ่าน...",
                label_visibility="collapsed",
            )
            if st.form_submit_button("เข้าสู่ระบบ", type="primary", width="stretch"):
                _handle_login(password_input, ip, ip_known)


def _handle_login(password_input: str, ip: str, ip_known: bool):
    if not password_input:
        st.warning("กรุณากรอกรหัสผ่าน")
        return

    correct = st.secrets["auth"]["password"]

    if hmac.compare_digest(password_input.encode("utf-8"), correct.encode("utf-8")):
        if ip_known:
            _set_ip_state(ip, attempts=0, lockout_until=0.0)
        st.session_state["authenticated"] = True
        st.session_state["last_activity"] = time.time()
        st.rerun()
    else:
        if not ip_known:
            new_attempts = st.session_state["session_attempts"] + 1
            if new_attempts >= MAX_ATTEMPTS:
                st.session_state["session_attempts"] = 0
                st.session_state["session_lockout_until"] = time.time() + LOCKOUT_SEC
                st.session_state["login_error"] = f"🔐 กรอกผิดครบ {MAX_ATTEMPTS} ครั้ง — ถูกล็อค 15 นาที"
            else:
                st.session_state["session_attempts"] = new_attempts
                st.session_state["login_error"] = f"❌ รหัสผ่านไม่ถูกต้อง ({new_attempts}/{MAX_ATTEMPTS})"
            st.rerun()
            return

        ip_state     = _get_ip_state(ip)
        new_attempts = ip_state["attempts"] + 1

        if new_attempts >= MAX_ATTEMPTS:
            _set_ip_state(ip, attempts=0, lockout_until=time.time() + LOCKOUT_SEC)
            st.session_state["login_error"] = f"🔐 กรอกผิดครบ {MAX_ATTEMPTS} ครั้ง — IP ถูกล็อค 15 นาที"
        else:
            _set_ip_state(ip, attempts=new_attempts, lockout_until=0.0)
            st.session_state["login_error"] = f"❌ รหัสผ่านไม่ถูกต้อง ({new_attempts}/{MAX_ATTEMPTS})"

        st.rerun()


def _show_sidebar_info():
    with st.sidebar:
        elapsed   = time.time() - st.session_state["last_activity"]
        remaining = max(0, SESSION_TTL - elapsed)
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        st.markdown("---")
        st.caption(f"⏱️ Session หมดอายุใน **{mins}:{secs:02d}**")
        if st.button("🔓 Logout", width="stretch"):
            _force_logout()


def _force_logout(message: str = ""):
    st.session_state["authenticated"] = False
    st.session_state["last_activity"] = 0.0
    if message:
        st.warning(message)
    st.rerun()
