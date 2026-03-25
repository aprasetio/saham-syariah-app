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
        background-color: #f0f2f6 !important; border: 1px solid #d6d6d6 !important; 
        padding: 15px !important; border-radius: 10px !important; height: 100% !important; 
        white-space: normal !important; word-wrap: break-word !important; overflow-wrap: break-word !important;
    }
    [data-testid="stMetricLabel"] p { 
        color: #31333F !important; font-weight: bold !important; font-size: 0.95rem !important; 
        white-space: normal !important; word-wrap: break-word !important; overflow-wrap: break-word !important;
    }
    [data-testid="stMetricValue"] div { 
        color: #000000 !important; font-size: 1.2rem !important; 
        white-space: normal !important; word-wrap: break-word !important; overflow-wrap: break-word !important;
    }
    [data-testid="stMetricDelta"] div {
        white-space: normal !important; word-wrap: break-word !important; overflow-wrap: break-word !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 7. DAFTAR SAHAM (Lapis 1 & 2) ---
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
    latest_market_date = df.index[-1].date()
    if latest_market_date == wib_time.date() and wib_time.hour < 18:
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

# --- 9. FUNGSI TEKNIKAL ANTI-CRASH ---
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

    if 'Stock_Ret_20' in df.columns and 'IHSG_Ret_20' in df.columns:
        if not pd.isna(curr['Stock_Ret_20']) and curr['Stock_Ret_20'] > curr['IHSG_Ret_20'] and curr['Stock_Ret_20'] > 0:
            score_tech += 1.5; reasons.append("🌟 IHSG")
        
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

# --- 10. FITUR BARU: DIVIDEND HUNTER (KALENDER DIVIDEN) ---
def show_dividend_hunter(stock_list, category_name):
    st.header(f"📅 Dividend Hunter ({category_name})")
    
    with st.expander("📖 Panduan Wajib Dividen: Cum-Date vs Ex-Date (Klik untuk buka)"):
        st.markdown("""
        Jangan sampai salah tanggal! Ini adalah aturan emas berburu dividen:
        * 🟢 **Cum-Date (Cumulative Date):** Hari TERAKHIR Anda wajib membeli/memiliki saham agar nama Anda tercatat sebagai penerima dividen.
        * 🔴 **Ex-Date (Expired Date):** Hari di mana hak dividen sudah **hangus**. Jika Anda baru beli di hari ini, Anda **TIDAK** dapat dividen.
        * 💡 **Strategi Rahasia:** Jika Anda sudah membeli sejak *Cum-Date*, Anda BOLEH langsung menjual saham Anda di pagi hari saat *Ex-Date*. Anda tetap akan menerima uang dividennya!
        """)
        
    # ETALASE UNTUK USER FREE (Freemium Upsell)
    if user_role == 'free':
        st.warning("🔒 **Fitur Eksklusif VIP/Pro Terkunci**")
        st.info("Upgrade ke VIP/Pro untuk membuka *scanner* dividen *real-time*. Temukan saham yang memberikan keuntungan dividen jauh di atas bunga deposito bank, lengkap dengan tanggal Ex-Date-nya!")
        
        st.markdown("**Preview Fitur (Data Ilustrasi):**")
        dummy_data = pd.DataFrame({
            "Kode": ["PTBA", "ITMG", "ADRO", "🔒", "🔒"],
            "Harga": ["Rp 2,800", "Rp 26,000", "Rp 2,700", "🔒 VIP", "🔒 VIP"],
            "Yield (Bunga)": ["15.2%", "12.5%", "10.1%", "🔒 VIP", "🔒 VIP"],
            "Ex-Date": ["Segera Datang", "Segera Datang", "Segera Datang", "🔒 VIP", "🔒 VIP"]
        })
        st.dataframe(dummy_data, hide_index=True, use_container_width=True)
        return

    # LOGIKA UNTUK USER PRO
    if st.button("Pindai Kalender Dividen 🔍"):
        progress = st.progress(0)
        status = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in stock_list]
        
        for i, t in enumerate(tickers):
            status.text(f"Memeriksa data dividen: {t} ...")
            progress.progress((i+1)/len(tickers))
            try:
                info = yf.Ticker(t).info
                
                # --- PERBAIKAN BUG DATA YAHOO FINANCE ---
                div_rate = info.get('dividendRate', 0)     # Total dividen dlm Rupiah
                price = info.get('previousClose', 1)       # Harga penutupan kemarin
                div_yield_raw = info.get('dividendYield', 0) 
                ex_date_ts = info.get('exDividendDate', None)
                
                # Hitung manual (Rupiah / Harga * 100) agar tidak tertipu persentase error YF
                if pd.notna(div_rate) and div_rate > 0 and pd.notna(price) and price > 0:
                    calculated_yield = (div_rate / price) * 100
                elif pd.notna(div_yield_raw) and div_yield_raw > 0:
                    # Jika data rupiah kosong, terpaksa pakai persentase raw YF
                    calculated_yield = (div_yield_raw * 100) if div_yield_raw < 1 else div_yield_raw
                else:
                    calculated_yield = 0
                
                # FILTER LOGIKA: Tidak mungkin ada dividen IHSG > 40%. Jika lebih, itu pasti data sampah.
                if calculated_yield > 0 and calculated_yield <= 40:
                    ex_date_str = "Belum Diumumkan"
                    if ex_date_ts:
                        # Konversi dari Unix Timestamp ke YYYY-MM-DD
                        ex_date_str = datetime.utcfromtimestamp(ex_date_ts).strftime('%Y-%m-%d')
                        
                    results.append({
                        "Kode": t.replace(".JK", ""),
                        "Harga": int(price),
                        "Yield (%)": round(calculated_yield, 2),
                        "Ex-Date": ex_date_str
                    })
            except: continue
        
        progress.empty(); status.empty()
        
        if results:
            df_div = pd.DataFrame(results)
            df_div = df_div.sort_values(by="Yield (%)", ascending=False) 
            st.success(f"✅ Selesai! Menemukan {len(results)} saham dengan data dividen valid.")
            
            st.dataframe(df_div, use_container_width=True, hide_index=True,
                column_config={
                    "Kode": st.column_config.TextColumn(width="small"),
                    "Harga": st.column_config.NumberColumn(format="Rp %d"),
                    "Yield (%)": st.column_config.NumberColumn(format="%.2f %%"),
                    "Ex-Date": st.column_config.TextColumn(width="medium")
                }
            )
        else:
            st.info("Belum ada data dividen yang masuk akal / tercatat untuk kategori ini hari ini.")
# --- 11. FITUR SCREENER ---
def run_screener(use_idx_data, stock_list, category_name):
    st.header(f"🔍 Smart Money Screener ({category_name})")
    
    with st.expander("📖 Panduan Membaca Hasil Screener (Klik di sini)"):
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
            **🔖 Arti Simbol Katalis:**
            * 🔥 **MA** : Uptrend.
            * 🌟 **IHSG** : Return positif dan mengalahkan IHSG.
            * 🐳 **CMF** : Deteksi akumulasi bandar.
            * 💎 **RSI** : Harga diskon (Oversold).
            * 🚀 **EPS** : Laba perusahaan bertumbuh.
            """)

    if st.button("MULAI SCANNING"):
        if category_name == "Lapis 1 (JII30)" and use_idx_data:
            with st.spinner("⚡ Menyedot data dari Server..."):
                res = supabase.table('jii30_daily_data').select('*').execute()
                if res.data:
                    df_res = pd.DataFrame(res.data)
                    if user_role == 'free':
                        df_res['power_asing'] = None; df_res['modal_asing'] = None
                    df_res = df_res[['kode', 'harga', 'tp', 'sl', 'fase', 'power_asing', 'modal_asing', 'status', 'katalis']]
                    df_res.columns = ['Kode', 'Harga', 'TP', 'SL', 'Fase', 'Power Asing', 'Modal Asing', 'Status', 'Katalis']
                    
                    st.success(f"✅ Selesai! Ditemukan {len(df_res)} Saham.")
                    
                    col_config = {
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
                else: st.warning("⚠️ Data server IDX masih kosong.")
        else:
            progress = st.progress(0); status = st.empty(); results = []
            tickers = [f"{s}.JK" for s in stock_list]
            ihsg_df = get_ihsg_data()
            price_data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False, threads=True)
            
            for i, t in enumerate(tickers):
                status.text(f"Menganalisa: {t} ...")
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
                    
                    rec = "WAIT"
                    if total_score >= 6 or "BULLISH DIV" in divergence or "🔥 MA" in reasons: rec = "💎 STRONG BUY"
                    elif total_score >= 4 or "Accumulation" in wyckoff_phase: rec = "✅ BUY"
                    if total_score < 3 and "Accumulation" not in wyckoff_phase: continue
                    
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

# --- 12. FITUR CHART DETAIL ---
def show_chart(use_idx_data):
    st.header("📊 Deep Analysis & Target Tracker")
    
    with st.expander("📖 Panduan Membaca Fase & Grafik (Klik di sini)"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **Fase Bandar (Wyckoff):**
            1. 🟢 **Accumulation:** Harga di bawah. Waktu terbaik cicil beli.
            2. 🔵 **Markup:** Harga terbang uptrend. Tahan untung.
            3. 🔴 **Distribution:** Harga di pucuk. Bandar jualan. Waspada.
            4. 🟠 **Markdown:** Harga jatuh bebas. Hindari.
            """)
        with c2:
            st.markdown("""
            **🎯 Target & Stop Loss:** Jarak otomatis melebar saat saham liar (Sistem ATR).
            **🐳 Garis Biru:** Posisi modal rata-rata Asing (Hanya di Data IDX).
            """)
    st.divider()

    with st.form(key='chart_search_form'):
        c_input, c_btn = st.columns([4, 1])
        with c_input: ticker = st.text_input("Masukkan Kode Saham (Contoh: BBCA, SIDO)", "").upper()
        with c_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_search = st.form_submit_button("Cari Saham 🔍")
            
    if submit_search and ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        ticker_only = ticker.replace(".JK", "")
        
        try: supabase.table('audit_logs').insert({"user_email": user_email, "action": "SEARCH_CHART", "details": f"Mencari chart: {ticker_only}"}).execute()
        except: pass
        
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
        total_score = s_tech + s_fund + s_bandar + s_candle
        
        # BANNER REKOMENDASI
        rec_status = "WAIT (Hindari / Pantau Saja)"
        if total_score >= 6 or "BULLISH DIV" in divergence or "🔥 MA" in reasons: 
            rec_status = "💎 STRONG BUY (Sangat Disarankan)"
        elif total_score >= 4 or "Accumulation" in wyckoff_phase: 
            rec_status = "✅ BUY (Boleh Cicil Beli)"
            
        st.info(f"💡 **Kesimpulan Sistem:** Saat ini saham **{ticker_only}** berada dalam status **{rec_status}**")
        st.divider()
        
        idx_date = get_idx_target_date(df)
        cache_key = f"{ticker_only}_{idx_date}"
        net_foreign, avg_buy_price, fetch_time = None, 0, None
        
        if use_idx_data:
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
        c1.metric("Harga Terakhir & Fase", f"Rp {int(close):,}", fase_text, delta_color=fase_color)
        
        tp_pct = ((target_profit - close) / close) * 100 if close > 0 else 0
        sl_pct = ((close - stop_loss) / close) * 100 if close > 0 else 0
        c2.metric(f"Target Profit (+{tp_pct:.1f}%)", f"Rp {int(target_profit):,}", f"Batas Rugi (SL): Rp {int(stop_loss):,} (-{sl_pct:.1f}%)", delta_color="off")
        
        if net_foreign is not None:
            power_pct = (abs(net_foreign) / daily_turnover) * 100 if daily_turnover > 0 else 0
            c3.metric(f"Asing ({'🟢 AKUM' if net_foreign > 0 else '🔴 DISTRIB'})", format_rupiah(net_foreign), f"Dominasi: {power_pct:.1f}% | Modal: Rp {int(avg_buy_price):,}", delta_color="normal" if net_foreign > 0 else "inverse")
        else:
            c3.metric("Data Bandar (Asing)", "Tidak Tersedia", "Mode Standar / Kuota Habis", delta_color="off") 
        
        is_outperform = "🌟 IHSG" in " ".join(reasons)
        eps_g = fund.get('EPS_Growth') if fund else None
        pasar_text = "🌟 MENGALAHKAN IHSG" if is_outperform else "-📉 UNDERPERFORM"
        c4.metric("Status vs Pasar", pasar_text, f"Laba: +{eps_g*100:.1f}%" if eps_g and eps_g > 0 else "Laba: N/A", delta_color="normal")
        
        st.subheader(f"Visualisasi Grafik {ticker_only}")
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.08, subplot_titles=("1. Pergerakan Harga & Target", "2. Volume Harian", "3. Akumulasi Bandar (CMF)"))
        
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
        
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=60, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- 13. FITUR ADMIN DASHBOARD (EKSKLUSIF) ---
def show_admin_dashboard():
    st.header("👑 Admin Dashboard & Audit Logs")
    st.markdown("Pusat kendali intelijen dan analitik pengguna. Data ditarik secara *real-time* dari server.")
    st.divider()
    
    tab1, tab2 = st.tabs(["📜 Log Persetujuan ToS (Legal)", "🔍 Log Pencarian Saham (Analitik)"])
    
    with tab1:
        st.subheader("Riwayat Login & Persetujuan ToS")
        st.caption("Gunakan data ini sebagai bukti legal bahwa pengguna telah menyetujui Disclaimer Risiko sebelum masuk ke aplikasi.")
        if st.button("Muat Data Persetujuan ToS", type="primary"):
            with st.spinner("Mengambil log dari database..."):
                res = supabase.table('audit_logs').select('*').eq('action', 'LOGIN_TOS_ACCEPTED').order('created_at', desc=True).limit(100).execute()
                if res.data:
                    df = pd.DataFrame(res.data)
                    df['Waktu (UTC)'] = df['created_at'].str.slice(0, 19).str.replace('T', ' ')
                    st.dataframe(df[['Waktu (UTC)', 'user_email', 'details']], use_container_width=True, hide_index=True)
                else:
                    st.info("Belum ada data log persetujuan ToS.")
                    
    with tab2:
        st.subheader("Riwayat Pencarian Saham oleh User")
        st.caption("Pantau saham apa saja yang sedang ramai dicari oleh pengguna Anda untuk riset tren pasar.")
        if st.button("Muat Data Pencarian Saham", type="primary"):
            with st.spinner("Mengambil log dari database..."):
                res = supabase.table('audit_logs').select('*').eq('action', 'SEARCH_CHART').order('created_at', desc=True).limit(100).execute()
                if res.data:
                    df = pd.DataFrame(res.data)
                    df['Waktu (UTC)'] = df['created_at'].str.slice(0, 19).str.replace('T', ' ')
                    st.dataframe(df[['Waktu (UTC)', 'user_email', 'details']], use_container_width=True, hide_index=True)
                else:
                    st.info("Belum ada data log pencarian saham.")


# --- 14. PENGATURAN SIDEBAR & SMART ROUTING (ETALASE FREEMIUM) ---
st.sidebar.markdown(f"👤 **Halo, {user_email.split('@')[0]}**")
st.sidebar.caption(f"Status Akun: **{user_role.upper()}**")

# Cek Sisa Kuota Realtime dari DB
try:
    current_db = supabase.table('profiles').select('daily_quota, used_quota').eq('id', user_id).execute().data[0]
    st.sidebar.caption(f"Sisa Kuota API Personal: **{current_db['daily_quota'] - current_db['used_quota']} / {current_db['daily_quota']}**")
except: pass

st.sidebar.divider()

# Dinamisasi Pilihan Menu Utama
menu_options = ["🔍 Super Screener", "📊 Advanced Chart", "📅 Dividend Hunter"]
if is_admin:
    menu_options.append("👑 Admin Dashboard")
    
mode = st.sidebar.radio("Pilih Menu:", menu_options)
st.sidebar.divider()

# Logika Smart UI Routing & Etalase Upsell
use_idx_data = False
active_stock_list = SHARIA_STOCKS
active_category_name = "Lapis 1 (JII30)"

# 1. LOGIKA SIDEBAR: SUPER SCREENER
if mode == "🔍 Super Screener":
    kategori_saham = st.sidebar.radio("Pilih Kategori Saham:", ["👑 Lapis 1 (JII30)", "🚀 Lapis 2 (Mid-Small Caps)"])
    st.sidebar.divider()
    
    if kategori_saham == "🚀 Lapis 2 (Mid-Small Caps)":
        active_stock_list = SHARIA_MIDCAP_STOCKS
        active_category_name = "Lapis 2"
        st.sidebar.info("✨ Mode Lapis 2 otomatis menggunakan **Data Standar (0 Kuota)** agar aman untuk limit API harian Anda.")
        use_idx_data = False
    else:
        active_stock_list = SHARIA_STOCKS
        active_category_name = "Lapis 1 (JII30)"
        
        # FITUR ETALASE
        data_source = st.sidebar.radio("Pilih Sumber Data:", ["🌐 Data Standar (Gratis)", "🏦 Data IDX (Premium)"]) 
        if "Data IDX" in data_source:
            if user_role == 'free':
                st.sidebar.warning("🔒 **Fitur Terkunci.** Anda menggunakan versi Free. Upgrade ke VIP/Pro untuk membuka visualisasi aliran Modal Asing!")
                use_idx_data = False 
            else:
                use_idx_data = True
        else:
            use_idx_data = False

# 2. LOGIKA SIDEBAR: DIVIDEND HUNTER (DIPISAH AGAR TIDAK MUNCUL OPSI API IDX)
elif mode == "📅 Dividend Hunter":
    kategori_saham = st.sidebar.radio("Pilih Kategori Saham:", ["👑 Lapis 1 (JII30)", "🚀 Lapis 2 (Mid-Small Caps)"])
    st.sidebar.divider()
    
    if kategori_saham == "🚀 Lapis 2 (Mid-Small Caps)":
        active_stock_list = SHARIA_MIDCAP_STOCKS
        active_category_name = "Lapis 2"
    else:
        active_stock_list = SHARIA_STOCKS
        active_category_name = "Lapis 1 (JII30)"
        
    use_idx_data = False # Mutlak false karena hanya pakai Yahoo Finance
    st.sidebar.caption("🌐 Menggunakan Data Standar (Gratis - 0 Kuota)")

# 3. LOGIKA SIDEBAR: ADVANCED CHART
elif mode == "📊 Advanced Chart":
    # FITUR ETALASE DI CHART
    data_source = st.sidebar.radio("Pilih Sumber Data:", ["🌐 Data Standar (Gratis)", "🏦 Data IDX (Premium)"]) 
    if "Data IDX" in data_source:
        if user_role == 'free':
            st.sidebar.warning("🔒 **Fitur Terkunci.** Anda menggunakan versi Free. Upgrade ke VIP/Pro untuk memunculkan Garis Biru pertahanan Bandar Asing di grafik!")
            use_idx_data = False
        else:
            use_idx_data = True
    else:
        use_idx_data = False

if is_admin:
    st.sidebar.divider()
    st.sidebar.markdown("⚙️ **System Control**")
    if st.sidebar.button("🧹 Bersihkan Memori Cache"):
        st.cache_data.clear()
        api_registry.clear()
        st.sidebar.success("✅ Memori dibersihkan!")

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
    run_screener(use_idx_data, active_stock_list, active_category_name)
elif mode == "📊 Advanced Chart": 
    show_chart(use_idx_data)
elif mode == "📅 Dividend Hunter":
    show_dividend_hunter(active_stock_list, active_category_name)
elif mode == "👑 Admin Dashboard":
    show_admin_dashboard()
