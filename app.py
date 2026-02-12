import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sharia Stock Screener", layout="wide", page_icon="☪️")

# --- DAFTAR SAHAM SYARIAH (JII 30 - Liquid) ---
# Anda bisa menambah daftar ini sendiri nanti
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- 1. FUNGSI ANALISA TEKNIKAL (INTI) ---
def calculate_technical(df):
    # RSI
    df['RSI'] = df.ta.rsi(length=14)
    
    # MACD
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    
    # Bollinger Bands
    bbands = df.ta.bbands(length=20, std=2)
    df = pd.concat([df, bbands], axis=1)
    
    # Volume MA
    df['VOL_MA_20'] = df['Volume'].rolling(window=20).mean()
    
    return df

def get_signal_score(row):
    score = 0
    reasons = []
    
    # MACD (Trend)
    if row['MACD_12_26_9'] > row['MACDs_12_26_9']:
        score += 1
    else:
        score -= 1

    # RSI (Momentum)
    if row['RSI'] < 30: score += 2  # Oversold (Murah)
    elif row['RSI'] > 70: score -= 2 # Overbought (Mahal)
    
    # Volume Breakout
    if row['Volume'] > (1.5 * row['VOL_MA_20']):
        score += 0.5
        
    return score

# --- 2. FITUR SCREENER (SCANNER) ---
def run_screener():
    st.header("🔍 Market Screener (Saham Syariah JII)")
    
    if st.button("Mulai Scan Pasar (Butuh ~10 Detik)"):
        progress_bar = st.progress(0)
        results = []
        
        # Tambahkan .JK
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        # Download Bulk Data (Supaya Cepat)
        # Kita ambil 6 bulan data
        data = yf.download(tickers, period="6mo", group_by='ticker', progress=False, threads=True)
        
        total = len(tickers)
        for i, ticker_raw in enumerate(tickers):
            # Update Progress
            progress_bar.progress((i + 1) / total)
            
            try:
                # Extract data per saham
                df_stock = data[ticker_raw].copy()
                
                # Bersihkan data kosong
                df_stock.dropna(inplace=True)
                
                if df_stock.empty: continue

                # Hitung Indikator
                df_stock = calculate_technical(df_stock)
                
                # Ambil data hari terakhir
                last_row = df_stock.iloc[-1]
                
                # Hitung Skor
                score = get_signal_score(last_row)
                
                # Filter: Hanya tampilkan yang sinyalnya BUY
                if score >= 1:
                    rec = "STRONG BUY" if score >= 2 else "BUY"
                    results.append({
                        "Kode": ticker_raw.replace(".JK", ""),
                        "Harga": last_row['Close'],
                        "RSI": round(last_row['RSI'], 2),
                        "Rekomendasi": rec,
                        "Score": score
                    })
                    
            except Exception as e:
                continue
                
        progress_bar.empty()
        
        if len(results) > 0:
            st.success(f"Ditemukan {len(results)} Saham Potensial!")
            # Buat DataFrame
            df_res = pd.DataFrame(results)
            # Sorting berdasarkan Score tertinggi
            df_res = df_res.sort_values(by="Score", ascending=False)
            
            st.dataframe(df_res, use_container_width=True)
            st.info("Catat kode saham di atas, lalu cek detail chartnya di menu 'Single Analysis'.")
        else:
            st.warning("Sedang tidak ada sinyal BUY yang kuat saat ini. Pasar mungkin sedang bearish.")

# --- 3. FITUR CHART DETAIL (SINGLE) ---
def show_single_chart():
    st.header("📊 Detail Chart Analysis")
    ticker = st.text_input("Masukkan Kode Saham dari Hasil Scan", value="ADRO").upper()
    
    if ticker:
        symbol = f"{ticker}.JK"
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        
        if not df.empty:
            df = calculate_technical(df)
            
            # Chart Harga & Volume
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
            
            # Candlestick
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'],
                                         low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
            
            # Bollinger Bands
            fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot'), name='Upper BB'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot'), name='Lower BB'), row=1, col=1)

            # Volume
            colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
            
            fig.update_layout(xaxis_rangeslider_visible=False, height=600)
            st.plotly_chart(fig, use_container_width=True)
            
            # Tampilkan Indikator Terakhir
            last = df.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric("RSI", f"{last['RSI']:.2f}")
            c2.metric("MACD", f"{last['MACD_12_26_9']:.2f}")
            c3.metric("Volume", f"{int(last['Volume']):,}")
            
        else:
            st.error("Saham tidak ditemukan.")

# --- MAIN LAYOUT ---
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Market Screener (Cari Saham)", "📊 Single Chart (Lihat Detail)"])

if mode == "🔍 Market Screener (Cari Saham)":
    run_screener()
else:
    show_single_chart()

