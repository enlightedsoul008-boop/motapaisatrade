import streamlit as st
import requests, json, os
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ================= BASIC CONFIG =================
st.set_page_config(page_title="World Class Futures Scanner", layout="wide")

# ================= SECRETS =================
APP_PASSWORD = st.secrets["APP_PASSWORD"]
TG_TOKEN = st.secrets["TG_TOKEN"]
TG_CHAT_ID = st.secrets["TG_CHAT_ID"]

API_URL = "https://api.delta.exchange/v2/tickers"
DATA_FILE = "trades.json"
OI_FILE = "oi_snapshot.json"
AUTO_SCAN_SECONDS = 60

# ================= PASSWORD =================
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    pwd = st.text_input("🔐 Enter Password", type="password")
    if st.button("LOGIN"):
        if pwd == APP_PASSWORD:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

# ================= FILE HELPERS =================
def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path))
    except:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=5)
    except:
        pass

# ================= FETCH =================
@st.cache_data(ttl=15)
def fetch_data():
    r = requests.get(API_URL, timeout=10)
    data = r.json().get("result", [])
    return list(data.values()) if isinstance(data, dict) else data

# ================= PROCESS =================
def prepare_df(data):
    rows = []
    for d in data:
        try:
            rows.append({
                "Symbol": d["symbol"],
                "Price": float(d["mark_price"]),
                "Volume": float(d.get("volume", 0)),
                "OI": float(d.get("oi", 0)),
                "Funding": float(d.get("funding_rate", 0)),
                "Change": float(d.get("price_change_percent", 0))
            })
        except:
            pass
    return pd.DataFrame(rows)

# ================= TP LOGIC =================
def calc_tp(price, direction):
    p1, p2 = (0.01, 0.02) if price > 1 else (0.03, 0.06)
    return (
        round(price * (1 + p1 if direction == "LONG" else 1 - p1), 6),
        round(price * (1 + p2 if direction == "LONG" else 1 - p2), 6)
    )

# ================= STRATEGY =================
def find_trade(df, oi_prev):
    best, best_score = None, 0
    df = df.sort_values("Volume", ascending=False).head(25)

    for _, r in df.iterrows():
        if r["Volume"] < 1000 or r["OI"] < 1000:
            continue

        prev_oi = oi_prev.get(r["Symbol"], 0)
        oi_delta = r["OI"] - prev_oi
        if oi_delta <= 0:
            continue

        # 🟡 BUILDING PHASE (alert once)
        if abs(r["Change"]) < 0.05:
            key = f"build_{r['Symbol']}"
            if not st.session_state.get(key):
                send_telegram(f"🟡 BUILDING PHASE\n{r['Symbol']}")
                st.session_state[key] = True
            continue

        if r["Change"] > 0:
            direction = "LONG"
        else:
            direction = "SHORT"

        if direction == "LONG" and r["Funding"] > 0.01:
            continue
        if direction == "SHORT" and r["Funding"] < -0.01:
            continue

        score = (r["Volume"] * oi_delta) / (abs(r["Change"]) + 0.001)

        if score > best_score:
            tp1, tp2 = calc_tp(r["Price"], direction)
            best = {
                "Time": datetime.now().strftime("%H:%M:%S"),
                "Symbol": r["Symbol"],
                "Direction": direction,
                "Entry": f"{r['Price']:.6f}",
                "TP1": f"{tp1:.6f}",
                "TP2": f"{tp2:.6f}",
                "Status": "RUNNING"
            }
            best_score = score

    return best

# ================= AUTO REFRESH =================
st_autorefresh(interval=AUTO_SCAN_SECONDS * 1000, key="scan")

# ================= UI =================
st.title("🚀 World Class Futures Scanner")

trades = load_json(DATA_FILE, [])
oi_prev = load_json(OI_FILE, {})

df = prepare_df(fetch_data())
price_map = dict(zip(df["Symbol"], df["Price"]))

# TP HIT ALERT
for t in trades:
    if t["Status"] == "RUNNING" and t["Symbol"] in price_map:
        price = price_map[t["Symbol"]]
        tp1, tp2 = float(t["TP1"]), float(t["TP2"])
        old = t["Status"]

        if t["Direction"] == "LONG":
            if price >= tp2:
                t["Status"] = "TP ACHIEVED"
            elif price >= tp1:
                t["Status"] = "TP1 HIT"
        else:
            if price <= tp2:
                t["Status"] = "TP ACHIEVED"
            elif price <= tp1:
                t["Status"] = "TP1 HIT"

        if old != t["Status"]:
            send_telegram(f"🛑 {t['Status']}\n{t['Symbol']}")

save_json(DATA_FILE, trades)
save_json(OI_FILE, dict(zip(df["Symbol"], df["OI"])))

st.caption(f"📊 Markets scanned: {len(df)}")

# ================= AUTO SIGNAL =================
trade = find_trade(df, oi_prev)
if trade:
    trades.insert(0, trade)
    save_json(DATA_FILE, trades)
    send_telegram(
        f"🔥 MOTA PAISA TRADE\n{trade['Symbol']}\n{trade['Direction']}\nEntry: {trade['Entry']}"
    )

st.dataframe(pd.DataFrame(trades), use_container_width=True)
