import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sharia Stock AI", layout="wide", page_icon="📈")

# --- CSS CUSTOM (Agar Tabel Lebih Rapi) ---
st.markdown("""
<style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- DAFTAR SAHAM SYARIAH (JII 30) ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- HELPER: PEMBERSIH DATA ---
def fix_dataframe(df):
    if df.empty: return df
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = df.columns.get_level_values(0)
        except: pass
    df.columns = [str(c).capitalize() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df

# --- FUNGSI DETEKSI POLA CANDLESTICK ---
def check_candlestick_patterns(curr, prev):
    pattern_score = 0
    pattern_name = []
    
    body_size = abs(curr['Close'] - curr['Open'])
    upper_wick = curr['High'] - max(curr['Close'], curr['Open'])
    lower_wick = min(curr['Close'], curr['Open']) - curr['Low']
    
    # 1. HAMMER (Palu)
    if (lower_wick > 2 * body_size) and (upper_wick < body_size):
        pattern_score += 1.0
        pattern_name.append("🔨 Hammer")

    # 2. BULLISH ENGULFING
    if (prev['Close'] < prev['Open']) and (curr['Close'] > curr['Open']): 
        if (curr['Open'] < prev['Close']) and (curr['Close'] > prev['Open']):
            pattern_score += 1.5
            pattern_name.append("🦁 Engulfing")

    # 3. MARUBOZU (Full Body Green)
    if (curr['Close'] > curr['Open']) and (upper_wick < body_size * 0.1) and (lower_wick < body_size * 0.1):
        pattern_score += 1.0
        pattern_name.append("🟩 Marubozu")

    return pattern_score, pattern_name

# --- FUNGSI ANALISA TEKNIKAL ---
def calculate_technical(df):
    df = fix_dataframe(df)
    
    # Indikator Dasar
    try:
        # RSI
        rsi = df.ta.rsi(close=df['Close'], length=14)
        if isinstance(rsi, pd.DataFrame): rsi = rsi.iloc[:, 0]
        df['Rsi'] = rsi
        
        # MACD
        macd = df.ta.macd(close=df['Close'], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # Bollinger
        bbands = df.ta.bbands(close=df['Close'], length=20, std=2)
        df = pd.concat([df, bbands], axis=1)
        
        # Volume MA
        if 'Volume' in df.columns:
            df['Vol_ma_20'] = df['Volume'].rolling(window=20).mean()
        else:
            df['Vol_ma_20'] = 0
            
    except: pass
    
    return df

# --- LOGIKA SKOR FINAL (AI SCORE) ---
def get_final_analysis(df):
    if len(df) < 2: return 0, ["Data kurang"], df.iloc[-1]
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    score = 0
    reasons = []
    
    # 1. MACD (Trend) - Bobot: 1.0
    macd_val = curr.get('MACD_12_26_9', 0)
    macd_sig = curr.get('MACDs_12_26_9', 0)
    
    if macd_val > macd_sig: 
        score += 1.0
        reasons.append("📈 Trend Naik (MACD)")
    else:
        score -= 1.0 # Hukuman jika trend turun

    # 2. RSI (Momentum) - Bobot: 1.5
    rsi = curr.get('Rsi', 50)
    if rsi < 35: 
        score += 1.5
        reasons.append("💎 Harga Diskon (RSI Oversold)")
    elif 35 <= rsi <= 60:
        score += 0.5 # Netral positif
    elif rsi > 70: 
        score -= 2.0
        reasons.append("⚠️ Harga Mahal (RSI Overbought)")

    # 3. Volume - Bobot: 0.5
    vol = curr.get('Volume', 0)
    vol_ma = curr.get('Vol_ma_20', 1)
    if vol > (1.2 * vol_ma):
        score += 0.5
        reasons.append("🚀 Volume Tinggi")

    # 4. Candlestick - Bobot: 1.0 - 1.5
    candle_score, candle_patterns = check_candlestick_patterns(curr, prev)
    score += candle_score
    if candle_patterns:
        reasons.append(f"🕯️ Pola: {', '.join(candle_patterns)}")

    return score, reasons, curr

# --- FUNGSI TAMPILKAN LEGEND (PANDUAN) ---
def show_legend():
    with st.expander("📖 PANDUAN: Cara Membaca Data & Legend (Klik Disini)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 🎯 Arti Skor AI")
            st.info("""
            * **Skor > 3.0 (STRONG BUY):** Sempurna. Trend naik + Harga murah + Volume besar.
            * **Skor 1.5 - 3.0 (BUY):** Bagus. Memenuhi sebagian besar kriteria.
            * **Skor 0.5 - 1.5 (HOLD/WATCH):** Netral. Masuk watchlist dulu.
            * **Skor < 0 (SELL/AVOID):** Buruk. Trend turun atau harga kemahalan.
            """)
        with c2:
            st.markdown("### 💡 Istilah Teknis")
            st.write("""
            * **RSI Oversold (<30):** Ibarat barang diskon besar-besaran (Waktunya beli).
            * **MACD Golden Cross:** Sinyal awal perubahan arah trend menjadi naik.
            * **Hammer/Engulfing:** Bentuk lilin (candle) yang menandakan pembeli mulai masuk dominan.
            """)

# --- FITUR SCREENER ---
def run_screener():
    st.header("🔍 Smart Stock Screener")
    show_legend()
    
    # INPUT USER: MINIMAL SKOR
    c_filter, c_btn = st.columns([3, 1])
    with c_filter:
        min_score = st.slider("Atur Ketatnya Seleksi (Minimal Skor)", min_value=0.0, max_value=4.0, value=1.0, step=0.5, help="Geser ke kiri (0.5) untuk melihat lebih banyak saham. Geser ke kanan (2.5) untuk saham yang sangat perfect saja.")
    
    if c_btn.button("SCAN SEKARANG"):
        progress = st.progress(0)
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        try:
            data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
            
            for i, t in enumerate(tickers):
                progress.progress((i+1)/len(tickers))
                try:
                    df = data[t].copy()
                    df = fix_dataframe(df)
                    if df.empty: continue
                    
                    df = calculate_technical(df)
                    score, reasons, last_row = get_final_analysis(df)
                    
                    # Filter berdasarkan Slider User
                    if score >= min_score: 
                        rec = "STRONG BUY 🔥" if score >= 2.5 else "BUY ✅"
                        if score < 1.5: rec = "WATCHLIST 👀"
                        
                        results.append({
                            "Kode": t.replace(".JK",""),
                            "Harga": int(last_row['Close']),
                            "Rekomendasi": rec,
                            "Skor AI": score,
                            "Alasan": ", ".join(reasons)
                        })
                except: continue
        except Exception as e:
            st.error("Gagal mengambil data. Coba refresh.")
            
        progress.empty()
        
        if results:
            st.success(f"Ditemukan {len(results)} Saham dengan Skor >= {min_score}")
            df_res = pd.DataFrame(results).sort_values("Skor AI", ascending=False)
            st.dataframe(
                df_res.style.background_gradient(subset=['Skor AI'], cmap='RdYlGn'),
                use_container_width=True
            )
            st.caption("*Tips: Masukkan kode saham di menu sebelah kiri (Sidebar) untuk melihat chart detailnya.*")
        else:
            st.warning(f"Tidak ada saham dengan skor >= {min_score}. Coba turunkan slider 'Minimal Skor' ke angka lebih kecil (misal 0.5).")

# --- FITUR CHART ---
def show_chart():
    st.header("📊 Detail Analisa Chart")
    show_legend()
    
    # Input Ticker dipindah ke halaman utama agar lebih jelas
    col_input, col_info = st.columns([1, 2])
    with col_input:
        ticker = st.text_input("Ketik Kode Saham", "ANTM").upper()
    
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        try:
            df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
            df = fix_dataframe(df)
            df = calculate_technical(df)
            
            if not df.empty:
                score, reasons, last = get_final_analysis(df)
                
                # TAMPILAN SKOR BESAR
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Harga Terakhir", f"Rp {int(last['Close']):,}")
                c2.metric("Skor AI", f"{score}/4.0", delta_color="normal" if score < 1.5 else "inverse")
                c3.metric("Rekomendasi", "STRONG BUY 🔥" if score>=2.5 else ("BUY ✅" if score>=1.5 else "WAIT ✋"))
                
                st.write("**Alasan Analisa:**")
                for r in reasons:
                    st.write(f"- {r}")
                
                # CHART
                st.subheader(f"Grafik {ticker}")
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                
                # Candle
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
                
                # Marker untuk Pola Candle (Visual)
                # Menandai candle terakhir jika ada pola
                _, patterns = check_candlestick_patterns(df.iloc[-1], df.iloc[-2])
                if patterns:
                     fig.add_annotation(x=df.index[-1], y=df['High'].iloc[-1], text=patterns[0], showarrow=True, arrowhead=1)

                # Indikator di Chart
                if 'BBU_20_2.0' in df.columns:
                    fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot', width=1), name='Upper BB'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot', width=1), name='Lower BB'), row=1, col=1)

                # Volume
                colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
                fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
                
                fig.update_layout(xaxis_rangeslider_visible=False, height=600, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Data tidak ditemukan.")
        except Exception as e:
            st.error(f"Error: {e}")

# --- MAIN NAVIGATION ---
st.sidebar.title("Menu Aplikasi")
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Screener (Cari Saham)", "📊 Detail Chart"])

if mode == "🔍 Screener (Cari Saham)":
    run_screener()
else:
    show_chart()
 
