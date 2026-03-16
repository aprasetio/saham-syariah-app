import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import numpy as np

# --- 1. KONFIGURASI HALAMAN & API KEY ---
st.set_page_config(page_title="Ultimate Smart Money Analyst", layout="wide", page_icon="🏦")

# KUNCI RAHASIA GOAPI ANDA
GOAPI_KEY = "d63f23fe-bab5-516f-e0a7-c3b0f3ee"

# --- 2. CSS FIX (TAMPILAN DARK MODE) ---
st.markdown("""
<style>
    [data-testid="stMetric"] {
        background-color: #f0f2f6 !important;
        border: 1px solid #d6d6d6 !important;
        padding: 10px !important;
        border-radius: 10px !important;
    }
    [data-testid="stMetricLabel"] p { color: #31333F !important; font-weight: bold !important; }
    [data-testid="stMetricValue"] div { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. DAFTAR SAHAM (JII 30) ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- 4. HELPER FUNCTIONS ---
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

# --- 5. FUNGSI FETCH GOAPI (TRUE BANDARMOLOGY & RISK) ---
def fetch_goapi_data(symbol, target_date):
    """Mengambil Data Suspend, Notasi, dan Arus Dana Asing dari GOAPI"""
    headers = {'accept': 'application/json', 'X-API-KEY': GOAPI_KEY}
    
    is_suspended = False
    notasi = ""
    net_foreign = 0
    
    # 1. Cek Profil & Risiko (Suspend/Notasi)
    try:
        url_prof = f"https://api.goapi.io/stock/idx/{symbol}/profile"
        res_prof = requests.get(url_prof, headers=headers).json()
        if res_prof.get('status') == 'success':
            data_prof = res_prof['data']
            is_suspended = data_prof.get('is_suspended', False)
            notes = data_prof.get('special_notations', [])
            if notes: notasi = ", ".join(notes)
    except: pass

    # 2. Cek Foreign Flow (Arus Asing)
    try:
        url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
        res_broker = requests.get(url_broker, headers=headers).json()
        if res_broker.get('status') == 'success':
            for broker in res_broker['data']['results']:
                if broker['side'] == 'BUY':
                    net_foreign += broker['value']
                elif broker['side'] == 'SELL':
                    net_foreign -= broker['value']
    except: pass

    return is_suspended, notasi, net_foreign

# --- 6. FUNGSI FETCH FUNDAMENTAL (YAHOO) ---
@st.cache_data(ttl=3600) 
def get_fundamental_info(symbol):
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            "PBV": info.get('priceToBook', None),
            "PER": info.get('trailingPE', None),
            "ROE": info.get('returnOnEquity', None), 
            "DER": info.get('debtToEquity', None),
            "DivYield": info.get('dividendYield', None)
        }
    except: return None

# --- 7. FUNGSI TEKNIKAL & WYCKOFF ---
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
            if is_valid_support: score += 1; patterns.append("🔨 Hammer (Valid)")
        if (prev['Close'] < prev['Open']) and (curr['Close'] > curr['Open']): 
            if (curr['Open'] < prev['Close']) and (curr['Close'] > prev['Open']):
                if is_valid_support: score += 1.5; patterns.append("🦁 Engulfing (Valid)")
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
        
        change = abs(df['Close'] - df['Close'].shift(14))
        volatility = abs(df['Close'] - df['Close'].shift(1)).rolling(window=14).sum()
        df['ER'] = change / volatility
        
        df = pd.concat([df, macd, bbands], axis=1)
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
    except: pass
    return df

def advanced_analysis(df):
    if len(df) < 15: return "N/A", "N/A", 0
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
    
    cmf = curr.get('CMF', 0)
    if cmf > 0.1: score_bandar = 2
    elif cmf > 0.05: score_bandar = 1
    elif cmf < -0.1: score_bandar = -2
        
    if curr.get('MACD_12_26_9', 0) > curr.get('MACDs_12_26_9', 0): score_tech += 1
    rsi = curr.get('Rsi', 50)
    if rsi < 35: score_tech += 2
    elif rsi > 70: score_tech -= 1
    
    if fund_data:
        pbv = fund_data.get('PBV')
        roe = fund_data.get('ROE')
        der = fund_data.get('DER')
        if pbv and pbv < 1.5: score_fund += 2
        if roe and roe > 0.15: score_fund += 2
        if der and der < 100: score_fund += 1
        
    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns: reasons.append(f"🕯️ {patterns[0]}")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr

# --- 8. FITUR SCREENER (SUPER FILTER GOAPI) ---
def run_screener():
    st.header("🔍 GOAPI Super Screener (Foreign Flow & Wyckoff)")
    st.info("Screener ini memiliki Filter Berlapis: Membuang saham Suspend, Sepi Likuiditas, dan Distribusi Asing.")
    
    if st.button("MULAI SCANNING (Mode Ketat)"):
        progress = st.progress(0)
        status = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        price_data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        for i, t in enumerate(tickers):
            status.text(f"Analisa Lapis 1 (GOAPI): {t} ...")
            progress.progress((i+1)/len(tickers))
            
            try:
                df = price_data[t].copy()
                df = fix_dataframe(df)
                if df.empty or len(df) < 20: continue
                
                # Cek Likuiditas (Abaikan jika volume hari ini di bawah 5 juta lembar)
                vol_hari_ini = df['Volume'].iloc[-1]
                if vol_hari_ini < 5000000: continue
                
                # Cek GOAPI: Suspend, Notasi, & Foreign Flow
                symbol_only = t.replace(".JK", "")
                last_date = df.index[-1].strftime('%Y-%m-%d')
                
                is_suspended, notasi, net_foreign = fetch_goapi_data(symbol_only, last_date)
                
                # FILTER 1: Buang Saham Bermasalah
                if is_suspended or notasi != "": continue
                
                # FILTER 2: Buang Jika Asing Keluar (Net Sell)
                if net_foreign < 0: continue
                
                # JIKA LOLOS FILTER GOAPI, LANJUT ANALISA TEKNIKAL
                df = calculate_metrics(df)
                fund = get_fundamental_info(t)
                s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                wyckoff_phase, divergence, er_val = advanced_analysis(df)
                
                total_score = s_tech + s_fund + s_bandar + s_candle
                
                # Rekomendasi
                rec = "WAIT"
                if total_score >= 6 or "BULLISH DIV" in divergence: rec = "💎 STRONG BUY"
                elif total_score >= 4 or "Accumulation" in wyckoff_phase: rec = "✅ BUY"
                
                div_disp = "-"
                if fund and fund.get('DivYield') is not None:
                    div_disp = f"{fund.get('DivYield')*100:.1f}%" # Fix Persentase
                
                # Tambahkan keterangan Asing di alasan
                reasons.append(f"🌐 ASING MASUK: {format_rupiah(net_foreign)}")

                if total_score >= 2 or "BULLISH DIV" in divergence or "Accumulation" in wyckoff_phase:
                    results.append({
                        "Kode": symbol_only,
                        "Harga": int(last['Close']),
                        "Wyckoff": wyckoff_phase.split(" ")[1],
                        "Net Foreign (Rp)": format_rupiah(net_foreign),
                        "ER (Trend)": f"{er_val:.2f}",
                        "Rek": rec,
                        "Skor Tech": s_tech + s_candle,
                        "Skor Fund": s_fund,
                        "Dividen": div_disp,
                        "Alasan": " | ".join(reasons)
                    })
            except: continue
            
        progress.empty()
        status.empty()
        
        if results:
            df_res = pd.DataFrame(results).sort_values(by=["Skor Tech", "Wyckoff"], ascending=[False, False])
            st.success(f"Selesai! {len(results)} Saham Berkualitas (Asing Akumulasi) Ditemukan.")
            st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Data kosong. Asing sedang keluar dari pasar / Semua saham tidak masuk kriteria (Wait & See).")

# --- 9. FITUR CHART DETAIL (DENGAN STATUS GOAPI) ---
def show_chart():
    st.header("📊 Deep Analysis & Foreign Flow Chart")
    
    ticker = st.text_input("Kode Saham", "BBRI").upper()
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        ticker_only = ticker.replace(".JK", "")
        
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_metrics(df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
        wyckoff_phase, divergence, er_val = advanced_analysis(df)
        
        # Tarik data GOAPI
        last_date = df.index[-1].strftime('%Y-%m-%d')
        is_suspended, notasi, net_foreign = fetch_goapi_data(ticker_only, last_date)
        
        # --- PERINGATAN RISIKO GOAPI ---
        if is_suspended:
            st.error("🚨 SAHAM INI SEDANG DI-SUSPEND OLEH BURSA EFEK INDONESIA!")
        if notasi:
            st.warning(f"⚠️ Perhatian! Saham ini memiliki Notasi Khusus dari BEI: {notasi}")
            
        st.divider()
        # --- TOP METRICS ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga Terakhir", f"Rp {int(last['Close']):,}")
        c2.metric("Fase Wyckoff", wyckoff_phase.split(" ")[0] + " " + wyckoff_phase.split(" ")[1])
        
        # Metric Net Foreign Baru!
        foreign_label = "🟢 ASING AKUMULASI" if net_foreign > 0 else ("🔴 ASING DISTRIBUSI" if net_foreign < 0 else "⚪ ASING NETRAL")
        c3.metric("Foreign Flow (Hari Terakhir)", foreign_label, format_rupiah(net_foreign), delta_color="normal" if net_foreign > 0 else "inverse")
        
        er_status = "Trending 🚀" if er_val > 0.3 else ("Choppy/Sideways 💤" if er_val < 0.2 else "Netral")
        c4.metric("Trend Quality (ER)", f"{er_val:.2f}", delta=er_status, delta_color="normal" if er_val > 0.3 else "off")
        
        # --- ALERT DIVERGENCE ---
        if "BULLISH DIV" in divergence:
            st.success(f"🚨 **DIVERGENCE ALERT:** {divergence} - Peluang besar harga akan segera rebound!")
        elif "BEARISH DIV" in divergence:
            st.error(f"🚨 **DIVERGENCE ALERT:** {divergence} - Hati-hati, indikator CMF/Bandar jualan di pucuk!")
        
        st.subheader(f"Visualisasi Grafik {ticker_only}")
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                            row_heights=[0.5, 0.25, 0.25],
                            vertical_spacing=0.05,
                            subplot_titles=("Harga & Pola", "Volume", "Bandar Flow (CMF)"))
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA20'], line=dict(color='orange', width=1.5), name='MA20'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], line=dict(color='blue', width=1.5), name='MA50'), row=1, col=1)
        
        _, patterns = check_candlestick_patterns(df.iloc[-1], df.iloc[-2])
        if patterns:
             fig.add_annotation(x=df.index[-1], y=df['High'].iloc[-1], text=patterns[0], showarrow=True, arrowhead=1, row=1, col=1)
        
        colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol, name='Volume'), row=2, col=1)
        
        cmf_colors = ['green' if v >= 0 else 'red' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=cmf_colors, name='Money Flow'), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="black", row=3, col=1)
        
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- MAIN ---
mode = st.sidebar.radio("Pilih Menu:", ["🔍 GOAPI Super Screener", "📊 Advanced Chart (Asing Tracker)"])
if mode == "🔍 GOAPI Super Screener": run_screener()
else: show_chart() 
