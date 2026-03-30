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

# --- TAHAP 5: IMPORT MACHINE LEARNING UNTUK FRONTEND ---
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

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
                    st.error("🚫 Email tidak terdaftar atau Password salah!")

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
US_STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "LLY", "JPM", "V", "MA", "UNH", "HD", "PG", "COST", "JNJ", "NFLX", "AMD", "CRM"]
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
# --- 10. FITUR DIVIDEND HUNTER (FULL VERSION) ---
def show_dividend(use_idx_data, market_choice):
    st.header("📅 Dividend Hunter & Yield Analysis")
    st.markdown("Pantau riwayat pembagian dividen dan estimasi *Dividend Yield* untuk saham pilihan Anda.")

    col_input, col_info = st.columns([1, 2])
    with col_input:
        symbol = st.text_input("🔍 Masukkan Kode Saham (Contoh: PTBA / MSFT):", "").upper()

    if symbol:
        if check_and_deduct_quota(f"div_{symbol}"):
            with st.spinner(f"Mengambil data dividen {symbol}..."):
                # Sesuaikan format ticker berdasarkan bursa yang dipilih
                ticker_symbol = f"{symbol}.JK" if "Indonesia" in market_choice and not symbol.endswith(".JK") else symbol
                try:
                    saham = yf.Ticker(ticker_symbol)
                    hist_div = saham.dividends

                    if hist_div.empty:
                        st.warning(f"⚠️ Tidak ada catatan riwayat pembagian dividen untuk saham {symbol} di database Yahoo Finance.")
                    else:
                        # Konversi index zona waktu agar aman ditampilkan di Plotly
                        hist_div.index = hist_div.index.tz_localize(None)
                        
                        # Ambil data 5 tahun terakhir
                        lima_tahun_lalu = datetime.now() - timedelta(days=5*365)
                        hist_div_5y = hist_div[hist_div.index >= lima_tahun_lalu]

                        if hist_div_5y.empty:
                            st.info(f"Saham {symbol} belum membagikan dividen dalam 5 tahun terakhir.")
                        else:
                            df_div = pd.DataFrame(hist_div_5y).reset_index()
                            df_div.columns = ['Tanggal', 'Dividen']
                            df_div['Tanggal'] = df_div['Tanggal'].dt.strftime('%Y-%m-%d')
                            
                            # Info harga saat ini untuk hitung Dividend Yield
                            info = saham.info
                            current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
                            
                            # Hitung total dividen 12 bulan terakhir (Trailing Twelve Months / TTM)
                            setahun_lalu = datetime.now() - timedelta(days=365)
                            div_ttm = hist_div[hist_div.index >= setahun_lalu].sum()
                            
                            yield_pct = (div_ttm / current_price) * 100 if current_price > 0 else 0

                            st.success(f"✅ Data Dividen {symbol} Berhasil Ditarik!")
                            
                            c1, c2, c3 = st.columns(3)
                            mata_uang = "$" if "US" in market_choice else "Rp"
                            
                            c1.metric("Total Dividen (1 Tahun Terakhir)", f"{mata_uang} {div_ttm:,.2f}")
                            c2.metric("Harga Saham Saat Ini", f"{mata_uang} {current_price:,.2f}")
                            c3.metric("Estimasi Dividend Yield (TTM)", f"{yield_pct:.2f}%")

                            # Grafik Riwayat Dividen
                            st.markdown("### 📊 Grafik Riwayat Dividen (5 Tahun Terakhir)")
                            fig = go.Figure(data=[
                                go.Bar(x=df_div['Tanggal'], y=df_div['Dividen'], marker_color='#f39c12')
                            ])
                            fig.update_layout(
                                xaxis_title="Tanggal Ex-Date / Payment",
                                yaxis_title=f"Jumlah Dividen ({mata_uang})",
                                template="plotly_dark",
                                margin=dict(l=20, r=20, t=30, b=20)
                            )
                            st.plotly_chart(fig, use_container_width=True)
                            
                            with st.expander("Tabel Rincian Dividen"):
                                st.dataframe(df_div.sort_values('Tanggal', ascending=False), use_container_width=True, hide_index=True)
                                
                except Exception as e:
                    st.error(f"Gagal menarik data dividen: {e}")
        else:
            st.error("❌ Kuota API Harian Anda habis! Upgrade akun atau tunggu *reset* besok jam 00:00 WIB.")


# --- 11. PUSAT EDUKASI & STRATEGI DENGAN KAMUS FULL ---
def show_education():
    st.header("📚 Pusat Edukasi & Strategi Trading")
    st.markdown("Pelajari cara kerja sistem kecerdasan buatan (AI) ini agar Anda bisa memaksimalkan profit dan menghindari jebakan pasar.")
    st.divider()

    st.subheader("📖 Kamus Lengkap Indikator & Istilah AI")
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("**💎 REKOMENDASI AI**")
        st.markdown("""
        * **💎 STRONG BUY** : Saham sangat istimewa. Fundamental murah, Tren Bullish, dan Machine Learning melihat probabilitas naik > 70%. Sangat disarankan.
        * **✅ BUY** : Saham bagus untuk diakumulasi cicil beli. Risiko penurunan sangat rendah.
        * **WAIT** : Saham belum memiliki momentum yang jelas. Lebih baik pantau dulu.
        """)
        
        st.success("**🌊 FASE WYCKOFF (Siklus Bandar)**")
        st.markdown("""
        * **🟢 Accumulation** : Fase paling aman. Bandar sedang diam-diam mengumpulkan barang di harga bawah.
        * **🔵 Markup** : Harga sedang diterbangkan oleh Bandar. Sangat cocok untuk *trend-following* (ikut arus).
        * **🔴 Distribution** : HATI-HATI! Bandar sedang jualan (buang barang) ke ritel di pucuk harga.
        * **🟠 Markdown** : Harga sedang dihancurkan ke bawah. Hindari saham ini!
        """)

    with col2:
        st.warning("**🔥 KATALIS PENDORONG (Alasan Saham Lolos)**")
        st.markdown("""
        * **🤖 AI Bullish** : Algoritma *Machine Learning* mendeteksi pola yang mengindikasikan harga besok akan naik.
        * **🔥 Top Momentum** : Pergerakan harga saham ini termasuk yang paling liar dan kuat dalam 6 bulan terakhir.
        * **💰 Undervalued** : Saham ini sedang "Salah Harga" (Sangat murah dibanding nilai buku perusahaannya/PBV rendah).
        * **🌟 Market Beat** : Saham ini bergerak melawan arus (Misal: IHSG/S&P 500 hancur, tapi dia malah naik sendirian).
        * **🐳 CMF (Chaikin Money Flow)** : Ada indikasi aliran dana besar (*Smart Money*) masuk diam-diam ke saham ini.
        * **💎 RSI** : Indikator RSI (Relative Strength Index) menunjukkan saham ini sudah sangat *Oversold* (jenuh jual/terlalu murah) dan siap mantul naik.
        * **🚀 Breakout DC** : Harga saham baru saja menjebol atap *Donchian Channel* (indikasi tren super kuat baru saja dimulai).
        * **🔥 MA** : Harga saham berada di atas semua garis *Moving Average* penting (Uptrend sempurna).
        """)

    st.divider()
    st.subheader("🧠 FAQ & Strategi Trading")
    with st.expander("🤔 1. Kenapa Status Saham di Screener & Chart Bisa Berbeda?"):
        st.markdown("Screener memindai data secara keseluruhan di malam hari (melihat tren besar), sedangkan Advanced Chart menganalisis pergerakan harga secara *live* detik ini juga. Gunakan Screener untuk mencari kandidat, dan Chart untuk eksekusi beli.")

    with st.expander("⏱️ 2. Apakah Data di Aplikasi Ini 100% Live?"):
        st.markdown("Ada jeda 10-15 menit dari pasar asli. Aplikasi ini dirancang untuk **Swing Trading** (menahan saham beberapa hari/minggu), bukan untuk *Scalping* harian. Waktu analisa terbaik adalah 15:30 WIB (menjelang bursa tutup).")
# --- 12. MESIN UTAMA: SMART SCREENER (DATABASE + LIVE SCAN) ---
def show_kamus_screener():
    st.markdown("---")
    st.markdown("### 📖 Kamus Indikator AI & Istilah")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        **💎 REKOMENDASI AI:**
        * **💎 STRONG BUY** : Saham istimewa (Fundamental murah, Tren Bullish, Probabilitas > 70%).
        * **✅ BUY** : Saham bagus untuk diakumulasi cicil beli (Risiko rendah).
        
        **🌊 FASE WYCKOFF (Siklus Bandar):**
        * **🟢 Accumulation** : Fase paling aman. Bandar sedang mengumpulkan barang.
        * **🔵 Markup** : Harga sedang diterbangkan. Cocok untuk *trend-following*.
        * **🔴 Distribution** : HATI-HATI! Bandar sedang jualan di pucuk.
        * **🟠 Markdown** : Harga sedang dihancurkan ke bawah. Hindari!
        """)
    with c2:
        st.markdown("""
        **🔥 KATALIS PENDORONG:**
        * **🤖 AI Bullish** : Machine Learning memprediksi besok harga akan naik.
        * **🔥 Top Momentum** : Pergerakan terkuat dalam 6 bulan.
        * **💰 Undervalued** : Sangat murah dibanding nilai buku.
        * **🌟 Market Beat** : Saham bergerak naik melawan arus market yang turun.
        * **🐳 CMF** : Uang besar (Smart Money) masuk secara akumulatif.
        * **💎 RSI** : Oversold (jenuh jual/terlalu murah) dan siap mantul.
        * **🚀 Breakout DC** : Menjebol atap *Donchian Channel*.
        * **🔥 MA** : Uptrend sempurna (Harga di atas SMA 20, 50, 100, EMA 200).
        """)

def run_screener(use_idx_data, stock_list, category_name, market_choice):
    st.header(f"🔍 AI Smart Screener - {category_name}")
    st.markdown("Menampilkan hasil *screening* algoritma Quant & AI. Lapis 1 & US Market ditarik dari Database Harian. Lapis 2 di-scan secara *Live* (Real-Time).")

    is_us_market = "US" in market_choice or "Wall Street" in market_choice

    if st.button("🔄 Jalankan Screener", type="primary"):
        if check_and_deduct_quota("screener_run"):
            df_res = pd.DataFrame()
            
            # LOGIKA 1: BACA DARI DATABASE (Hanya untuk Lapis 1 & Wall Street)
            if category_name == "Lapis 1 (JII30)" or is_us_market:
                with st.spinner(f"Memindai database {category_name}..."):
                    try:
                        table_name = 'us_daily_data' if is_us_market else 'jii30_daily_data'
                        res = supabase.table(table_name).select('*').execute()
                        if res.data:
                            df_res = pd.DataFrame(res.data)
                    except Exception as e:
                        st.error(f"Gagal mengambil data dari database: {e}")
            
            # LOGIKA 2: LIVE SCAN GRATISAN (Hanya untuk Lapis 2)
            else:
                with st.spinner(f"Melakukan Live Scan untuk {len(stock_list)} saham {category_name}... (Bisa memakan waktu 1-2 menit)"):
                    try:
                        ihsg_df = get_ihsg_data()
                        live_results = []
                        for symbol in stock_list:
                            ticker = f"{symbol}.JK"
                            df = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
                            if df.empty or len(df) < 50: continue
                            
                            df = calculate_metrics(df, ihsg_df)
                            fund_data = get_fundamental_info(ticker)
                            score_tech, score_fund, score_bandar, score_candle, reasons, curr = score_analysis(df, fund_data)
                            
                            total_score = score_tech + score_fund + score_bandar + score_candle
                            phase, _ = advanced_analysis(df)
                            
                            rec = "WAIT"
                            if total_score >= 4.5 or "Accumulation" in phase: rec = "✅ BUY"
                            if total_score >= 8.0: rec = "💎 STRONG BUY"
                            
                            if total_score < 3.5 and "Accumulation" not in phase:
                                continue
                            
                            close_price = curr['Close']
                            atr = curr.get('ATR', 0)
                            target_profit = close_price + (3.0 * atr) if atr > 0 else close_price * 1.1
                            stop_loss = close_price - (1.5 * atr) if atr > 0 else close_price * 0.9
                            
                            live_results.append({
                                "fetch_date": datetime.now().strftime("%Y-%m-%d"),
                                "kode": symbol,
                                "harga": close_price,
                                "tp": target_profit,
                                "sl": stop_loss,
                                "status": rec,
                                "fase": phase,
                                "katalis": ", ".join(reasons)
                            })
                        df_res = pd.DataFrame(live_results)
                    except Exception as e:
                        st.error(f"Gagal melakukan Live Scan Lapis 2: {e}")

            # --- TAMPILAN HASIL ---
            if not df_res.empty:
                if 'kode' in df_res.columns and len(df_res) == 1 and df_res['kode'].iloc[0] == 'CASH':
                    st.error(f"**MODE PROTEKSI MODAL AKTIF (Update: {df_res['fetch_date'].iloc[0]})**")
                    st.warning("🛡️ **CASH IS KING!** " + df_res['katalis'].iloc[0])
                    st.info("Sistem AI mendeteksi probabilitas kemenangan yang sangat rendah di pasar hari ini. Sangat disarankan untuk menahan uang *cash*.")
                else:
                    st.success(f"✅ Menampilkan **{len(df_res)}** saham terbaik hasil kurasi ketat AI.")
                    
                    # Formatting Mata Uang
                    if is_us_market:
                        df_res['Harga (USD)'] = df_res['harga'].apply(lambda x: format_currency(x, True))
                        df_res['Target Profit'] = df_res['tp'].apply(lambda x: format_currency(x, True))
                        df_res['Stop Loss'] = df_res['sl'].apply(lambda x: format_currency(x, True))
                    else:
                        df_res['Harga (Rp)'] = df_res['harga'].apply(lambda x: format_currency(x, False))
                        df_res['Target Profit'] = df_res['tp'].apply(lambda x: format_currency(x, False))
                        df_res['Stop Loss'] = df_res['sl'].apply(lambda x: format_currency(x, False))
                    
                    display_cols = ['kode']
                    if is_us_market: display_cols.extend(['Harga (USD)', 'Target Profit', 'Stop Loss'])
                    else: display_cols.extend(['Harga (Rp)', 'Target Profit', 'Stop Loss'])
                    
                    display_cols.extend(['status', 'fase'])
                    
                    if not is_us_market and 'power_asing' in df_res.columns and 'modal_asing' in df_res.columns:
                        df_res['Power Asing'] = df_res['power_asing'].apply(lambda x: f"{float(x):.2f}%" if pd.notna(x) else "0%")
                        df_res['Avg Harga Asing'] = df_res['modal_asing'].apply(lambda x: format_currency(x, False))
                        display_cols.extend(['Power Asing', 'Avg Harga Asing'])
                    
                    display_cols.append('katalis')
                    
                    # Filter kolom yang benar-benar ada agar tidak crash
                    valid_display_cols = [c for c in display_cols if c in df_res.columns]
                    df_display = df_res[valid_display_cols].copy()
                    df_display.rename(columns={'kode': 'Ticker', 'status': 'Rekomendasi AI', 'fase': 'Fase Wyckoff', 'katalis': 'Katalis Pendorong'}, inplace=True)
                    
                    st.dataframe(df_display, use_container_width=True, hide_index=True, height=(len(df_display) * 35) + 40)
            else:
                st.warning("⚠️ Tidak ada saham yang lolos filter AI hari ini (atau database sedang kosong).")
            
            # MEMUNCULKAN KAMUS SETELAH HASIL (CASH IS KING, Kosong, atau Sukses)
            show_kamus_screener()
            
        else:
            st.error("❌ Kuota API Harian Anda habis! Upgrade akun atau tunggu *reset* besok jam 00:00 WIB.")
    else:
        # Jika user belum menekan tombol, tampilkan kamus sebagai panduan
        show_kamus_screener()
# --- 13. FITUR ADVANCED CHART & AI SNIPER ---
def show_chart(use_idx_data, market_choice):
    st.header("📊 Advanced Chart & AI Analysis")
    st.markdown("Ketik kode saham untuk melihat grafik teknikal interaktif dan analisis mendalam.")

    # Kolom input pencarian saham
    col_input, col_info = st.columns([1, 2])
    with col_input:
        symbol = st.text_input("🔍 Masukkan Kode Saham (Contoh: BBCA / AAPL):", "").upper()
    
    if symbol:
        if check_and_deduct_quota(f"chart_{symbol}"):
            with st.spinner(f"Menganalisis pergerakan {symbol}..."):
                # Tambahkan .JK HANYA jika pasar Indonesia
                ticker_symbol = f"{symbol}.JK" if "Indonesia" in market_choice and not symbol.endswith(".JK") else symbol
                
                try:
                    # Menarik data riwayat harga dari Yahoo Finance
                    df = yf.download(ticker_symbol, period="1y", auto_adjust=True, progress=False)
                    if df.empty:
                        st.error(f"❌ Data saham {symbol} tidak ditemukan! Pastikan kode benar.")
                        return
                    
                    df = fix_dataframe(df)
                    
                    # Benchmark penyesuaian: IHSG untuk Indo, S&P 500 untuk US
                    benchmark_ticker = "^JKSE" if "Indonesia" in market_choice else "^GSPC"
                    ihsg_df = get_ihsg_data(benchmark_ticker)
                    df = calculate_metrics(df, ihsg_df)
                    
                    fund_data = get_fundamental_info(ticker_symbol)
                    
                    # Ambil data bandar (HANYA untuk Indonesia dan jika toggle premium menyala)
                    net_foreign, avg_buy_price, fetch_time = 0, 0, "-"
                    if use_idx_data and "Indonesia" in market_choice:
                        target_date = get_idx_target_date(df)
                        net_foreign, avg_buy_price, fetch_time = fetch_idx_foreign_flow(symbol.replace('.JK',''), target_date)
                    
                    # Eksekusi AI & Algoritma Penilaian
                    score_tech, score_fund, score_bandar, score_candle, reasons, curr = score_analysis(df, fund_data)
                    total_score = score_tech + score_fund + score_bandar + score_candle
                    
                    phase, divergence = advanced_analysis(df)
                    
                    # PENENTUAN STATUS AI
                    rec = "WAIT"
                    if total_score >= 4.5 or "Accumulation" in phase: rec = "✅ BUY"
                    if total_score >= 8.0: rec = "💎 STRONG BUY"
                    
                    # --- TAMPILAN DASHBOARD METRIK ---
                    st.markdown("### 🤖 Kesimpulan AI Quant")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Status AI", rec)
                    c2.metric("Skor Total", f"{total_score} / 10")
                    c3.metric("Fase Siklus", phase)
                    
                    # Penyesuaian Mata Uang dan Blok Bandarmologi
                    close_price = curr['Close']
                    if "Indonesia" in market_choice:
                        c4.metric("Harga Saat Ini", format_rupiah(close_price))
                        
                        st.markdown("### 🌊 Analisis Foreign Flow (Bandar Asing)")
                        b1, b2, b3 = st.columns(3)
                        status_bandar = "🟢 AKUMULASI" if net_foreign > 0 else ("🔴 DISTRIBUSI" if net_foreign < 0 else "⚪ NETRAL")
                        b1.metric("Status Asing Hari Ini", status_bandar)
                        b2.metric("Net Foreign Volume", format_rupiah(net_foreign))
                        
                        dominasi = 0
                        if curr['Volume'] > 0 and close_price > 0:
                            dominasi = (abs(net_foreign) / (curr['Volume'] * close_price)) * 100
                        b3.metric("Power Asing (% Dominasi)", f"{dominasi:.2f}%")
                        st.caption(f"*Data Bandar ditarik via GoAPI Premium. Terakhir update: {fetch_time}*")
                    else:
                        c4.metric("Harga Saat Ini", format_currency(close_price, is_us=True))
                        st.info("ℹ️ Mode Wall Street: Analisis Bandarmologi (Foreign Flow) dinonaktifkan karena sistem *Dark Pools*.")
                    
                    st.markdown(f"**🔥 Katalis Penggerak:** {', '.join(reasons) if reasons else 'Belum ada momentum kuat'}")
                    st.divider()

                    # --- GRAFIK PLOTLY INTERAKTIF ---
                    st.markdown("### 📈 Grafik Teknikal Interaktif")
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                    
                    # Candlestick
                    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Harga'), row=1, col=1)
                    
                    # Moving Averages
                    if not df['SMA50'].isna().all(): fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], line=dict(color='blue', width=1), name='SMA 50'), row=1, col=1)
                    if not df['EMA200'].isna().all(): fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], line=dict(color='red', width=2), name='EMA 200'), row=1, col=1)
                    
                    # Indikator Bawah (RSI)
                    if not df['Rsi'].isna().all():
                        fig.add_trace(go.Scatter(x=df.index, y=df['Rsi'], line=dict(color='purple', width=1), name='RSI (14)'), row=2, col=1)
                        fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
                        fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)

                    fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig, use_container_width=True)

                    # --- KAMUS DI ADVANCED CHART ---
                    with st.expander("📖 Kamus Indikator AI & Istilah (Klik untuk Buka)"):
                        st.markdown("""
                        **💎 REKOMENDASI AI:**
                        * **💎 STRONG BUY** : Saham istimewa (Fundamental murah, Tren Bullish, AI melihat probabilitas naik > 70%).
                        * **✅ BUY** : Saham bagus untuk diakumulasi cicil beli (Risiko rendah).
                        
                        **🌊 FASE WYCKOFF (Siklus Bandar):**
                        * **🟢 Accumulation** : Fase paling aman. Bandar sedang mengumpulkan barang di harga bawah.
                        * **🔵 Markup** : Harga sedang diterbangkan. Cocok untuk *trend-following*.
                        * **🔴 Distribution** : HATI-HATI! Bandar sedang jualan (buang barang) ke ritel di pucuk.
                        * **🟠 Markdown** : Harga sedang dihancurkan ke bawah. Hindari!
                        
                        **🔥 KATALIS PENDORONG:**
                        * **🤖 AI Bullish** : Machine Learning memprediksi besok harga akan naik.
                        * **🔥 Top Momentum** : Pergerakan harga saham ini termasuk yang paling liar dan kuat.
                        * **💰 Undervalued** : Harga saham ini sedang "Salah Harga" (Sangat murah).
                        * **🌟 Market Beat** : Saham ini bergerak melawan arus pasar.
                        """)

                except Exception as e:
                    st.error(f"Terjadi kesalahan saat memproses grafik: {e}")
        else:
            st.error("❌ Kuota API Harian Anda habis! Upgrade akun atau tunggu *reset* besok jam 00:00 WIB.")
# --- 14. PENGATURAN SIDEBAR & SMART ROUTING ---
st.sidebar.markdown(f"👤 **Halo, {user_email.split('@')[0]}**")
st.sidebar.caption(f"Status Akun: **{user_role.upper()}**")

try:
    current_db = supabase.table('profiles').select('daily_quota, used_quota').eq('id', user_id).execute().data[0]
    st.sidebar.caption(f"Sisa Kuota API Personal: **{current_db['daily_quota'] - current_db['used_quota']} / {current_db['daily_quota']}**")
except: pass
st.sidebar.divider()

menu_options = ["🔍 Super Screener", "📊 Advanced Chart", "📅 Dividend Hunter", "📚 Pusat Edukasi"]
if is_admin:
    menu_options.append("👑 Admin Dashboard")
    
mode = st.sidebar.radio("Pilih Menu:", menu_options)
st.sidebar.divider()

# --- FITUR BARU: SAKELAR BENUA & LOGIKA SIDEBAR ---
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
                    if user_role == 'free': st.sidebar.warning("🔒 Fitur Terkunci. Upgrade ke VIP/Pro.")
                    else: use_idx_data = True
    elif mode == "📊 Advanced Chart":
        active_stock_list = SHARIA_STOCKS
        active_category_name = "Lapis 1"
        data_source = st.sidebar.radio("Pilih Sumber Data:", ["🌐 Data Standar (Gratis)", "🏦 Data IDX (Premium)"])
        if "Data IDX" in data_source:
            if user_role == 'free': st.sidebar.warning("🔒 Fitur Terkunci. Upgrade ke VIP/Pro.")
            else: use_idx_data = True
else:
    # MODE WALL STREET
    active_stock_list = US_STOCKS
    active_category_name = "US Top Tech"
    if mode == "📊 Advanced Chart" or mode == "🔍 Super Screener":
        st.sidebar.info("ℹ️ Mode Wall Street: Data Bandar/Asing tidak tersedia (Sistem Dark Pools).")

# --- KONTROL ADMIN ---
if is_admin:
    st.sidebar.divider()
    st.sidebar.markdown("**👑 Admin Control**")
    if st.sidebar.button("🧹 Bersihkan Memori Cache"):
        st.cache_data.clear()
        api_registry.clear()
        st.sidebar.success("✅ Memori dibersihkan!")

# --- LOGOUT ---
st.sidebar.divider()
if st.sidebar.button("Keluar (Logout)"):
    st.session_state['logged_in'] = False
    st.session_state['user'] = None
    supabase.auth.sign_out()
    st.rerun()

# --- DISCLAIMER RISIKO (WAJIB FINTECH) ---
st.sidebar.divider()
st.sidebar.markdown("""
<div style="font-size: 0.8rem; color: #666; text-align: justify;">
<b>⚠️ DISCLAIMER & PERINGATAN RISIKO</b><br>
Semua data, analisis, dan rekomendasi yang ditampilkan di aplikasi ini murni untuk tujuan informasi dan edukasi, <b>BUKAN</b> merupakan nasihat keuangan resmi atau ajakan pasti untuk membeli/menjual saham.<br><br>
Perdagangan saham memiliki risiko kerugian finansial yang tinggi. Segala keputusan transaksi dan risiko kerugian sepenuhnya merupakan <b>tanggung jawab pribadi pengguna</b>. Pembuat aplikasi dibebaskan dari segala tuntutan hukum atas kerugian materiil maupun imateriil.
</div>
""", unsafe_allow_html=True)

# --- MENJALANKAN APLIKASI UTAMA ---
if mode == "🔍 Super Screener": 
    run_screener(use_idx_data, active_stock_list, active_category_name, market_choice)
elif mode == "📊 Advanced Chart": 
    show_chart(use_idx_data, market_choice)
elif mode == "📅 Dividend Hunter":
    show_dividend(use_idx_data, market_choice)
elif mode == "📚 Pusat Edukasi":
    show_education()
elif mode == "👑 Admin Dashboard" and is_admin:
    st.header("👑 Admin Dashboard")
    st.info("Anda masuk sebagai Administrator. (Fitur manajemen *user* dan kuota dapat ditambahkan di sini).")