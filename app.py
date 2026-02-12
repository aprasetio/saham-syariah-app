import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sharia Stock Screener", layout="wide", page_icon="☪️")

# --- DAFTAR SAHAM SYARIAH (JII 30 - Liquid) ---
SHARIA_STOCKS = [
    "ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", 
    "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", 
    "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", 
    "AMRT", "ASII", "TPIA"
]

# --- HELPER: PERBAIKI FORMAT DATA ---
def fix_dataframe(df):
    """Fungsi untuk mengatasi masalah MultiIndex dari yfinance"""
    if df.empty:
        return df
        
    # Jika kolomnya bertingkat (MultiIndex), ratakan ambil level terbawah
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    
    # Kadang yfinance menyisakan Ticker sebagai nama kolom, kita rename jadi standar
    # (Opsional, tapi aman dilakukan)
    df.columns = [c.capitalize() for c in df.columns]
    
    return df

# --- 1. FUNGSI ANALISA TEKNIKAL (INTI) ---
def calculate_technical(df):
    # Pastikan data sudah bersih sebelum masuk sini
    # RSI
    df['Rsi'] = df.ta.rsi(length=14)
    
    # MACD
    macd = df.ta.macd(fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    
    # Bollinger Bands
    bbands = df.ta.bbands(length=20, std=2)
    df = pd.concat([df, bbands], axis=1)
    
    # Volume MA
    # Pastikan kolom Volume ada (kadang yfinance namakan 'Volume', kadang 'Vol')
    vol_col = 'Volume' if 'Volume' in df.columns else 'Vol'
    if vol_col in df.columns:
        df['Vol_ma_20'] = df[vol_col].rolling(window=20).mean()
    
    return df

def get_signal_score(row):
    score = 0
    
    # Akses kolom dengan aman (menggunakan .get untuk menghindari error jika kolom tidak ada)
    # Nama kolom MACD standar pandas-ta: MACD_12_26_9, MACDs_12_26_9
    macd_val = row.get('MACD_12_26_9', 0)
    macd_sig = row.get('MACDs_12_26_9', 0)
    
    if macd_val > macd_sig:
        score += 1
    else:
        score -= 1

    # RSI
    rsi = row.get('Rsi', 50) # Default 50 jika error
    if rsi < 30: score += 2  
    elif rsi > 70: score -= 2 
    
    # Volume Breakout
    vol = row.get('Volume', 0)
    vol_ma = row.get('Vol_ma_20', 0)
    
    if vol_ma > 0 and vol > (1.5 * vol_ma):
        score += 0.5
        
    return score

# --- 2. FITUR SCREENER (SCANNER) ---
def run_screener():
    st.header("🔍 Market Screener (Saham Syariah JII)")
    
    if st.button("Mulai Scan Pasar (Butuh ~10 Detik)"):
        progress_bar = st.progress(0)
        results = []
        
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        # Download Bulk
        try:
            data = yf.download(tickers, period="6mo", group_by='ticker', progress=False, threads=True)
            
            total = len(tickers)
            for i, ticker_raw in enumerate(tickers):
                progress_bar.progress((i + 1) / total)
                
                try:
                    # Ambil data per ticker
                    # yfinance baru mengembalikan MultiIndex, kita slice dulu
                    df_stock = data[ticker_raw].copy()
                    
                    # PERBAIKAN: Ratakan index
                    df_stock = fix_dataframe(df_stock)
                    
                    df_stock.dropna(inplace=True)
                    if df_stock.empty: continue

                    # Hitung Indikator
                    df_stock = calculate_technical(df_stock)
                    last_row = df_stock.iloc[-1]
                    
                    score = get_signal_score(last_row)
                    
                    if score >= 1:
                        rec = "STRONG BUY" if score >= 2 else "BUY"
                        results.append({
                            "Kode": ticker_raw.replace(".JK", ""),
                            "Harga": last_row['Close'],
                            "RSI": round(last_row['Rsi'], 2),
                            "Rekomendasi": rec,
                            "Score": score
                        })
                        
                except Exception as e:
                    continue
            
            progress_bar.empty()
            
            if len(results) > 0:
                st.success(f"Ditemukan {len(results)} Saham Potensial!")
                df_res = pd.DataFrame(results)
                df_res = df_res.sort_values(by="Score", ascending=False)
                st.dataframe(df_res, use_container_width=True)
                st.info("Catat kode saham di atas, lalu cek detail chartnya di menu 'Single Analysis'.")
            else:
                st.warning("Tidak ada sinyal BUY yang kuat saat ini.")
                
        except Exception as main_e:
            st.error(f"Gagal mengambil data pasar: {main_e}")

# --- 3. FITUR CHART DETAIL (SINGLE) ---
def show_single_chart():
    st.header("📊 Detail Chart Analysis")
    ticker = st.text_input("Masukkan Kode Saham dari Hasil Scan", value="ADRO").upper()
    
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        
        # Ambil Data
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        
        # PERBAIKAN UTAMA DI SINI
        df = fix_dataframe(df)
        
        if not df.empty:
            try:
                df = calculate_technical(df)
                
                # Chart
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                
                # Candlestick
                fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'],
                                             low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
                
                # Bollinger Bands (Cek dulu kolomnya ada atau tidak)
                if 'BBU_20_2.0' in df.columns:
                    fig.add_trace(go.Scatter(x=df.index, y=df['BBU_20_2.0'], line=dict(color='gray', dash='dot'), name='Upper BB'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df.index, y=df['BBL_20_2.0'], line=dict(color='gray', dash='dot'), name='Lower BB'), row=1, col=1)

                # Volume
                colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
                fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
                
                fig.update_layout(xaxis_rangeslider_visible=False, height=600)
                st.plotly_chart(fig, use_container_width=True)
                
                # Indikator
                last = df.iloc[-1]
                c1, c2, c3 = st.columns(3)
                c1.metric("RSI", f"{last.get('Rsi', 0):.2f}")
                c2.metric("MACD", f"{last.get('MACD_12_26_9', 0):.2f}")
                c3.metric("Volume", f"{int(last.get('Volume', 0)):,}")
            
            except Exception as e:
                st.error(f"Terjadi kesalahan saat analisa: {e}")
                st.write("Debug info (Columns):", df.columns)
            
        else:
            st.error("Saham tidak ditemukan.")

# --- MAIN LAYOUT ---
mode = st.sidebar.radio("Pilih Mode:", ["🔍 Market Screener (Cari Saham)", "📊 Single Chart (Lihat Detail)"])

if mode == "🔍 Market Screener (Cari Saham)":
    run_screener()
else:
    show_single_chart()
