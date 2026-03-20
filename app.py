import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import numpy as np
import time
from datetime import datetime, timedelta

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Ultimate Smart Money Analyst", layout="wide", page_icon="🏦")

# --- DAFTAR ADMIN ---
ADMIN_USERS = ["bos_besar", "admin_utama", "aprasetio"] 

# --- 2. SISTEM LOGIN AMAN ---
def check_password():
    def password_entered():
        if st.session_state["username"] in st.secrets["passwords"] and st.session_state["password"] == st.secrets["passwords"][st.session_state["username"]]:
            st.session_state["password_correct"] = True
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("<h1 style='text-align: center;'>🔒 Gerbang Keamanan</h1>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.text_input("Username", key="username")
            st.text_input("Password", type="password", key="password")
            st.button("Login", on_click=password_entered, use_container_width=True)
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("<h1 style='text-align: center;'>🔒 Gerbang Keamanan</h1>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.text_input("Username", key="username")
            st.text_input("Password", type="password", key="password")
            st.button("Login", on_click=password_entered, use_container_width=True)
            st.error("🚫 Username tidak dikenal atau Password salah!")
        return False
    else:
        return True

if not check_password():
    st.stop()

# --- 3. AMBIL DATA RAHASIA & STATUS ADMIN ---
IDX_API_KEY = st.secrets.get("IDX_API_KEY", st.secrets.get("GOAPI_KEY", ""))
admin_list = st.secrets.get("ADMIN_USERS", ADMIN_USERS)

current_user = st.session_state.get('username', '')
is_admin = current_user in admin_list

# --- 4. BUKU TAMU GLOBAL (SHARED CACHE REGISTRY) ---
@st.cache_resource
def get_api_registry():
    return set()

api_registry = get_api_registry()

# --- 5. CSS FIX (JUBAH GAIB DIPERBAIKI & STYLING TABEL HTML) ---
st.markdown("""
<style>
    /* 1. Sembunyikan HANYA menu kanan atas & tulisan deploy, biarkan tombol Sidebar Kiri hidup */
    [data-testid="stToolbar"] {display: none !important;}
    footer {display: none !important;}

    /* 2. Styling Visual Kotak Metrik (Milik Advanced Chart) */
    [data-testid="stMetric"] { background-color: #f0f2f6 !important; border: 1px solid #d6d6d6 !important; padding: 15px !important; border-radius: 10px !important; height: 100% !important; }
    [data-testid="stMetricLabel"] p { color: #31333F !important; font-weight: bold !important; font-size: 1rem !important; white-space: normal !important; }
    [data-testid="stMetricValue"] div { color: #000000 !important; font-size: 1.25rem !important; white-space: normal !important; line-height: 1.2 !important; }
    [data-testid="stMetricDelta"] div { font-size: 0.95rem !important; white-space: normal !important; }
    
    /* 3. Styling Khusus Tabel Dataframe (Memaksa Teks Turun Ke Bawah) */
    .styled-table {
        border-collapse: collapse;
        margin: 25px 0;
        font-size: 0.9em;
        font-family: sans-serif;
        width: 100%;
        box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
        border-radius: 8px 8px 0 0;
        overflow: hidden;
    }
    .styled-table thead tr {
        background-color: #f0f2f6;
        color: #31333F;
        text-align: left;
        font-weight: bold;
    }
    .styled-table th, .styled-table td {
        padding: 12px 15px;
        vertical-align: top;
        border-bottom: 1px solid #dddddd;
    }
    .styled-table tbody tr:last-of-type {
        border-bottom: 2px solid #009879;
    }
</style>
""", unsafe_allow_html=True)

# --- 6. DAFTAR SAHAM ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

SHARIA_MIDCAP_STOCKS = [
    "BRMS", "ELSA", "ENRG", "PTRO", "SIDO", "MYOR", "ESSA", "CTRA", "BSDE",
    "SMRA", "PWON", "ARTO", "BTPS", "MIKA", "HEAL", "SILO", "MAPA", "AUTO",
    "SMSM", "TAPG", "DSNG", "LSIP", "AALI", "WIKA", "PTPP", "TOTL", "NRCA",
    "SCMA", "MNCN", "ERAA"
]

# --- 7. HELPER FUNCTIONS ---
def fix_dataframe(df):
    if df.empty: return df
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.get_level_values(0)
        except: pass
    df.columns = [str(c).capitalize() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df

def format_rupiah(angka):
    if angka == 0: return "Rp 0"
    is_negative = angka < 0
    angka = abs(angka)
    if angka >= 1e9: formatted = f"Rp {angka/1e9:.2f} M"
    elif angka >= 1e6: formatted = f"Rp {angka/1e6:.2f} Jt"
    else: formatted = f"Rp {angka:,.0f}"
    return f"-{formatted}" if is_negative else formatted

def get_idx_target_date(df):
    wib_time = datetime.utcnow() + timedelta(hours=7)
    latest_yf_date = df.index[-1].date()
    if latest_yf_date == wib_time.date() and wib_time.hour < 18:
        return df.index[-2].strftime('%Y-%m-%d') if len(df) > 1 else df.index[-1].strftime('%Y-%m-%d')
    else:
        return df.index[-1].strftime('%Y-%m-%d')

# --- 8. FUNGSI FETCH IHSG & FUNDAMENTAL & DATA IDX ---
@st.cache_data(ttl=3600)
def get_ihsg_data():
    try:
        ihsg = yf.download("^JKSE", period="1y", auto_adjust=True, progress=False)
        ihsg = fix_dataframe(ihsg)
        return ihsg[['Close']].rename(columns={'Close': 'IHSG_Close'})
    except:
        return pd.DataFrame()

@st.cache_data(ttl=43200)
def fetch_idx_foreign_flow(symbol, target_date):
    headers = {
        'accept': 'application/json', 
        'X-API-KEY': IDX_API_KEY,
        'User-Agent': 'Mozilla/5.0'
    }
    net_foreign, avg_buy_price = 0, 0
    wib_time = datetime.utcnow() + timedelta(hours=7)
    fetch_time = wib_time.strftime("%d %b %Y, %H:%M WIB")
    
    try:
        url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
        res_broker = requests.get(url_broker, headers=headers, timeout=10)
        if res_broker.status_code != 200:
            st.sidebar.error(f"🚨 Data IDX Error {symbol}: {res_broker.status_code}")
            return None, 0, None
        
        res_broker_json = res_broker.json()
        total_buy_val, total_buy_lot, total_sell_val = 0, 0, 0
        
        if res_broker_json.get('status') == 'success':
            for broker in res_broker_json['data']['results']:
                if broker['side'] == 'BUY':
                    total_buy_val += broker['value']
                    total_buy_lot += broker['lot']
                elif broker['side'] == 'SELL':
                    total_sell_val += broker['value']
                    
            net_foreign = total_buy_val - total_sell_val
            if total_buy_lot > 0:
                avg_buy_price = total_buy_val / (total_buy_lot * 100)
    except Exception as e: 
        st.sidebar.error(f"🔌 Koneksi API Terputus: {e}")
        return None, 0, None
        
    return net_foreign, avg_buy_price, fetch_time

@st.cache_data(ttl=3600) 
def get_fundamental_info(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            "PBV": info.get('priceToBook', None),
            "ROE": info.get('returnOnEquity', None), 
            "DER": info.get('debtToEquity', None),
            "DivYield": info.get('dividendYield', None),
            "EPS_Growth": info.get('earningsQuarterlyGrowth', None)
        }
    except: return None

# --- 9. FUNGSI TEKNIKAL & RELATIVE STRENGTH ---
def check_candlestick_patterns(curr, prev):
    score = 0
    patterns = []
    try:
        body = abs(curr['Close'] - curr['Open'])
        upper = curr['High'] - max(curr['Close'], curr['Open'])
        lower = min(curr['Close'], curr['Open']) - curr['Low']
        rsi = curr.get('Rsi', 50)
        lower_bb = curr.get('BBL_20_2.0', 0)
        is_valid_support = (rsi < 40) or (curr['Low'] <= lower_bb * 1.01)

        if (lower > 2 * body) and (upper < body):
            if is_valid_support: score += 1; patterns.append("🔨 Hammer")
        if (prev['Close'] < prev['Open']) and (curr['Close'] > curr['Open']): 
            if (curr['Open'] < prev['Close']) and (curr['Close'] > prev['Open']):
                if is_valid_support: score += 1.5; patterns.append("🦁 Engulfing")
    except: pass
    return score, patterns

def calculate_metrics(df, ihsg_df=None):
    df = fix_dataframe(df)
    try:
        df['Rsi'] = df.ta.rsi(length=14)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        bbands = df.ta.bbands(length=20, std=2)
        
        df['SMA20'] = df.ta.sma(length=20)
        df['SMA50'] = df.ta.sma(length=50)
        df['SMA100'] = df.ta.sma(length=100)
        df['EMA200'] = df.ta.ema(length=200)
        df['ATR'] = df.ta.atr(length=14)
        
        df = pd.concat([df, macd, bbands], axis=1)
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
        
        if ihsg_df is not None and not ihsg_df.empty:
            df = df.join(ihsg_df, how='left')
            df['IHSG_Close'] = df['IHSG_Close'].ffill() 
            df['Stock_Ret_20'] = (df['Close'] - df['Close'].shift(20)) / df['Close'].shift(20)
            df['IHSG_Ret_20'] = (df['IHSG_Close'] - df['IHSG_Close'].shift(20)) / df['IHSG_Close'].shift(20)
            
    except: pass
    return df

def advanced_analysis(df):
    if len(df) < 15: return "N/A", "-"
    curr = df.iloc[-1]
    
    close, ma20, ma50, cmf = curr['Close'], curr['SMA20'], curr['SMA50'], curr['CMF']
    phase = "Sideways/Noise"
    if close > ma20 and ma20 > ma50: phase = "🔵 Markup (Naik)"
    elif close < ma20 and ma20 < ma50: phase = "🟠 Markdown (Turun)"
    elif close > ma50 and cmf < 0: phase = "🔴 Distribution (Pucuk)"
    elif close < ma50 and cmf > 0: phase = "🟢 Accumulation (Bawah)"

    divergence = "-"
    if len(df) > 10:
        price_trend = df['Close'].iloc[-1] - df['Close'].iloc[-10]
        cmf_trend = df['CMF'].iloc[-1] - df['CMF'].iloc[-10]
        if price_trend < 0 and cmf_trend > 0.15: divergence = "🟢 BULLISH DIV"
        elif price_trend > 0 and cmf_trend < -0.15: divergence = "🔴 BEARISH DIV"
            
    return phase, divergence

def score_analysis(df, fund_data):
    if df.empty or len(df)<2: return 0, 0, 0, 0, ["Data Kurang"], df.iloc[-1]
    curr, prev = df.iloc[-1], df.iloc[-2]
    
    score_tech, score_fund, score_bandar, score_candle = 0, 0, 0, 0
    reasons = []
    
    is_all_above_ma = False
    if not pd.isna(curr.get('SMA100')) and not pd.isna(curr.get('EMA200')):
        if (curr['Close'] > curr['SMA20'] and curr['Close'] > curr['SMA50'] and 
            curr['Close'] > curr['SMA100'] and curr['Close'] > curr['EMA200']):
            is_all_above_ma = True
            score_tech += 2  
            reasons.append("🔥 ALL ABOVE MA")
            
    if not is_all_above_ma and not pd.isna(curr.get('EMA200')) and curr['Close'] > curr['EMA200']:
        score_tech += 1
        reasons.append("📈 Tren Mayor Naik")

    if 'Stock_Ret_20' in df.columns and 'IHSG_Ret_20' in df.columns:
        stock_ret = curr['Stock_Ret_20']
        ihsg_ret = curr['IHSG_Ret_20']
        if not pd.isna(stock_ret) and not pd.isna(ihsg_ret):
            if stock_ret > ihsg_ret:
                score_tech += 1.5 
                reasons.append(f"🌟 Outperform IHSG")
        
    cmf = curr.get('CMF', 0)
    if cmf > 0.1: score_bandar = 2; reasons.append("🐳 Akumulasi CMF")
    elif cmf > 0.05: score_bandar = 1
    elif cmf < -0.1: score_bandar = -2; reasons.append("🔻 Distribusi CMF")
        
    if curr.get('MACD_12_26_9', 0) > curr.get('MACDs_12_26_9', 0): score_tech += 1
    rsi = curr.get('Rsi', 50)
    if rsi < 35: score_tech += 2; reasons.append("💎 RSI Oversold")
    elif rsi > 70: score_tech -= 1
    
    if fund_data:
        pbv = fund_data.get('PBV')
        eps_g = fund_data.get('EPS_Growth')
        if pbv and pbv < 1.5: score_fund += 2
        if eps_g and eps_g > 0.10: 
            score_fund += 2
            reasons.append(f"🚀 Laba Tumbuh")
        
    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns: reasons.append(f"🕯️ {patterns[0]}")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr
# --- 10. FITUR SCREENER (DENGAN TABEL HTML KUSTOM) ---
def run_screener(use_idx_data, stock_list, category_name):
    st.header(f"🔍 Smart Money Screener ({category_name})")
    if use_idx_data: 
        st.success("🏦 Mode Data IDX: Memfilter Foreign Flow & Harga Modal Bandar aktif.")
    else: 
        st.info("🌐 Mode Yahoo Finance: Scanning Cepat Unlimited (Fokus Pergerakan Bandar Lokal & Teknikal).")
    
    if st.button("MULAI SCANNING"):
        progress = st.progress(0)
        status = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in stock_list]
        
        status.text("Mengambil Data IHSG (Benchmark)...")
        ihsg_df = get_ihsg_data()
        
        price_data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        last_sync_time, last_bursa_date, idx_date_used = None, None, None
        
        for i, t in enumerate(tickers):
            status.text(f"Menganalisa Saham: {t} ...")
            progress.progress((i+1)/len(tickers))
            
            try:
                df = price_data[t].copy()
                df = fix_dataframe(df)
                if df.empty or len(df) < 50: continue
                min_vol = 5000000 if category_name == "Lapis 1 (JII30)" else 2000000
                if df['Volume'].iloc[-1] < min_vol: continue
                
                df = calculate_metrics(df, ihsg_df)
                fund = get_fundamental_info(t)
                s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                wyckoff_phase, divergence = advanced_analysis(df)
                total_score = s_tech + s_fund + s_bandar + s_candle
                
                atr = last.get('ATR', 0)
                close = last['Close']
                volume = last['Volume']
                daily_turnover = close * volume 
                
                if atr > 0:
                    stop_loss = close - (1.5 * atr) 
                    target_profit = close + (3.0 * atr) 
                else:
                    stop_loss, target_profit = close * 0.9, close * 1.1
                
                rec = "WAIT"
                if total_score >= 6 or "BULLISH DIV" in divergence or "ALL ABOVE MA" in " ".join(reasons): 
                    rec = "💎 STRONG BUY"
                elif total_score >= 4 or "Accumulation" in wyckoff_phase: 
                    rec = "✅ BUY"
                
                if total_score < 3 and "BULLISH DIV" not in divergence and "Accumulation" not in wyckoff_phase and "ALL ABOVE MA" not in " ".join(reasons):
                    continue
                
                symbol_only = t.replace(".JK", "")
                net_foreign, avg_buy_price, power_pct = None, 0, 0
                
                idx_date = get_idx_target_date(df)
                idx_date_used = idx_date
                last_bursa_date = df.index[-1].strftime('%d %b %Y') 
                
                if use_idx_data:
                    status.text(f"Menarik Data IDX: {t} ...")
                    time.sleep(1) 
                    net_foreign, avg_buy_price, fetch_time = fetch_idx_foreign_flow(symbol_only, idx_date)
                    if fetch_time: last_sync_time = fetch_time 
                    
                    api_registry.add(f"{symbol_only}_{idx_date}")
                    
                    if net_foreign is not None and net_foreign <= 0: continue
                
                if net_foreign is not None:
                    if daily_turnover > 0: power_pct = (abs(net_foreign) / daily_turnover) * 100
                    power_str = f" 🔥 (Power: {power_pct:.1f}%)" if power_pct >= 10 else f" (Power: {power_pct:.1f}%)"
                    modal_str = f" Modal: Rp {int(avg_buy_price):,}" if avg_buy_price > 0 else ""
                    reasons.append(f"🌐 ASING: {format_rupiah(net_foreign)}{power_str} |{modal_str}")

                status_ihsg = "✅ Outperform" if "🌟 Outperform IHSG" in reasons else "❌ Underperform"

                # Pemisah baris menggunakan tag HTML <br> agar turun ke bawah
                formatted_reasons = "<br>".join([f"• {r.strip()}" for r in reasons])
                formatted_target = f"TP: Rp {int(target_profit):,}<br>SL: Rp {int(stop_loss):,}"

                results.append({
                    "Kode": symbol_only,
                    "Harga": int(close),
                    "Target_SL": formatted_target,
                    "Wyckoff": wyckoff_phase.split(" ")[1] if len(wyckoff_phase.split(" ")) > 1 else wyckoff_phase,
                    "Vs_IHSG": status_ihsg,
                    "Asing": f"{power_pct:.1f}%" if use_idx_data and net_foreign is not None else "-",
                    "Rek": rec,
                    "Alasan": formatted_reasons
                })
            except Exception as loop_e: 
                continue
            
        progress.empty()
        status.empty()
        
        if results:
            st.success(f"Selesai! {len(results)} Saham Terbaik Ditemukan.")
            if use_idx_data and last_sync_time:
                st.caption(f"📅 **Data Harga Per:** {last_bursa_date} | 🔄 **Data Asing Diambil Tgl:** {idx_date_used} (Sync: {last_sync_time})")
            elif last_bursa_date:
                st.caption(f"📅 **Data Bursa Per:** {last_bursa_date} | 🌐 **Sumber Bandar:** Yahoo Finance")
            
            # --- PEMBUATAN TABEL HTML KUSTOM (ANTI-GESER KANAN) ---
            html_table = "<table class='styled-table'>"
            html_table += "<thead><tr><th>Kode</th><th>Harga</th><th>Target / SL</th><th>Wyckoff</th><th>Vs IHSG</th><th>Dominasi Asing</th><th>Status</th><th>Poin Analisa (Alasan)</th></tr></thead><tbody>"
            
            for r in results:
                # Memberi warna khusus untuk rekomendasi
                rek_color = "#009879" if "BUY" in r['Rek'] else "#d9534f"
                
                html_table += f"""
                <tr>
                    <td><strong>{r['Kode']}</strong></td>
                    <td>Rp {r['Harga']:,}</td>
                    <td>{r['Target_SL']}</td>
                    <td>{r['Wyckoff']}</td>
                    <td>{r['Vs_IHSG']}</td>
                    <td>{r['Asing']}</td>
                    <td><strong style='color:{rek_color}'>{r['Rek']}</strong></td>
                    <td>{r['Alasan']}</td>
                </tr>
                """
            html_table += "</tbody></table>"
            
            # Render HTML ke layar Streamlit
            st.markdown(html_table, unsafe_allow_html=True)
            
        else:
            st.warning("Data kosong / Tidak ada saham yang lolos kriteria.")

# --- 11. FITUR CHART DETAIL ---
def show_chart(use_idx_data):
    st.header("📊 Deep Analysis & Target Tracker")
    
    with st.form(key='chart_search_form'):
        c_input, c_btn = st.columns([4, 1])
        with c_input:
            ticker = st.text_input("Masukkan Kode Saham (Contoh: BRMS, ELSA, PTBA)", "").upper()
        with c_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_search = st.form_submit_button("Cari Saham 🔍")
            
    if submit_search and ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        ticker_only = ticker.replace(".JK", "")
        
        ihsg_df = get_ihsg_data()
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        if df.empty:
            st.error("Saham tidak ditemukan di Yahoo Finance!")
            return

        df = calculate_metrics(df, ihsg_df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
        wyckoff_phase, divergence = advanced_analysis(df)
        
        net_foreign, avg_buy_price, fetch_time = None, 0, None
        
        idx_date = get_idx_target_date(df)
        last_date_disp = df.index[-1].strftime('%d %b %Y')
        
        # --- PERLINDUNGAN KUOTA (SMART WHITELIST) ---
        cache_key = f"{ticker_only}_{idx_date}"
        if use_idx_data and not is_admin:
            if cache_key not in api_registry:
                st.info(f"ℹ️ **Info:** Saham {ticker_only} belum terdapat di dalam data Smart Screener hari ini. Aplikasi otomatis menggunakan data Yahoo Finance.")
                use_idx_data = False
        
        if use_idx_data:
            net_foreign, avg_buy_price, fetch_time = fetch_idx_foreign_flow(ticker_only, idx_date)
            if is_admin:
                api_registry.add(cache_key)
            
        st.divider()
        
        if use_idx_data and fetch_time:
            st.caption(f"📅 **Harga Per:** {last_date_disp} | 🔄 **Asing Diambil Tgl:** {idx_date} (Sync: {fetch_time})")
        else:
            st.caption(f"📅 **Data Bursa Per:** {last_date_disp} | 🌐 **Sumber Bandar:** Yahoo Finance (Estimasi / Tanpa Asing)")
        
        atr = last.get('ATR', 0)
        close = last['Close']
        volume = last['Volume']
        daily_turnover = close * volume
        
        if atr > 0:
            stop_loss = close - (1.5 * atr)
            target_profit = close + (3.0 * atr)
            tp_pct = ((target_profit - close) / close) * 100
        else:
            stop_loss, target_profit, tp_pct = close, close, 0
            
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga Terakhir & Fase", f"Rp {int(close):,}", wyckoff_phase)
        c2.metric("Target (TP) & Stop Loss", f"Rp {int(target_profit):,}", f"Cut Loss: Rp {int(stop_loss):,} (+{tp_pct:.1f}% TP)", delta_color="normal")
        
        if net_foreign is not None:
            power_pct = (abs(net_foreign) / daily_turnover) * 100 if daily_turnover > 0 else 0
            foreign_label = "🟢 AKUMULASI" if net_foreign > 0 else ("🔴 DISTRIBUSI" if net_foreign < 0 else "⚪ NETRAL")
            power_info = f"Dominasi Asing: {power_pct:.1f}% | Modal: Rp {int(avg_buy_price):,}" if avg_buy_price > 0 else f"Dominasi Asing: {power_pct:.1f}%"
            if power_pct >= 10: power_info = "🔥 " + power_info
            c3.metric(f"Asing ({foreign_label})", format_rupiah(net_foreign), power_info, delta_color="normal" if net_foreign > 0 else "inverse")
        else:
            c3.metric("Foreign Flow (Asing)", "Dinonaktifkan", "Dialihkan ke Mode Yahoo Finance", delta_color="off")
        
        is_outperform = "🌟 Outperform IHSG" in " ".join(reasons)
        rrg_status = "🌟 MENGALAHKAN IHSG" if is_outperform else "📉 UNDERPERFORM"
        eps_g = fund.get('EPS_Growth') if fund else None
        laba_str = f"Laba: +{eps_g*100:.1f}% 🚀" if eps_g and eps_g > 0 else (f"Laba: {eps_g*100:.1f}% 🔻" if eps_g else "Laba: N/A")
        
        c4.metric("Status vs Pasar (RRG)", rrg_status, laba_str, delta_color="normal" if is_outperform else "off")
        
        if "BULLISH DIV" in divergence:
            st.success(f"🚨 **DIVERGENCE ALERT:** {divergence} - Peluang besar harga akan segera rebound!")
        elif "BEARISH DIV" in divergence:
            st.error(f"🚨 **DIVERGENCE ALERT:** {divergence} - Hati-hati, indikator distribusi di pucuk!")
        
        st.subheader(f"Visualisasi Grafik {ticker_only} & Titik Krusial")
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.05, subplot_titles=("Harga, MA Pelangi, & Target", "Volume", "Bandar Flow (CMF)"))
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], line=dict(color='blue', width=1.5), name='MA50'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA100'], line=dict(color='green', width=2), name='MA100'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], line=dict(color='purple', width=2.5), name='EMA200'), row=1, col=1)
        
        if atr > 0:
            fig.add_hline(y=target_profit, line_dash="dash", line_color="green", annotation_text=f"Target: Rp {int(target_profit):,}", row=1, col=1)
            fig.add_hline(y=stop_loss, line_dash="dash", line_color="red", annotation_text=f"Stop Loss: Rp {int(stop_loss):,}", row=1, col=1)
        if use_idx_data and avg_buy_price > 0:
            fig.add_hline(y=avg_buy_price, line_dash="dot", line_color="blue", annotation_text=f"Modal Asing: Rp {int(avg_buy_price):,}", row=1, col=1)
        
        _, patterns = check_candlestick_patterns(df.iloc[-1], df.iloc[-2])
        if patterns: fig.add_annotation(x=df.index[-1], y=df['High'].iloc[-1], text=patterns[0], showarrow=True, arrowhead=1, row=1, col=1)
        
        colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol, name='Volume'), row=2, col=1)
        
        cmf_colors = ['green' if v >= 0 else 'red' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=cmf_colors, name='Money Flow'), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="black", row=3, col=1)
        
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- 12. PENGATURAN SIDEBAR & AKUN ---
st.sidebar.header("⚙️ Pengaturan Menu")
mode = st.sidebar.radio("Pilih Menu Utama:", ["🔍 Super Screener", "📊 Advanced Chart"])
st.sidebar.divider()

st.sidebar.markdown("**⚙️ Sumber Data Bandar**")
data_source = st.sidebar.radio("Pilih Sumber Data:", ["🌐 Yahoo Finance (Gratis/Estimasi)", "🏦 Data IDX (Akurat/Premium)"])
use_idx_data = "Data IDX" in data_source

st.sidebar.divider()

if mode == "🔍 Super Screener":
    st.sidebar.markdown("**📂 Pilih Kolam Saham**")
    kategori_saham = st.sidebar.radio("Kategori Saham:", ["👑 Lapis 1 (JII30)", "🚀 Lapis 2 (Mid-Small Caps)"])
    
    if kategori_saham == "🚀 Lapis 2 (Mid-Small Caps)":
        st.sidebar.info("⚡ Mode Lapis 2 mematikan koneksi API secara otomatis untuk menghemat limit. 100% menggunakan Yahoo Finance.")
        use_idx_data = False
        active_stock_list = SHARIA_MIDCAP_STOCKS
        active_category_name = "Lapis 2 (Mid-Small Caps)"
    else:
        active_stock_list = SHARIA_STOCKS
        active_category_name = "Lapis 1 (JII30)"
else:
    active_stock_list = SHARIA_STOCKS
    active_category_name = "Advanced Chart"

st.sidebar.divider()

# --- MENU KHUSUS ADMIN PANEL ---
if is_admin:
    st.sidebar.markdown("👑 **Admin Panel**")
    if st.sidebar.button("🧹 Bersihkan Memori (Refresh Data)"):
        st.cache_data.clear()
        api_registry.clear()
        st.sidebar.success("✅ Memori berhasil dihapus!")
    st.sidebar.divider()

st.sidebar.markdown(f"👤 Login sebagai: **{current_user}**")
if st.sidebar.button("Keluar (Logout)"):
    st.session_state["password_correct"] = False
    st.rerun()

# --- MENJALANKAN APLIKASI ---
if mode == "🔍 Super Screener": 
    run_screener(use_idx_data, active_stock_list, active_category_name)
else: 
    show_chart(use_idx_data)