import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Ultimate Stock Analyst", layout="wide", page_icon="🚀")

# --- 2. CSS FIX (TAMPILAN) ---
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

# --- 5. FUNGSI FETCH FUNDAMENTAL (+ INFO DIVIDEN) ---
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
            "DivYield": info.get('dividendYield', None) # Data dividen ditarik tapi tidak diskor
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
            if is_valid_support:
                score += 1
                patterns.append("🔨 Hammer (Valid/Support)")
            else:
                patterns.append("🔨 Hammer (Lemah/Sideways)")

        if (prev['Close'] < prev['Open']) and (curr['Close'] > curr['Open']): 
            if (curr['Open'] < prev['Close']) and (curr['Close'] > prev['Open']):
                if is_valid_support:
                    score += 1.5
                    patterns.append("🦁 Engulfing (Valid/Support)")
                else:
                    patterns.append("🦁 Engulfing (Lemah/Sideways)")
    except: pass
    
    return score, patterns

# --- 7. FUNGSI LEGEND LENGKAP ---
def show_legend():
    with st.expander("📖 KAMUS LENGKAP: FUNDAMENTAL + TEKNIKAL + BANDAR + CANDLE (Klik Disini)", expanded=False):
        t1, t2, t3, t4 = st.tabs(["🏛️ Fundamental", "💰 Bandar", "📈 Teknikal", "🕯️ Candle"])
        
        with t1:
            st.info("**PBV < 1x:** Murah (Diskon).\n\n**ROE > 15%:** Profit Tinggi.\n\n**DER < 100%:** Utang Aman.\n\n**Info Dividen:** Persentase imbal hasil per tahun (Hanya sebagai informasi tambahan).")
        with t2:
            st.success("**Akumulasi (CMF > 0):** Bandar sedang beli. **Distribusi (CMF < 0):** Bandar sedang jual.")
        with t3:
            st.warning("**RSI < 30:** Oversold (Waktunya Pantul). **MACD Cross:** Perubahan Tren.")
        with t4:
            st.error("**Hammer/Engulfing (Valid):** Pola muncul di harga Support/Murah. Sinyal Kuat!\n**Hammer/Engulfing (Lemah):** Pola muncul di tengah pasar datar (Sideways). Abaikan.")

# --- 8. LOGIKA PERHITUNGAN GABUNGAN ---
def calculate_metrics(df):
    df = fix_dataframe(df)
    try:
        df['Rsi'] = df.ta.rsi(length=14)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        bbands = df.ta.bbands(length=20, std=2)
        df = pd.concat([df, macd, bbands], axis=1)
        
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
    except: pass
    return df

def score_analysis(df, fund_data):
    if df.empty or len(df)<2: return 0, 0, 0, 0, ["Data Kurang"], df.iloc[-1]
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    score_tech = 0
    score_fund = 0
    score_bandar = 0
    score_candle = 0
    reasons = []
    
    # 1. BANDAR (Money Flow)
    cmf = curr.get('CMF', 0)
    if cmf > 0.1: score_bandar = 2; reasons.append("🐳 BANDAR: Akumulasi Besar")
    elif cmf > 0.05: score_bandar = 1; reasons.append("💰 BANDAR: Ada Akumulasi")
    elif cmf < -0.1: score_bandar = -2; reasons.append("🔻 BANDAR: Distribusi")
        
    # 2. TEKNIKAL (MACD & RSI)
    if curr.get('MACD_12_26_9', 0) > curr.get('MACDs_12_26_9', 0): score_tech += 1
    rsi = curr.get('Rsi', 50)
    if rsi < 35: score_tech += 2; reasons.append("💎 TEKNIKAL: Oversold (Murah)")
    elif rsi > 70: score_tech -= 1
    
    # 3. FUNDAMENTAL
    if fund_data:
        pbv = fund_data.get('PBV')
        roe = fund_data.get('ROE')
        der = fund_data.get('DER')
        
        if pbv and pbv < 1.5: score_fund += 2; reasons.append("🏛️ FUNDAMENTAL: Undervalue")
        if roe and roe > 0.15: score_fund += 2
        if der and der < 100: score_fund += 1
        
    # 4. CANDLESTICK (Pattern)
    s_candle, patterns = check_candlestick_patterns(curr, prev)
    score_candle += s_candle
    if patterns:
        reasons.append(f"🕯️ CANDLE: {', '.join(patterns)}")

    return score_tech, score_fund, score_bandar, score_candle, reasons, curr

# --- 9. FITUR SCREENER ---
def run_screener():
    st.header("🔍 Ultimate Screener (Fund + Tech + Bandar + Candle)")
    show_legend()
    
    if st.button("MULAI SCANNING"):
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
                
                s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
                
                total_score = s_tech + s_fund + s_bandar + s_candle
                
                cmf = last.get('CMF', 0)
                bandar_stat = "AKUMULASI 🐳" if cmf > 0.1 else ("DISTRIBUSI 🔻" if cmf < -0.1 else "Netral")
                
                rec = "WAIT"
                if total_score >= 6: rec = "💎 STRONG BUY"
                elif total_score >= 4: rec = "✅ BUY"
                
                # --- PERBAIKAN BUG DIVIDEN YIELD DI SINI ---
                div_disp = "-"
                if fund and fund.get('DivYield') is not None:
                    # * 100 DIHAPUS, DIBUAT 2 ANGKA DESIMAL (.2f)
                    div_disp = f"{fund.get('DivYield'):.2f}%" 
                
                if total_score >= 3 or s_candle > 0:
                    results.append({
                        "Kode": t.replace(".JK",""),
                        "Harga": int(last['Close']),
                        "Rek": rec,
                        "Dividen": div_disp, 
                        "Bandar": bandar_stat,
                        "Skor Fund": s_fund,
                        "Skor Tech": s_tech + s_candle, 
                        "Alasan": ", ".join(reasons)
                    })
            except: continue
            
        progress.empty()
        status.empty()
        
        if results:
            df_res = pd.DataFrame(results).sort_values("Bandar", ascending=False)
            st.success(f"Selesai! {len(results)} Saham Potensial Ditemukan.")
            try:
                st.dataframe(df_res.style.background_gradient(subset=['Skor Fund', 'Skor Tech'], cmap='Greens'), use_container_width=True)
            except:
                st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Data kosong / Pasar sepi.")

# --- 10. FITUR CHART DETAIL ---
def show_chart():
    st.header("📊 Deep Analysis Chart")
    show_legend()
    
    ticker = st.text_input("Kode Saham", "ADRO").upper()
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_metrics(df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, s_candle, reasons, last = score_analysis(df, fund)
        
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga", f"Rp {int(last['Close']):,}")
        
        c2.metric("Skor Fundamental", f"{s_fund}/5", help="Maksimal 5: Evaluasi dari PBV, ROE, dan DER")
        c3.metric("Skor Teknikal+Candle", f"{s_tech + s_candle}/4")
        
        cmf_val = last.get('CMF', 0)
        bandar_label = "NETRAL"
        bandar_color = "off"
        if s_bandar > 0: bandar_label = "🐳 AKUMULASI"; bandar_color="normal"
        elif s_bandar < 0: bandar_label = "🔻 DISTRIBUSI"; bandar_color="inverse"
        
        c4.metric("Status Bandar", bandar_label, f"{cmf_val:.2f}", delta_color=bandar_color)
        
        st.info(f"**Kesimpulan AI:** {', '.join(reasons)}")
        
        st.subheader(f"Visualisasi {ticker}")
        
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                            row_heights=[0.5, 0.25, 0.25],
                            vertical_spacing=0.05,
                            subplot_titles=("Harga & Candle", "Volume", "Bandar Flow (CMF)"))
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        
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
        
        if fund:
            div_val = fund.get('DivYield')
            # --- PERBAIKAN BUG DIVIDEN YIELD DI SINI JUGA ---
            div_str = f"{div_val:.2f}%" if div_val is not None else "-" 
            st.caption(f"Data Fundamental: PBV {fund.get('PBV','-')}x | PER {fund.get('PER','-')}x | ROE {float(fund.get('ROE',0))*100:.1f}% | DER {fund.get('DER','-')}% | **Info Dividen: {div_str}**")

# --- MAIN ---
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Ultimate Screener", "📊 Chart Detail"])
if mode == "🔍 Ultimate Screener": run_screener()
else: show_chart()
