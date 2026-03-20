import os
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- 1. AMBIL KUNCI RAHASIA DARI GITHUB SECRETS ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
IDX_API_KEY = os.getenv("IDX_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]

# --- 2. FUNGSI TEKNIKAL & PENDETEKSI HARI LIBUR ---
def check_candlestick_patterns(curr, prev):
    score = 0; patterns = []
    try:
        body = abs(curr['Close'] - curr['Open'])
        upper = curr['High'] - max(curr['Close'], curr['Open'])
        lower = min(curr['Close'], curr['Open']) - curr['Low']
        rsi = curr.get('Rsi', 50)
        lower_bb = curr.get('BBL_20_2.0', 0)
        is_valid_support = (rsi < 40) or (curr['Low'] <= lower_bb * 1.01)

        if (lower > 2 * body) and (upper < body):
            if is_valid_support: score += 1; patterns.append("🔨 Hammer")
        if (prev['Close'] < prev['Open']) and (curr['Close'] > curr['Open']): 
            if (curr['Open'] < prev['Close']) and (curr['Close'] > prev['Open']):
                if is_valid_support: score += 1.5; patterns.append("🦁 Engulfing")
    except: pass
    return score, patterns

def get_ihsg_data():
    try:
        ihsg = yf.download("^JKSE", period="1y", auto_adjust=True, progress=False)
        if isinstance(ihsg.columns, pd.MultiIndex): ihsg.columns = ihsg.columns.get_level_values(0)
        ihsg.columns = [str(c).capitalize() for c in ihsg.columns]
        return ihsg[['Close']].rename(columns={'Close': 'IHSG_Close'})
    except: return pd.DataFrame()

# 🧠 OTAK BARU: Pendeteksi Tanggal Bursa Terakhir yang Valid
def get_idx_target_date(df):
    wib_time = datetime.utcnow() + timedelta(hours=7)
    latest_yf_date = df.index[-1].date()
    if latest_yf_date == wib_time.date() and wib_time.hour < 18:
        return df.index[-2].strftime('%Y-%m-%d') if len(df) > 1 else df.index[-1].strftime('%Y-%m-%d')
    else:
        return df.index[-1].strftime('%Y-%m-%d')

# --- 3. PROSES UTAMA SCREENING ---
print(f"[{datetime.utcnow()}] 🚀 Memulai Auto-Screening JII30...")
ihsg_df = get_ihsg_data()
tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
price_data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False, threads=True)

results = []

for t in tickers:
    try:
        df = price_data[t].copy()
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).capitalize() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        
        if df.empty or len(df) < 50 or df['Volume'].iloc[-1] < 5000000: continue
        
        # 🎯 Menentukan Tanggal Anti-Libur untuk API GOAPI
        target_date = get_idx_target_date(df)
        
        df['Rsi'] = df.ta.rsi(length=14)
        df = pd.concat([df, df.ta.macd(fast=12, slow=26, signal=9), df.ta.bbands(length=20, std=2)], axis=1)
        df['SMA20'] = df.ta.sma(length=20); df['SMA50'] = df.ta.sma(length=50)
        df['SMA100'] = df.ta.sma(length=100); df['EMA200'] = df.ta.ema(length=200)
        df['ATR'] = df.ta.atr(length=14)
        
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / (df['High'] - df['Low'])) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
        
        if not ihsg_df.empty:
            df = df.join(ihsg_df, how='left')
            df['IHSG_Close'] = df['IHSG_Close'].ffill() 
            df['Stock_Ret_20'] = (df['Close'] - df['Close'].shift(20)) / df['Close'].shift(20)
            df['IHSG_Ret_20'] = (df['IHSG_Close'] - df['IHSG_Close'].shift(20)) / df['IHSG_Close'].shift(20)

        curr, prev = df.iloc[-1], df.iloc[-2]
        close, volume, atr = curr['Close'], curr['Volume'], curr.get('ATR', 0)
        
        score = 0; reasons = []
        if curr['Close'] > curr.get('EMA200', 0): score += 1; reasons.append("📈 Uptrend")
        if curr.get('Stock_Ret_20', 0) > curr.get('IHSG_Ret_20', 0): score += 1.5; reasons.append("🌟 IHSG")
        if curr.get('CMF', 0) > 0.1: score += 2; reasons.append("🐳 CMF")
        if curr.get('Rsi', 50) < 35: score += 2; reasons.append("💎 RSI")
        s_candle, _ = check_candlestick_patterns(curr, prev)
        score += s_candle
        
        wyckoff = "Sideways"
        if close > curr.get('SMA50', 0): wyckoff = "Markup" if close > curr.get('SMA20', 0) else "Distribution"
        else: wyckoff = "Markdown" if close < curr.get('SMA20', 0) else "Accumulation"

        rec = "WAIT"
        if score >= 4 or "Accumulation" in wyckoff: rec = "✅ BUY"
        if score >= 6: rec = "💎 STRONG BUY"
        
        if score < 3 and "Accumulation" not in wyckoff: continue 

        # 4. TARIK DATA ASING DENGAN TANGGAL ANTI-LIBUR
        symbol = t.replace(".JK", "")
        net_foreign, avg_buy_price, power_pct = 0, 0, 0
        
        url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
        res_broker = requests.get(url_broker, headers={'accept': 'application/json', 'X-API-KEY': IDX_API_KEY})
        if res_broker.status_code == 200:
            data = res_broker.json().get('data', {}).get('results', [])
            buy_val = sum(b['value'] for b in data if b['side'] == 'BUY')
            buy_lot = sum(b['lot'] for b in data if b['side'] == 'BUY')
            sell_val = sum(b['value'] for b in data if b['side'] == 'SELL')
            net_foreign = buy_val - sell_val
            if buy_lot > 0: avg_buy_price = buy_val / (buy_lot * 100)
            if (close * volume) > 0: power_pct = (abs(net_foreign) / (close * volume)) * 100

        if net_foreign <= 0: continue 

        target_profit = close + (3.0 * atr) if atr > 0 else close * 1.1
        stop_loss = close - (1.5 * atr) if atr > 0 else close * 0.9

        results.append({
            "fetch_date": target_date,
            "kode": symbol,
            "harga": int(close),
            "tp": int(target_profit),
            "sl": int(stop_loss),
            "fase": wyckoff,
            "power_asing": float(power_pct),
            "modal_asing": int(avg_buy_price),
            "status": rec,
            "katalis": ", ".join(reasons)
        })
        print(f"✅ Lolos: {symbol} (Tgl: {target_date})")
    except Exception as e:
        print(f"❌ Error {t}: {e}")

# --- 5. SIMPAN KE SUPABASE ---
if results:
    # Hapus data sebelumnya di tanggal yang sama (mencegah duplikat)
    unique_dates = list(set([r['fetch_date'] for r in results]))
    for d in unique_dates:
        supabase.table('jii30_daily_data').delete().eq('fetch_date', d).execute()
        
    supabase.table('jii30_daily_data').insert(results).execute()
    print(f"[{datetime.utcnow()}] 🎉 Sukses menyimpan {len(results)} saham ke Database!")
else:
    print(f"[{datetime.utcnow()}] ⚠️ Tidak ada saham yang lolos kriteria.")