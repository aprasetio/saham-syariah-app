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

# --- 3. BUKU TAMU GLOBAL ---
@st.cache_resource
def get_api_registry():
    return set()

api_registry = get_api_registry()

# --- 4. SISTEM LOGIN SAAS ---
def login_ui():
    st.markdown("<h1 style='text-align: center;'>🔒 Portal Login Member</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                profile = supabase.table('profiles').select('*').eq('id', res.user.id).execute()
                if profile.data:
                    st.session_state['user'] = profile.data[0]
                    st.session_state['logged_in'] = True
                    st.rerun()
                else: st.error("Profil tidak ditemukan di database!")
            except Exception as e:
                st.error("🚫 Email tidak terdaftar atau Password salah!")

if 'logged_in' not in st.session_state or not st.session_state['logged_in']:
    login_ui()
    st.stop()

user_data = st.session_state['user']
user_id = user_data['id']
user_role = user_data['role'] 
user_email = user_data['email']
is_admin = (user_role == 'admin')

# --- 5. LOGIKA KUOTA API ---
def check_and_deduct_quota(cache_key):
    if cache_key in api_registry or is_admin: return True
    try:
        res = supabase.table('profiles').select('daily_quota, used_quota, last_reset_date').eq('id', user_id).execute()
        db_user = res.data[0]
        today_str = datetime.utcnow().strftime('%Y-%m-%d')
        used_quota = db_user['used_quota']
        
        if db_user['last_reset_date'] != today_str:
            used_quota = 0
            supabase.table('profiles').update({'used_quota': 0, 'last_reset_date': today_str}).eq('id', user_id).execute()
            
        if used_quota < db_user['daily_quota']:
            supabase.table('profiles').update({'used_quota': used_quota + 1}).eq('id', user_id).execute()
            return True
        else: return False
    except Exception as e: return False

# --- 6. CSS FIX ---
st.markdown("""
<style>
    .stAppDeployButton {display:none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stMetric"] { background-color: #f0f2f6 !important; border: 1px solid #d6d6d6 !important; padding: 15px !important; border-radius: 10px !important; height: 100% !important; }
    [data-testid="stMetricLabel"] p { color: #31333F !important; font-weight: bold !important; font-size: 1rem !important; }
    [data-testid="stMetricValue"] div { color: #000000 !important; font-size: 1.25rem !important; }
</style>
""", unsafe_allow_html=True)

# --- 7. DAFTAR SAHAM ---
SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]
SHARIA_MIDCAP_STOCKS = ["BRMS", "ELSA", "ENRG", "PTRO", "SIDO", "MYOR", "ESSA", "CTRA", "BSDE", "SMRA", "PWON", "ARTO", "BTPS", "MIKA", "HEAL", "SILO", "MAPA", "AUTO", "SMSM", "TAPG", "DSNG", "LSIP", "AALI", "WIKA", "PTPP", "TOTL", "NRCA", "SCMA", "MNCN", "ERAA"]
IDX_API_KEY = st.secrets.get("IDX_API_KEY", "")

# --- 8. HELPER FUNCTIONS ---
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
    return df.index[-1].strftime('%Y-%m-%d')

@st.cache_data(ttl=3600)
def get_ihsg_data():
    try:
        ihsg = yf.download("^JKSE", period="1y", auto_adjust=True, progress=False)
        ihsg = fix_dataframe(ihsg)
        return ihsg[['Close']].rename(columns={'Close': 'IHSG_Close'})
    except: return pd.DataFrame()

@st.cache_data(ttl=43200)
def fetch_idx_foreign_flow(symbol, target_date):
    headers = {'accept': 'application/json', 'X-API-KEY': IDX_API_KEY, 'User-Agent': 'Mozilla/5.0'}
    net_foreign, avg_buy_price = 0, 0
    fetch_time = (datetime.utcnow() + timedelta(hours=7)).strftime("%d %b %Y, %H:%M WIB")
    try:
        url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
        res_broker = requests.get(url_broker, headers=headers, timeout=10)
        if res_broker.status_code == 200:
            res_broker_json = res_broker.json()
            if res_broker_json.get('status') == 'success':
                buy_val = sum(b['value'] for b in res_broker_json['data']['results'] if b['side'] == 'BUY')
                buy_lot = sum(b['lot'] for b in res_broker_json['data']['results'] if b['side'] == 'BUY')
                sell_val = sum(b['value'] for b in res_broker_json['data']['results'] if b['side'] == 'SELL')
                net_foreign = buy_val - sell_val
                if buy_lot > 0: avg_buy_price = buy_val / (buy_lot * 100)
    except: pass
    return net_foreign, avg_buy_price, fetch_time

@st.cache_data(ttl=3600) 
def get_fundamental_info(symbol):
    try:
        info = yf.Ticker(symbol).info
        return {"PBV": info.get('priceToBook', None), "EPS_Growth": info.get('earningsQuarterlyGrowth', None)}
    except: return None

# --- 9. FUNGSI TEKNIKAL ---
def check_candlestick_patterns(curr, prev):
    score = 0; patterns = []
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
        df = pd.concat([df, df.ta.macd(fast=12, slow=26, signal=9), df.ta.bbands(length=20, std=2)], axis=1)
        df['SMA20'] = df.ta.sma(length=20)
        df['SMA50'] = df.ta.sma(length=50)
        df['SMA100'] = df.ta.sma(length=100)
        df['EMA200'] = df.ta.ema(length=200)
        df['ATR'] = df.ta.atr(length=14)
        
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
    phase = "Sideways"
    if close > ma50: phase = "🔵 Markup" if close > ma20 else "🔴 Distribution"
    else: phase = "🟠 Markdown" if close < ma20 else "🟢 Accumulation"

    divergence = "-"
    if len(df) > 10:
        if curr['Close'] - df['Close'].iloc[-10] < 0 and curr['CMF'] - df['CMF'].iloc[-10] > 0.15: divergence = "🟢 BULLISH DIV"
    return phase, divergence

def score_analysis(df, fund_data):
    if df.empty or len(df)<2: return 0, 0, 0, 0, ["Data Kurang"], df.iloc[-1]
    curr, prev = df.iloc[-1], df.iloc[-2]
    score_tech, score_fund, score_bandar, score_candle = 0, 0, 0, 0; reasons = []
    
    if not pd.isna(curr.get('SMA100')) and not pd.isna(curr.get('EMA200')):
        if curr['Close'] > curr['SMA20'] and curr['Close'] > curr['SMA50'] and curr['Close'] > curr['SMA100'] and curr['Close'] > curr['EMA200']:
            score_tech += 2; reasons.append("🔥 MA")
    elif not pd.isna(curr.get('EMA200')) and curr['Close'] > curr['EMA200']:
        score_tech += 1; reasons.append("📈 Uptrend")

    if 'Stock_Ret_20' in df.columns and 'IHSG_Ret_20' in df.columns:
        if not pd.isna(curr['Stock_Ret_20']) and curr['Stock_Ret_20'] > curr['IHSG_Ret_20']:
            score_tech += 1.5; reasons.append("🌟 IHSG")
        
    cmf = curr.get('CMF', 0)
    if cmf > 0.1: score_bandar = 2; reasons.append("🐳 CMF")
    
    if curr.get('Rsi', 50) < 35: score_tech += 2; reasons.append("💎 RSI")
    
    if fund_data and fund_data.get('EPS_Growth') and fund_data.get('EPS_Growth') > 0.10: 
        score_fund += 2; reasons.append("🚀 EPS")
        
    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns: reasons.append("🕯️ Pola")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr

# --- 10. FITUR SCREENER ---
def run_screener(use_idx_data, stock_list, category_name):
    st.header(f"🔍 Smart Money Screener ({category_name})")
    
    with st.expander("📖 Kamus Indikator & Panduan Power Asing (Klik untuk membuka)"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **⚡ Panduan Power Asing:**
            * **< 5%** : Lemah (Asing kurang peduli)
            * **5% - 15%** : Sedang (Ada akumulasi wajar)
            * **15% - 30%** : Kuat (Asing menyetir harga)
            * **> 30%** : Sangat Kuat / Dominan
            """)
        with c2:
            st.markdown("""
            **🔖 Arti Simbol Katalis:**
            * 🔥 **MA** : Uptrend (Di atas semua MA)
            * 🌟 **IHSG** : Outperform IHSG
            * 🐳 **CMF** : Akumulasi Bandar Besar
            * 💎 **RSI** : Harga Oversold (Murah)
            * 🚀 **EPS** : Laba Perusahaan Tumbuh
            * 🕯️ **Pola** : Pola Reversal (Hammer, dll)
            """)

    if st.button("MULAI SCANNING"):
        
        # ==========================================================
        # JALUR 1: JII30 + DATA IDX (BACA INSTAN DARI SUPABASE SERVER)
        # ==========================================================
        if category_name == "Lapis 1 (JII30)" and use_idx_data:
            with st.spinner("⚡ Menyedot data matang dari Server..."):
                res = supabase.table('jii30_daily_data').select('*').execute()
                if res.data:
                    df_res = pd.DataFrame(res.data)
                    
                    # Sensor Data Asing Jika User Gratisan
                    if user_role == 'free':
                        df_res['power_asing'] = None
                        df_res['modal_asing'] = None
                        
                    # Merapikan Urutan Kolom
                    df_res = df_res[['kode', 'harga', 'tp', 'sl', 'fase', 'power_asing', 'modal_asing', 'status', 'katalis']]
                    df_res.columns = ['Kode', 'Harga', 'TP', 'SL', 'Fase', 'Power Asing', 'Modal Asing', 'Status', 'Katalis']
                    
                    st.success(f"✅ Selesai! (Loading Instan | 0 Kuota API) - Ditemukan {len(df_res)} Saham.")
                    st.caption(f"📅 **Terakhir Diupdate oleh Server Robot:** {res.data[0]['fetch_date'] if 'fetch_date' in res.data[0] else 'Hari Ini'}")
                    
                    # Konfigurasi Tampilan Kolom
                    col_config = {
                        "Kode": st.column_config.TextColumn(width="small"),
                        "Harga": st.column_config.NumberColumn(format="Rp %d"),
                        "TP": st.column_config.NumberColumn(format="Rp %d"),
                        "SL": st.column_config.NumberColumn(format="Rp %d"),
                        "Katalis": st.column_config.TextColumn(width="medium")
                    }
                    
                    # Efek Sensor di Tabel
                    if user_role == 'free':
                        col_config["Power Asing"] = st.column_config.TextColumn(default="🔒 VIP")
                        col_config["Modal Asing"] = st.column_config.TextColumn(default="🔒 VIP")
                    else:
                        col_config["Power Asing"] = st.column_config.NumberColumn(format="%.1f %%")
                        col_config["Modal Asing"] = st.column_config.NumberColumn(format="Rp %d")

                    st.dataframe(df_res.fillna("🔒 VIP"), use_container_width=True, hide_index=True, column_config=col_config)
                else:
                    st.warning("⚠️ Data server IDX masih kosong hari ini (Mungkin bursa libur atau tidak ada saham yang lolos filter bandar). Silakan gunakan mode Yahoo Finance.")

        # ==========================================================
        # JALUR 2: SCANNING LIVE YFINANCE (Untuk Lapis 2 ATAU Lapis 1 Mode Gratis)
        # ==========================================================
        else:
            progress = st.progress(0)
            status = st.empty()
            results = []
            tickers = [f"{s}.JK" for s in stock_list]
            
            status.text("Mengambil Data IHSG...")
            ihsg_df = get_ihsg_data()
            price_data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False, threads=True)
            
            for i, t in enumerate(tickers):
                status.text(f"Menganalisa: {t} ...")
                progress.progress((i+1)/len(tickers))
                try:
                    df = price_data[t].copy()
                    df = fix_dataframe(df)
                    df = df[df['Volume'] > 0] # Anti Ghost Row
                    if df.empty or len(df) < 50: continue
                    
                    # Batas volume: Lapis 1 = 5jt, Lapis 2 = 2jt
                    min_vol = 5000000 if category_name == "Lapis 1 (JII30)" else 2000000
                    if df['Volume'].iloc[-1] < min_vol: continue
                    
                    df = calculate_metrics(df, ihsg_df)
                    fund = get_fundamental_info(t)
                    s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                    wyckoff_phase, divergence = advanced_analysis(df)
                    total_score = s_tech + s_fund + s_bandar + s_candle
                    
                    atr, close = last.get('ATR', 0), last['Close']
                    stop_loss = close - (1.5 * atr) if atr > 0 else close * 0.9
                    target_profit = close + (3.0 * atr) if atr > 0 else close * 1.1
                    
                    rec = "WAIT"
                    if total_score >= 6 or "BULLISH DIV" in divergence or "🔥 MA" in reasons: rec = "💎 STRONG BUY"
                    elif total_score >= 4 or "Accumulation" in wyckoff_phase: rec = "✅ BUY"
                    
                    if total_score < 3 and "Accumulation" not in wyckoff_phase: continue
                    
                    results.append({
                        "Kode": t.replace(".JK", ""), "Harga": int(close), "TP": int(target_profit), "SL": int(stop_loss),
                        "Fase": wyckoff_phase.split(" ")[1] if len(wyckoff_phase.split(" ")) > 1 else wyckoff_phase,
                        "Power Asing": 0.0, "Modal Asing": 0, "Status": rec, "Katalis": ", ".join(reasons) if reasons else "-"
                    })
                except Exception as e: continue
                
            progress.empty(); status.empty()
            
            if results:
                df_res = pd.DataFrame(results)
                st.success(f"Selesai! {len(results)} Saham {category_name} Ditemukan.")
                st.caption("🌐 **Sumber:** Yahoo Finance (Data Asing Dinonaktifkan)")
                
                st.dataframe(df_res, use_container_width=True, hide_index=True,
                    column_config={
                        "Kode": st.column_config.TextColumn(width="small"),
                        "Harga": st.column_config.NumberColumn(format="Rp %d"),
                        "TP": st.column_config.NumberColumn(format="Rp %d"),
                        "SL": st.column_config.NumberColumn(format="Rp %d"),
                        "Power Asing": st.column_config.TextColumn(default="Tidak Tersedia"),
                        "Modal Asing": st.column_config.TextColumn(default="Tidak Tersedia"),
                        "Katalis": st.column_config.TextColumn(width="medium")
                    }
                )
            else: st.warning("Data kosong / Tidak ada saham yang lolos kriteria teknikal hari ini.")

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

        df = fix_dataframe(df)
        df = df[df['Volume'] > 0]
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
        
        is_outperform = "🌟 IHSG" in " ".join(reasons)
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
    st.sidebar.caption(f"Sisa Kuota API Personal: **{current_db['daily_quota'] - current_db['used_quota']} / {current_db['daily_quota']}**")
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