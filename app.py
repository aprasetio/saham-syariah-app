import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Super Stock Analyst", layout="wide", page_icon="🚀")

# --- 2. CSS FIX (TAMPILAN DARK MODE & TABEL) ---
st.markdown("""
<style>
    /* Paksa Kotak Metric jadi Terang & Teks Hitam */
    [data-testid="stMetric"] {
        background-color: #f0f2f6 !important;
        border: 1px solid #d6d6d6 !important;
        padding: 10px !important;
        border-radius: 10px !important;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
        color: #31333F !important;
        font-weight: bold !important;
    }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] div {
        color: #000000 !important;
    }
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
        }
    except: return None

# --- 6. FUNGSI LEGEND LENGKAP (FUNDAMENTAL + TEKNIKAL + BANDAR) ---
def show_legend():
    with st.expander("📖 KAMUS LENGKAP: FUNDAMENTAL, TEKNIKAL & BANDARMOLOGY (Klik Disini)", expanded=False):
        
        tab1, tab2, tab3 = st.tabs(["🏛️ Fundamental (Kualitas)", "💰 Bandarmology (Arus Uang)", "📈 Teknikal (Timing)"])
        
        with tab1:
            st.markdown("### Menilai Kesehatan Perusahaan")
            c1, c2 = st.columns(2)
            c1.info("**PBV (Price to Book Value)**\n* Membandingkan harga saham dengan aset bersihnya.\n* **< 1x:** Diskon/Murah.\n* **> 2x:** Mulai Mahal.")
            c1.info("**PER (Price to Earning)**\n* Berapa tahun balik modal dari laba.\n* **< 10x:** Murah.\n* **> 20x:** Mahal.")
            c2.success("**ROE (Return on Equity)**\n* Kemampuan perusahaan mencetak laba.\n* **> 15%:** Perusahaan Hebat (Profit Tebal).")
            c2.warning("**DER (Debt to Equity)**\n* Rasio Utang.\n* **< 100%:** Aman.\n* **> 150%:** Risiko Tinggi (Awas Gagal Bayar).")

        with tab2:
            st.markdown("### Mendeteksi Pergerakan 'Big Player'")
            st.write("""
            Fitur ini menggunakan indikator **CMF (Chaikin Money Flow)** untuk melihat apakah Uang Besar sedang masuk atau keluar.
            """)
            c1, c2 = st.columns(2)
            c1.success("**🐳 AKUMULASI (CMF > 0.05)**\n* **Artinya:** Bandar/Institusi sedang diam-diam membeli (Nyicil Beli).\n* **Strategi:** Ikut beli (Follow the Giant).")
            c2.error("**🔻 DISTRIBUSI (CMF < -0.05)**\n* **Artinya:** Bandar sedang jualan pelan-pelan saat harga naik.\n* **Strategi:** Hati-hati / Jual.")

        with tab3:
            st.markdown("### Menentukan Waktu Beli (Timing)")
            st.write("* **RSI Oversold (<30):** Harga sudah jatuh terlalu dalam (Waktunya pantul naik).\n* **MACD Golden Cross:** Momentum perubahan tren dari turun menjadi naik.")

# --- 7. LOGIKA PERHITUNGAN (ALL IN ONE) ---
def calculate_all_metrics(df):
    df = fix_dataframe(df)
    try:
        # 1. Teknikal Dasar
        df['Rsi'] = df.ta.rsi(length=14)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # 2. Bandarmology (Money Flow / CMF)
        # Rumus Chaikin Money Flow: Mengukur tekanan beli vs jual dikali volume
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        # Handle division by zero jika High == Low
        ad = ad.fillna(0)
        df['CMF'] = ad.rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
        
    except: pass
    return df

def score_analysis(df, fund_data):
    score_tech = 0
    score_fund = 0
    score_bandar = 0
    reasons = []
    
    # Ambil data terakhir
    if df.empty or len(df)<2: return 0, 0, 0, ["Data Kurang"], df.iloc[-1]
    curr = df.iloc[-1]
    
    # --- A. SKOR BANDAR (MONEY FLOW) ---
    cmf = curr.get('CMF', 0)
    if cmf > 0.15:
        score_bandar = 2
        reasons.append("🐳 BANDAR: Akumulasi Besar (CMF Tinggi)")
    elif cmf > 0.05:
        score_bandar = 1
        reasons.append("💰 BANDAR: Ada Akumulasi")
    elif cmf < -0.1:
        score_bandar = -2
        reasons.append("🔻 BANDAR: Distribusi (Keluar)")
        
    # --- B. SKOR TEKNIKAL ---
    # MACD
    if curr.get('MACD_12_26_9', 0) > curr.get('MACDs_12_26_9', 0):
        score_tech += 1
    # RSI
    rsi = curr.get('Rsi', 50)
    if rsi < 35: score_tech += 2; reasons.append("💎 TEKNIKAL: Oversold (Murah)")
    elif rsi > 70: score_tech -= 1
    
    # --- C. SKOR FUNDAMENTAL ---
    if fund_data:
        pbv = fund_data.get('PBV')
        roe = fund_data.get('ROE')
        der = fund_data.get('DER')
        
        if pbv and pbv < 1.5: score_fund += 2
        if roe and roe > 0.15: score_fund += 2
        if der and der < 100: score_fund += 1
        
        if pbv and pbv < 1.0: reasons.append("🏛️ FUNDAMENTAL: Salah Harga (Undervalue)")
        if roe and roe > 0.15: reasons.append("🔥 FUNDAMENTAL: Laba Tinggi")

    return score_tech, score_fund, score_bandar, reasons, curr

# --- 8. FITUR SCREENER ---
def run_screener():
    st.header("🔍 Super Screener (Fund + Tech + Bandar)")
    show_legend()
    
    if st.button("MULAI SCANNING"):
        progress = st.progress(0)
        status = st.empty()
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        # Download data harga dulu
        price_data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        for i, t in enumerate(tickers):
            status.text(f"Menganalisa Saham: {t} ...")
            progress.progress((i+1)/len(tickers))
            try:
                # 1. Analisa Harga & Bandar
                df = price_data[t].copy()
                df = calculate_all_metrics(df)
                
                # 2. Ambil Data Fundamental (Cache)
                fund = get_fundamental_info(t)
                
                # 3. Hitung Skor
                s_tech, s_fund, s_bandar, reasons, last = score_analysis(df, fund)
                
                # 4. Filter: Hanya tampilkan yang minimal ada potensi
                total_score = s_tech + s_fund + s_bandar
                
                # Labeling Status Bandar
                cmf = last.get('CMF', 0)
                if cmf > 0.1: bandar_stat = "🐳 AKUMULASI"
                elif cmf < -0.1: bandar_stat = "🔻 DISTRIBUSI"
                else: bandar_stat = "Netral"
                
                # Tentukan Rekomendasi
                rec = "WAIT"
                if total_score >= 5: rec = "💎 STRONG BUY"
                elif total_score >= 3: rec = "✅ BUY"
                
                results.append({
                    "Kode": t.replace(".JK",""),
                    "Harga": int(last['Close']),
                    "Rek": rec,
                    "Status Bandar": bandar_stat,
                    "Skor Fund": s_fund,
                    "Skor Tech": s_tech,
                    "Alasan": ", ".join(reasons)
                })
            except: continue
            
        progress.empty()
        status.empty()
        
        if results:
            df_res = pd.DataFrame(results).sort_values("Status Bandar", ascending=False) # Sort by Bandar
            st.success(f"Selesai! {len(results)} Saham Dianalisa.")
            try:
                # Warna Warni
                st.dataframe(df_res.style.background_gradient(subset=['Skor Fund', 'Skor Tech'], cmap='Greens'), use_container_width=True)
            except:
                st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Data kosong.")

# --- 9. FITUR CHART DETAIL (DENGAN BANDAR DETECTOR) ---
def show_chart():
    st.header("📊 Deep Analysis Chart")
    show_legend()
    
    ticker = st.text_input("Kode Saham", "BRPT").upper()
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        # Load Data
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_all_metrics(df)
        fund = get_fundamental_info(symbol)
        s_tech, s_fund, s_bandar, reasons, last = score_analysis(df, fund)
        
        # --- DASHBOARD METRICS ---
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Harga", f"Rp {int(last['Close']):,}")
        c2.metric("Skor Fundamental", f"{s_fund}/5", help="Max 5: Kualitas Perusahaan")
        c3.metric("Skor Teknikal", f"{s_tech}/3", help="Max 3: Waktu Beli")
        
        # Metric Bandar Spesial
        cmf_val = last.get('CMF', 0)
        bandar_label = "NETRAL"
        bandar_color = "off"
        if s_bandar > 0: bandar_label = "🐳 AKUMULASI"; bandar_color="normal"
        elif s_bandar < 0: bandar_label = "🔻 DISTRIBUSI"; bandar_color="inverse"
        
        c4.metric("Status Bandar", bandar_label, f"{cmf_val:.2f}", delta_color=bandar_color)
        
        # Tampilkan Alasan
        st.info(f"**Kesimpulan AI:** {', '.join(reasons)}")
        
        # --- CHART 3 BARIS (Price, Volume, Money Flow) ---
        st.subheader(f"Visualisasi {ticker} + Bandar Detector")
        
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                            row_heights=[0.5, 0.25, 0.25],
                            vertical_spacing=0.05,
                            subplot_titles=("Pergerakan Harga", "Volume", "Bandar Detector (Money Flow)"))
        
        # 1. Harga
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
        
        # 2. Volume
        colors_vol = ['red' if r['Open'] - r['Close'] >= 0 else 'green' for i, r in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors_vol, name='Volume'), row=2, col=1)
        
        # 3. Bandar Detector (CMF)
        # Warna Hijau jika Inflow, Merah jika Outflow
        cmf_colors = ['green' if v >= 0 else 'red' for v in df['CMF']]
        fig.add_trace(go.Bar(x=df.index, y=df['CMF'], marker_color=cmf_colors, name='Money Flow'), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="black", row=3, col=1) # Garis Nol
        
        fig.update_layout(height=800, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
        
        # Info Fundamental Bawah
        if fund:
            st.caption(f"Data Fundamental: PBV {fund.get('PBV','-')}x | PER {fund.get('PER','-')}x | ROE {float(fund.get('ROE',0))*100:.1f}% | DER {fund.get('DER','-')}%")

# --- MAIN ---
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Screener All-in-One", "📊 Chart Detail + Bandar"])
if mode == "🔍 Screener All-in-One": run_screener()
else: show_chart()
