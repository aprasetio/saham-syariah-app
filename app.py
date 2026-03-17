import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import numpy as np
import time

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Ultimate Smart Money Analyst", layout="wide", page_icon="🏦")

# --- 2. SISTEM LOGIN AMAN (STREAMLIT SECRETS) ---
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

GOAPI_KEY = st.secrets["GOAPI_KEY"]

# --- 3. CSS FIX ---
st.markdown("""
<style>
    [data-testid="stMetric"] { background-color: #f0f2f6 !important; border: 1px solid #d6d6d6 !important; padding: 15px !important; border-radius: 10px !important; height: 100% !important; }
    [data-testid="stMetricLabel"] p { color: #31333F !important; font-weight: bold !important; font-size: 1rem !important; white-space: normal !important; }
    [data-testid="stMetricValue"] div { color: #000000 !important; font-size: 1.25rem !important; white-space: normal !important; line-height: 1.2 !important; }
    [data-testid="stMetricDelta"] div { font-size: 0.95rem !important; white-space: normal !important; }
</style>
""", unsafe_allow_html=True)

# --- 4. DAFTAR SAHAM (JII 30) ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- 5. HELPER FUNCTIONS ---
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
    if angka >= 1e9: formatted = f"Rp {angka/1e9:.2f} Miliar"
    elif angka >= 1e6: formatted = f"Rp {angka/1e6:.2f} Juta"
    else: formatted = f"Rp {angka:,.0f}"
    return f"-{formatted}" if is_negative else formatted

# --- 6. FUNGSI FETCH GOAPI (FOREIGN FLOW & HARGA MODAL ASING) ---
@st.cache_data(ttl=43200)
def fetch_goapi_foreign_flow(symbol, target_date):
    headers = {
        'accept': 'application/json', 
        'X-API-KEY': GOAPI_KEY,
        'User-Agent': 'Mozilla/5.0'
    }
    net_foreign = 0
    avg_buy_price = 0
    
    try:
        url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
        res_broker = requests.get(url_broker, headers=headers, timeout=10)
        if res_broker.status_code != 200: return None, 0
        
        res_broker_json = res_broker.json()
        total_buy_val = 0
        total_buy_lot = 0
        total_sell_val = 0
        
        if res_broker_json.get('status') == 'success':
            for broker in res_broker_json['data']['results']:
                if broker['side'] == 'BUY':
                    total_buy_val += broker['value']
                    total_buy_lot += broker['lot']
                elif broker['side'] == 'SELL':
                    total_sell_val += broker['value']
                    
            net_foreign = total_buy_val - total_sell_val
            # Hitung Harga Rata-rata Beli Asing (1 Lot = 100 lembar)
            if total_buy_lot > 0:
                avg_buy_price = total_buy_val / (total_buy_lot * 100)
                
    except Exception as e: return None, 0
    return net_foreign, avg_buy_price

# --- 7. FUNGSI FETCH FUNDAMENTAL & PERTUMBUHAN LABA (YAHOO) ---
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
            "EPS_Growth": info.get('earningsQuarterlyGrowth', None) # Data Pertumbuhan Laba YoY
        }
    except: return None

# --- 8. FUNGSI TEKNIKAL, WYCKOFF, ATR & EMA200 ---
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

def calculate_metrics(df):
    df = fix_dataframe(df)
    try:
        df['Rsi'] = df.ta.rsi(length=14)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        bbands = df.ta.bbands(length=20, std=2)
        df['SMA20'] = df.ta.sma(length=20)
        df['SMA50'] = df.ta.sma(length=50)
        
        # Tambahan Dewa: EMA 200 & ATR (Volatilitas)
        df['EMA200'] = df.ta.ema(length=200)
        df['ATR'] = df.ta.atr(length=14)
        
        change = abs(df['Close'] - df['Close'].shift(14))
        volatility = abs(df['Close'] - df['Close'].shift(1)).rolling(window=14).sum()
        df['ER'] = change / volatility
        
        df = pd.concat([df, macd, bbands], axis=1)
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
    except: pass
    return df

def advanced_analysis(df):
    if len(df) < 15: return "N/A", "-", 0
    curr = df.iloc[-1]
    er_val = curr.get('ER', 0)
    
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
            
    return phase, divergence, er_val

def score_analysis(df, fund_data):
    if df.empty or len(df)<2: return 0, 0, 0, 0, ["Data Kurang"], df.iloc[-1]
    curr, prev = df.iloc[-1], df.iloc[-2]
    
    score_tech, score_fund, score_bandar, score_candle = 0, 0, 0, 0
    reasons = []
    
    # Tren Mayor EMA 200
    if not pd.isna(curr.get('EMA200')) and curr['Close'] > curr['EMA200']:
        score_tech += 1
        reasons.append("📈 Tren Mayor Naik (> EMA200)")
        
    # CMF Bandar Analysis
    cmf = curr.get('CMF', 0)
    if cmf > 0.1: score_bandar = 2; reasons.append("🐳 CMF: Akumulasi Besar")
    elif cmf > 0.05: score_bandar = 1
    elif cmf < -0.1: score_bandar = -2; reasons.append("🔻 CMF: Distribusi")
        
    if curr.get('MACD_12_26_9', 0) > curr.get('MACDs_12_26_9', 0): score_tech += 1
    rsi = curr.get('Rsi', 50)
    if rsi < 35: score_tech += 2; reasons.append("💎 RSI Oversold")
    elif rsi > 70: score_tech -= 1
    
    # Fundamental & Laba
    if fund_data:
        pbv = fund_data.get('PBV')
        eps_g = fund_data.get('EPS_Growth')
        if pbv and pbv < 1.5: score_fund += 2
        # Skor ekstra jika Laba tumbuh positif > 10%
        if eps_g and eps_g > 0.10: 
            score_fund += 2
            reasons.append(f"🚀 Laba Tumbuh +{eps_g*100:.1f}%")
        
    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns: reasons.append(f"🕯️ {patterns[0]}")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr

# --- 9. FITUR SCREENER ---
def run_screener(use_goapi):
    st.header("🔍 Smart Money Screener (Optimized)")
    if use_goapi: st.success("🏦 Mode GOAPI VIP: Memfilter Foreign Flow & Harga Modal Bandar (Akurat & Hemat Kuota).")
    else: st.info("🌐 Mode Yahoo Finance: Scanning Cepat Unlimited (Berdasarkan CMF Bandar).")
    
    if st.button("MULAI SCANNING"):
        progress = st.progress(0)
        status = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        # Tarik data 1 Tahun agar bisa menghitung EMA 200 dengan akurat
        price_data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        for i, t in enumerate(tickers):
            status.text(f"Analisa Lapis 1 (Yahoo): {t} ...")
            progress.progress((i+1)/len(tickers))
            
            try:
                df = price_data[t].copy()
                df = fix_dataframe(df)
                if df.empty or len(df) < 50: continue
                if df['Volume'].iloc[-1] < 5000000: continue
                
                df = calculate_metrics(df)
                fund = get_fundamental_info(t)
                s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                wyckoff_phase, divergence, er_val = advanced_analysis(df)
                total_score = s_tech + s_fund + s_bandar + s_candle
                
                # Kalkulasi ATR Stop Loss & Target Profit
                atr = last.get('ATR', 0)
                close = last['Close']
                if atr > 0:
                    stop_loss = close - (1.5 * atr) # Cut Loss ketat di 1.5 ATR
                    target_profit = close + (3.0 * atr) # Reward 2x Lipat dari Risiko
                else:
                    stop_loss, target_profit = close * 0.9, close * 1.1
                
                rec = "WAIT"
                if total_score >= 6 or "BULLISH DIV" in divergence: rec = "💎 STRONG BUY"
                elif total_score >= 4 or "Accumulation" in wyckoff_phase: rec = "✅ BUY"
                
                if total_score < 3 and "BULLISH DIV" not in divergence and "Accumulation" not in wyckoff_phase:
                    continue
                
                symbol_only = t.replace(".JK", "")
                net_foreign = None
                avg_buy_price = 0
                
                if use_goapi:
                    status.text(f"Analisa Lapis 2 (GOAPI - Cek Asing): {t} ...")
                    time.sleep(1) 
                    last_date = df.index[-1].strftime('%Y-%m-%d')
                    net_foreign, avg_buy_price = fetch_goapi_foreign_flow(symbol_only, last_date)
                    if net_foreign is not None and net_foreign <= 0: continue
                
                if net_foreign is not None:
                    modal_str = f" (Modal: Rp {int(avg_buy_price):,})" if avg_buy_price > 0 else ""
                    reasons.append(f"🌐 ASING: {format_rupiah(net_foreign)}{modal_str}")

                results.append({
                    "Kode": symbol_only,
                    "Harga": int(close),
                    "Area TP / SL": f"Rp {int(target_profit):,} / Rp {int(stop_loss):,}",
                    "Wyckoff": wyckoff_phase.split(" ")[1] if len(wyckoff_phase.split(" ")) > 1 else wyckoff_phase,
                    "Net Foreign": format_rupiah(net_foreign) if net_foreign is not None else "N/A",
                    "Modal Asing": f"Rp {int(avg_buy_price):,}" if (use_goapi and avg_buy_price > 0) else "-",
                    "Rek": rec,
                    "Alasan Utama": " | ".join(reasons)
                })
            except: continue
            
        progress.empty()
        status.empty()
        
        if results:
            df_res = pd.DataFrame(results)
            st.success(f"Selesai! {len(results)} Saham Terbaik Ditemukan.")
            st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Data kosong / Tidak ada saham yang masuk kriteria.")

# --- 10. FITUR CHART DETAIL ---
def show_chart(use_goapi):
    st.header("📊 Deep Analysis & Target Tracker")
    
    with st.form(key='chart_search_form'):
        c_input, c_btn = st.columns([4, 1])
        with c_input:
            ticker = st.text_input("Masukkan Kode Saham (Contoh: BBRI, TLKM, ADRO)", "").upper()
        with c_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            submit_search = st.form_submit_button("Cari Saham 🔍")
            
    if submit_search and ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        ticker_only = ticker.replace(".JK", "")
        
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_metrics(df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
        wyckoff_phase, divergence, er_val = advanced_analysis(df)
        
        net_foreign, avg_buy_price = None, 0
        if use_goapi:
            last_date = df.index[-1].strftime('%Y-%m-%d')
            net_foreign, avg_buy_price = fetch_goapi_foreign_flow(ticker_only, last_date)
            
        st.divider()
        
        # Kalkulasi ATR Stop Loss & Target Profit
        atr = last.get('ATR', 0)
        close = last['Close']
        if atr > 0:
            stop_loss = close - (1.5 * atr)
            target_profit = close + (3.0 * atr)
            tp_pct = ((target_profit - close) / close) * 100
        else:
            stop_loss, target_profit, tp_pct = close, close, 0
            
        # TAMPILAN METRIK (4 KOLOM)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga Terakhir & Fase", f"Rp {int(close):,}", wyckoff_phase)
        c2.metric("Target (TP) & Stop Loss", f"Rp {int(target_profit):,}", f"Cut Loss: Rp {int(stop_loss):,} (+{tp_pct:.1f}% TP)", delta_color="normal")
        
        if net_foreign is not None:
            foreign_label = "🟢 AKUMULASI" if net_foreign > 0 else ("🔴 DISTRIBUSI" if net_foreign < 0 else "⚪ NETRAL")
            modal_str = f"Modal Bandar: Rp {int(avg_buy_price):,}" if avg_buy_price > 0 else "Modal: -"
            c3.metric(f"Asing ({foreign_label})", format_rupiah(net_foreign), modal_str, delta_color="normal" if net_foreign > 0 else "inverse")
        else:
            c3.metric("Foreign Flow (Asing)", "N/A", "Gunakan Mode GOAPI / Limit Habis", delta_color="off")
        
        # Ekstrak Laba YoY
        eps_g = fund.get('EPS_Growth') if fund else None
        laba_str = f"Laba (YoY): +{eps_g*100:.1f}% 🚀" if eps_g and eps_g > 0 else (f"Laba: {eps_g*100:.1f}% 🔻" if eps_g else "Laba: N/A")
        c4.metric("Trend Mayor (>EMA200)", "✅ BULLISH" if not pd.isna(last.get('EMA200')) and close > last['EMA200'] else "❌ BEARISH", laba_str, delta_color="normal" if (eps_g and eps_g > 0) else "off")
        
        if "BULLISH DIV" in divergence:
            st.success(f"🚨 **DIVERGENCE ALERT:** {divergence} - Peluang besar harga akan segera rebound!")
        elif "BEARISH DIV" in divergence:
            st.error(f"🚨 **DIVERGENCE ALERT:** {divergence} - Hati-hati, indikator distribusi di pucuk!")
        
        st.subheader(f"Visualisasi Grafik {ticker_only} & Titik Krusial")
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.05, subplot_titles=("Harga, Target, & Trend Mayor", "Volume", "Bandar Flow (CMF)"))
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], line=dict(color='purple', width=2.5), name='EMA200 (Mayor)'), row=1, col=1)
        
        # Gambar Garis Target Profit (Hijau), Stop Loss (Merah), dan Modal Asing (Biru)
        if atr > 0:
            fig.add_hline(y=target_profit, line_dash="dash", line_color="green", annotation_text="Target Profit", row=1, col=1)
            fig.add_hline(y=stop_loss, line_dash="dash", line_color="red", annotation_text="Stop Loss", row=1, col=1)
        if use_goapi and avg_buy_price > 0:
            fig.add_hline(y=avg_buy_price, line_dash="dot", line_color="blue", annotation_text="Modal Asing", row=1, col=1)
        
        _, patterns = check_candlestick_patterns(df.iloc[-1], df.iloc[-2])
        if patterns: fig.add_annotation(x=df.index[-1], y=df['High'].iloc[-1], text=patterns[0], showarrow=True, arrowhead=1, row=1, col=1)
        
        colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol, name='Volume'), row=2, col=1)
        
        cmf_colors = ['green' if v >= 0 else 'red' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=cmf_colors, name='Money Flow'), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="black", row=3, col=1)
        
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- 11. PENGATURAN SIDEBAR & AKUN ---
st.sidebar.header("⚙️ Pengaturan")
mode = st.sidebar.radio("Pilih Menu:", ["🔍 Super Screener", "📊 Advanced Chart"])
st.sidebar.divider()
data_source = st.sidebar.radio("Sumber Data Bandar:", ["🌐 Yahoo Finance (Unlimited/Estimasi)", "🏦 GOAPI (Akurat/Limit Harian)"])
use_goapi = "GOAPI" in data_source

st.sidebar.divider()
st.sidebar.markdown(f"👤 Login sebagai: **{st.session_state.get('username', '')}**")
if st.sidebar.button("Keluar (Logout)"):
    st.session_state["password_correct"] = False
    st.rerun()

if mode == "🔍 Super Screener": run_screener(use_goapi)
else: show_chart(use_goapi) 
