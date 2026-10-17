import ftplib
import io
import random
import streamlit as st
import yfinance as yf
import pandas as pd
import ta

# محاولة استيراد مكتبة finvizfinance إذا كانت متوفرة
try:
    from finvizfinance.screener.overview import Overview
    FINVIZ_AVAILABLE = True
except ImportError:
    FINVIZ_AVAILABLE = False

st.set_page_config(page_title="ماسح الأسهم", layout="centered")

st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; text-align: right; }
</style>
""", unsafe_allow_html=True)

PRICE_RANGES = {
    "أي سعر": (0, 1e9), "أقل من 1": (0, 1), "1 - 5": (1, 5),
    "5 - 20": (5, 20), "أكثر من 20": (20, 1e9),
}
CAP_RANGES = {
    "أي قيمة": (0, 1e15),
    "مايكرو (أقل من 300 مليون)": (0, 3e8),
    "صغيرة (300 مليون - 2 مليار)": (3e8, 2e9),
    "متوسطة (2 - 10 مليار)": (2e9, 1e10),
    "كبيرة (أكثر من 10 مليار)": (1e10, 1e15),
}
MAX_DETAIL = 150

DEFAULTS = {
    "market": "الكل", "market_value": "أي قيمة", "price": "أي سعر",
    "price_loc": "الكل", "use_float": True, "float_min": 0, "float_max": 1000000,
    "use_reverse": True, "use_max_rise_split": True, "split_days": 60,
    "max_rise_split": 20.0,
    "use_rsi": True, "use_macd": True, "timeframe": "يومي",
    "rsi_from": 23.0, "rsi_to": 30.0, "macd_from": -2.0, "macd_to": 0.0,
    "use_short": True, "use_support": True, "max_short_float": 50000,
    "support_tests": 5, "search_sessions": 10, "max_rise_support": 20.0,
    "quick": True,
}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

st.title("إعدادات الفحص (Yahoo + Finviz)")

with st.expander("01 البيانات الأساسية", expanded=True):
    st.selectbox("السوق", ["الكل", "ناسداك", "NYSE"], key="market")
    st.selectbox("القيمة السوقية", list(CAP_RANGES), key="market_value")
    st.selectbox("السعر", list(PRICE_RANGES), key="price")
    st.selectbox("موقع السعر", ["الكل", "فوق المتوسط 50", "تحت المتوسط 50"], key="price_loc")
    st.checkbox("عدد الأسهم الحرة", key="use_float")
    st.number_input("الحد الأدنى للأسهم الحرة (بالآلاف)", step=1000, key="float_min")
    st.number_input("الحد الأقصى للأسهم الحرة (بالآلاف)", step=1000, key="float_max")

with st.expander("02 تقسيم الأسهم", expanded=True):
    st.checkbox("التقسيم العكسي", key="use_reverse")
    st.checkbox("أقصى ارتفاع (%) بعد التقسيم", key="use_max_rise_split")
    st.selectbox("فترة التقسيم (أيام)", [30, 60, 90, 180, 365], key="split_days")
    st.number_input("أقصى ارتفاع (%)", step=1.0, format="%.2f", key="max_rise_split")

with st.expander("03 المؤشرات الفنية", expanded=True):
    st.checkbox("RSI (14)", key="use_rsi")
    st.checkbox("MACD", key="use_macd")
    st.selectbox("الإطار الزمني", ["يومي", "أسبوعي", "شهري"], key="timeframe")
    st.number_input("RSI من", step=1.0, format="%.2f", key="rsi_from")
    st.number_input("RSI إلى", step=1.0, format="%.2f", key="rsi_to")
    st.number_input("MACD من", step=0.5, format="%.2f", key="macd_from")
    st.number_input("MACD إلى", step=0.5, format="%.2f", key="macd_to")

with st.expander("04 أسهم الشورت و الدعم", expanded=True):
    st.checkbox("فلتر الأسهم المتاحة للاقتراض", key="use_short")
    st.checkbox("اختبار الدعم", key="use_support")
    st.number_input("الحد الأقصى للأسهم المتاحة", step=1000, key="max_short_float")
    st.number_input("اختبارات الدعم (جلسات)", step=1, key="support_tests")
    st.number_input("جلسات البحث", step=1, key="search_sessions")
    st.number_input("أقصى ارتفاع عن الدعم (%)", step=1.0, format="%.2f", key="max_rise_support")

st.checkbox("فحص تجريبي سريع (300 سهم عشوائي)", key="quick")


# ---------------- جلب البيانات (مدمج Yahoo و Finviz) ----------------
@st.cache_data(ttl=86400)
def load_universe(market):
    symbols = []

    # 1. Finviz (فقط عند اختيار "الكل" لأنه لا يفرّق بين الأسواق هنا)
    if FINVIZ_AVAILABLE and market == "الكل":
        try:
            overview = Overview()
            df_finviz = overview.screener_view()
            if not df_finviz.empty and "Ticker" in df_finviz.columns:
                symbols.extend(df_finviz["Ticker"].tolist())
        except Exception:
            pass

    # 2. الجلب الأساسي من ناسداك
    base = "https://www.nasdaqtrader.com/dynamic/SymDir/"
    parts = []
    try:
        if market in ("الكل", "ناسداك"):
            d = pd.read_csv(base + "nasdaqlisted.txt", sep="|")
            d = d[(d["Test Issue"] == "N") & (d["ETF"] == "N")]
            parts.append(d["Symbol"])
        if market in ("الكل", "NYSE"):
            d = pd.read_csv(base + "otherlisted.txt", sep="|")
            d = d[(d["Test Issue"] == "N") & (d["ETF"] == "N")]
            parts.append(d["ACT Symbol"])
        if parts:
            s = pd.concat(parts).dropna().astype(str)
            s = s[s.str.fullmatch(r"[A-Z]{1,5}")]
            symbols.extend(s.unique().tolist())
    except Exception:
        pass

    return sorted(set(symbols))


@st.cache_data(ttl=3600)
def load_shortable():
    try:
        ftp = ftplib.FTP("ftp3.interactivebrokers.com", timeout=30)
        ftp.login("shortstock", "")
        buf = io.BytesIO()
        ftp.retrbinary("RETR usa.txt", buf.write)
        ftp.quit()
        out = {}
        for line in buf.getvalue().decode("utf-8", "ignore").splitlines():
            if line.startswith("#") or "|" not in line:
                continue
            p = line.split("|")
            if len(p) < 8:
                continue
            raw = p[7].replace(">", "").strip()
            if raw.isdigit():
                out[p[0]] = int(raw)
        return out
    except Exception:
        return None


def scan_indicators(symbols, s):
    period = "5y" if s.timeframe == "شهري" else "2y" if s.timeframe == "أسبوعي" else "1y"
    pmin, pmax = PRICE_RANGES[s.price]
    rows = []
    bar = st.progress(0.0)
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        done = min(i + 100, len(symbols))
        bar.progress(done / len(symbols), text=f"تحميل الأسعار {done} / {len(symbols)}")
        try:
            data = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                               auto_adjust=True,
