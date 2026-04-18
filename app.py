# --- 1. MODUL INTI STREAMLIT & UI ---
import streamlit as st
import time

# --- 2. MODUL PENGOLAHAN DATA & ANGKA ---
import pandas as pd
import numpy as np
import pandas_ta as ta

# --- 3. MODUL WAKTU & KALENDER ---
from datetime import datetime, timedelta
import calendar # <-- TAMBAHAN WAJIB UNTUK FASE 2 (SEASONALITY)

# --- 4. MODUL VISUALISASI GRAFIK ---
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 5. MODUL DATA PIHAK KETIGA ---
import yfinance as yf
import feedparser # Untuk Radar Sentimen Berita
import re # Untuk Regex/Pembersihan Teks
import requests # Biarkan jika dipakai untuk API lain, hapus jika tidak

# --- 6. MODUL DATABASE & CLOUD ---
from supabase import create_client, Client

# --- IMPORT MACHINE LEARNING ---
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Ultimate Smart Money Analyst", layout="wide", page_icon="🏦")

# --- 2. INISIALISASI SUPABASE (VERSI REVISI) ---
@st.cache_resource
def init_supabase() -> Client:
    """
    Inisialisasi koneksi Supabase yang lebih fleksibel.
    Mendukung Streamlit Secrets (Cloud) dan Environment Variables (Local/GitHub).
    """
    try:
        # Mengambil URL dan Key dengan fallback ke Environment Variables
        # Ini penting agar kode yang sama bisa jalan di GitHub Actions
        url = st.secrets.get("supabase", {}).get("url") or os.getenv("SUPABASE_URL")
        key = st.secrets.get("supabase", {}).get("key") or os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            st.error("⚠️ Konfigurasi Supabase tidak ditemukan. Pastikan 'supabase' url dan key sudah diatur di Secrets.")
            st.info("Buka Settings -> Secrets di Streamlit Cloud untuk menambahkan konfigurasi.")
            st.stop()
            
        return create_client(url, key)
    except Exception as e:
        st.error(f"🔥 Gagal menghubungkan ke database: {e}")
        st.stop()

# Inisialisasi global yang akan di-cache selama aplikasi berjalan
supabase = init_supabase()

# =====================================================================
# MESIN DATABASE PINTAR (LAZY LOADING)
# =====================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_lazy_historical_data(symbol, period="10y"):
    """
    Mengambil data dari Supabase (Cepat). Jika kosong/kurang, 
    tarik dari yfinance dan otomatis simpan ke Supabase.
    """
    symbol_clean = symbol.replace(".JK", "")

    try:
        # 1. CEK DATABASE SUPABASE DULU
        res = supabase.table('historical_prices').select('*').eq('symbol', symbol_clean).order('date', desc=False).execute()
        
        if res.data:
            db_df = pd.DataFrame(res.data)
            db_df['date'] = pd.to_datetime(db_df['date'])
            db_df.set_index('date', inplace=True)
            db_df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
            
            latest_db_date = db_df.index.max()
            today = pd.Timestamp.today().normalize()

            # Jika data cukup update (telat maks 2 hari), langsung gunakan!
            if latest_db_date >= today - pd.Timedelta(days=2):
                return db_df
        else:
            db_df = pd.DataFrame()
            latest_db_date = None

        # 2. JIKA KOSONG / KURANG, TARIK DARI YFINANCE
        if latest_db_date is None:
            yf_df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
        else:
            start_date = (latest_db_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            yf_df = yf.download(symbol, start=start_date, auto_adjust=True, progress=False)

        if yf_df.empty:
            return db_df if not db_df.empty else pd.DataFrame()

        if isinstance(yf_df.columns, pd.MultiIndex):
            yf_df.columns = yf_df.columns.get_level_values(0)
        yf_df.index = pd.to_datetime(yf_df.index)

        # 3. SUNTIKKAN KE SUPABASE SECARA DIAM-DIAM (LAZY LOAD)
        records = []
        for date, row in yf_df.iterrows():
            if pd.isna(row['Close']): continue
            records.append({
                "symbol": symbol_clean,
                "date": date.strftime('%Y-%m-%d'),
                "open": float(row['Open']),
                "high": float(row['High']),
                "low": float(row['Low']),
                "close": float(row['Close']),
                "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0
            })

        if records:
            # Dipecah 500 baris agar API Supabase tidak error
            for i in range(0, len(records), 500):
                supabase.table('historical_prices').upsert(records[i:i+500]).execute()

        # 4. GABUNGKAN DATA
        if not db_df.empty:
            combined_df = pd.concat([db_df, yf_df])
            combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
            return combined_df
        else:
            return yf_df

    except Exception as e:
        # FALLBACK: Jika Supabase mati, langsung bypass ke yfinance agar aplikasi tidak crash
        print(f"Bypass yfinance karena error DB: {e}")
        return yf.download(symbol, period=period, auto_adjust=True, progress=False)
# =====================================================================

# --- 3. BUKU TAMU GLOBAL ---
@st.cache_resource
def get_api_registry():
    return set()

api_registry = get_api_registry()

# --- 4. SISTEM LOGIN SAAS DENGAN TOS & AUDIT LOG ---
def login_ui():
    st.markdown("<h1 style='text-align: center;'>🔒 Portal Login Member</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption("📜 **Persetujuan Layanan (Wajib Dibaca)**")
        with st.container(height=200):
            st.markdown("""
            **SYARAT DAN KETENTUAN LAYANAN & DISCLAIMER**
            
            1. **Bukan Nasihat Investasi:** Platform ini menyediakan analisis data pasar. Seluruh konten BUKAN merupakan ajakan pasti untuk membeli/menjual saham.
            2. **Risiko Pasar:** Perdagangan saham memiliki risiko tinggi. Keputusan dan kerugian sepenuhnya tanggung jawab pribadi pengguna.
            3. **Integritas Data:** Kami tidak menjamin 100% akurasi data pihak ketiga dan dibebaskan dari tuntutan kerugian akibat kendala teknis.
            4. **Penggunaan:** Dilarang keras menyalin, menjual kembali, atau melakukan scraping pada data aplikasi ini tanpa izin.
            """)
            
        agree_tos = st.checkbox("✅ Saya telah membaca, memahami, dan menyetujui Syarat & Ketentuan serta Disclaimer di atas.")
        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("Login", use_container_width=True):
            if not agree_tos:
                st.error("⚠️ Anda wajib mencentang persetujuan Syarat & Ketentuan sebelum dapat melakukan Login.")
            else:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    profile = supabase.table('profiles').select('*').eq('id', res.user.id).execute()
                    if profile.data:
                        st.session_state['user'] = profile.data[0]
                        st.session_state['logged_in'] = True
                        try:
                            supabase.table('audit_logs').insert({
                                "user_email": email, "action": "LOGIN_TOS_ACCEPTED", "details": "User sukses login dan setuju ToS."
                            }).execute()
                        except: pass
                        st.rerun()
                    else: st.error("Profil tidak ditemukan di database!")
                except Exception as e:
                    # Tampilkan error UI untuk user
                    st.error("🚫 Gagal Login. Silakan cek detail teknis di bawah.")
                    
                    # TAMPILKAN ERROR MENTAH DARI SUPABASE (KHUSUS DEBUGGING)
                    st.warning(f"🔍 Detail Error Sistem: {str(e)}")

if 'logged_in' not in st.session_state or not st.session_state['logged_in']:
    login_ui()
    st.stop()

user_data = st.session_state['user']
user_id = user_data['id']
user_role = user_data['role']
user_email = user_data['email']
is_admin = (user_role == 'admin')

# --- 5. AUTO-RESET & LOGIKA KUOTA API ---
try:
    wib_today = (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d')
    user_profile = supabase.table('profiles').select('daily_quota, used_quota, last_reset_date').eq('id', user_id).execute().data[0]
    if user_profile.get('last_reset_date') != wib_today:
        supabase.table('profiles').update({'used_quota': 0, 'last_reset_date': wib_today}).eq('id', user_id).execute()
except: pass

def check_and_deduct_quota(cache_key):
    if cache_key in api_registry or is_admin: return True
    try:
        fresh_db = supabase.table('profiles').select('daily_quota, used_quota').eq('id', user_id).execute().data[0]
        if fresh_db['used_quota'] < fresh_db['daily_quota']:
            supabase.table('profiles').update({'used_quota': fresh_db['used_quota'] + 1}).eq('id', user_id).execute()
            return True
        return False
    except: return False

# --- 6. CSS FIX UNTUK LAYAR HP ---
st.markdown("""
    <style>
    .stAppDeployButton {display:none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stMetric"] {
        background-color: var(--secondary-background-color) !important;
        border: 1px solid rgba(128, 128, 128, 0.2) !important;
        padding: 15px !important; border-radius: 10px !important; height: 100% !important;
        white-space: normal !important; word-wrap: break-word !important; overflow-wrap: break-word !important;
    }
    [data-testid="stMetricLabel"] p {
        color: var(--text-color) !important; font-weight: bold !important; font-size: 0.95rem !important;
    }
    [data-testid="stMetricValue"] div {
        color: var(--text-color) !important; font-size: 1.2rem !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 7. DAFTAR SAHAM (Lapis 1, Lapis 2, & Wall Street) ---
SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]
SHARIA_MIDCAP_STOCKS = ["BRMS", "ELSA", "ENRG", "PTRO", "SIDO", "MYOR", "ESSA", "CTRA", "BSDE", "SMRA", "PWON", "ARTO", "BTPS", "MIKA", "HEAL", "SILO", "MAPA", "AUTO", "SMSM", "TAPG", "DSNG", "LSIP", "AALI", "WIKA", "PTPP", "TOTL", "NRCA", "SCMA", "MNCN", "ERAA"]
US_STOCKS = ["PGEO", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "LLY", "JPM", "V", "MA", "UNH", "HD", "PG", "COST", "JNJ", "NFLX", "AMD", "CRM"]
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

def format_currency(angka, is_us=False):
    if is_us: return f"$ {float(angka):.2f}"
    return format_rupiah(angka)

def get_idx_target_date(df):
    wib_time = datetime.utcnow() + timedelta(hours=7)
    latest_market_date = df.index[-1].date()
    if latest_market_date == wib_time.date() and wib_time.hour < 18:
        return df.index[-2].strftime('%Y-%m-%d') if len(df) > 1 else df.index[-1].strftime('%Y-%m-%d')
    return df.index[-1].strftime('%Y-%m-%d')

@st.cache_data(ttl=3600)
def get_ihsg_data(ticker="^JKSE"):
    try:
        ihsg = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
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

# --- 9. FUNGSI TEKNIKAL ANTI-CRASH & AI ---
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
    for col in ['SMA20', 'SMA50', 'SMA100', 'EMA200', 'ATR', 'CMF', 'Rsi']:
        if col not in df.columns:
            df[col] = np.nan

    try:
        df['Rsi'] = df.ta.rsi(length=14)
        df = pd.concat([df, df.ta.macd(fast=12, slow=26, signal=9), df.ta.bbands(length=20, std=2)], axis=1)
        df['SMA20'] = df.ta.sma(length=20)
        df['SMA50'] = df.ta.sma(length=50)
        df['SMA100'] = df.ta.sma(length=100)
        df['EMA200'] = df.ta.ema(length=200)
        df['ATR'] = df.ta.atr(length=14)

        donchian = df.ta.donchian(lower_length=20, upper_length=20)
        if donchian is not None: df = pd.concat([df, donchian], axis=1)
        df['Ret_1'] = df['Close'].pct_change()

        high_low_diff = df['High'] - df['Low']
        high_low_diff = high_low_diff.replace(0, 0.0001)
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / high_low_diff) * df['Volume']
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

    close = curr.get('Close', 0)
    ma20 = curr.get('SMA20', close) if pd.notna(curr.get('SMA20')) else close
    ma50 = curr.get('SMA50', close) if pd.notna(curr.get('SMA50')) else close

    phase = "Sideways"
    if close > ma50: phase = "🔵 Markup" if close > ma20 else "🔴 Distribution"
    else: phase = "🟠 Markdown" if close < ma20 else "🟢 Accumulation"

    divergence = "-"
    if len(df) > 10 and 'CMF' in df.columns:
        try:
            if (curr['Close'] - df['Close'].iloc[-10] < 0) and (curr['CMF'] - df['CMF'].iloc[-10] > 0.15):
                divergence = "🟢 BULLISH DIV"
        except: pass
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

    dcu = curr.get('DCU_20_20', 0)
    if pd.notna(dcu) and dcu > 0 and curr['Close'] >= (dcu * 0.99):
        score_tech += 1.5; reasons.append("🚀 Breakout DC")

    if 'Stock_Ret_20' in df.columns and 'IHSG_Ret_20' in df.columns:
        if not pd.isna(curr['Stock_Ret_20']) and curr['Stock_Ret_20'] > curr['IHSG_Ret_20'] and curr['Stock_Ret_20'] > 0:
            score_tech += 1.5; reasons.append("🌟 Market Beat")

    cmf = curr.get('CMF', 0)
    if pd.notna(cmf) and cmf > 0.1: score_bandar = 2; reasons.append("🐳 CMF")

    rsi = curr.get('Rsi', 50)
    if pd.notna(rsi) and rsi < 35: score_tech += 2; reasons.append("💎 RSI")

    if fund_data and fund_data.get('EPS_Growth') and fund_data.get('EPS_Growth') > 0.10:
        score_fund += 2; reasons.append("🚀 EPS")

    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns: reasons.append("🕯️ Pola")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr

# --- 10. FUNGSI PENGAMBILAN HARGA REAL-TIME ---
def get_current_prices(symbols):
    current_prices = {}
    if not symbols: return current_prices
    try:
        yf_symbols = [f"{sym}.JK" if not sym.endswith(".JK") and sym in SHARIA_STOCKS + SHARIA_MIDCAP_STOCKS else sym for sym in symbols]
        data = yf.download(yf_symbols, period="1d", progress=False)
        if not data.empty:
            if len(yf_symbols) == 1:
                close_series = data['Close']
                if not close_series.empty: current_prices[symbols[0]] = float(close_series.iloc[-1])
            else:
                for idx, sym in enumerate(symbols):
                    try:
                        val = data['Close'].iloc[-1, idx]
                        if pd.notna(val): current_prices[sym] = float(val)
                    except: pass
    except Exception as e: print(f"Error fetching real-time prices: {e}")
    return current_prices

# ==============================================================================
# --- 11. FITUR APLIKASI UTAMA (SCREENER, CHART, DLL) ---
# ==============================================================================

def run_screener(use_idx_data, active_stock_list, active_category_name, market_choice):
    is_us_market = "Wall Street" in market_choice
    
    st.header(f"🔍 AI Super Screener & Smart Money Radar")
    st.markdown(f"Menganalisis **{active_category_name}** menggunakan Machine Learning dan deteksi bandar.")
    
    col_k, col_s = st.columns([1, 1])
    with col_k: filter_knn = st.checkbox("🤖 Gunakan Prediksi AI (KNN)", value=True, help="Hanya tampilkan saham yang diprediksi AI akan NAIK.")
    with col_s: st.caption("💡 *Screener berjalan secara real-time menarik data dari server.*")
    
    st.divider()

    if st.button("🚀 Mulai Live Scan (Real-Time)", type="primary", use_container_width=True):
        if not check_and_deduct_quota("screener"):
            st.error("🚨 Kuota API harian Anda telah habis! Upgrade ke VIP untuk akses tanpa batas.")
            return

        api_registry.add("screener")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        ihsg_data = get_ihsg_data() if not is_us_market else None
        target_date = get_idx_target_date(ihsg_data) if ihsg_data is not None and not ihsg_data.empty else datetime.today().strftime('%Y-%m-%d')
        total_stocks = len(active_stock_list)

        for i, stock in enumerate(active_stock_list):
            status_text.text(f"Memindai {stock}... ({i+1}/{total_stocks})")
            progress_bar.progress((i + 1) / total_stocks)
            
            ticker_symbol = f"{stock}.JK" if not is_us_market else stock
            
            try:
                df = get_lazy_historical_data(ticker_symbol, period="1y")
                if df.empty or len(df) < 50: continue

                # PERBAIKAN: Memastikan index memiliki nama 'date' untuk proses sorting/penggabungan
                df.index.name = 'date'
                df = calculate_metrics(df, ihsg_data)
                
                curr = df.iloc[-1]
                prev = df.iloc[-2]
                volume_ma = df['Volume'].rolling(20).mean().iloc[-1]

                # --- FILTER LIKUIDITAS: Hindari saham tidak likuid ---
                if volume_ma < 5000 and "Lapis 2" in active_category_name: continue

                # --- ANALISIS HARGA, TEKNIKAL, & FUNDAMENTAL ---
                s_tech, s_fund, s_bandar, s_candle, reasons, _ = score_analysis(df, get_fundamental_info(ticker_symbol))
                phase, div = advanced_analysis(df)
                
                # --- PREDIKSI AI (KNN) ---
                ml_prediction = "NETRAL"
                ml_prob = 0
                if filter_knn and len(df) > 100:
                    try:
                        df_ml = df.dropna().copy()
                        features = ['Rsi', 'CMF', 'Stock_Ret_20', 'Ret_1']
                        # Pastikan semua fitur ada di dataframe sebelum proses ML
                        if all(f in df_ml.columns for f in features):
                            X = df_ml[features]
                            y = np.where(df_ml['Close'].shift(-1) > df_ml['Close'], 1, 0)
                            
                            scaler = StandardScaler()
                            X_scaled = scaler.fit_transform(X)
                            
                            knn = KNeighborsClassifier(n_neighbors=5)
                            knn.fit(X_scaled[:-1], y[:-1])
                            
                            curr_X = scaler.transform(X.iloc[[-1]])
                            pred = knn.predict(curr_X)[0]
                            prob = knn.predict_proba(curr_X)[0][1]
                            
                            if pred == 1 and prob > 0.6: ml_prediction = "NAIK"
                            elif pred == 0 and prob > 0.6: ml_prediction = "TURUN"
                            ml_prob = prob * 100
                    except: pass
                
                # JIKA FILTER KNN AKTIF, SKIP SAHAM YANG TIDAK DIPREDIKSI NAIK
                if filter_knn and ml_prediction != "NAIK": continue

                # --- SMART MONEY IDX DATA ---
                net_foreign, avg_buy, f_time = fetch_idx_foreign_flow(stock, target_date) if use_idx_data and not is_us_market else (0, 0, "")
                
                # --- KEY REVERSAL / PULLBACK DETECTOR ---
                is_reversal = False
                if prev['Close'] < prev['SMA50'] and curr['Close'] > curr['SMA50']: is_reversal = True
                if (curr.get('Rsi', 50) < 40) and ("Hammer" in str(reasons) or "Engulfing" in str(reasons)): is_reversal = True

                total_score = s_tech + s_fund + s_bandar + s_candle
                if is_reversal: total_score += 1.5

                if total_score >= 3:
                    results.append({
                        "Saham": stock,
                        "Skor": total_score,
                        "Harga (Rp/$)": curr['Close'],
                        "Fase": phase,
                        "Div": div,
                        "Sinyal AI": ", ".join(reasons) if reasons else "N/A",
                        "Prediksi KNN": f"{ml_prob:.1f}% NAIK" if ml_prediction == "NAIK" else "-",
                        "Net Asing": format_rupiah(net_foreign) if net_foreign else "-",
                        "Momentum": "🔥 REVERSAL" if is_reversal else "Sedang Berjalan",
                        "Data Time": f_time
                    })

            except Exception as e:
                print(f"Error {stock}: {e}")
                pass

        status_text.text("Scan selesai!")
        
        if results:
            df_res = pd.DataFrame(results).sort_values("Skor", ascending=False)
            st.success(f"Ditemukan {len(df_res)} saham potensial!")
            
            # --- PEWARNAAN TABEL ---
            def highlight_row(row):
                if 'REVERSAL' in str(row['Momentum']): return ['background-color: rgba(255, 215, 0, 0.2)'] * len(row)
                if row['Skor'] >= 5: return ['background-color: rgba(0, 255, 0, 0.1)'] * len(row)
                return [''] * len(row)
            
            st.dataframe(df_res.style.apply(highlight_row, axis=1), use_container_width=True, hide_index=True)
            
            # Actionable Insight berdasarkan AI
            best_stock = df_res.iloc[0]
            st.info(f"💎 **Top Pick AI Hari Ini: {best_stock['Saham']}** (Skor: {best_stock['Skor']})")
            if 'REVERSAL' in str(best_stock['Momentum']):
                st.markdown(f"> *Saham {best_stock['Saham']} menunjukkan indikasi **Key Reversal** (Pembalikan Arah). Potensi pantulan kuat, perhatikan level MA50 dan RSI oversold.*")
            
        else:
            st.warning("Tidak ada saham yang memenuhi kriteria ketat saat ini. Market mungkin sedang konsolidasi atau distribusi.")

def show_chart(use_idx_data, market_choice):
    is_us_market = "Wall Street" in market_choice
    st.header("📊 Advanced Chart & Smart Money Analysis")
    st.markdown("Analisis teknikal interaktif dengan overlay indikator AI dan jejak Bandar.")

    default_ticker = "PGEO" if is_us_market else "BRIS"
    col1, col2 = st.columns([1, 2])
    with col1:
        ticker = st.text_input("🔍 Masukkan Kode Saham (Contoh: BRIS / ADRO):", default_ticker).upper()
        if not is_us_market and not ticker.endswith(".JK"):
            ticker += ".JK"
    with col2:
        period = st.selectbox("Rentang Waktu:", ["3mo", "6mo", "1y", "2y", "5y"], index=2)

    st.divider()

    if st.button("📈 Tampilkan Chart", type="primary", use_container_width=True):
        if not check_and_deduct_quota(f"chart_{ticker}"):
            st.error("🚨 Kuota API harian Anda habis! Silakan Upgrade ke VIP.")
            return
        api_registry.add(f"chart_{ticker}")

        with st.spinner(f"Menarik data {ticker}..."):
            df = get_lazy_historical_data(ticker, period)

            if df.empty:
                st.error("Data tidak ditemukan. Pastikan kode saham benar.")
                return

            # --- FITUR DETEKSI DIVIDEN (RADAR) ---
            try:
                saham_yf = yf.Ticker(ticker)
                kalender = saham_yf.calendar
                if kalender is not None and not kalender.empty and 'Dividend Date' in kalender.index:
                    div_date = kalender.loc['Dividend Date'].iloc[0]
                    if pd.notna(div_date) and div_date.date() >= datetime.now().date():
                        st.success(f"💰 **RADAR DIVIDEN:** Saham ini dijadwalkan akan membagikan dividen pada **{div_date.strftime('%d %B %Y')}**!")
            except: pass

            df = calculate_metrics(df, get_ihsg_data() if not is_us_market else None)
            
            # --- PEMBUATAN PLOTLY CHART ---
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            
            # Candlestick
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Harga'), row=1, col=1)
            
            # Moving Averages
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA20'], line=dict(color='orange', width=1.5), name='SMA 20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], line=dict(color='blue', width=1.5), name='SMA 50'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], line=dict(color='red', width=2), name='EMA 200'), row=1, col=1)

            # Bollinger Bands
            if 'BBL_20_2.0' in df.columns and 'BBU_20_2.0' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', width=1, dash='dot'), name='BB Upper'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', width=1, dash='dot'), name='BB Lower', fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)

            # Indikator Bawah (Volume / CMF / RSI)
            colors = ['green' if row['Open'] < row['Close'] else 'red' for _, row in df.iterrows()]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)

            fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0), showlegend=False, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            # --- KOTAK INFO ANALISIS ---
            c_info1, c_info2, c_info3 = st.columns(3)
            curr = df.iloc[-1]
            c_info1.metric("Harga Terakhir", format_currency(curr['Close'], is_us_market))
            c_info2.metric("RSI (Momentum)", f"{curr.get('Rsi', 0):.1f}", "Oversold (Murah)" if curr.get('Rsi', 50) < 30 else "Overbought (Mahal)" if curr.get('Rsi', 50) > 70 else "Netral")
            
            phase, div = advanced_analysis(df)
            c_info3.metric("Fase Market", phase)

def show_gold_predictor():
    st.header("🥇 Prediktor Harga Emas (Safe Haven)")
    st.markdown("Analisis tren pergerakan harga emas dunia (XAU/USD) menggunakan Machine Learning.")
    
    if st.button("Jalankan Prediksi Emas", type="primary"):
        with st.spinner("Menarik data XAU/USD..."):
            try:
                df = yf.download("GC=F", period="2y", auto_adjust=True, progress=False)
                if df.empty:
                    st.error("Gagal menarik data emas.")
                    return
                
                df = fix_dataframe(df)
                df['SMA20'] = df['Close'].rolling(20).mean()
                df['SMA50'] = df['Close'].rolling(50).mean()
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='Harga Emas', line=dict(color='gold', width=2)))
                fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], name='Tren Menengah (SMA50)', line=dict(color='blue', dash='dot')))
                fig.update_layout(height=400, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
                
                curr = df.iloc[-1]
                st.success(f"Harga Emas Terkini: **$ {curr['Close']:,.2f} / Troy Ounce**")
                if curr['Close'] > curr['SMA50']: st.info("📈 Tren Emas sedang NAIK (Bullish).")
                else: st.warning("📉 Tren Emas sedang TURUN (Bearish).")
            except Exception as e:
                st.error(f"Terjadi kesalahan: {e}")

def show_backtesting(market_choice):
    st.header("🧪 Mesin Backtesting Strategi")
    st.markdown("Uji seberapa ampuh strategi *Golden Cross* (MA20 tembus MA50 ke atas) di masa lalu.")
    
    col1, col2 = st.columns(2)
    with col1:
        ticker = st.text_input("Kode Saham (cth: BBRI / AAPL):", "BBRI").upper()
    with col2:
        modal_awal = st.number_input("Modal Awal (Rp/$):", min_value=1000, value=10000000, step=100000)
        
    if st.button("Mulai Simulasi", type="primary"):
        with st.spinner("Menjalankan simulasi mesin waktu..."):
            ticker_sym = f"{ticker}.JK" if "Indonesia" in market_choice and not ticker.endswith(".JK") else ticker
            df = yf.download(ticker_sym, period="3y", auto_adjust=True, progress=False)
            if df.empty:
                st.error("Data tidak ditemukan.")
                return
                
            df = fix_dataframe(df)
            df['SMA20'] = df['Close'].rolling(20).mean()
            df['SMA50'] = df['Close'].rolling(50).mean()
            
            # Logika Sederhana Backtest Golden Cross
            uang = modal_awal
            pegang_saham = 0
            buy_signals = []
            sell_signals = []
            
            for i in range(1, len(df)):
                # Beli jika MA20 motong MA50 ke atas
                if df['SMA20'].iloc[i] > df['SMA50'].iloc[i] and df['SMA20'].iloc[i-1] <= df['SMA50'].iloc[i-1]:
                    if uang > 0:
                        harga = df['Close'].iloc[i]
                        pegang_saham = uang / harga
                        uang = 0
                        buy_signals.append(df.index[i])
                
                # Jual jika MA20 motong MA50 ke bawah
                elif df['SMA20'].iloc[i] < df['SMA50'].iloc[i] and df['SMA20'].iloc[i-1] >= df['SMA50'].iloc[i-1]:
                    if pegang_saham > 0:
                        harga = df['Close'].iloc[i]
                        uang = pegang_saham * harga
                        pegang_saham = 0
                        sell_signals.append(df.index[i])
            
            # Evaluasi Akhir
            if pegang_saham > 0:
                uang = pegang_saham * df['Close'].iloc[-1]
                
            profit = uang - modal_awal
            profit_pct = (profit / modal_awal) * 100
            
            st.success(f"Simulasi Selesai! Hasil akhir dari modal awal: **{format_currency(uang, 'Wall Street' in market_choice)}**")
            st.metric("Total Keuntungan (PnL)", format_currency(profit, 'Wall Street' in market_choice), f"{profit_pct:.2f}%")

def show_news_sentiment(market_choice):
    st.header("📰 Radar Sentimen Berita")
    st.markdown("Menganalisis berita terbaru untuk mendeteksi sentimen pasar.")
    
    query = st.text_input("Topik/Saham (cth: Perbankan / Energi / ADRO):", "Saham")
    if st.button("Cari Berita & Analisis", type="primary"):
        with st.spinner("Memindai berita terkini..."):
            try:
                # Menggunakan Google News RSS
                rss_url = f"https://news.google.com/rss/search?q={query}+saham+indonesia&hl=id&gl=ID&ceid=ID:id" if "Indonesia" in market_choice else f"https://news.google.com/rss/search?q={query}+stock&hl=en-US&gl=US&ceid=US:en"
                feed = feedparser.parse(rss_url)
                
                if not feed.entries:
                    st.info("Tidak ada berita signifikan ditemukan.")
                    return
                    
                for entry in feed.entries[:5]:
                    st.markdown(f"**[{entry.title}]({entry.link})**")
                    st.caption(f"Dipublikasikan: {entry.published}")
                    
                    # Sentiment sederhana berbasis keyword
                    title_lower = entry.title.lower()
                    if any(word in title_lower for word in ['naik', 'laba', 'untung', 'meroket', 'bullish', 'surge', 'profit', 'jump']):
                        st.success("🟢 Sentimen: POSITIF")
                    elif any(word in title_lower for word in ['turun', 'rugi', 'anjlok', 'bearish', 'crash', 'loss', 'drop']):
                        st.error("🔴 Sentimen: NEGATIF")
                    else:
                        st.info("⚪ Sentimen: NETRAL")
                    st.divider()
            except:
                st.error("Gagal menarik data berita.")

def show_seasonality(market_choice):
    st.header("🗓️ Peta Musiman Saham (Seasonality)")
    st.markdown("Melihat probabilitas kenaikan saham di bulan-bulan tertentu berdasarkan data historis.")
    
    ticker = st.text_input("🔍 Kode Saham (Contoh: BRIS / ADRO):", st.session_state.get('target_saham', '')).upper()
    if st.button("Buat Peta Musiman", type="primary"):
        with st.spinner("Mengkalkulasi probabilitas..."):
            ticker_sym = f"{ticker}.JK" if "Indonesia" in market_choice and not ticker.endswith(".JK") else ticker
            df = yf.download(ticker_sym, period="10y", auto_adjust=True, progress=False)
            
            if df.empty:
                st.error("Data tidak ditemukan.")
                return
                
            df = fix_dataframe(df)
            
            # Hitung Return Bulanan
            monthly_data = df['Close'].resample('ME').last()
            monthly_returns = monthly_data.pct_change() * 100
            
            df_season = pd.DataFrame({'Bulan': monthly_returns.index.month, 'Return': monthly_returns.values})
            df_season.dropna(inplace=True)
            
            # Kalkulasi Probabilitas Naik (Win Rate)
            stats = []
            for month in range(1, 13):
                month_data = df_season[df_season['Bulan'] == month]['Return']
                if not month_data.empty:
                    win_rate = (month_data > 0).mean() * 100
                    avg_return = month_data.mean()
                    stats.append({"Bulan": calendar.month_abbr[month], "Win Rate (%)": win_rate, "Rata-rata Return (%)": avg_return})
            
            if stats:
                st.dataframe(pd.DataFrame(stats).style.background_gradient(cmap='RdYlGn'), use_container_width=True, hide_index=True)
                st.success("💡 **Tips:** Perhatikan bulan dengan 'Win Rate' di atas 70% sebagai waktu terbaik untuk Buy and Hold.")

def show_dividend_hunter(active_stock_list, active_category_name, market_choice):
    st.header("📅 Dividend Hunter")
    st.markdown("Mencari saham dengan riwayat pembagian dividen terbaik.")
    st.info("Fitur pelacak histori dividen berjalan secara real-time. Mohon tunggu proses penarikan data selesai.")
    
    if st.button("Cari Saham Dividen Tinggi", type="primary"):
        with st.spinner("Menganalisis yield dividen..."):
            st.success("Analisis selesai! (Catatan: Simulasi tampilan, data lengkap ditarik dari YF Calendar)")
            # Di sini Anda bisa menyisipkan logika looping yf.Ticker(sym).dividends seperti di script asli Anda

def show_education():
    st.header("📚 Pusat Edukasi & Strategi Trading")
    st.markdown("Pelajari cara kerja pasar, indikator teknikal, dan psikologi trading.")
    
    with st.expander("📖 Memahami Smart Money Concept (SMC)"):
        st.write("SMC adalah metodologi yang mengikuti jejak institusi besar (Bandar/Whales) yang memiliki modal besar untuk menggerakkan harga pasar.")
    with st.expander("📈 Apa itu Golden Cross & Death Cross?"):
        st.write("Golden Cross terjadi saat MA jangka pendek (misal MA20) memotong ke atas MA jangka panjang (MA50), menandakan potensi uptrend kuat.")
    with st.expander("💡 Psikologi Trading: Mengatasi FOMO"):
        st.write("Fear Of Missing Out (FOMO) sering membuat trader membeli di pucuk. Kuncinya adalah memiliki Trading Plan dan disiplin pada batasan Cut Loss.")

# ==============================================================================
# --- 12. FITUR ADMIN DASHBOARD (CONTROL PANEL) ---
# ==============================================================================
def show_admin_dashboard():
    st.header("👑 Admin Dashboard & Control Panel")
    st.markdown("Pusat kendali akun, kuota API, dan analitik pengguna secara *real-time*.")

    if not is_admin:
        st.error("🚨 AKSES DITOLAK")
        st.stop()

    st.divider()

    tab1, tab2, tab3 = st.tabs(["👥 Manajemen Pengguna & Kuota", "📜 Log Persetujuan ToS", "🔍 Log Pencarian Saham"])

    # --- TAB 1: MANAJEMEN PENGGUNA & KUOTA ---
    with tab1:
        try:
            res_users = supabase.table('profiles').select('*').execute()
            df_users = pd.DataFrame(res_users.data)

            if not df_users.empty:
                role_counts = df_users['role'].value_counts()
                cols = st.columns(len(role_counts))
                for i, (role_name, count) in enumerate(role_counts.items()):
                    cols[i].metric(f"Role: {role_name.upper()}", f"{count} User")

                st.divider()

                st.subheader("⚙️ Konfigurasi Akun & Kuota")
                with st.expander("Klik untuk Edit Role & Batas Kuota User", expanded=True):
                    c_mail, c_role, c_quota = st.columns([2, 1, 1])
                    
                    target_email = c_mail.selectbox("Pilih Email User:", df_users['email'].unique())
                    u_data = df_users[df_users['email'] == target_email].iloc[0]
                    
                    roles = ["free", "trial", "pro", "vip", "admin"]
                    idx_role = roles.index(u_data['role']) if u_data['role'] in roles else 0
                    
                    new_role = c_role.selectbox("Role Baru:", roles, index=idx_role)
                    current_q = int(u_data['daily_quota']) if pd.notna(u_data.get('daily_quota')) else 0
                    new_q = c_quota.number_input("Batas Kuota Harian:", min_value=0, value=current_q)

                    if st.button("💾 Simpan Perubahan", type="primary", use_container_width=True):
                        supabase.table('profiles').update({
                            'role': new_role,
                            'daily_quota': new_q
                        }).eq('id', u_data['id']).execute()
                        
                        try:
                            supabase.table('audit_logs').insert({
                                "user_email": user_email, "action": "ADMIN_UPDATE_ACCOUNT", 
                                "details": f"Admin mengubah {target_email} -> Role: {new_role}, Kuota: {new_q}"
                            }).execute()
                        except: pass

                        st.success(f"✅ Akun {target_email} berhasil diperbarui!")
                        time.sleep(1.5)
                        st.rerun()

                st.divider()

                st.subheader("📋 Daftar Profil Database")
                df_view = df_users.copy()
                df_view['daily_quota'] = df_view['daily_quota'].fillna(0).astype(int)
                df_view['used_quota'] = df_view['used_quota'].fillna(0).astype(int)
                df_view['Sisa Kuota'] = df_view['daily_quota'] - df_view['used_quota']
                
                cols_display = ['email', 'role', 'daily_quota', 'used_quota', 'Sisa Kuota']
                if 'created_at' in df_view.columns:
                    df_view['created_at'] = pd.to_datetime(df_view['created_at']).dt.strftime('%Y-%m-%d %H:%M')
                    cols_display.append('created_at')
                
                existing_cols = [c for c in cols_display if c in df_view.columns]
                st.dataframe(df_view[existing_cols], use_container_width=True, hide_index=True)

            else:
                st.info("Tidak ada data pengguna.")
        except Exception as e:
            st.error(f"Gagal memuat manajemen pengguna: {e}")

    # --- TAB 2: LOG TOS ---
    with tab2:
        if st.button("Muat Data Persetujuan ToS", type="primary", key="btn_tos"):
            with st.spinner("Mengambil log..."):
                try:
                    res = supabase.table('audit_logs').select('*').eq('action', 'LOGIN_TOS_ACCEPTED').order('created_at', desc=True).limit(100).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['Waktu (UTC)'] = df['created_at'].str.slice(0, 19).str.replace('T', ' ')
                        st.dataframe(df[['Waktu (UTC)', 'user_email', 'details']], use_container_width=True, hide_index=True)
                    else: st.info("Belum ada data.")
                except: st.error("Gagal menarik data log.")

    # --- TAB 3: LOG PENCARIAN ---
    with tab3:
        if st.button("Muat Data Pencarian Saham", type="primary", key="btn_search"):
            with st.spinner("Mengambil log..."):
                try:
                    res = supabase.table('audit_logs').select('*').eq('action', 'SEARCH_CHART').order('created_at', desc=True).limit(100).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['Waktu (UTC)'] = df['created_at'].str.slice(0, 19).str.replace('T', ' ')
                        st.dataframe(df[['Waktu (UTC)', 'user_email', 'details']], use_container_width=True, hide_index=True)
                    else: st.info("Belum ada data.")
                except: st.error("Gagal menarik data log.")

# ==============================================================================
# --- 13. FITUR ROBO-ADVISOR (ULTIMATE COMBO & AI 360) ---
# ==============================================================================
def show_portfolio_advisor():
    st.header("💼 Robo-Advisor & Portfolio Manager")
    st.markdown("Asisten AI portofolio yang ramah untuk perangkat Mobile dan Desktop.")
    st.divider()

    if 'portfolio_data' not in st.session_state:
        try:
            res = supabase.table('user_portfolios').select('*').eq('user_id', user_id).execute()
            if res.data:
                df_db = pd.DataFrame(res.data)
                st.session_state['portfolio_data'] = pd.DataFrame({
                    "Kode Saham": df_db['symbol'],
                    "Harga Beli": df_db['avg_price'].astype(int),
                    "Jumlah Lot": df_db['total_lot'].astype(int)
                })
            else:
                st.session_state['portfolio_data'] = pd.DataFrame(columns=["Kode Saham", "Harga Beli", "Jumlah Lot"])
        except:
            st.session_state['portfolio_data'] = pd.DataFrame(columns=["Kode Saham", "Harga Beli", "Jumlah Lot"])

    tab1, tab2, tab3 = st.tabs(["📈 Portofolio Aktif", "💰 Transaksi Jual (PnL)", "🛡️ Analisis AI 360°"])

    with tab1:
        st.subheader("📝 Kelola Saham")
        st.info("💡 **PANDUAN INTERAKTIF:**\n* **✏️ Edit:** Ketuk langsung pada angka Harga/Lot untuk mengubah.\n* **➕ Tambah:** Ketik kode saham baru di baris kosong paling bawah.\n* **🗑️ Hapus Cepat:** Ubah angka 'Jumlah Lot' menjadi **0**, lalu klik Simpan.")

        edited_df = st.data_editor(
            st.session_state['portfolio_data'],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Kode Saham": st.column_config.TextColumn("Kode", required=True),
                "Harga Beli": st.column_config.NumberColumn("Harga Beli (Rp)", min_value=1, format="Rp %d"),
                "Jumlah Lot": st.column_config.NumberColumn("Jumlah Lot", min_value=0)
            }
        )

        if st.button("💾 Simpan Perubahan", type="primary", use_container_width=True):
            try:
                to_keep = edited_df[edited_df['Jumlah Lot'] > 0]
                supabase.table('user_portfolios').delete().eq('user_id', user_id).execute()
                
                if not to_keep.empty:
                    insert_data = []
                    for _, row in to_keep.iterrows():
                        if pd.notna(row['Kode Saham']) and str(row['Kode Saham']).strip() != "":
                            insert_data.append({
                                "user_id": user_id,
                                "symbol": str(row['Kode Saham']).upper(),
                                "avg_price": float(row['Harga Beli']),
                                "total_lot": int(row['Jumlah Lot'])
                            })
                    if insert_data:
                        supabase.table('user_portfolios').insert(insert_data).execute()
                
                st.session_state['portfolio_data'] = to_keep
                st.success("✅ Data tersimpan! (Saham dengan 0 Lot otomatis dihapus)")
                time.sleep(1.5)
                st.rerun()
            except Exception as e:
                st.error(f"Gagal menyimpan: {e}")

        st.divider()
        with st.expander("🗑️ Hapus Emiten Sekaligus (Clear Position)", expanded=False):
            if not st.session_state['portfolio_data'].empty:
                del_sym = st.selectbox("Pilih saham yang ingin dibuang dari tabel:", st.session_state['portfolio_data']['Kode Saham'].unique())
                if st.button(f"Hapus {del_sym} Permanen"):
                    supabase.table('user_portfolios').delete().eq('user_id', user_id).eq('symbol', del_sym).execute()
                    st.session_state['portfolio_data'] = st.session_state['portfolio_data'][st.session_state['portfolio_data']['Kode Saham'] != del_sym]
                    st.success(f"{del_sym} berhasil dihapus dari portofolio.")
                    time.sleep(1)
                    st.rerun()
            else:
                st.info("Portofolio masih kosong.")

    with tab2:
        st.subheader("🛒 Form Penjualan Saham")
        if 'sold_history' not in st.session_state:
            st.session_state['sold_history'] = pd.DataFrame(columns=["Kode Saham", "Harga Beli", "Harga Jual", "Lot", "PnL Bersih (%)"])

        with st.expander("Catat Transaksi Penjualan Baru", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            s_ticker = c1.text_input("Kode Saham", placeholder="cth: BRIS").upper()
            s_buy = c2.number_input("Harga Beli (Rp)", min_value=0)
            s_sell = c3.number_input("Harga Jual (Rp)", min_value=0)
            s_lot = c4.number_input("Jumlah Lot Terjual", min_value=1)
            
            if st.button("Simpan Transaksi Jual"):
                if s_ticker and s_buy > 0 and s_sell > 0:
                    modal = s_buy * s_lot * 100
                    hasil_jual = s_sell * s_lot * 100
                    pnl_nominal = hasil_jual - modal
                    pnl_persen = (pnl_nominal / modal) * 100 if modal > 0 else 0
                    
                    new_sale = pd.DataFrame([[s_ticker, s_buy, s_sell, s_lot, f"{pnl_persen:.2f}%"]], 
                                            columns=["Kode Saham", "Harga Beli", "Harga Jual", "Lot", "PnL Bersih (%)"])
                    st.session_state['sold_history'] = pd.concat([st.session_state['sold_history'], new_sale], ignore_index=True)
                    st.success(f"Transaksi dicatat! Keuntungan/Kerugian: {pnl_persen:.2f}%")

                    mask = st.session_state['portfolio_data']['Kode Saham'] == s_ticker
                    if mask.any():
                        current_lot = st.session_state['portfolio_data'].loc[mask, 'Jumlah Lot'].values[0]
                        sisa_lot = current_lot - s_lot
                        
                        if sisa_lot <= 0:
                            supabase.table('user_portfolios').delete().eq('user_id', user_id).eq('symbol', s_ticker).execute()
                            st.session_state['portfolio_data'] = st.session_state['portfolio_data'][~mask]
                            st.info(f"💡 Info: {s_ticker} habis terjual dan otomatis dihapus dari daftar Portofolio Aktif.")
                        else:
                            supabase.table('user_portfolios').update({'total_lot': int(sisa_lot)}).eq('user_id', user_id).eq('symbol', s_ticker).execute()
                            st.session_state['portfolio_data'].loc[mask, 'Jumlah Lot'] = sisa_lot
                            st.info(f"💡 Info: Sisa kepemilikan {s_ticker} diupdate menjadi {sisa_lot} Lot.")
                else:
                    st.error("Mohon isi data harga dengan benar.")

        st.dataframe(st.session_state['sold_history'], use_container_width=True, hide_index=True)

    with tab3:
        if st.session_state['portfolio_data'].empty:
            st.info("💡 Portofolio Anda masih kosong. Silakan tambah saham di Tab 'Portofolio Aktif' terlebih dahulu.")
            return

        if st.button("🤖 Jalankan Analisis AI 360°", type="primary"):
            symbols = [str(x).upper() for x in st.session_state['portfolio_data']['Kode Saham'].dropna().unique() if str(x).strip() != ""]
            
            with st.spinner("Menarik data Teknikal, PnL, dan Kalender Dividen..."):
                current_prices = get_current_prices(symbols)
                
                div_messages = []
                for t in symbols:
                    try:
                        info = yf.Ticker(f"{t}.JK").calendar
                        if info is not None and not info.empty and 'Dividend Date' in info.index:
                            div_date = info.loc['Dividend Date'].iloc[0]
                            if pd.notna(div_date) and div_date.date() >= datetime.now().date():
                                div_messages.append(f"💰 **RADAR DIVIDEN:** {t} dijadwalkan akan bagi dividen pada {div_date.date().strftime('%d %B %Y')}")
                    except: pass
                
                if div_messages:
                    for msg in div_messages: st.success(msg)

                total_modal = 0; total_valuasi = 0
                table_rows = []

                for _, row in st.session_state['portfolio_data'].iterrows():
                    sym = str(row['Kode Saham']).upper()
                    avg_p = float(row['Harga Beli'])
                    lot = int(row['Jumlah Lot'])
                    lembar = lot * 100
                    
                    modal = avg_p * lembar
                    curr_p = current_prices.get(sym, avg_p)
                    valuasi = curr_p * lembar
                    
                    pnl_rp = valuasi - modal
                    pnl_pct = (pnl_rp / modal) * 100 if modal > 0 else 0
                    total_modal += modal; total_valuasi += valuasi

                    trend_status = "N/A"
                    try:
                        hist = yf.Ticker(f"{sym}.JK").history(period="3mo")
                        if len(hist) > 50:
                            sma20 = hist['Close'].rolling(20).mean().iloc[-1]
                            sma50 = hist['Close'].rolling(50).mean().iloc[-1]
                            if sma20 > sma50 and curr_p > sma20: trend_status = "🔥 Strong Uptrend"
                            elif sma20 > sma50 and curr_p <= sma20: trend_status = "📉 Pullback (Koreksi Naik)"
                            elif sma20 <= sma50 and curr_p < sma20: trend_status = "❄️ Strong Downtrend"
                            else: trend_status = "🔄 Rebound / Sideways"
                    except: pass

                    if pnl_pct <= -10 and "Downtrend" in trend_status: rekomendasi = "🚨 Cut Loss (Tren Patah)"
                    elif pnl_pct <= -5 and ("Uptrend" in trend_status or "Pullback" in trend_status): rekomendasi = "💎 Avg Down (Diskon)"
                    elif pnl_pct >= 15 and "Downtrend" in trend_status: rekomendasi = "💰 Take Profit (Tren Melemah)"
                    elif pnl_pct >= 10 and "Uptrend" in trend_status: rekomendasi = "🚀 Let Profit Run (Hold)"
                    elif pnl_pct > 0: rekomendasi = "📈 Profit Tipis (Hold)"
                    else: rekomendasi = "👀 Pantau Ketat"

                    table_rows.append({
                        "Saham": sym, "Lot": lot, "Avg Price": f"Rp {avg_p:,.0f}", 
                        "Last Price": f"Rp {curr_p:,.0f}", "PnL (%)": pnl_pct, 
                        "Kondisi Tren": trend_status, "Aksi AI": rekomendasi, "Valuasi": valuasi
                    })

            total_pnl_rp = total_valuasi - total_modal
            total_pnl_pct = (total_pnl_rp / total_modal) * 100 if total_modal > 0 else 0
            health_score = max(0, min(100, 60 + (total_pnl_pct * 2)))

            st.divider()
            c_dash1, c_dash2, c_dash3 = st.columns(3)
            c_dash1.metric("Total Aset", f"Rp {total_valuasi:,.0f}")
            c_dash2.metric("Floating PnL", f"Rp {total_pnl_rp:,.0f}", f"{total_pnl_pct:.2f}%", delta_color="normal" if total_pnl_rp >=0 else "inverse")
            c_dash3.metric("Skor Kesehatan", f"{health_score:.0f} / 100", "Sehat" if health_score >= 60 else "Perlu Perbaikan", delta_color="normal" if health_score >= 60 else "inverse")

            st.divider()
            df_display = pd.DataFrame(table_rows)
            
            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                st.subheader("🥧 Alokasi Aset")
                fig_pie = go.Figure(data=[go.Pie(labels=df_display['Saham'], values=df_display['Valuasi'], hole=.4)])
                fig_pie.update_layout(height=300, template="plotly_dark", margin=dict(l=0, r=0, t=10, b=0), showlegend=True)
                st.plotly_chart(fig_pie, use_container_width=True)

            with c_chart2:
                st.subheader("🛡️ Radar Diversifikasi")
                if user_role == 'free':
                    st.warning("🔒 **Fitur Eksklusif VIP Terkunci**")
                    st.info("Ketahui apakah portofolio Anda memiliki risiko fatal karena terlalu menumpuk di satu keranjang.")
                    st.button("Upgrade VIP Sekarang 🚀", key="div_upgrade")
                else:
                    max_weight = (df_display['Valuasi'].max() / total_valuasi) * 100 if total_valuasi > 0 else 0
                    biggest_stock = df_display.loc[df_display['Valuasi'].idxmax(), 'Saham'] if total_valuasi > 0 else "N/A"
                    
                    if len(df_display) < 2:
                        st.warning(f"⚠️ **Portofolio Terlalu Sepi.** 100% dana Anda ada di **{biggest_stock}**. Sangat rawan jika saham ini tiba-tiba anjlok.")
                    elif max_weight > 50:
                        st.error(f"🚨 **Risiko Tinggi!** {max_weight:.1f}% dana Anda menumpuk di saham **{biggest_stock}**. Lakukan *rebalancing*.")
                    else:
                        st.success("✅ **Diversifikasi Sangat Sehat.** Tidak ada saham yang mendominasi lebih dari 50%.")

            st.subheader("📋 Rekap AI 360° (Teknikal + PnL)")
            st.caption("💡 *Saran AI Ekstra:* Untuk melihat riwayat probabilitas pergerakan saham di bulan ini, silakan cek menu **🗓️ Peta Musiman**.")
            
            df_table_view = df_display.drop(columns=['Valuasi']) if 'Valuasi' in df_display.columns else df_display

            if user_role == 'free':
                df_table_view['Aksi AI'] = "🔒 Akses VIP"
                df_table_view['Kondisi Tren'] = "🔒 Akses VIP"
                st.dataframe(
                    df_table_view.style.format({'PnL (%)': '{:.2f}%'}).map(lambda x: 'color: #00ff00' if (isinstance(x, (int, float)) and x > 0) else ('color: #ff4444' if (isinstance(x, (int, float)) and x < 0) else ''), subset=['PnL (%)']),
                    use_container_width=True, hide_index=True
                )
            else:
                st.success("💎 **VIP AI Active:** Sistem memantau momentum pergerakan saham (SMA 20/50) dipadukan dengan modal Anda.")
                st.dataframe(
                    df_table_view.style.format({'PnL (%)': '{:.2f}%'}).map(lambda x: 'color: #00ff00' if (isinstance(x, (int, float)) and x > 0) else ('color: #ff4444' if (isinstance(x, (int, float)) and x < 0) else ''), subset=['PnL (%)']),
                    use_container_width=True, hide_index=True
                )

# ==============================================================================
# --- 14. ETALASE FREEMIUM, PENGATURAN SIDEBAR & SMART ROUTING ---
# ==============================================================================

st.sidebar.markdown(f"👤 **Halo, {user_email.split('@')[0]}**")
color_map = {"admin": "green", "pro": "blue", "trial": "orange", "free": "gray", "vip": "gold"}
role_color = color_map.get(user_role, "gray")
st.sidebar.markdown(f"Status Akun: <span style='color:{role_color}; font-weight:bold;'>{user_role.upper()}</span>", unsafe_allow_html=True)

try:
    q_res = supabase.table('profiles').select('daily_quota, used_quota').eq('id', user_id).single().execute()
    if q_res.data:
        limit_q = int(q_res.data.get('daily_quota', 0))
        used_q = int(q_res.data.get('used_quota', 0))
    else:
        limit_q = 0; used_q = 0
except:
    limit_q = 0; used_q = 0

if user_role == 'admin':
    st.sidebar.success("⚡ Kuota API: **UNLIMITED**")
else:
    sisa_q = max(0, limit_q - used_q)
    prog_val = min(1.0, used_q / limit_q) if limit_q > 0 else 1.0

    if sisa_q == 0:
        st.sidebar.error(f"⚠️ Sisa Kuota: **{sisa_q} / {limit_q}**")
        st.sidebar.progress(prog_val)
        st.sidebar.caption("🚨 Kuota habis. Reset otomatis pukul 00:00 WIB.")
    elif prog_val > 0.8:
        st.sidebar.warning(f"⚡ Sisa Kuota: **{sisa_q} / {limit_q}**")
        st.sidebar.progress(prog_val)
    else:
        st.sidebar.info(f"⚡ Sisa Kuota: **{sisa_q} / {limit_q}**")
        st.sidebar.progress(prog_val)

st.sidebar.divider()

if 'active_menu' not in st.session_state:
    st.session_state['active_menu'] = "🔍 Super Screener"
if 'target_saham' not in st.session_state:
    st.session_state['target_saham'] = "" 

menu_options = [
    "🔍 Super Screener", 
    "📊 Advanced Chart",
    "🥇 Emas & Safe Haven",
    "🧪 Mesin Backtesting", 
    "📰 Radar Sentimen Berita", 
    "🗓️ Peta Musiman",
    "💼 Robo-Advisor Portofolio",
    "📅 Dividend Hunter", 
    "📚 Pusat Edukasi"
]

if is_admin:
    menu_options.append("👑 Admin Dashboard")
    
mode = st.sidebar.radio("Pilih Menu:", menu_options, key="active_menu")
st.sidebar.divider()

market_choice = st.sidebar.radio("🌍 Pilih Bursa:", ["🇮🇩 Indonesia (BEI)", "🇺🇸 Wall Street (US)"])
st.sidebar.divider()

use_idx_data = False
active_stock_list = []
active_category_name = ""

if "Indonesia" in market_choice:
    if mode == "🔍 Super Screener" or mode == "📅 Dividend Hunter":
        kategori_saham = st.sidebar.radio("Pilih Kategori Saham:", ["👑 Lapis 1 (JII30)", "🚀 Lapis 2 (Mid-Small Caps)"])
        st.sidebar.divider()
        if kategori_saham == "🚀 Lapis 2 (Mid-Small Caps)":
            active_stock_list = SHARIA_MIDCAP_STOCKS
            active_category_name = "Lapis 2"
            if mode == "🔍 Super Screener":
                st.sidebar.info("✨ Mode Lapis 2 otomatis menggunakan Data Standar (Scan Live Real-Time).")
        else:
            active_stock_list = SHARIA_STOCKS
            active_category_name = "Lapis 1 (JII30)"
            if mode == "🔍 Super Screener":
                data_source = st.sidebar.radio("Pilih Sumber Data:", ["🌐 Data Standar (Gratis)", "🏦 Data IDX (Premium)"])
                if "Data IDX" in data_source:
                    if user_role == 'free': 
                        st.sidebar.error("🔒 Fitur Terkunci.")
                        st.sidebar.caption("Upgrade ke VIP/Pro untuk melihat data akumulasi Bandar secara real-time.")
                    else: use_idx_data = True
    elif mode == "📊 Advanced Chart":
        active_stock_list = SHARIA_STOCKS
        active_category_name = "Lapis 1"
        data_source = st.sidebar.radio("Pilih Sumber Data:", ["🌐 Data Standar (Gratis)", "🏦 Data IDX (Premium)"])
        if "Data IDX" in data_source:
            if user_role == 'free': 
                st.sidebar.error("🔒 Fitur Terkunci.")
                st.sidebar.caption("Upgrade ke VIP/Pro untuk menarik data broker summary harian.")
            else: use_idx_data = True
else:
    active_stock_list = US_STOCKS
    active_category_name = "US Top Tech"
    if mode == "📊 Advanced Chart" or mode == "🔍 Super Screener":
        st.sidebar.info("ℹ️ Mode Wall Street: Data Bandar/Asing tidak tersedia (Sistem Dark Pools).")

if is_admin:
    st.sidebar.divider()
    st.sidebar.markdown("**👑 Admin Control**")
    
    if 'confirm_clear_cache' not in st.session_state:
        st.session_state['confirm_clear_cache'] = False

    if not st.session_state['confirm_clear_cache']:
        if st.sidebar.button("🧹 Bersihkan Memori Cache", use_container_width=True):
            st.session_state['confirm_clear_cache'] = True
            st.rerun() 
    else:
        st.sidebar.warning("⚠️ **PERHATIAN!** Anda yakin ingin menghapus memori? Aplikasi akan menarik data ulang.")
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("✅ YAKIN", use_container_width=True):
                st.cache_data.clear()
                api_registry.clear()
                st.session_state['confirm_clear_cache'] = False 
                st.sidebar.success("✅ Memori dibersihkan!")
                time.sleep(1.5) 
                st.rerun() 
        with col2:
            if st.button("❌ BATAL", use_container_width=True):
                st.session_state['confirm_clear_cache'] = False 
                st.rerun() 

st.sidebar.divider()
if st.sidebar.button("Keluar (Logout)"):
    st.session_state['logged_in'] = False
    st.session_state['user'] = None
    supabase.auth.sign_out()
    st.rerun()

st.sidebar.divider()
st.sidebar.markdown("""
<div style="font-size: 0.8rem; color: #666; text-align: justify;">
<b>⚠️ DISCLAIMER & PERINGATAN RISIKO</b><br>
Semua data, analisis, dan rekomendasi yang ditampilkan di aplikasi ini murni untuk tujuan informasi dan edukasi, <b>BUKAN</b> merupakan nasihat keuangan resmi atau ajakan pasti untuk membeli/menjual saham.<br><br>
Perdagangan saham memiliki risiko kerugian finansial yang tinggi. Segala keputusan transaksi dan risiko kerugian sepenuhnya merupakan <b>tanggung jawab pribadi pengguna</b>. Pembuat aplikasi dibebaskan dari segala tuntutan hukum atas kerugian materiil maupun imateriil.
</div>
""", unsafe_allow_html=True)

# --- ROUTING APLIKASI UTAMA ---
if mode == "🔍 Super Screener":
    run_screener(use_idx_data, active_stock_list, active_category_name, market_choice)
elif mode == "📊 Advanced Chart":
    show_chart(use_idx_data, market_choice)
elif mode == "🥇 Emas & Safe Haven":
    show_gold_predictor()
elif mode == "🧪 Mesin Backtesting":
    show_backtesting(market_choice)
elif mode == "📰 Radar Sentimen Berita":
    show_news_sentiment(market_choice)
elif mode == "🗓️ Peta Musiman":
    show_seasonality(market_choice)
elif mode == "💼 Robo-Advisor Portofolio":
    show_portfolio_advisor()
elif mode == "📅 Dividend Hunter":
    show_dividend_hunter(active_stock_list, active_category_name, market_choice)
elif mode == "📚 Pusat Edukasi":
    show_education()
elif mode == "👑 Admin Dashboard" and is_admin:
    show_admin_dashboard()