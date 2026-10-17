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
                               auto_adjust=True, progress=False, threads=True)
        except Exception:
            continue
        for sym in chunk:
            try:
                close = data[sym]["Close"].dropna()
                price = float(close.iloc[-1])
                if not (pmin <= price <= pmax):
                    continue
                if s.timeframe == "أسبوعي":
                    close = close.resample("W").last().dropna()
                elif s.timeframe == "شهري":
                    close = close.resample("ME").last().dropna()
                if len(close) < 40:
                    continue
                sma = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
                if s.price_loc == "فوق المتوسط 50" and (sma is None or price <= sma):
                    continue
                if s.price_loc == "تحت المتوسط 50" and (sma is None or price >= sma):
                    continue
                rsi = float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])
                macd = float(ta.trend.MACD(close).macd().iloc[-1])
                if s.use_rsi and not (s.rsi_from <= rsi <= s.rsi_to):
                    continue
                if s.use_macd and not (s.macd_from <= macd <= s.macd_to):
                    continue
                rows.append({"sym": sym, "price": price, "rsi": rsi, "macd": macd})
            except Exception:
                continue
    bar.empty()
    return rows


def detail_checks(row, s, shortable):
    sym = row["sym"]
    t = yf.Ticker(sym)
    info = t.info
    cap, flt = info.get("marketCap"), info.get("floatShares")

    if s.market_value != "أي قيمة":
        lo, hi = CAP_RANGES[s.market_value]
        if cap is None or not (lo <= cap <= hi):
            return None
    if s.use_float:
        if flt is None or not (s.float_min * 1000 <= flt <= s.float_max * 1000):
            return None

    hist = t.history(period="1y", interval="1d")
    if hist.empty:
        return None

    if s.use_reverse:
        sp = t.splits
        if len(sp) == 0:
            return None
        cutoff = pd.Timestamp.now(tz=sp.index.tz) - pd.Timedelta(days=int(s.split_days))
        rev = sp[(sp < 1) & (sp.index >= cutoff)]
        if rev.empty:
            return None
        if s.use_max_rise_split:
            after = hist[hist.index >= rev.index[-1]]
            if after.empty:
                return None
            rise = (after["High"].max() / after["Close"].iloc[0] - 1) * 100
            if rise > s.max_rise_split:
                return None

    avail = shortable.get(sym) if shortable else None
    if s.use_short and shortable is not None:
        if avail is None or not (0 < avail <= s.max_short_float):
            return None

    rise_sup = None
    if s.use_support:
        w = hist.tail(int(s.search_sessions))
        if len(w) < int(s.search_sessions):
            return None
        sup = w["Low"].min()
        tests = int((w["Low"] <= sup * 1.02).sum())
        if tests < s.support_tests:
            return None
        rise_sup = (hist["Close"].iloc[-1] / sup - 1) * 100
        if rise_sup > s.max_rise_support:
            return None

    return {
        "الرمز": sym,
        "السعر": round(row["price"], 2),
        "RSI": round(row["rsi"], 2),
        "MACD": round(row["macd"], 3),
        "الأسهم الحرة (مليون)": round(flt / 1e6, 2) if flt else None,
        "المتاح للاقتراض": avail,
        "ارتفاع عن الدعم %": round(rise_sup, 1) if rise_sup is not None else None,
    }


def run_scan():
    s = st.session_state
    symbols = load_universe(s.market)
    if s.quick:
        # عشوائي بدل أول 300 (اللي كانت كلها تبدأ بحرف A)
        symbols = random.sample(symbols, min(300, len(symbols)))

    shortable = load_shortable() if s.use_short else None
    if s.use_short and shortable is None:
        st.warning("تعذر جلب بيانات الاقتراض، تم تخطي هذا الفلتر.")

    rows = scan_indicators(symbols, s)
    st.write(f"مرّ {len(rows)} سهم من فلتر السعر والمؤشرات. جاري الفحص التفصيلي...")
    if len(rows) > MAX_DETAIL:
        st.warning(f"النتائج كثيرة، سيتم فحص {MAX_DETAIL} سهم عشوائياً. ضيّق الشروط للحصول على نتيجة أدق.")
        rows = random.sample(rows, MAX_DETAIL)

    results, bar = [], st.progress(0.0)
    for i, r in enumerate(rows):
        bar.progress((i + 1) / max(len(rows), 1), text=f"فحص {r['sym']}")
        try:
            out = detail_checks(r, s, shortable)
        except Exception:
            continue
        if out:
            results.append(out)
    bar.empty()
    return results


def reset_all():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


start = st.button("▶ بدء الفحص", type="primary", use_container_width=True)
st.button("■ إيقاف الفحص", use_container_width=True)
st.button("↺ إعادة تعيين", on_click=reset_all, use_container_width=True)

if start:
    found = run_scan()
    if found:
        st.success(f"تم العثور على {len(found)} سهم مطابق")
        st.dataframe(pd.DataFrame(found), use_container_width=True, hide_index=True)
    else:
        st.warning("ما فيه أسهم مطابقة للشروط الحالية.")
