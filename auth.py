"""
auth.py
-------
ระบบ password gate พร้อม:
- Rate Limiting  : ล็อค 15 นาที หลังกรอกผิด 5 ครั้ง
- Session Timeout: หมดอายุอัตโนมัติหลัง 30 นาที ไม่มีกิจกรรม
"""

import hmac
import time
import threading
import streamlit as st

# =========================================================
# CONFIG
# =========================================================
MAX_ATTEMPTS   = 5          # กรอกผิดได้สูงสุดกี่ครั้ง
LOCKOUT_SEC    = 15 * 60    # ล็อคนานกี่วินาที (15 นาที)
SESSION_TTL    = 30 * 60    # session หมดอายุหลังกี่วินาที (30 นาที)


_rl_lock = threading.Lock()
_ip_store: dict[str, dict] = {}


def _get_client_ip() -> str:
    """ดึง IP จาก request headers"""
    try:
        headers = st.context.headers
        for header in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip"):
            val = headers.get(header, "")
            if val:
                return val.split(",")[0].strip()
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
            return
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
        ip_state = _get_ip_state(ip)
        now = time.time()
        remaining = ip_state["lockout_until"] - now

        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            st.error(f"🔐 บัญชีถูกล็อคชั่วคราว กรุณารอ **{mins}:{secs:02d}** นาที")
            st.caption(f"เกิดจากการกรอกรหัสผ่านผิดเกิน {MAX_ATTEMPTS} ครั้ง")
            st.rerun()
            return

        attempts = ip_state["attempts"]
        if attempts > 0:
            left = MAX_ATTEMPTS - attempts
            st.warning(f"⚠️ กรอกผิดไปแล้ว {attempts} ครั้ง — เหลืออีก {left} ครั้งก่อนถูกล็อค")

        password_input = st.text_input(
            label="รหัสผ่าน",
            type="password",
            placeholder="กรอกรหัสผ่าน...",
            label_visibility="collapsed",
        )

        if st.button("เข้าสู่ระบบ", type="primary", use_container_width=True):
            _handle_login(password_input, ip)


def _handle_login(password_input: str, ip: str):
    if not password_input:
        st.warning("กรุณากรอกรหัสผ่าน")
        return

    correct = st.secrets["auth"]["password"]

    if hmac.compare_digest(password_input.encode("utf-8"), correct.encode("utf-8")):
        _set_ip_state(ip, attempts=0, lockout_until=0.0)
        st.session_state["authenticated"] = True
        st.session_state["last_activity"] = time.time()
        st.rerun()
    else:
        ip_state = _get_ip_state(ip)
        new_attempts = ip_state["attempts"] + 1

        if new_attempts >= MAX_ATTEMPTS:
            _set_ip_state(ip, attempts=0, lockout_until=time.time() + LOCKOUT_SEC)
            st.error(f"🔐 กรอกผิดครบ {MAX_ATTEMPTS} ครั้ง — IP ถูกล็อค 15 นาที")
        else:
            _set_ip_state(ip, attempts=new_attempts, lockout_until=0.0)
            st.error(f"❌ รหัสผ่านไม่ถูกต้อง ({new_attempts}/{MAX_ATTEMPTS})")
        st.rerun()


def _show_sidebar_info():
    with st.sidebar:
        elapsed   = time.time() - st.session_state["last_activity"]
        remaining = max(0, SESSION_TTL - elapsed)
        mins = int(remaining // 60)
        secs = int(remaining % 60)

        st.markdown("---")
        st.caption(f"⏱️ Session หมดอายุใน **{mins}:{secs:02d}**")
        if st.button("🔓 Logout", use_container_width=True):
            _force_logout()


def _force_logout(message: str = ""):
    st.session_state["authenticated"] = False
    st.session_state["last_activity"] = 0.0
    if message:
        st.warning(message)
    st.rerun()
