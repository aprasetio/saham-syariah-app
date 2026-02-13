import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Pro Stock Analyst", layout="wide", page_icon="💎")

# --- 2. CSS FIX (TAMPILAN) ---
st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background-color: #f0f2f6 !important;
        border: 1px solid #d6d6d6; color: black !important;
    }
    div[data-testid="stMetricLabel"] p { color: #31333F !important; }
    div[data-testid="stMetricValue"] div { color: #000000 !important; }
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
        data = {
            "PBV": info.get('priceToBook', None),
            "PER": info.get('trailingPE', None),
            "ROE": info.get('returnOnEquity', None), 
            "DER": info.get('debtToEquity', None),   
            "MarketCap": info.get('marketCap', 0)
        }
        return data
    except: return None

# --- 6. FUNGSI LEGEND / PANDUAN (BARU DIKEMBALIKAN) ---
def show_legend():
    with st.expander("📖 KAMUS & PANDUAN CARA BACA (Klik Disini)", expanded=False):
        st.markdown("### 🏆 Arti Rekomendasi")
        c1, c2, c3 = st.columns(3)
        c1.info("**💎 GEM (Permata):**\nSaham Sempurna! Fundamental Bagus (Laba Tinggi/Murah) DAN Teknikal Bagus (Sedang Naik). Target Utama.")
        c2.success("**🛡️ INVEST BUY:**\nFundamental Sangat Bagus (Aman untuk jangka panjang), tapi harga sedang diam/turun. Cocok untuk menabung.")
        c3.warning("**📈 TRADING BUY:**\nFundamental Biasa/Jelek, tapi Grafik Teknikal Bagus (Ada Bandar/Volume). Hanya untuk jangka pendek (Cepat Jual).")
        
        st.divider()
        
        st.markdown("### 📊 Indikator Fundamental (Kualitas)")
        f1, f2, f3, f4 = st.columns(4)
        f1.write("**PBV (Harga vs Aset)**\n* < 1x: Murah (Diskon)\n* > 2x: Wajar/Mahal")
        f2.write("**PER (Balik Modal)**\n* < 10x: Cepat (Murah)\n* > 20x: Lama (Mahal)")
        f3.write("**ROE (Profitabilitas)**\n* > 15%: Perusahaan Hebat\n* < 5%: Perusahaan Lemah")
        f4.write("**DER (Utang)**\n* < 100%: Aman\n* > 150%: Risiko Tinggi")

# --- 7. LOGIKA SKOR FUNDAMENTAL ---
def score_fundamental(data):
    score = 0
    reasons = []
    if not data: return 0, ["Data Fundamental N/A"]

    # PBV
    pbv = data['PBV']
    if pbv is not None:
        if pbv < 1.0: score += 2; reasons.append("💎 PBV Sangat Murah (<1x)")
        elif pbv < 2.0: score += 1
        elif pbv > 5.0: score -= 1; reasons.append("⚠️ PBV Mahal")

    # PER
    per = data['PER']
    if per is not None:
        if 0 < per < 10: score += 2; reasons.append("💎 PER Murah (<10x)")
        elif per > 30: score -= 1; reasons.append("⚠️ PER Mahal")

    # ROE
    roe = data['ROE']
    if roe is not None:
        roe_pct = roe * 100 
        if roe_pct > 15: score += 2; reasons.append(f"🔥 ROE Tinggi ({roe_pct:.1f}%)")
        elif roe_pct < 5: score -= 1; reasons.append("🔻 ROE Rendah")

    # DER
    der = data['DER']
    if der is not None:
        if der < 50: score += 2; reasons.append("🛡️ Utang Sangat Aman")
        elif der > 150: score -= 2; reasons.append("⚠️ Utang Berbahaya")

    return score, reasons

# --- 8. LOGIKA TEKNIKAL ---
def calculate_technical(df):
    df = fix_dataframe(df)
    try:
        df['Rsi'] = df.ta.rsi(length=14)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
    except: pass
    return df

def score_technical(df):
    if df.empty or len(df) < 2: return 0, ["Data Kurang"], df.iloc[-1]
    curr = df.iloc[-1]
    score = 0
    reasons = []
    
    if curr.get('MACD_12_26_9', 0) > curr.get('MACDs_12_26_9', 0): score += 1; reasons.append("📈 Trend Naik (MACD)")
    else: score -= 1
    
    rsi = curr.get('Rsi', 50)
    if rsi < 35: score += 2; reasons.append("💎 Oversold (RSI)")
    elif rsi > 70: score -= 2; reasons.append("⚠️ Overbought (RSI)")
    
    cmf = curr.get('CMF', 0)
    if cmf > 0.1: score += 1; reasons.append("💰 Ada Akumulasi Bandar")
    
    return score, reasons, curr

# --- 9. FITUR SCREENER ---
def run_screener():
    st.header("🔍 Screener: Fundamental + Teknikal")
    show_legend() # TAMPILKAN LEGEND DISINI
    
    if st.button("MULAI SCANNING (Mode Lambat & Akurat)"):
        progress = st.progress(0)
        status_text = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        data_price = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        total = len(tickers)
        for i, t in enumerate(tickers):
            status_text.text(f"Menganalisa Laporan Keuangan: {t} ...")
            progress.progress((i+1)/total)
            try:
                # Teknikal
                df = data_price[t].copy()
                df = fix_dataframe(df)
                if df.empty: continue
                df = calculate_technical(df)
                score_tec, reason_tec, last = score_technical(df)
                
                # Fundamental
                fund_data = get_fundamental_info(t)
                score_fund, reason_fund = score_fundamental(fund_data)
                
                # Rekomendasi
                rec = "NEUTRAL"
                if score_tec > 0 and score_fund > 3: rec = "💎 GEM"
                elif score_tec > 1: rec = "📈 TRADING BUY"
                elif score_fund > 4: rec = "🛡️ INVEST BUY"
                
                # Format
                roe_disp = f"{fund_data['ROE']*100:.1f}%" if fund_data and fund_data['ROE'] else "-"
                pbv_disp = f"{fund_data['PBV']:.2f}x" if fund_data and fund_data['PBV'] else "-"
                per_disp = f"{fund_data['PER']:.1f}x" if fund_data and fund_data['PER'] else "-"
                
                results.append({
                    "Kode": t.replace(".JK",""),
                    "Harga": int(last['Close']),
                    "Rek": rec,
                    "Skor Tech": score_tec,
                    "Skor Fund": score_fund,
                    "ROE": roe_disp,
                    "PBV": pbv_disp,
                    "PER": per_disp,
                    "Alasan": ", ".join(reason_fund)
                })
            except: continue
            
        progress.empty()
        status_text.empty()
        
        if results:
            df_res = pd.DataFrame(results).sort_values("Skor Tech", ascending=False)
            st.success(f"Selesai! Menampilkan {len(results)} saham.")
            try:
                st.dataframe(df_res.style.background_gradient(subset=['Skor Tech', 'Skor Fund'], cmap='Greens'), use_container_width=True)
            except:
                st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Gagal mengambil data.")

# --- 10. FITUR CHART DETAIL ---
def show_chart():
    st.header("📊 Deep Dive Analysis")
    show_legend() # TAMPILKAN LEGEND DISINI JUGA
    
    ticker = st.text_input("Kode Saham", "ADRO").upper()
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_technical(df)
        score_t, reasons_t, last = score_technical(df)
        
        fund = get_fundamental_info(symbol)
        score_f, reasons_f = score_fundamental(fund)
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Harga", f"Rp {int(last['Close']):,}")
        c2.metric("Skor Teknikal", f"{score_t}/4", delta="Bagus" if score_t > 1 else "Jelek")
        c3.metric("Skor Fundamental", f"{score_f}/8", delta="Bagus" if score_f > 4 else "Jelek")
        
        st.subheader("📑 Data Fundamental")
        if fund:
            f1, f2, f3, f4 = st.columns(4)
            pbv, per, roe, der = fund.get('PBV'), fund.get('PER'), fund.get('ROE'), fund.get('DER')
            
            f1.metric("PBV", f"{pbv:.2f}x" if pbv else "-", delta="Murah" if pbv and pbv<1 else None, delta_color="inverse")
            f2.metric("PER", f"{per:.1f}x" if per else "-", delta="Cepat" if per and per<10 else None, delta_color="inverse")
            f3.metric("ROE", f"{roe*100:.1f}%" if roe else "-", delta="Profit" if roe and roe>0.15 else None)
            f4.metric("DER", f"{der:.1f}%" if der else "-", delta="Aman" if der and der<100 else "Bahaya", delta_color="inverse")
        else: st.warning("Data Fundamental N/A")

        st.subheader("📈 Grafik")
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=500)
        st.plotly_chart(fig, use_container_width=True)

# --- MAIN ---
mode = st.sidebar.radio("Mode:", ["🔍 Screener Lengkap", "📊 Detail Chart"])
if mode == "🔍 Screener Lengkap": run_screener()
else: show_chart()
