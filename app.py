import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sharia Stock AI", layout="wide", page_icon="📈")

# --- 2. CSS FIX (AGAR JELAS DI DARK MODE) ---
# Kode ini memaksa kotak angka berwarna terang dengan tulisan HITAM
st.markdown("""
<style>
    /* Mengubah tampilan Metric Card */
    div[data-testid="stMetric"] {
        background-color: #f0f2f6 !important; /* Latar belakang abu-abu terang */
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #d6d6d6;
        color: black !important;
    }
    
    /* Memaksa Label (Judul kecil) menjadi abu-abu gelap */
    div[data-testid="stMetricLabel"] p {
        color: #31333F !important;
    }
    
    /* Memaksa Value (Angka besar) menjadi hitam pekat */
    div[data-testid="stMetricValue"] div {
        color: #000000 !important;
    }
    
    /* Memaksa Delta (Persentase) agar tetap terlihat */
    div[data-testid="stMetricDelta"] div {
        color: inherit !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. DAFTAR SAHAM SYARIAH (JII 30) ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- 4. HELPER: PEMBERSIH DATA (PENTING) ---
def fix_dataframe(df):
    """Membersihkan format data yfinance agar bisa dihitung"""
    if df.empty: return df
    
    # Ratakan MultiIndex jika ada
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = df.columns.get_level_values(0)
        except: pass
        
    # Standarisasi Nama Kolom
    df.columns = [str(c).capitalize() for c in df.columns]
    
    # Hapus kolom duplikat (Solusi Error 'Cannot set DataFrame...')
    df = df.loc[:, ~df.columns.duplicated()]
    
    return df

# --- 5. FUNGSI DETEKSI POLA CANDLESTICK ---
def check_candlestick_patterns(curr, prev):
    pattern_score = 0
    pattern_name = []
    
    try:
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
            
    except: pass # Skip jika data tidak lengkap

    return pattern_score, pattern_name

# --- 6. FUNGSI ANALISA TEKNIKAL ---
def calculate_technical(df):
    df = fix_dataframe(df)
    
    try:
        # RSI
        rsi = df.ta.rsi(close=df['Close'], length=14)
        if isinstance(rsi, pd.DataFrame): rsi = rsi.iloc[:, 0]
        df['Rsi'] = rsi
        
        # MACD
        macd = df.ta.macd(close=df['Close'], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # Bollinger Bands
        bbands = df.ta.bbands(close=df['Close'], length=20, std=2)
        df = pd.concat([df, bbands], axis=1)
        
        # Volume MA
        col_vol = 'Volume' if 'Volume' in df.columns else 'Vol'
        if col_vol in df.columns:
            df['Vol_ma_20'] = df[col_vol].rolling(window=20).mean()
        else:
            df['Vol_ma_20'] = 0
            
    except: pass
    
    return df

# --- 7. LOGIKA SKOR FINAL (AI SCORE) ---
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
        score -= 1.0 

    # 2. RSI (Momentum) - Bobot: 1.5
    rsi = curr.get('Rsi', 50)
    if rsi < 35: 
        score += 1.5
        reasons.append("💎 Harga Diskon (RSI Oversold)")
    elif 35 <= rsi <= 60:
        score += 0.5 
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

# --- 8. FUNGSI TAMPILKAN LEGEND (PANDUAN) ---
def show_legend():
    with st.expander("📖 PANDUAN & LEGEND (Klik Disini)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 🎯 Arti Skor AI")
            st.info("""
            * **Skor > 2.5 (STRONG BUY):** Sempurna. Trend naik + Murah + Volume.
            * **Skor 1.5 - 2.5 (BUY):** Bagus. Memenuhi kriteria utama.
            * **Skor 0.5 - 1.5 (HOLD):** Netral. Masuk watchlist.
            * **Skor < 0 (AVOID):** Buruk/Mahal.
            """)
        with c2:
            st.markdown("### 💡 Istilah")
            st.write("""
            * **RSI Oversold:** Barang diskon (Waktunya beli).
            * **MACD Golden Cross:** Awal trend naik.
            * **Hammer:** Pola lilin pembalikan arah (Bullish).
            """)

# --- 9. FITUR SCREENER ---
def run_screener():
    st.header("🔍 Smart Stock Screener")
    show_legend()
    
    # Slider Sensitivitas
    c_filter, c_btn = st.columns([3, 1])
    with c_filter:
        min_score = st.slider("Atur Ketatnya Seleksi (Minimal Skor)", 0.0, 4.0, 1.0, 0.5)
    
    if c_btn.button("SCAN SEKARANG"):
        progress = st.progress(0)
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        try:
            # Download Data Bulk (Lebih Cepat)
            data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
            
            for i, t in enumerate(tickers):
                progress.progress((i+1)/len(tickers))
                try:
                    df = data[t].copy()
                    df = fix_dataframe(df)
                    if df.empty: continue
                    
                    df = calculate_technical(df)
                    score, reasons, last_row = get_final_analysis(df)
                    
                    if score >= min_score: 
                        rec = "STRONG BUY 🔥" if score >= 2.5 else "BUY ✅"
                        if score < 1.5: rec = "WATCH 👀"
                        
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
            st.success(f"Ditemukan {len(results)} Saham Pilihan!")
            df_res = pd.DataFrame(results).sort_values("Skor AI", ascending=False)
            
            # Tampilkan Tabel dengan Warna (Butuh matplotlib di requirements.txt)
            try:
                st.dataframe(
                    df_res.style.background_gradient(subset=['Skor AI'], cmap='RdYlGn'),
                    use_container_width=True
                )
            except:
                st.dataframe(df_res, use_container_width=True)
                
            st.caption("*Catat kode saham, lalu cek chart di menu sebelah kiri.*")
        else:
            st.warning(f"Tidak ada saham dengan skor >= {min_score}. Coba geser slider ke kiri.")

# --- 10. FITUR CHART ---
def show_chart():
    st.header("📊 Detail Analisa Chart")
    show_legend()
    
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
                
                # Perubahan Harga
                change = 0
                if len(df) > 1:
                    prev_close = df.iloc[-2]['Close']
                    change = ((last['Close'] - prev_close) / prev_close) * 100
                
                c1.metric("Harga Terakhir", f"Rp {int(last['Close']):,}", f"{change:.2f}%")
                c2.metric("Skor AI", f"{score}/4.0")
                c3.metric("Rekomendasi", "STRONG BUY 🔥" if score>=2.5 else ("BUY ✅" if score>=1.5 else "WAIT ✋"))
                
                st.write("**Alasan Analisa:**")
                for r in reasons:
                    st.write(f"- {r}")
                
                # CHART
                st.subheader(f"Grafik {ticker}")
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                
                # Candle
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
                
                # Marker untuk Pola Candle
                _, patterns = check_candlestick_patterns(df.iloc[-1], df.iloc[-2])
                if patterns:
                     fig.add_annotation(x=df.index[-1], y=df['High'].iloc[-1], text=patterns[0], showarrow=True, arrowhead=1)

                # Indikator
                if 'BBU_20_2.0' in df.columns:
                    fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot', width=1), name='Upper BB'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot', width=1), name='Lower BB'), row=1, col=1)

                # Volume
                colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
                fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
                
                fig.update_layout(xaxis_rangeslider_visible=False, height=600, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Data tidak ditemukan atau koneksi bermasalah.")
        except Exception as e:
            st.error(f"Error: {e}")

# --- MAIN NAVIGATION ---
st.sidebar.title("Menu Aplikasi")
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Screener (Cari Saham)", "📊 Detail Chart"])

if mode == "🔍 Screener (Cari Saham)":
    run_screener()
else:
    show_chart()
 
