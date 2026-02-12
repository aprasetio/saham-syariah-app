import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sharia Stock Screener", layout="wide", page_icon="☪️")

# --- DAFTAR SAHAM SYARIAH (JII 30) ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- HELPER: PEMBERSIH DATA (FIX ERROR) ---
def fix_dataframe(df):
    """
    Membersihkan DataFrame dari MultiIndex dan Kolom Duplikat
    agar tidak error saat dihitung pandas_ta.
    """
    if df.empty:
        return df
        
    # 1. Jika MultiIndex (Bertingkat), ambil level terbawah (Nama Ticker/Harga)
    if isinstance(df.columns, pd.MultiIndex):
        try:
            # Biasanya level 0 adalah Price (Open/Close), level 1 adalah Ticker
            # Kita drop level Ticker jika ada
            df.columns = df.columns.get_level_values(0)
        except:
            pass
    
    # 2. Standarisasi Nama Kolom (Huruf Depan Kapital)
    # Contoh: 'close' -> 'Close', 'Adj Close' -> 'Adj close'
    df.columns = [str(c).capitalize() for c in df.columns]
    
    # 3. HAPUS KOLOM DUPLIKAT (Ini penyebab utama error Anda)
    # Kadang ada dua kolom 'Close'. Kita ambil yang pertama saja.
    df = df.loc[:, ~df.columns.duplicated()]
    
    # 4. Pastikan kolom wajib ada
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_cols:
        if col not in df.columns:
            # Jika misal 'Volume' tidak ada, isi 0
            df[col] = 0
            
    # Kembalikan hanya kolom yang dibutuhkan agar bersih
    return df[required_cols]

# --- 1. FUNGSI ANALISA TEKNIKAL ---
def calculate_technical(df):
    # Pastikan data bersih dulu
    df = fix_dataframe(df)
    
    # Hitung RSI (Explicitly use Close column)
    # Gunakan .iloc untuk memastikan kita mengambil Series (1 dimensi)
    try:
        rsi_val = df.ta.rsi(close=df['Close'], length=14)
        # Jika hasilnya DataFrame (karena bug), paksa jadi Series
        if isinstance(rsi_val, pd.DataFrame):
            rsi_val = rsi_val.iloc[:, 0]
        df['Rsi'] = rsi_val
    except Exception:
        df['Rsi'] = 50 # Default jika gagal
    
    # Hitung MACD
    try:
        macd = df.ta.macd(close=df['Close'], fast=12, slow=26, signal=9)
        # macd return DataFrame, kita gabung aman
        df = pd.concat([df, macd], axis=1)
    except Exception:
        pass
        
    # Hitung Bollinger Bands
    try:
        bbands = df.ta.bbands(close=df['Close'], length=20, std=2)
        df = pd.concat([df, bbands], axis=1)
    except Exception:
        pass
    
    # Volume MA
    df['Vol_ma_20'] = df['Volume'].rolling(window=20).mean()
    
    return df

def get_signal_score(row):
    score = 0
    
    # Ambil nilai dengan aman (.get) agar tidak error jika kolom hilang
    # Nama kolom default MACD dari pandas-ta
    macd_val = row.get('MACD_12_26_9', 0)
    macd_sig = row.get('MACDs_12_26_9', 0)
    
    if macd_val > macd_sig: score += 1
    else: score -= 1

    # RSI
    rsi = row.get('Rsi', 50)
    if pd.isna(rsi): rsi = 50 # Handle NaN
    
    if rsi < 30: score += 2  
    elif rsi > 70: score -= 2 
    
    # Volume
    vol = row.get('Volume', 0)
    vol_ma = row.get('Vol_ma_20', 0)
    
    if vol_ma > 0 and vol > (1.5 * vol_ma):
        score += 0.5
        
    return score

# --- 2. FITUR SCREENER ---
def run_screener():
    st.header("🔍 Market Screener (Saham Syariah JII)")
    
    if st.button("Mulai Scan Pasar"):
        progress_bar = st.progress(0)
        results = []
        
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        # Download Data (Auto Adjust False agar struktur lebih stabil)
        data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        total = len(tickers)
        for i, ticker_raw in enumerate(tickers):
            progress_bar.progress((i + 1) / total)
            
            try:
                # Ambil data per saham
                # PENTING: .copy() agar tidak merusak data asli
                df_stock = data[ticker_raw].copy()
                
                # Bersihkan Data
                df_stock = fix_dataframe(df_stock)
                
                if df_stock.empty: continue
                
                # Drop baris NaN
                df_stock.dropna(subset=['Close'], inplace=True)

                # Analisa
                df_stock = calculate_technical(df_stock)
                last_row = df_stock.iloc[-1]
                
                score = get_signal_score(last_row)
                
                if score >= 1:
                    rec = "STRONG BUY" if score >= 2 else "BUY"
                    results.append({
                        "Kode": ticker_raw.replace(".JK", ""),
                        "Harga": last_row['Close'],
                        "RSI": round(last_row.get('Rsi', 0), 2),
                        "Rekomendasi": rec,
                        "Score": score
                    })
                    
            except Exception as e:
                # Skip saham yang error, jangan stop aplikasi
                continue
            
        progress_bar.empty()
        
        if len(results) > 0:
            st.success(f"Ditemukan {len(results)} Saham Potensial!")
            df_res = pd.DataFrame(results).sort_values(by="Score", ascending=False)
            st.dataframe(df_res, use_container_width=True)
        else:
            st.warning("Tidak ada sinyal BUY yang kuat saat ini.")

# --- 3. FITUR CHART DETAIL ---
def show_single_chart():
    st.header("📊 Detail Chart Analysis")
    ticker = st.text_input("Masukkan Kode Saham", value="ADRO").upper()
    
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        # Download data tunggal
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        
        # Bersihkan & Analisa
        df = calculate_technical(df)
        
        if not df.empty:
            # Chart
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
            
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'],
                                         low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
            
            # Bollinger (Cek kolom dulu)
            if 'BBU_20_2.0' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot'), name='Upper BB'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot'), name='Lower BB'), row=1, col=1)

            colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
            
            fig.update_layout(xaxis_rangeslider_visible=False, height=600)
            st.plotly_chart(fig, use_container_width=True)
            
            # Info
            last = df.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric("RSI", f"{last.get('Rsi', 0):.2f}")
            c2.metric("MACD", f"{last.get('MACD_12_26_9', 0):.2f}")
            c3.metric("Volume", f"{int(last.get('Volume', 0)):,}")
        else:
            st.error("Data saham tidak ditemukan.")

# --- MAIN LAYOUT ---
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Market Screener (Cari Saham)", "📊 Single Chart (Lihat Detail)"])

if mode == "🔍 Market Screener (Cari Saham)":
    run_screener()
else:
    show_single_chart()
