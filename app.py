import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sharia Stock AI", layout="wide", page_icon="📈")

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

# --- FUNGSI DETEKSI POLA CANDLESTICK (BARU!) ---
def check_candlestick_patterns(curr, prev):
    """
    Mendeteksi pola candle berdasarkan bentuk geometri
    curr = data hari ini (Current)
    prev = data kemarin (Previous)
    """
    pattern_score = 0
    pattern_name = []
    
    # Hitung ukuran candle hari ini
    body_size = abs(curr['Close'] - curr['Open'])
    upper_wick = curr['High'] - max(curr['Close'], curr['Open'])
    lower_wick = min(curr['Close'], curr['Open']) - curr['Low']
    total_range = curr['High'] - curr['Low']
    
    # 1. POLA HAMMER (Palu) - Sinyal Reversal Kuat
    # Syarat: Ekor bawah panjang (2x badan), ekor atas kecil, tren sedang turun (RSI < 50)
    if (lower_wick > 2 * body_size) and (upper_wick < body_size) and (curr['Rsi'] < 50):
        pattern_score += 1.5
        pattern_name.append("🔨 Hammer (Pantulan Kuat)")

    # 2. POLA BULLISH ENGULFING (Memakan)
    # Syarat: Kemarin Merah, Hari ini Hijau & Badan hari ini menutupi badan kemarin
    if (prev['Close'] < prev['Open']) and (curr['Close'] > curr['Open']): # Kemarin Merah, Skrg Hijau
        if (curr['Open'] < prev['Close']) and (curr['Close'] > prev['Open']):
            pattern_score += 2
            pattern_name.append("🦁 Bullish Engulfing (Dominasi Pembeli)")

    # 3. POLA DOJ (Ragu-ragu)
    # Syarat: Badan sangat tipis (Open mirip Close)
    if (body_size <= (0.1 * total_range)):
        pattern_name.append("✨ Doji (Pasar Galau)")
        # Doji netral, tapi jika muncul di RSI rendah bisa jadi tanda balik arah
        if curr['Rsi'] < 30:
            pattern_score += 0.5
            pattern_name.append("(Potensi Reversal)")

    return pattern_score, pattern_name

# --- FUNGSI ANALISA TEKNIKAL ---
def calculate_technical(df):
    df = fix_dataframe(df)
    
    # RSI
    try:
        rsi = df.ta.rsi(close=df['Close'], length=14)
        if isinstance(rsi, pd.DataFrame): rsi = rsi.iloc[:, 0]
        df['Rsi'] = rsi
    except: df['Rsi'] = 50
    
    # MACD
    try:
        macd = df.ta.macd(close=df['Close'], fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
    except: pass
    
    # Bollinger
    try:
        bbands = df.ta.bbands(close=df['Close'], length=20, std=2)
        df = pd.concat([df, bbands], axis=1)
    except: pass
    
    # Volume MA
    if 'Volume' in df.columns:
        df['Vol_ma_20'] = df['Volume'].rolling(window=20).mean()
    else:
        df['Volume'] = 0
        df['Vol_ma_20'] = 0
    
    return df

# --- LOGIKA SKOR FINAL ---
def get_final_analysis(df):
    if len(df) < 2: return 0, ["Data kurang"]
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    score = 0
    reasons = []
    
    # A. Indikator (MACD & RSI)
    macd_val = curr.get('MACD_12_26_9', 0)
    macd_sig = curr.get('MACDs_12_26_9', 0)
    
    if macd_val > macd_sig: 
        score += 1
        reasons.append("📈 Trend: MACD Naik")
    
    rsi = curr.get('Rsi', 50)
    if rsi < 30: 
        score += 1.5
        reasons.append("💎 Momentum: Oversold (Murah)")
    elif rsi > 70: 
        score -= 2
        reasons.append("⚠️ Momentum: Overbought (Mahal)")

    # B. Analisa Volume
    vol = curr.get('Volume', 0)
    vol_ma = curr.get('Vol_ma_20', 1)
    if vol > (1.5 * vol_ma):
        score += 0.5
        reasons.append("🚀 Volume: Ledakan Transaksi")

    # C. ANALISA CANDLESTICK (BARU!)
    candle_score, candle_patterns = check_candlestick_patterns(curr, prev)
    score += candle_score
    if candle_patterns:
        reasons.append(f"🕯️ Pola: {', '.join(candle_patterns)}")

    return score, reasons, curr

# --- FITUR SCREENER ---
def run_screener():
    st.header("🔍 Market Screener (Technical + Candlestick)")
    
    if st.button("Mulai Scan Pasar"):
        progress = st.progress(0)
        results = []
        tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
        
        data = yf.download(tickers, period="6mo", group_by='ticker', auto_adjust=True, progress=False, threads=True)
        
        for i, t in enumerate(tickers):
            progress.progress((i+1)/len(tickers))
            try:
                df = data[t].copy()
                df = fix_dataframe(df)
                if df.empty: continue
                
                df = calculate_technical(df)
                score, reasons, last_row = get_final_analysis(df)
                
                if score >= 1.5: # Ambang batas minimal
                    rec = "STRONG BUY" if score >= 2.5 else "BUY"
                    results.append({
                        "Saham": t.replace(".JK",""),
                        "Harga": int(last_row['Close']),
                        "RSI": round(last_row.get('Rsi', 0), 2),
                        "Sinyal": rec,
                        "Skor": score,
                        "Alasan Utama": ", ".join(reasons)
                    })
            except: continue
            
        progress.empty()
        
        if results:
            st.success(f"Ketemu {len(results)} Saham Pilihan!")
            st.dataframe(pd.DataFrame(results).sort_values("Skor", ascending=False), use_container_width=True)
        else:
            st.warning("Pasar sedang sepi sinyal bagus.")

# --- FITUR CHART ---
def show_chart():
    st.header("📊 Analisa Detail")
    ticker = st.text_input("Kode Saham", "ANTM").upper()
    if ticker:
        symbol = f"{ticker}.JK" if not ticker.endswith(".JK") else ticker
        df = yf.download(symbol, period="1y", auto_adjust=True, progress=False)
        df = calculate_technical(df)
        
        if not df.empty:
            score, reasons, last = get_final_analysis(df)
            
            st.subheader(f"Skor AI: {score} ({'Beli' if score > 1.5 else 'Wait/Jual'})")
            for r in reasons: st.write(f"- {r}")
            
            # Chart
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
            
            # Tambahkan Marker Pola Candle jika ada (Visualisasi)
            # Ini fitur visual canggih: Menandai Hammer di chart
            # Kita tandai candle terakhir saja
            if "Hammer" in str(reasons):
                fig.add_annotation(x=df.index[-1], y=df['Low'].iloc[-1], text="Hammer!", showarrow=True, arrowhead=1)

            colors = ['red' if row['Open'] - row['Close'] >= 0 else 'green' for index, row in df.iterrows()]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Vol'), row=2, col=1)
            fig.update_layout(xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)

# --- MAIN ---
mode = st.sidebar.radio("Menu", ["Screener (Scan)", "Chart (Detail)"])
if mode == "Screener (Scan)": run_screener()
else: show_chart()
 
