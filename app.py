import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import requests
import numpy as np
import time
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Ultimate Smart Money Analyst", layout="wide", page_icon="🏦")

# --- 2. INISIALISASI SUPABASE ---
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

# --- 3. BUKU TAMU GLOBAL (SHARED CACHE REGISTRY) ---
@st.cache_resource
def get_api_registry():
    return set()

api_registry = get_api_registry()

# --- 4. SISTEM LOGIN SAAS (SUPABASE AUTH) ---
def login_ui():
    st.markdown("<h1 style='text-align: center;'>🔒 Portal Login Member</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            try:
                # Coba login via Supabase
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                
                # Ambil data profil (Role & Kuota)
                profile = supabase.table('profiles').select('*').eq('id', res.user.id).execute()
                
                if profile.data:
                    st.session_state['user'] = profile.data[0]
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Profil tidak ditemukan di database!")
            except Exception as e:
                st.error("🚫 Email tidak terdaftar atau Password salah!")

if 'logged_in' not in st.session_state or not st.session_state['logged_in']:
    login_ui()
    st.stop()

# --- AMBIL DATA USER SAAT INI ---
user_data = st.session_state['user']
user_id = user_data['id']
user_role = user_data['role'] # 'admin', 'vip', 'trial', 'free'
user_email = user_data['email']
is_admin = (user_role == 'admin')

# --- 5. LOGIKA PEMOTONGAN KUOTA API (BILLING SYSTEM) ---
def check_and_deduct_quota(cache_key):
    # 1. Jika data sudah ada di Cache Global, GRATIS! (Tidak potong kuota)
    if cache_key in api_registry:
        return True
        
    # 2. Jika Admin, bebas tanpa batas
    if is_admin:
        return True
        
    # 3. Ambil data terbaru dari database
    res = supabase.table('profiles').select('daily_quota, used_quota, last_reset_date').eq('id', user_id).execute()
    db_user = res.data[0]
    
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    used_quota = db_user['used_quota']
    
    # 4. Reset harian jika berganti hari
    if db_user['last_reset_date'] != today_str:
        used_quota = 0
        supabase.table('profiles').update({'used_quota': 0, 'last_reset_date': today_str}).eq('id', user_id).execute()
        
    # 5. Cek apakah kuota masih cukup
    if used_quota < db_user['daily_quota']:
        # Potong kuota!
        supabase.table('profiles').update({'used_quota': used_quota + 1}).eq('id', user_id).execute()
        return True
    else:
        return False

# --- 6. CSS FIX & JUBAH GAIB ---
st.markdown("""
<style>
    .stAppDeployButton {display:none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    [data-testid="stMetric"] { background-color: #f0f2f6 !important; border: 1px solid #d6d6d6 !important; padding: 15px !important; border-radius: 10px !important; height: 100% !important; }
    
    /* --- CSS KHUSUS TABEL ANTI-GESER --- */
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        font-family: sans-serif;
        font-size: 0.9em;
        margin-top: 15px;
    }
    .custom-table thead tr {
        background-color: #f0f2f6;
        color: #31333F;
        text-align: left;
    }
    .custom-table th, .custom-table td {
        padding: 12px 15px;
        border-bottom: 1px solid #ddd;
        vertical-align: top;
    }
    .custom-table tbody tr:hover {
        background-color: #f9f9f9;
    }
</style>
""", unsafe_allow_html=True)

# --- 7. DAFTAR SAHAM ---
SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]
SHARIA_MIDCAP_STOCKS = ["BRMS", "ELSA", "ENRG", "PTRO", "SIDO", "MYOR", "ESSA", "CTRA", "BSDE", "SMRA", "PWON", "ARTO", "BTPS", "MIKA", "HEAL", "SILO", "MAPA", "AUTO", "SMSM", "TAPG", "DSNG", "LSIP", "AALI", "WIKA", "PTPP", "TOTL", "NRCA", "SCMA", "MNCN", "ERAA"]

IDX_API_KEY = st.secrets.get("IDX_API_KEY", "")

# --- 8. HELPER & FETCH FUNCTIONS ---
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
    headers = {'accept': 'application/json', 'X-API-KEY': IDX_API_KEY, 'User-Agent': 'Mozilla/5.0'}
    net_foreign, avg_buy_price = 0, 0
    wib_time = datetime.utcnow() + timedelta(hours=7)
    fetch_time = wib_time.strftime("%d %b %Y, %H:%M WIB")
    
    try:
        url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
        res_broker = requests.get(url_broker, headers=headers, timeout=10)
        if res_broker.status_code != 200: return None, 0, None
        
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
    except Exception as e: return None, 0, None
        
    return net_foreign, avg_buy_price, fetch_time

@st.cache_data(ttl=3600) 
def get_fundamental_info(symbol):
    try:
        info = yf.Ticker(symbol).info
        return {"PBV": info.get('priceToBook', None), "EPS_Growth": info.get('earningsQuarterlyGrowth', None)}
    except: return None

# --- 9. FUNGSI TEKNIKAL ---
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
    if close > ma20 and ma20 > ma50: phase = "🔵 Markup"
    elif close < ma20 and ma20 < ma50: phase = "🟠 Markdown"
    elif close > ma50 and cmf < 0: phase = "🔴 Distribution"
    elif close < ma50 and cmf > 0: phase = "🟢 Accumulation"

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
        if not pd.isna(curr['Stock_Ret_20']) and not pd.isna(curr['IHSG_Ret_20']):
            if curr['Stock_Ret_20'] > curr['IHSG_Ret_20']:
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
        if fund_data.get('PBV') and fund_data.get('PBV') < 1.5: score_fund += 2
        if fund_data.get('EPS_Growth') and fund_data.get('EPS_Growth') > 0.10: 
            score_fund += 2
            reasons.append(f"🚀 Laba Tumbuh")
        
    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns: reasons.append(f"🕯️ {patterns[0]}")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr

# --- 10. FITUR SCREENER ---
def run_screener(use_idx_data, stock_list, category_name):
    st.header(f"🔍 Smart Money Screener ({category_name})")
    
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
                if df['Volume'].iloc[-1] < (5000000 if category_name == "Lapis 1 (JII30)" else 2000000): continue
                
                df = calculate_metrics(df, ihsg_df)
                fund = get_fundamental_info(t)
                s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                wyckoff_phase, divergence = advanced_analysis(df)
                total_score = s_tech + s_fund + s_bandar + s_candle
                
                atr = last.get('ATR', 0)
                close, volume = last['Close'], last['Volume']
                daily_turnover = close * volume 
                
                stop_loss = close - (1.5 * atr) if atr > 0 else close * 0.9
                target_profit = close + (3.0 * atr) if atr > 0 else close * 1.1
                
                rec = "WAIT"
                if total_score >= 6 or "BULLISH DIV" in divergence or "ALL ABOVE MA" in " ".join(reasons): rec = "💎 STRONG BUY"
                elif total_score >= 4 or "Accumulation" in wyckoff_phase: rec = "✅ BUY"
                
                if total_score < 3 and "BULLISH DIV" not in divergence and "Accumulation" not in wyckoff_phase and "ALL ABOVE MA" not in " ".join(reasons):
                    continue
                
                symbol_only = t.replace(".JK", "")
                net_foreign, avg_buy_price, power_pct = None, 0, 0
                idx_date = get_idx_target_date(df)
                idx_date_used = idx_date
                last_bursa_date = df.index[-1].strftime('%d %b %Y') 
                
                cache_key = f"{symbol_only}_{idx_date}"
                
                if use_idx_data:
                    if check_and_deduct_quota(cache_key):
                        status.text(f"Menarik Data IDX: {t} ...")
                        time.sleep(1) 
                        net_foreign, avg_buy_price, fetch_time = fetch_idx_foreign_flow(symbol_only, idx_date)
                        if fetch_time: 
                            last_sync_time = fetch_time 
                            api_registry.add(cache_key) 
                    else:
                        st.sidebar.error("❌ Limit Kuota Harian Habis!")
                        use_idx_data = False 
                
                if net_foreign is not None and net_foreign <= 0: continue
                
                if net_foreign is not None:
                    if daily_turnover > 0: power_pct = (abs(net_foreign) / daily_turnover) * 100
                    power_str = f" 🔥 (Power: {power_pct:.1f}%)" if power_pct >= 10 else f" (Power: {power_pct:.1f}%)"
                    modal_str = f" Modal: Rp {int(avg_buy_price):,}" if avg_buy_price > 0 else ""
                    reasons.append(f"🌐 ASING: {format_rupiah(net_foreign)}{power_str} |{modal_str}")

                # Menggunakan tag HTML <br> untuk memaksa baris baru di tabel
                formatted_reasons = "<br>".join([f"• {r.strip()}" for r in reasons])
                formatted_target = f"TP: Rp {int(target_profit):,}<br>SL: Rp {int(stop_loss):,}"
                
                # Warna otomatis untuk Rekomendasi
                rek_color = "#009879" if "BUY" in rec else "#d9534f"

                results.append({
                    "Kode": f"<b>{symbol_only}</b>",
                    "Harga": f"Rp {int(close):,}",
                    "Target & SL": formatted_target,
                    "Fase Wyckoff": wyckoff_phase.split(" ")[1] if len(wyckoff_phase.split(" ")) > 1 else wyckoff_phase,
                    "Vs IHSG": "✅ Outperform" if "🌟 Outperform IHSG" in reasons else "❌ Underperform",
                    "Asing": f"{power_pct:.1f}%" if net_foreign is not None else "-",
                    "Status": f"<strong style='color:{rek_color};'>{rec}</strong>",
                    "Poin Analisa (Alasan)": formatted_reasons
                })
            except Exception as loop_e: continue
            
        progress.empty()
        status.empty()
        
        if results:
            df_res = pd.DataFrame(results)
            st.success(f"Selesai! {len(results)} Saham Ditemukan.")
            
            # Perbaikan Info Waktu agar selalu muncul
            waktu_info = f"📅 **Data Harga Per:** {last_bursa_date}"
            if use_idx_data:
                # Jika last_sync_time gagal ditangkap, ambil waktu sekarang
                sync_time_disp = last_sync_time if last_sync_time else (datetime.utcnow() + timedelta(hours=7)).strftime("%d %b %Y, %H:%M WIB")
                waktu_info += f" | 🔄 **Data Asing Diambil Tgl:** {idx_date_used} (Sync: {sync_time_disp})"
            else:
                waktu_info += " | 🌐 **Sumber Bandar:** Yahoo Finance"
            
            st.caption(waktu_info)
            
            # Render Tabel Pandas ke HTML murni (Anti-geser)
            html_table = df_res.to_html(escape=False, index=False, classes="custom-table")
            st.markdown(html_table, unsafe_allow_html=True)
            
        else:
            st.warning("Data kosong / Tidak ada saham yang lolos kriteria.")

# --- 11. FITUR CHART DETAIL ---
def show_chart(use_idx_data):
    st.header("📊 Deep Analysis & Target Tracker")
    with st.form(key='chart_search_form'):
        c_input, c_btn = st.columns([4, 1])
        with c_input: ticker = st.text_input("Masukkan Kode Saham", "").upper()
        with c_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_search = st.form_submit_button("Cari Saham 🔍")
            
    if submit_search and ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        ticker_only = ticker.replace(".JK", "")
        
        ihsg_df = get_ihsg_data()
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        if df.empty:
            st.error("Saham tidak ditemukan!")
            return

        df = calculate_metrics(df, ihsg_df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
        wyckoff_phase, divergence = advanced_analysis(df)
        
        idx_date = get_idx_target_date(df)
        cache_key = f"{ticker_only}_{idx_date}"
        net_foreign, avg_buy_price, fetch_time = None, 0, None
        
        if use_idx_data:
            if check_and_deduct_quota(cache_key):
                net_foreign, avg_buy_price, fetch_time = fetch_idx_foreign_flow(ticker_only, idx_date)
                if fetch_time: api_registry.add(cache_key)
            else:
                st.warning("⚠️ Kuota Harian API Anda Habis! Menggunakan data Yahoo Finance.")
            
        st.divider()
        close, volume, atr = last['Close'], last['Volume'], last.get('ATR', 0)
        daily_turnover = close * volume
        stop_loss = close - (1.5 * atr) if atr > 0 else close
        target_profit = close + (3.0 * atr) if atr > 0 else close
        tp_pct = ((target_profit - close) / close) * 100 if atr > 0 else 0
            
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga Terakhir & Fase", f"Rp {int(close):,}", wyckoff_phase)
        c2.metric("Target & Stop Loss", f"Rp {int(target_profit):,}", f"Cut Loss: Rp {int(stop_loss):,} (+{tp_pct:.1f}%)", delta_color="normal")
        
        if net_foreign is not None:
            power_pct = (abs(net_foreign) / daily_turnover) * 100 if daily_turnover > 0 else 0
            c3.metric(f"Asing ({'🟢 AKUMULASI' if net_foreign > 0 else '🔴 DISTRIBUSI'})", format_rupiah(net_foreign), f"Dominasi: {power_pct:.1f}% | Modal: Rp {int(avg_buy_price):,}", delta_color="normal" if net_foreign > 0 else "inverse")
        else:
            c3.metric("Data Bandar (Asing)", "Tidak Tersedia", "Yahoo Finance Mode / Kuota Habis", delta_color="off")
        
        is_outperform = "🌟 Outperform IHSG" in " ".join(reasons)
        eps_g = fund.get('EPS_Growth') if fund else None
        c4.metric("Status vs Pasar (RRG)", "🌟 MENGALAHKAN IHSG" if is_outperform else "📉 UNDERPERFORM", f"Laba: +{eps_g*100:.1f}%" if eps_g and eps_g > 0 else "Laba: N/A", delta_color="normal" if is_outperform else "off")
        
        st.subheader(f"Visualisasi Grafik {ticker_only}")
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.05)
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA20'], line=dict(color='orange')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], line=dict(color='blue')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA100'], line=dict(color='green')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], line=dict(color='purple')), row=1, col=1)
        
        if atr > 0:
            fig.add_hline(y=target_profit, line_dash="dash", line_color="green", row=1, col=1)
            fig.add_hline(y=stop_loss, line_dash="dash", line_color="red", row=1, col=1)
        if net_foreign is not None and avg_buy_price > 0:
            fig.add_hline(y=avg_buy_price, line_dash="dot", line_color="blue", row=1, col=1)
            
        colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol), row=2, col=1)
        
        cmf_colors = ['green' if v >= 0 else 'red' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=cmf_colors), row=3, col=1)
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- 12. PENGATURAN SIDEBAR ---
st.sidebar.markdown(f"👤 **Halo, {user_email.split('@')[0]}**")
st.sidebar.caption(f"Status Akun: **{user_role.upper()}**")

# Cek Sisa Kuota Realtime dari DB
try:
    current_db = supabase.table('profiles').select('daily_quota, used_quota').eq('id', user_id).execute().data[0]
    st.sidebar.caption(f"Sisa Kuota API: **{current_db['daily_quota'] - current_db['used_quota']} / {current_db['daily_quota']}**")
except: pass

st.sidebar.divider()
mode = st.sidebar.radio("Pilih Menu:", ["🔍 Super Screener", "📊 Advanced Chart"])
st.sidebar.divider()

if user_role == 'free':
    st.sidebar.info("🌐 Status Anda adalah FREE (Hanya akses Yahoo Finance). Upgrade ke VIP/Pro untuk membuka Data Asing (IDX).")
    use_idx_data = False
else:
    data_source = st.sidebar.radio("Sumber Data:", ["🌐 Yahoo Finance (Gratis)", "🏦 Data IDX (Potong Kuota)"])
    use_idx_data = "Data IDX" in data_source

st.sidebar.divider()

if mode == "🔍 Super Screener":
    kategori_saham = st.sidebar.radio("Kategori Saham:", ["👑 Lapis 1 (JII30)", "🚀 Lapis 2 (Mid-Small Caps)"])
    if kategori_saham == "🚀 Lapis 2 (Mid-Small Caps)":
        use_idx_data = False
        active_stock_list, active_category_name = SHARIA_MIDCAP_STOCKS, "Lapis 2"
    else:
        active_stock_list, active_category_name = SHARIA_STOCKS, "Lapis 1 (JII30)"
else:
    active_stock_list, active_category_name = SHARIA_STOCKS, "Advanced Chart"

st.sidebar.divider()

if is_admin:
    st.sidebar.markdown("👑 **Admin Panel**")
    if st.sidebar.button("🧹 Bersihkan Memori"):
        st.cache_data.clear()
        api_registry.clear()
        st.sidebar.success("✅ Memori dihapus!")
    st.sidebar.divider()

if st.sidebar.button("Keluar (Logout)"):
    st.session_state['logged_in'] = False
    st.session_state['user'] = None
    supabase.auth.sign_out()
    st.rerun()

# --- MENJALANKAN APLIKASI ---
if mode == "🔍 Super Screener": run_screener(use_idx_data, active_stock_list, active_category_name)
else: show_chart(use_idx_data)