import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Master Stock Analyst", layout="wide", page_icon="🧿")

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

# --- 4. HELPER: CLEAN DATA ---
def fix_dataframe(df):
    if df.empty: return df
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.get_level_values(0)
        except: pass
    df.columns = [str(c).capitalize() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df

# --- 5. FUNGSI FETCH FUNDAMENTAL ---
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

# --- 6. FUNGSI DETEKSI CANDLESTICK ---
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

# --- 7. FUNGSI LEGEND LENGKAP ---
def show_legend():
    with st.expander("📖 KAMUS LENGKAP: WYCKOFF, DIVERGENCE, BANDAR & FUNDAMENTAL (Klik)", expanded=False):
        t1, t2, t3, t4 = st.tabs(["📊 Wyckoff & Divergence", "💰 Bandar (CMF)", "🏛️ Fundamental", "📈 Teknikal & Candle"])
        
        with t1:
            st.markdown("""
            **Siklus Wyckoff:**
            * 🟢 **Accumulation:** Harga diam/sideways di bawah, tapi Bandar diam-diam mulai beli (CMF > 0). Waktu untuk nyicil.
            * 🔵 **Markup:** Harga terbang menembus resisten. Waktu untuk HOLD.
            * 🔴 **Distribution:** Harga tertahan di pucuk, Bandar pelan-pelan jualan (CMF < 0). Waspada!
            * 🟠 **Markdown:** Harga jatuh. Jauhi saham ini.
            
            **Sinyal Divergence (Anomali):**
            * 🟢 **Bullish Divergence:** Harga turun terus, TAPI CMF Bandar makin naik. Ini sinyal beli colongan yang sangat kuat!
            * 🔴 **Bearish Divergence:** Harga naik, TAPI CMF Bandar turun drastis (Bandar jualan saat ritel FOMO).
            
            **Efficiency Ratio (ER):**
            * **ER > 0.3:** Tren kuat (Naik/Turunnya lurus). Enak untuk ditradingkan.
            * **ER < 0.2:** Choppy/Sideways (Zig-zag berantakan). Susah ditradingkan.
            """)
        with t2:
            st.success("**Akumulasi (CMF > 0):** Bandar sedang beli. **Distribusi (CMF < 0):** Bandar sedang jual.")
        with t3:
            st.info("**PBV < 1x:** Murah. **ROE > 15%:** Profit Tinggi. **DER < 100%:** Utang Aman.")
        with t4:
            st.warning("**RSI < 30:** Oversold. **Hammer/Engulfing:** Pola pembalikan arah.")

# --- 8. LOGIKA PERHITUNGAN GABUNGAN (ALL METRICS & ADVANCED) ---
def calculate_metrics(df):
    df = fix_dataframe(df)
    try:
        df['Rsi'] = df.ta.rsi(length=14)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        bbands = df.ta.bbands(length=20, std=2)
        
        # Moving Average untuk Wyckoff
        df['SMA20'] = df.ta.sma(length=20)
        df['SMA50'] = df.ta.sma(length=50)
        
        # Efficiency Ratio (ER) - Rumus Kaufman
        change = abs(df['Close'] - df['Close'].shift(14))
        volatility = abs(df['Close'] - df['Close'].shift(1)).rolling(window=14).sum()
        df['ER'] = change / volatility
        
        df = pd.concat([df, macd, bbands], axis=1)
        
        # CMF Bandar
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
    except: pass
    return df

def advanced_analysis(df):
    """Mendeteksi Wyckoff Phase, Divergence, dan ER Status"""
    if len(df) < 15: return "N/A", "N/A", 0

    curr = df.iloc[-1]
    
    # 1. Efficiency Ratio (ER)
    er_val = curr.get('ER', 0)
    
    # 2. Wyckoff Phase Logic
    close, ma20, ma50, cmf = curr['Close'], curr['SMA20'], curr['SMA50'], curr['CMF']
    phase = "Sideways/Noise"
    
    if close > ma20 and ma20 > ma50:
        phase = "🔵 Markup (Naik)"
    elif close < ma20 and ma20 < ma50:
        phase = "🟠 Markdown (Turun)"
    elif close > ma50 and cmf < 0:
        phase = "🔴 Distribution (Pucuk)"
    elif close < ma50 and cmf > 0:
        phase = "🟢 Accumulation (Bawah)"

    # 3. Divergence Logic (Bandingkan trend harga vs trend CMF 10 hari terakhir)
    divergence = "-"
    if len(df) > 10:
        price_trend = df['Close'].iloc[-1] - df['Close'].iloc[-10]
        cmf_trend = df['CMF'].iloc[-1] - df['CMF'].iloc[-10]
        
        if price_trend < 0 and cmf_trend > 0.15:
            divergence = "🟢 BULLISH DIV (Harga Turun, Bandar Masuk!)"
        elif price_trend > 0 and cmf_trend < -0.15:
            divergence = "🔴 BEARISH DIV (Harga Naik, Bandar Jualan!)"
            
    return phase, divergence, er_val

def score_analysis(df, fund_data):
    if df.empty or len(df)<2: return 0, 0, 0, 0, ["Data Kurang"], df.iloc[-1]
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
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

# --- 9. FITUR SCREENER ---
def run_screener():
    st.header("🔍 Wyckoff & Divergence Screener")
    show_legend()
    
    if st.button("MULAI SCANNING (Analisa Tingkat Tinggi)"):
        progress = st.progress(0)
        status = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        price_data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        for i, t in enumerate(tickers):
            status.text(f"Analisa: {t} ...")
            progress.progress((i+1)/len(tickers))
            try:
                df = price_data[t].copy()
                df = calculate_metrics(df)
                fund = get_fundamental_info(t)
                
                # Basic Score
                s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                
                # Advanced Analysis
                wyckoff_phase, divergence, er_val = advanced_analysis(df)
                
                total_score = s_tech + s_fund + s_bandar + s_candle
                
                # Rekomendasi
                rec = "WAIT"
                if total_score >= 6 or "BULLISH DIV" in divergence: rec = "💎 STRONG BUY"
                elif total_score >= 4 or "Accumulation" in wyckoff_phase: rec = "✅ BUY"
                
                div_disp = "-"
                if fund and fund.get('DivYield') is not None:
                    div_disp = f"{fund.get('DivYield'):.2f}%" 
                
                if total_score >= 2 or "BULLISH DIV" in divergence or "Accumulation" in wyckoff_phase:
                    results.append({
                        "Kode": t.replace(".JK",""),
                        "Harga": int(last['Close']),
                        "Wyckoff Phase": wyckoff_phase,
                        "Sinyal Divergence": divergence,
                        "ER (Trend)": f"{er_val:.2f}",
                        "Rek": rec,
                        "Skor Flow": s_bandar,
                        "Skor Tech": s_tech + s_candle,
                        "Skor Fund": s_fund,
                        "Dividen": div_disp
                    })
            except: continue
            
        progress.empty()
        status.empty()
        
        if results:
            df_res = pd.DataFrame(results).sort_values(by=["Sinyal Divergence", "Skor Flow"], ascending=[False, False])
            st.success(f"Selesai! {len(results)} Saham Potensial Ditemukan.")
            try:
                st.dataframe(df_res.style.background_gradient(subset=['Skor Flow', 'Skor Tech', 'Skor Fund'], cmap='Greens'), use_container_width=True)
            except:
                st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Data kosong / Pasar sepi.")

# --- 10. FITUR CHART DETAIL ---
def show_chart():
    st.header("📊 Deep Analysis Chart (Advanced)")
    show_legend()
    
    ticker = st.text_input("Kode Saham", "ADRO").upper()
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_metrics(df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
        wyckoff_phase, divergence, er_val = advanced_analysis(df)
        
        st.divider()
        # --- TOP METRICS ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga", f"Rp {int(last['Close']):,}")
        c2.metric("Wyckoff Phase", wyckoff_phase.split(" ")[0] + " " + wyckoff_phase.split(" ")[1])
        
        er_status = "Trending 🚀" if er_val > 0.3 else ("Choppy/Sideways 💤" if er_val < 0.2 else "Netral")
        c3.metric("Trend Quality (ER)", f"{er_val:.2f}", delta=er_status, delta_color="normal" if er_val > 0.3 else "off")
        
        cmf_val = last.get('CMF', 0)
        c4.metric("Bandar Flow (CMF)", f"{cmf_val:.2f}", delta="Akumulasi" if cmf_val>0 else "Distribusi", delta_color="normal" if cmf_val>0 else "inverse")
        
        # --- ALERT DIVERGENCE ---
        if "BULLISH DIV" in divergence:
            st.success(f"🚨 **DIVERGENCE ALERT:** {divergence} - Peluang besar harga akan segera rebound!")
        elif "BEARISH DIV" in divergence:
            st.error(f"🚨 **DIVERGENCE ALERT:** {divergence} - Hati-hati, bandar jualan di pucuk!")
        else:
            st.info("Arah harga selaras dengan arah aliran uang (Tidak ada Divergence).")
        
        st.subheader(f"Visualisasi {ticker}")
        
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                            row_heights=[0.5, 0.25, 0.25],
                            vertical_spacing=0.05,
                            subplot_titles=("Harga & Pola", "Volume", "Bandar Flow (CMF)"))
        
        # 1. Chart Harga
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        
        # Tambahkan Garis MA20 dan MA50 untuk visualisasi Wyckoff
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA20'], line=dict(color='orange', width=1.5), name='MA20 (Pendek)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA50'], line=dict(color='blue', width=1.5), name='MA50 (Menengah)'), row=1, col=1)
        
        _, patterns = check_candlestick_patterns(df.iloc[-1], df.iloc[-2])
        if patterns:
             fig.add_annotation(x=df.index[-1], y=df['High'].iloc[-1], text=patterns[0], showarrow=True, arrowhead=1, row=1, col=1)
        
        # 2. Volume
        colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol, name='Volume'), row=2, col=1)
        
        # 3. CMF Flow
        cmf_colors = ['green' if v >= 0 else 'red' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=cmf_colors, name='Money Flow'), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="black", row=3, col=1)
        
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

# --- MAIN ---
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Master Screener", "📊 Advanced Chart"])
if mode == "🔍 Master Screener": run_screener()
else: show_chart()
