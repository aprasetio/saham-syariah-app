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
import feedparser
import re

# --- IMPORT MACHINE LEARNING ---
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
# --- 10. FITUR DIVIDEND HUNTER DENGAN HISTORICAL CHART (BULK SCANNER) ---
def show_dividend_hunter(stock_list, category_name, market_choice):
    st.header(f"📅 Dividend Hunter ({category_name})")

    with st.expander("📖 Panduan Wajib: Hindari Dividend Trap! (Klik di sini)"):
        st.markdown("""
        **Aturan Emas Berburu Dividen:**
        1. 🟢 **Beli di Titik Terendah (Accumulation Window):** Jangan beli saham seminggu sebelum jadwal dividen saat harga sedang di pucuk! Gunakan grafik di bawah untuk mencari titik harga terendah (Support).
        2. 🟢 **Cum-Date (Cumulative Date):** Hari TERAKHIR Anda wajib membeli/memiliki saham agar nama Anda tercatat.
        3. 🔴 **Ex-Date (Expired Date):** Hari di mana hak dividen **hangus** dan harga saham biasanya **DIBANTING TURUN (Dividend Trap)**.
        """)

    if user_role == 'free':
        st.warning("🔒 **Fitur Eksklusif VIP/Pro Terkunci**")
        st.info("Upgrade ke VIP/Pro untuk membuka *scanner* dividen, mencari saham dengan bunga di atas deposito, dan mengakses grafik histori harga untuk membeli di titik terendah!")
        
        st.markdown("**Preview Fitur (Data Ilustrasi):**")
        dummy_data = pd.DataFrame({
            "Kode": ["PTBA", "ITMG", "ADRO", "🔒", "🔒"],
            "Harga": ["Rp 2,800", "Rp 26,000", "Rp 2,700", "🔒 VIP", "🔒 VIP"],
            "Support Terendah": ["Rp 2,300", "Rp 23,000", "Rp 2,100", "🔒 VIP", "🔒 VIP"],
            "Yield (Bunga)": ["15.2%", "12.5%", "10.1%", "🔒 VIP", "🔒 VIP"],
            "Ex-Date": ["Segera Datang", "Segera Datang", "Segera Datang", "🔒 VIP", "🔒 VIP"]
        })
        st.dataframe(dummy_data, hide_index=True, use_container_width=True)
        return

    if st.button("Pindai Kalender Dividen Massal 🔍"):
        progress = st.progress(0); status = st.empty(); results = []
        
        # Penyesuaian Ticker untuk Wall Street / Indonesia
        tickers = [f"{s}.JK" if "Indonesia" in market_choice else s for s in stock_list]
        is_us = "US" in market_choice

        for i, t in enumerate(tickers):
            status.text(f"Memeriksa data dividen: {t} ...")
            progress.progress((i+1)/len(tickers))
            try:
                info = yf.Ticker(t).info
                div_rate = info.get('dividendRate', 0)
                price = info.get('previousClose', 1)
                div_yield_raw = info.get('dividendYield', 0)
                ex_date_ts = info.get('exDividendDate', None)
                low_52w = info.get('fiftyTwoWeekLow', 0)

                if pd.notna(div_rate) and div_rate > 0 and pd.notna(price) and price > 0:
                    calculated_yield = (div_rate / price) * 100
                elif pd.notna(div_yield_raw) and div_yield_raw > 0:
                    calculated_yield = (div_yield_raw * 100) if div_yield_raw < 1 else div_yield_raw
                else: calculated_yield = 0

                if calculated_yield > 0 and calculated_yield <= 40:
                    ex_date_str = "Belum Diumumkan"
                    if ex_date_ts: ex_date_str = datetime.utcfromtimestamp(ex_date_ts).strftime('%Y-%m-%d')
                    
                    kode_bersih = t.replace(".JK", "")
                    results.append({
                        "Kode": kode_bersih, "Harga": price, "Support 1Y": low_52w,
                        "Yield (%)": round(calculated_yield, 2), "Ex-Date": ex_date_str
                    })
            except: continue

        progress.empty(); status.empty()

        if results:
            df_div = pd.DataFrame(results).sort_values(by="Yield (%)", ascending=False)
            st.session_state['div_results'] = df_div
            st.success(f"✅ Selesai! Menemukan {len(results)} saham dengan data dividen valid.")
        else:
            st.info("Belum ada data dividen yang masuk akal / tercatat untuk kategori ini hari ini.")
            st.session_state['div_results'] = None

    if 'div_results' in st.session_state and st.session_state['div_results'] is not None:
        df_div = st.session_state['div_results']
        is_us = "US" in market_choice
        
        # Formatting dinamis Rupiah / USD
        if is_us:
            df_display = df_div.copy()
            df_display['Harga'] = df_display['Harga'].apply(lambda x: f"$ {x:.2f}")
            df_display['Support 1Y'] = df_display['Support 1Y'].apply(lambda x: f"$ {x:.2f}")
            df_display['Yield (%)'] = df_display['Yield (%)'].apply(lambda x: f"{x:.2f} %")
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_div, use_container_width=True, hide_index=True,
                column_config={
                    "Kode": st.column_config.TextColumn(width="small"),
                    "Harga": st.column_config.NumberColumn(format="Rp %d"),
                    "Support 1Y": st.column_config.NumberColumn(format="Rp %d"),
                    "Yield (%)": st.column_config.NumberColumn(format="%.2f %%"),
                    "Ex-Date": st.column_config.TextColumn(width="medium")
                })

        st.divider()
        st.subheader("📉 Analisis Titik Beli Terendah (Historical Chart)")
        st.caption("Gunakan grafik ini untuk melihat jarak harga saat ini dengan jurang dasar (Support) setahun terakhir.")

        selected_div_stock = st.selectbox("Pilih saham dari daftar di atas untuk dianalisis:", df_div['Kode'].tolist())

        if selected_div_stock:
            with st.spinner("Menggambar grafik..."):
                symbol_chart = f"{selected_div_stock}.JK" if "Indonesia" in market_choice else selected_div_stock
                df_hist = yf.download(symbol_chart, period="1y", auto_adjust=True, progress=False)
                
                if not df_hist.empty:
                    df_hist = fix_dataframe(df_hist)
                    current_price = df_hist['Close'].iloc[-1]
                    lowest_price = df_hist['Low'].min()

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['Close'], mode='lines', name='Harga', line=dict(color='#2E86C1', width=2)))
                    
                    # Garis Support
                    mata_uang = "$" if is_us else "Rp"
                    label_support = f"Support ({mata_uang} {lowest_price:.2f})" if is_us else f"Support 1Y (Rp {int(lowest_price):,})"
                    fig.add_hline(y=lowest_price, line_dash="dash", line_color="green", annotation_text=label_support, annotation_position="bottom right", annotation_font_color="green")

                    # Perbaikan Layout agar responsif di HP
                    fig.update_layout(title=f"Pergerakan Harga {selected_div_stock} (1 Tahun Terakhir)", height=400, margin=dict(l=10, r=10, t=50, b=10), yaxis_title="Harga", xaxis_rangeslider_visible=False, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)

                    jarak_ke_dasar = ((current_price - lowest_price) / lowest_price) * 100
                    
                    # Logika Jarak
                    harga_str = f"$ {current_price:.2f}" if is_us else f"Rp {int(current_price):,}"
                    if jarak_ke_dasar < 10: st.success(f"🔥 **Sangat Menarik!** Harga saat ini ({harga_str}) sangat dekat dengan titik dasar setahun terakhir. Risiko *Dividend Trap* rendah.")
                    elif jarak_ke_dasar > 40: st.error(f"⚠️ **Hati-Hati!** Harga saat ini sudah terbang +{jarak_ke_dasar:.1f}% dari titik terbawahnya. Waspada bantingan harga (Markdown) setelah Ex-Date.")
                    else: st.warning(f"⚖️ **Netral.** Harga berada di area tengah. Lakukan akumulasi bertahap.")


# --- 11. FITUR SCREENER ---
def run_screener(use_idx_data, stock_list, category_name, market_choice):
    st.header(f"🔍 Smart Money Screener ({category_name})")

    # KAMUS ASLI DENGAN FITUR QUANT & AI
    with st.expander("📖 Kamus Lengkap: Membaca Hasil Screener AI (Klik di sini)"):
        st.info("💡 **Tips:** Kombinasi Katalis yang banyak menandakan probabilitas kenaikan yang lebih tinggi.")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **⚡ Membaca Power Asing (% Dominasi):**
            * **< 5% (Lemah)** : Digerakkan bandar lokal.
            * **5% - 15% (Sedang)** : Mulai ada ketertarikan Asing.
            * **> 15% (Kuat)** : Asing bertindak sebagai *Market Maker*.

            **📊 Status Rekomendasi:**
            * 💎 **STRONG BUY** : Saham dalam kondisi Sempurna.
            * ✅ **BUY** : Saham mulai menunjukkan pantulan.
            * **WAIT** : Saham berisiko tinggi. Lebih baik hindari.
            """)
        with c2:
            st.markdown("""
            **🔖 Sinyal Quant & AI (NEW!):**
            * 🤖 **AI Bullish** : Historis (KNN) menunjukkan peluang naik tinggi.
            * 🔄 **Rebound Sektor** : Saham "salah harga" bersiap mantul.
            * 🔥 **Top Momentum** : Tren kenaikan terkuat 6 bulan terakhir.
            * 💰 **Undervalued** : Fundamental super murah.
            * 🚀 **Breakout DC** : Menembus harga tertinggi Donchian Channel.
            
            **🔖 Katalis Teknikal:**
            * 🔥 **MA** : Uptrend jangka panjang.
            * 🌟 **IHSG** : Return bulanan lebih tinggi daripada pasar.
            * 🐳 **CMF** : Deteksi arus uang raksasa.
            * 💎 **RSI** : Harga sedang diskon besar (Oversold).
            """)

    is_us_market = "US" in market_choice

    if st.button("MULAI SCANNING"):
        # JALUR 1: BACA INSTAN DARI SUPABASE (Lapis 1 / Wall Street)
        if (category_name == "Lapis 1 (JII30)" and use_idx_data) or is_us_market:
            with st.spinner(f"Memindai database {active_category_name}..."):
                try:
                    table_name = 'us_daily_data' if is_us_market else 'jii30_daily_data'
                    res = supabase.table(table_name).select('*').execute()

                    if res.data:
                        df_res = pd.DataFrame(res.data)

                        if 'fetch_date' in df_res.columns:
                            latest_date = df_res['fetch_date'].max()
                            df_res = df_res[df_res['fetch_date'] == latest_date]
                            update_text = latest_date
                        else:
                            update_text = "Hari Ini"

                        if 'kode' in df_res.columns and len(df_res) == 1 and df_res['kode'].iloc[0] == 'CASH':
                            st.error(f"**MODE PROTEKSI MODAL AKTIF (Update: {update_text})**")
                            st.warning("🛡️ **CASH IS KING!** " + df_res['katalis'].iloc[0])
                        else:
                            st.success(f"✅ Selesai! Ditemukan {len(df_res)} Saham unggulan.")
                            st.caption(f"📅 **Terakhir Diupdate (Oleh Server AI):** {update_text}")

                            if is_us_market:
                                df_res = df_res[['kode', 'harga', 'tp', 'sl', 'fase', 'status', 'katalis']]
                                df_res.columns = ['Kode', 'Harga', 'TP', 'SL', 'Fase', 'Status', 'Katalis']
                                df_res['Harga'] = df_res['Harga'].apply(lambda x: f"$ {x:.2f}")
                                df_res['TP'] = df_res['TP'].apply(lambda x: f"$ {x:.2f}")
                                df_res['SL'] = df_res['SL'].apply(lambda x: f"$ {x:.2f}")
                                st.dataframe(df_res, use_container_width=True, hide_index=True)
                            else:
                                if user_role == 'free':
                                    df_res['power_asing'] = None; df_res['modal_asing'] = None
                                df_res = df_res[['kode', 'harga', 'tp', 'sl', 'fase', 'power_asing', 'modal_asing', 'status', 'katalis']]
                                df_res.columns = ['Kode', 'Harga', 'TP', 'SL', 'Fase', 'Power Asing', 'Modal Asing', 'Status', 'Katalis']
                                
                                col_config = {
                                    "Kode": st.column_config.TextColumn(width="small"),
                                    "Harga": st.column_config.NumberColumn(format="Rp %d"),
                                    "TP": st.column_config.NumberColumn(format="Rp %d"),
                                    "SL": st.column_config.NumberColumn(format="Rp %d"),
                                }
                                if user_role == 'free':
                                    col_config["Power Asing"] = st.column_config.TextColumn(default="🔒 VIP")
                                    col_config["Modal Asing"] = st.column_config.TextColumn(default="🔒 VIP")
                                else:
                                    col_config["Power Asing"] = st.column_config.NumberColumn(format="%.1f %%")
                                    col_config["Modal Asing"] = st.column_config.NumberColumn(format="Rp %d")

                                st.dataframe(df_res.fillna("🔒 VIP"), use_container_width=True, hide_index=True, column_config=col_config)
                except Exception as e:
                    st.error(f"Gagal memuat database: {e}")

        # JALUR 2: SCANNING LIVE (Data Standar / Lapis 2)
        else:
            progress = st.progress(0); status = st.empty(); results = []
            tickers = [f"{s}.JK" for s in stock_list]

            status.text("Mengambil Data IHSG...")
            ihsg_df = get_ihsg_data()
            price_data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False, threads=True)

            for i, t in enumerate(tickers):
                status.text(f"Menganalisa Teknikal: {t} ...")
                progress.progress((i+1)/len(tickers))
                try:
                    df = price_data[t].copy(); df = fix_dataframe(df); df = df[df['Volume'] > 0]
                    if df.empty or len(df) < 50: continue
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

                    # PENGETATAN LOGIKA BUY (Skor min. 3.0 meski Accumulation)
                    rec = "WAIT"
                    if total_score >= 6 or "BULLISH DIV" in divergence or "🔥 MA" in reasons: rec = "💎 STRONG BUY"
                    elif total_score >= 4 or (total_score >= 3.0 and "Accumulation" in wyckoff_phase): rec = "✅ BUY"
                    if total_score < 3.0 and "Accumulation" not in wyckoff_phase: continue

                    results.append({
                        "Kode": t.replace(".JK", ""), "Harga": int(close), "TP": int(target_profit), "SL": int(stop_loss),
                        "Fase": wyckoff_phase.split(" ")[1] if len(wyckoff_phase.split(" ")) > 1 else wyckoff_phase,
                        "Power Asing": 0.0, "Modal Asing": 0, "Status": rec, "Katalis": ", ".join(reasons) if reasons else "-"
                    })
                except: continue

            progress.empty(); status.empty()
            if results:
                df_res = pd.DataFrame(results)
                st.success(f"Selesai! {len(results)} Saham Ditemukan.")
                st.dataframe(df_res, use_container_width=True, hide_index=True)
            else: st.warning("Tidak ada saham yang lolos kriteria teknikal hari ini.")
# --- 12. FITUR CHART DETAIL & LIVE AI PREDICTOR ---
def show_chart(use_idx_data, market_choice):
    st.header("📊 Deep Analysis, Quant & AI Predictor")

    with st.expander("📖 Panduan Membaca Fase, AI, & Grafik (Klik di sini)"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **Fase Bandar (Wyckoff):**
            * 🟢 **Accumulation:** Harga mendatar di bawah. Waktunya cicil beli.
            * 🔵 **Markup:** Harga terbang. Uptrend kuat.
            * 🔴 **Distribution:** Harga tertahan di pucuk. Bandar jualan.
            * 🟠 **Markdown:** Bandar keluar, harga jatuh.
            """)
        with c2:
            st.markdown("""
            **🤖 Live AI Predictor (KNN):**
            * 🔥 **> 70% (Bullish):** Peluang naik sangat tinggi.
            * ⚖️ **50% - 69% (Netral):** Pergerakan arah belum pasti.
            * ❄️ **< 50% (Bearish):** Peluang naik rendah.

            **🎯 Keterangan Grafik:**
            * **Garis Biru/Merah/Hijau/Ungu (MA):** Penunjuk arah tren harga.
            * **🟩 / 🟥 Lorong Donchian (Area Abu-abu):** Sabuk volatilitas. Jika harga menembus batas putus-putus **Hijau (Atas)** = Sinyal **BREAKOUT** kuat! Jika tembus Merah (Bawah) = Longsor.
            """)
    st.divider()

    with st.form(key='chart_search_form'):
        c_input, c_btn = st.columns([4, 1])
        with c_input: ticker = st.text_input("🔍 Masukkan Kode Saham (Contoh: BBCA / AAPL):", "").upper()
        with c_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_search = st.form_submit_button("Cari Saham 🔍")

    if submit_search and ticker:
        # Tambahkan .JK HANYA jika pasar Indonesia
        symbol = f"{ticker}.JK" if "Indonesia" in market_choice and not ticker.endswith(".JK") else ticker
        ticker_only = ticker.replace(".JK", "")

        try: supabase.table('audit_logs').insert({"user_email": user_email, "action": "SEARCH_CHART", "details": f"Mencari chart: {ticker_only}"}).execute()
        except: pass

        benchmark = "^JKSE" if "Indonesia" in market_choice else "^GSPC"
        ihsg_df = get_ihsg_data(benchmark)

        with st.spinner(f"Menganalisis {ticker_only}..."):
            df = yf.download(symbol, period="2y", auto_adjust=True, progress=False)
            if df.empty:
                st.error("❌ Saham tidak ditemukan! Pastikan kode benar.")
                return

            df = fix_dataframe(df)
            df = df[df['Volume'] > 0]
            df = calculate_metrics(df, ihsg_df)
            fund = get_fundamental_info(symbol)

            # --- MESIN KECERDASAN BUATAN (LIVE KNN PREDICTOR) ---
            prob_up = 0.5
            try:
                df['Target_Besok'] = (df['Close'].shift(-1) > df['Close']).astype(int)
                ml_df = df[['Rsi', 'CMF', 'Ret_1', 'Target_Besok']].dropna()

                if len(ml_df) > 100:
                    X = ml_df[['Rsi', 'CMF', 'Ret_1']]
                    y = ml_df['Target_Besok']
                    scaler = StandardScaler()
                    X_scaled = scaler.fit_transform(X)
                    knn = KNeighborsClassifier(n_neighbors=5)
                    knn.fit(X_scaled, y)

                    today_features = pd.DataFrame({'Rsi': [df['Rsi'].iloc[-1]], 'CMF': [df['CMF'].iloc[-1]], 'Ret_1': [df['Ret_1'].iloc[-1]]})
                    today_scaled = scaler.transform(today_features)
                    prob_up = knn.predict_proba(today_scaled)[0][1]
            except Exception as e: pass

            s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
            wyckoff_phase, divergence = advanced_analysis(df)
            total_score = s_tech + s_fund + s_bandar + s_candle

            if prob_up >= 0.7:
                total_score += 2.0
                reasons.append(f"🤖 AI Bullish ({int(prob_up*100)}%)")

            # LOGIKA STATUS REKOMENDASI ORISINAL
            rec_status = "WAIT (Hindari / Pantau Saja)"
            if total_score >= 6.5 or "BULLISH DIV" in divergence or "🔥 MA" in reasons:
                rec_status = "💎 STRONG BUY"
            elif total_score >= 4.5 or "Accumulation" in wyckoff_phase:
                rec_status = "✅ BUY"

            st.info(f"💡 **Kesimpulan Sistem:** Saat ini saham **{ticker_only}** berada dalam status **{rec_status}**")
            st.divider()

            is_us = "US" in market_choice
            idx_date = get_idx_target_date(df)
            cache_key = f"{ticker_only}_{idx_date}"
            net_foreign, avg_buy_price, fetch_time = None, 0, None

            if use_idx_data and not is_us:
                if check_and_deduct_quota(cache_key):
                    net_foreign, avg_buy_price, fetch_time = fetch_idx_foreign_flow(ticker_only, idx_date)
                    if fetch_time: api_registry.add(cache_key)
                else: st.warning("⚠️ Kuota Harian API Anda Habis! Menggunakan Data Standar.")

            close, volume, atr = last['Close'], last['Volume'], last.get('ATR', 0)
            daily_turnover = close * volume
            stop_loss = close - (1.5 * atr) if atr > 0 else close
            target_profit = close + (3.0 * atr) if atr > 0 else close

            c1, c2, c3, c4 = st.columns(4)

            fase_color = "normal"
            fase_text = f"-{wyckoff_phase}" if "Markdown" in wyckoff_phase or "Distribution" in wyckoff_phase else wyckoff_phase
            c1.metric("Harga Saat Ini & Fase", format_currency(close, is_us), fase_text, delta_color=fase_color)

            tp_pct = ((target_profit - close) / close) * 100 if close > 0 else 0
            sl_pct = ((close - stop_loss) / close) * 100 if close > 0 else 0
            c2.metric(f"Target Profit (+{tp_pct:.1f}%)", format_currency(target_profit, is_us), f"Batas Rugi: {format_currency(stop_loss, is_us)} (-{sl_pct:.1f}%)", delta_color="off")

            if is_us:
                c3.metric("Data Bandar (Asing)", "Tidak Tersedia", "Sistem Dark Pools (US)", delta_color="off")
            elif net_foreign is not None and (net_foreign != 0 or avg_buy_price != 0):
                power_pct = (abs(net_foreign) / daily_turnover) * 100 if daily_turnover > 0 else 0
                
                # CAPPING: Tangkap anomali Pasar Nego atau Delay YF
                if power_pct > 100:
                    power_display = ">100% (Ada Block/Nego)"
                else:
                    power_display = f"{power_pct:.1f}%"
                    
                c3.metric(f"Asing ({'🟢 AKUM' if net_foreign > 0 else '🔴 DISTRIB'})", format_rupiah(net_foreign), f"Dominasi: {power_display} | Modal: Rp {int(avg_buy_price):,}", delta_color="normal" if net_foreign > 0 else "inverse")
            elif net_foreign == 0 and avg_buy_price == 0 and use_idx_data:
                c3.metric("Data Bandar (Asing)", "Gagal Akses API", "Server IDX Sibuk / Timeout", delta_color="off")
            else:
                c3.metric("Data Bandar (Asing)", "Tidak Tersedia", "Mode Standar / Kuota Habis", delta_color="off")

            if prob_up >= 0.7: ai_status, ai_color = "🔥 Sinyal Bullish", "normal"
            elif prob_up < 0.5: ai_status, ai_color = "-❄️ Sinyal Bearish", "normal"
            else: ai_status, ai_color = "⚖️ Netral", "off"

            c4.metric(f"🤖 AI Predictor (Besok)", f"{int(prob_up*100)}% NAIK", ai_status, delta_color=ai_color)

            # VISUALISASI 3 LAPIS GRAFIK (HARGA, VOLUME, CMF)
            st.subheader(f"Visualisasi Grafik & Quant Radar {ticker_only}")
            df_plot = df.tail(100)

            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.08, subplot_titles=("1. Harga, MA, & Donchian", "2. Volume Transaksi", "3. Akumulasi CMF (Bandar)"))

            fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name="Harga"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA20'], line=dict(color='orange'), name="SMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA50'], line=dict(color='blue'), name="SMA 50"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA100'], line=dict(color='yellow'), name="SMA 100"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA200'], line=dict(color='purple'), name="EMA 200"), row=1, col=1)

            # --- SINKRONISASI WARNA DONCHIAN CHANNELS ---
            if 'DCU_20_20' in df_plot.columns and 'DCL_20_20' in df_plot.columns:
                # Batas Atas (Hijau)
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['DCU_20_20'], line=dict(color='rgba(0,255,0,0.8)', width=1.5, dash='dot'), name='Breakout Atas (DC)'), row=1, col=1)
                # Batas Bawah (Merah) dengan area isi abu-abu
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['DCL_20_20'], line=dict(color='rgba(255,0,0,0.8)', width=1.5, dash='dot'), name='Support Bawah (DC)', fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)

            if atr > 0:
                fig.add_hline(y=target_profit, line_dash="dash", line_color="green", row=1, col=1)
                fig.add_hline(y=stop_loss, line_dash="dash", line_color="red", row=1, col=1)
            if not is_us and net_foreign is not None and avg_buy_price > 0:
                fig.add_hline(y=avg_buy_price, line_dash="dot", line_color="blue", row=1, col=1)

            colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df_plot.iterrows()]
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], marker_color=colors_vol, name="Volume"), row=2, col=1)

            cmf_colors = ['green' if v >= 0 else 'red' for v in df_plot['CMF']]
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['CMF'], marker_color=cmf_colors, name="CMF"), row=3, col=1)

            # SETTING MARGIN 0 AGAR PENUH DI LAYAR HP
            fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=0, r=0, t=40, b=0), template="plotly_dark")
            # --- MENGHILANGKAN CELAH HARI LIBUR ---
            fig.update_xaxes(
                rangebreaks=[
                    dict(bounds=["sat", "mon"]) # Melompati hari Sabtu hingga Senin (Pagi)
                ]
            )
            st.plotly_chart(fig, use_container_width=True)

# --- 13. FITUR ADMIN DASHBOARD ---
def show_admin_dashboard():
    st.header("👑 Admin Dashboard & Audit Logs")
    st.markdown("Pusat kendali intelijen dan analitik pengguna. Data ditarik secara *real-time* dari server.")
    st.divider()

    tab1, tab2 = st.tabs(["📜 Log Persetujuan ToS", "🔍 Log Pencarian Saham"])

    with tab1:
        if st.button("Muat Data Persetujuan ToS", type="primary"):
            with st.spinner("Mengambil log..."):
                try:
                    res = supabase.table('audit_logs').select('*').eq('action', 'LOGIN_TOS_ACCEPTED').order('created_at', desc=True).limit(100).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['Waktu (UTC)'] = df['created_at'].str.slice(0, 19).str.replace('T', ' ')
                        st.dataframe(df[['Waktu (UTC)', 'user_email', 'details']], use_container_width=True, hide_index=True)
                    else: st.info("Belum ada data.")
                except: st.error("Gagal menarik data.")

    with tab2:
        if st.button("Muat Data Pencarian Saham", type="primary"):
            with st.spinner("Mengambil log..."):
                try:
                    res = supabase.table('audit_logs').select('*').eq('action', 'SEARCH_CHART').order('created_at', desc=True).limit(100).execute()
                    if res.data:
                        df = pd.DataFrame(res.data)
                        df['Waktu (UTC)'] = df['created_at'].str.slice(0, 19).str.replace('T', ' ')
                        st.dataframe(df[['Waktu (UTC)', 'user_email', 'details']], use_container_width=True, hide_index=True)
                    else: st.info("Belum ada data.")
                except: st.error("Gagal menarik data.")
                
# --- 14. PUSAT EDUKASI & STRATEGI TRADING (ORISINAL) ---
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

# --- 14.5 FITUR BARU: MESIN BACKTESTING (UJI SEJARAH STRATEGI) ---
def show_backtesting(market_choice):
    st.header("🧪 Mesin Backtesting (Uji Strategi AI)")
    st.markdown("Simulasikan performa strategi *Quant* jika Anda disiplin menerapkannya selama 3 tahun terakhir tanpa melibatkan emosi.")

    # Input Parameter
    with st.form(key='backtest_form'):
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1: 
            ticker = st.text_input("🔍 Kode Saham:", "BBCA").upper()
        with col2: 
            modal_awal = st.number_input("💰 Modal Awal (Rp/USD):", min_value=1000, value=10000000, step=1000000)
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_bt = st.form_submit_button("🚀 Mulai Simulasi", use_container_width=True)

    if submit_bt and ticker:
        with st.spinner("Mesin waktu berjalan... Menghitung ribuan data historis..."):
            is_us = "US" in market_choice
            symbol = f"{ticker}.JK" if not is_us and not ticker.endswith(".JK") else ticker
            ticker_only = ticker.replace(".JK", "")

            try:
                # Menarik data 3 tahun terakhir
                df = yf.download(symbol, period="3y", auto_adjust=True, progress=False)
                if df.empty:
                    st.error("❌ Data saham tidak ditemukan.")
                    return
                
                df = fix_dataframe(df)
                df = df[df['Volume'] > 0]
                
                # --- STRATEGI ALGORITMA (AI Trend Follower) ---
                # Aturan Beli: Harga menembus MA 50 ke atas (Uptrend Reversal)
                # Aturan Jual: Harga jatuh ke bawah MA 20 (Momentum Hilang)
                df['SMA20'] = df.ta.sma(length=20)
                df['SMA50'] = df.ta.sma(length=50)
                
                # Simulasi Keputusan (Vectorized - Super Cepat)
                df['Signal'] = 0
                df.loc[df['Close'] > df['SMA50'], 'Signal'] = 1  # Mode Beli/Hold
                df.loc[df['Close'] < df['SMA20'], 'Signal'] = 0  # Mode Jual/Cash
                
                df['Position'] = df['Signal'].ffill().fillna(0)
                
                # Hitung Keuntungan Harian
                df['Daily_Return'] = df['Close'].pct_change()
                df['Strategy_Return'] = df['Position'].shift(1) * df['Daily_Return']
                
                # Pertumbuhan Modal Berbunga (Compound Interest)
                df['Equity'] = modal_awal * (1 + df['Strategy_Return']).cumprod()
                df['Buy_Hold_Equity'] = modal_awal * (1 + df['Daily_Return']).cumprod()
                
                # --- KALKULASI METRIK PERFORMA ---
                df = df.dropna()
                modal_akhir = df['Equity'].iloc[-1]
                bnh_akhir = df['Buy_Hold_Equity'].iloc[-1]
                
                total_return = ((modal_akhir - modal_awal) / modal_awal) * 100
                bnh_return = ((bnh_akhir - modal_awal) / modal_awal) * 100
                
                # Menghitung Risiko (Max Drawdown / Penurunan Terdalam)
                rolling_max = df['Equity'].cummax()
                drawdown = (df['Equity'] - rolling_max) / rolling_max
                max_drawdown = drawdown.min() * 100

                # --- TAMPILAN DASHBOARD HASIL ---
                st.success(f"✅ Simulasi Selesai! Menguji {len(df)} hari perdagangan pada saham {ticker_only}.")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Modal Akhir (Strategi AI)", format_currency(modal_akhir, is_us), f"{total_return:.2f}% Profit")
                c2.metric("Jika Hanya Beli & Diam (B&H)", format_currency(bnh_akhir, is_us), f"{bnh_return:.2f}% Profit", delta_color="off")
                c3.metric("Risiko Terdalam (Max Drawdown)", f"{max_drawdown:.2f}%", "Penurunan uang dari puncak ke dasar", delta_color="inverse")

                if total_return > bnh_return:
                    st.info("🏆 **Kesimpulan:** Strategi *Quant AI* terbukti **lebih unggul** dan lebih aman daripada sekadar menahan saham membabi buta (*Buy and Hold*).")
                else:
                    st.warning("⚖️ **Kesimpulan:** Untuk saham ini, strategi *Buy and Hold* jangka panjang menghasilkan profit lebih besar, namun strategi *Quant AI* membantu melindungi Anda dari kerugian (Max Drawdown) yang ekstrem.")

                # --- GRAFIK PERTUMBUHAN MODAL (EQUITY CURVE) ---
                st.subheader("📈 Grafik Pertumbuhan Modal (Equity Curve)")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df.index, y=df['Equity'], mode='lines', name='Strategi Quant AI', line=dict(color='#00FF00', width=3)))
                fig.add_trace(go.Scatter(x=df.index, y=df['Buy_Hold_Equity'], mode='lines', name='Beli & Tahan Biasa', line=dict(color='#555555', width=2, dash='dot')))
                
                fig.update_layout(height=400, template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0), yaxis_title="Saldo Modal", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig, use_container_width=True)

            except Exception as e:
                st.error(f"Gagal melakukan simulasi: Terjadi kesalahan data ({e}).")
# --- 14.6 FITUR BARU: RADAR SENTIMEN BERITA LOKAL  ---

@st.cache_data(ttl=1800, show_spinner=False)
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_local_news(ticker):
    # UPGRADE: Menggunakan Google News RSS Search khusus regional Indonesia
    # Ini akan menyapu SELURUH media lokal secara spesifik mencari kode saham user.
    query = f"saham+{ticker}"
    url = f"https://news.google.com/rss/search?q={query}&hl=id&gl=ID&ceid=ID:id"
    
    news_list = []
    try:
        feed = feedparser.parse(url)
        
        # Ambil maksimal 10 berita paling relevan/terbaru
        for entry in feed.entries[:10]:
            raw_title = entry.title
            link = entry.link
            date = entry.get('published', '')
            
            # Google News RSS menggabungkan Judul dan Publisher (Contoh: "Laba BUMI Naik - CNBC Indonesia")
            # Kita pisahkan agar tampilannya tetap rapi di aplikasi Anda
            if " - " in raw_title:
                clean_title, publisher = raw_title.rsplit(" - ", 1)
            else:
                clean_title = raw_title
                publisher = "Media Finansial"
                
            news_list.append({
                "title": clean_title, 
                "link": link, 
                "publisher": publisher, 
                "date": date
            })
    except Exception as e:
        pass
        
    return news_list

def analyze_indonesian_sentiment(text):
    # Kamus NLP sederhana khusus bahasa gaul saham Indonesia
    kata_positif = ['naik', 'cuan', 'laba', 'untung', 'dividen', 'terbang', 'akumulasi', 'positif', 'rekor', 'melonjak', 'melesat', 'tumbuh', 'meroket', 'bullish', 'borong', 'lonjakan']
    kata_negatif = ['turun', 'rugi', 'anjlok', 'arb', 'distribusi', 'negatif', 'utang', 'suspensi', 'jeblok', 'merosot', 'hancur', 'jatuh', 'bearish', 'gagal', 'koreksi', 'dilepas', 'jual']
    
    text_lower = text.lower()
    score = 0
    
    # Deteksi sentimen
    for kata in kata_positif:
        if re.search(r'\b' + kata + r'\b', text_lower): score += 1
    for kata in kata_negatif:
        if re.search(r'\b' + kata + r'\b', text_lower): score -= 1
        
    if score > 0: return "🟢 POSITIF", score
    elif score < 0: return "🔴 NEGATIF", score
    else: return "⚪ NETRAL", score

def show_news_sentiment(market_choice):
    st.header("📰 Radar Sentimen Berita Lokal")
    st.markdown("Mesin pemindai yang memantau berita dari portal finansial top Indonesia untuk mencari katalis tersembunyi.")

    # Matikan fitur jika user sedang di Mode Wall Street
    if "US" in market_choice:
        st.warning("⚠️ Radar Berita Lokal dinonaktifkan di mode Wall Street. Silakan pindah ke bursa Indonesia.")
        return

    with st.form(key='news_form'):
        col1, col2 = st.columns([3, 1])
        with col1:
            ticker = st.text_input("🔍 Kode Saham (Contoh: WIKA / BBCA / GOTO):", "").upper()
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_news = st.form_submit_button("Radar Berita 🔍", use_container_width=True)

    if submit_news and ticker:
        with st.spinner(f"📡 Radar sedang menyapu portal berita lokal untuk saham {ticker}..."):
            ticker_only = ticker.replace(".JK", "")

            try:
                # Memanggil data dari fungsi penyedot RSS
                berita_lokal = fetch_local_news(ticker_only)

                if not berita_lokal:
                    st.warning(f"⚠️ Radar tidak menemukan berita terbaru yang menyebutkan saham {ticker_only} di CNBC atau Kontan hari ini.")
                    st.info("💡 Tips: Coba gunakan saham berkapitalisasi besar atau saham yang sedang ramai ditransaksikan.")
                    return

                total_score = 0
                news_items = []

                # Analisis satu per satu dengan Kamus Bahasa Indonesia
                for item in berita_lokal:
                    sentiment_label, score = analyze_indonesian_sentiment(item['title'])
                    total_score += score
                    news_items.append({
                        "title": item['title'],
                        "publisher": item['publisher'],
                        "sentiment": sentiment_label,
                        "link": item['link'],
                        "score": score,
                        "date": item['date']
                    })

                avg_score = total_score / len(berita_lokal)
                
                # --- DASHBOARD KESIMPULAN ---
                st.subheader(f"🧠 Kesimpulan Radar Sentimen {ticker_only}")
                c1, c2 = st.columns(2)
                
                if avg_score > 0:
                    status_berita = "🐂 OPTIMIS (Banyak Kabar Baik)"
                    warna = "normal"
                elif avg_score < 0:
                    status_berita = "🐻 PESIMIS (Banyak Kabar Buruk)"
                    warna = "inverse"
                else:
                    status_berita = "⚖️ NETRAL (Minim Sentimen)"
                    warna = "off"
                    
                c1.metric("Kondisi Emosi Media", status_berita, f"Skor Sentimen: {avg_score:.1f}", delta_color=warna)
                c2.info("Sistem secara pintar memindai kata kunci finansial (seperti laba, cuan, rugi, ARB) dari artikel lokal yang baru saja dirilis.")
                
                st.divider()
                
                # --- DAFTAR BERITA YANG DIBACA AI ---
                st.subheader("📑 Arsip Berita yang Terdeteksi")
                for item in news_items:
                    with st.expander(f"{item['sentiment']} | {item['title']}"):
                        st.write(f"**Sumber:** {item['publisher']} | **Waktu Terbit:** {item['date']}")
                        st.markdown(f"[🔗 Baca artikel selengkapnya di sini]({item['link']})")
                        
            except Exception as e:
                st.error(f"Gagal menyapu berita lokal: {e}")

# --- 15. ETALASE FREEMIUM, PENGATURAN SIDEBAR & SMART ROUTING ---
st.sidebar.markdown(f"👤 **Halo, {user_email.split('@')[0]}**")
role_color = "green" if user_role == 'admin' else ("blue" if user_role == 'vip' else "gray")
st.sidebar.markdown(f"Status Akun: <span style='color:{role_color}; font-weight:bold;'>{user_role.upper()}</span>", unsafe_allow_html=True)

try:
    current_db = supabase.table('profiles').select('daily_quota, used_quota').eq('id', user_id).execute().data[0]
    st.sidebar.caption(f"Sisa Kuota API Personal: **{current_db['daily_quota'] - current_db['used_quota']} / {current_db['daily_quota']}**")
except: pass
st.sidebar.divider()

menu_options = ["🔍 Super Screener", "📊 Advanced Chart", "🧪 Mesin Backtesting", "📰 Analisis Sentimen Berita", "📅 Dividend Hunter", "📚 Pusat Edukasi"]
if is_admin:
    menu_options.append("👑 Admin Dashboard")
    
mode = st.sidebar.radio("Pilih Menu:", menu_options)
st.sidebar.divider()

# --- SAKELAR BENUA & LOGIKA SIDEBAR ---
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
    # MODE WALL STREET
    active_stock_list = US_STOCKS
    active_category_name = "US Top Tech"
    if mode == "📊 Advanced Chart" or mode == "🔍 Super Screener":
        st.sidebar.info("ℹ️ Mode Wall Street: Data Bandar/Asing tidak tersedia (Sistem Dark Pools).")

# --- KONTROL ADMIN ---
if is_admin:
    st.sidebar.divider()
    st.sidebar.markdown("**👑 Admin Control**")
    
    # Inisialisasi memori untuk tombol konfirmasi
    if 'confirm_clear_cache' not in st.session_state:
        st.session_state['confirm_clear_cache'] = False

    # Jika tombol belum ditekan, tampilkan tombol biasa
    if not st.session_state['confirm_clear_cache']:
        if st.sidebar.button("🧹 Bersihkan Memori Cache", use_container_width=True):
            st.session_state['confirm_clear_cache'] = True
            st.rerun() # Refresh layar untuk memunculkan konfirmasi
    
    # Jika tombol sudah ditekan, ubah wujudnya menjadi peringatan & konfirmasi
    else:
        st.sidebar.warning("⚠️ **PERHATIAN!** Anda yakin ingin menghapus memori? Aplikasi akan menarik data ulang.")
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("✅ YAKIN", use_container_width=True):
                st.cache_data.clear()
                api_registry.clear()
                st.session_state['confirm_clear_cache'] = False # Kembalikan status tombol
                st.sidebar.success("✅ Memori dibersihkan!")
                time.sleep(1.5) # Beri jeda 1.5 detik agar Anda bisa membaca pesan sukses
                st.rerun() # Kembalikan tampilan ke semula
        with col2:
            if st.button("❌ BATAL", use_container_width=True):
                st.session_state['confirm_clear_cache'] = False # Batalkan
                st.rerun() # Kembalikan tampilan ke semula

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
elif mode == "🧪 Mesin Backtesting":
    show_backtesting(market_choice)
elif mode == "📅 Dividend Hunter":
    show_dividend_hunter(active_stock_list, active_category_name, market_choice)
elif mode == "📚 Pusat Edukasi":
    show_education()
elif mode == "👑 Admin Dashboard" and is_admin:
    show_admin_dashboard()
elif mode == "📰 Analisis Sentimen Berita":
    show_news_sentiment(market_choice)
    
