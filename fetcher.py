import os
import numpy as np
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- TAHAP 4: IMPORT MACHINE LEARNING ---
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

# --- 1. AMBIL KUNCI RAHASIA DARI GITHUB SECRETS ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
IDX_API_KEY = os.getenv("IDX_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]

# --- 2. FUNGSI TEKNIKAL ---
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

def get_idx_target_date(df):
    return df.index[-1].strftime('%Y-%m-%d')

# --- 3. PENGUMPULAN DATA & KALKULASI ---
print(f"[{datetime.utcnow()}] 🚀 Memulai Auto-Screening, Quant Ranking, & AI Prediction JII30...")
ihsg_df = get_ihsg_data()
tickers = [f"{s}.JK" for s in SHARIA_STOCKS]
price_data = yf.download(tickers, period="2y", group_by='ticker', auto_adjust=True, progress=False, threads=True) # Tambah periode ke 2y utk ML

raw_data_list = []

for t in tickers:
    try:
        df = price_data[t].copy()
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).capitalize() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]

        df = df[df['Volume'] > 0]
        if df.empty or len(df) < 50: continue

        if df['Volume'].iloc[-1] < 5000000:
            continue

        target_date = get_idx_target_date(df)

        df['Rsi'] = df.ta.rsi(length=14)
        df = pd.concat([df, df.ta.macd(fast=12, slow=26, signal=9), df.ta.bbands(length=20, std=2)], axis=1)
        df['SMA20'] = df.ta.sma(length=20); df['SMA50'] = df.ta.sma(length=50)
        df['SMA100'] = df.ta.sma(length=100); df['EMA200'] = df.ta.ema(length=200)
        df['ATR'] = df.ta.atr(length=14)

        donchian = df.ta.donchian(lower_length=20, upper_length=20)
        if donchian is not None: df = pd.concat([df, donchian], axis=1)

        high_low_diff = df['High'] - df['Low']
        high_low_diff = high_low_diff.replace(0, 0.0001)
        ad = ((2 * df['Close'] - df['High'] - df['Low']) / high_low_diff) * df['Volume']
        df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
        df['Ret_1'] = df['Close'].pct_change() # Kinerja Harian untuk AI

        if not ihsg_df.empty:
            df = df.join(ihsg_df, how='left')
            df['IHSG_Close'] = df['IHSG_Close'].ffill()
            df['Stock_Ret_20'] = (df['Close'] - df['Close'].shift(20)) / df['Close'].shift(20)
            df['IHSG_Ret_20'] = (df['IHSG_Close'] - df['IHSG_Close'].shift(20)) / df['IHSG_Close'].shift(20)

        # --- TAHAP 4: MACHINE LEARNING (K-Nearest Neighbors) ---
        prob_up = 0.5
        try:
            # 1. Labeling: Apakah besoknya naik (1) atau turun (0)?
            df['Target_Besok'] = (df['Close'].shift(-1) > df['Close']).astype(int)
            
            # 2. Siapkan Data Pembelajaran AI (Tanpa baris terakhir karena besok belum terjadi)
            ml_df = df[['Rsi', 'CMF', 'Ret_1', 'Target_Besok']].dropna()
            
            if len(ml_df) > 100: # Syarat AI jalan: Harus ada minimal 100 hari histori
                X = ml_df[['Rsi', 'CMF', 'Ret_1']]
                y = ml_df['Target_Besok']
                
                # Standarisasi Skala Data
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)
                
                # Latih AI (Mencari 5 tetangga terdekat)
                knn = KNeighborsClassifier(n_neighbors=5)
                knn.fit(X_scaled, y)
                
                # Prediksi Hari Ini
                today_features = pd.DataFrame({'Rsi': [df['Rsi'].iloc[-1]], 'CMF': [df['CMF'].iloc[-1]], 'Ret_1': [df['Ret_1'].iloc[-1]]})
                today_scaled = scaler.transform(today_features)
                
                # Ambil Probabilitas Naik (Class 1)
                prob_up = knn.predict_proba(today_scaled)[0][1]
        except Exception as e:
            print(f"⚠️ AI Error {t}: {e}")

        curr, prev = df.iloc[-1], df.iloc[-2]
        close, volume, atr = curr['Close'], curr['Volume'], curr.get('ATR', 0)
        ret_20 = curr.get('Stock_Ret_20', 0) 

        score = 0; reasons = []
        if curr['Close'] > curr.get('EMA200', 0): score += 1; reasons.append("📈 Uptrend")
        if ret_20 > curr.get('IHSG_Ret_20', 0): score += 1.5; reasons.append("🌟 IHSG")
        if curr.get('CMF', 0) > 0.1: score += 2; reasons.append("🐳 CMF")
        if curr.get('Rsi', 50) < 35: score += 2; reasons.append("💎 RSI")
        
        dcu = curr.get('DCU_20_20', 0)
        if pd.notna(dcu) and dcu > 0 and curr['Close'] >= (dcu * 0.99):
            score += 1.5; reasons.append("🚀 Breakout DC")
        
        # Injeksi Sinyal AI ke dalam Katalis
        if prob_up >= 0.7: 
            score += 2.0; reasons.append(f"🤖 AI Bullish ({int(prob_up*100)}%)")
        
        s_candle, _ = check_candlestick_patterns(curr, prev)
        score += s_candle

        wyckoff = "Sideways"
        if close > curr.get('SMA50', 0): wyckoff = "Markup" if close > curr.get('SMA20', 0) else "Distribution"
        else: wyckoff = "Markdown" if close < curr.get('SMA20', 0) else "Accumulation"

        try:
            info = yf.Ticker(t).info
            pbv = info.get('priceToBook', 0)
            bp_ratio = (1 / pbv) if (pd.notna(pbv) and pbv > 0) else 0
            sector = info.get('sector', 'Unknown') 
        except: bp_ratio = 0; sector = 'Unknown'

        try:
            if len(df) >= 125:
                mom_6m = (curr['Close'] / df['Close'].iloc[-125]) - 1
                vol_6m = df['Close'].pct_change().tail(125).std() * np.sqrt(252)
            else:
                mom_6m = 0; vol_6m = 999
        except: mom_6m = 0; vol_6m = 999

        raw_data_list.append({
            'ticker': t, 'symbol': t.replace(".JK", ""), 'close': close, 'volume': volume, 
            'atr': atr, 'target_date': target_date, 'wyckoff': wyckoff, 
            'base_score': score, 'reasons': reasons, 'ret_20': ret_20,
            'mom_6m': mom_6m, 'vol_6m': vol_6m, 'bp_ratio': bp_ratio, 'sector': sector
        })
    except Exception as e:
        print(f"❌ Error Fetching {t}: {e}")

# --- 4. CROSS-SECTIONAL RANKING & MEAN-REVERSION ---
results = []
if raw_data_list:
    print("📊 Menjalankan Cross-Sectional & Sectoral Ranking...")
    df_quant = pd.DataFrame(raw_data_list)
    
    df_quant['mom_rank'] = df_quant['mom_6m'].rank(pct=True)
    df_quant['vol_rank'] = df_quant['vol_6m'].rank(ascending=False, pct=True) 
    df_quant['bp_rank'] = df_quant['bp_ratio'].rank(pct=True)

    df_quant['sector_mean_ret'] = df_quant.groupby('sector')['ret_20'].transform('mean')
    df_quant['sector_diff'] = df_quant['ret_20'] - df_quant['sector_mean_ret']
    df_quant['mr_rank'] = df_quant['sector_diff'].rank(ascending=True, pct=True)

    for index, row in df_quant.iterrows():
        symbol = row['symbol']
        final_score = row['base_score']
        reasons = row['reasons'].copy()
        
        if row['mom_rank'] >= 0.8: final_score += 1.5; reasons.append("🔥 Top Momentum")
        if row['vol_rank'] >= 0.8: final_score += 1.0; reasons.append("🛡️ Low Volatility")
        if row['bp_rank'] >= 0.8: final_score += 1.5; reasons.append("💰 Undervalued")

        if row['mr_rank'] <= 0.2 and row['sector_diff'] < 0:
            final_score += 2.0  
            reasons.append(f"🔄 Rebound {row['sector'][:8]}") 

        wyckoff = row['wyckoff']
        rec = "WAIT"
        if final_score >= 4.5 or "Accumulation" in wyckoff: rec = "✅ BUY"
        if final_score >= 8.0: rec = "💎 STRONG BUY"

        if final_score < 3.5 and "Accumulation" not in wyckoff:
            continue 

        target_date = row['target_date']
        close, volume, atr = row['close'], row['volume'], row['atr']
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
        print(f"✅ LOLOS: {symbol} | Katalis: {', '.join(reasons)}")

# --- 5. SIMPAN KE SUPABASE ---
if results:
    try:
        supabase.table('jii30_daily_data').delete().neq('id', 0).execute()
        print("🧹 Database lama berhasil dibersihkan.")
    except Exception as e:
        print(f"Gagal membersihkan database: {e}")

    supabase.table('jii30_daily_data').insert(results).execute()
    print(f"[{datetime.utcnow()}] 🎉 Sukses menyimpan {len(results)} saham ke Database!")
else:
    print(f"[{datetime.utcnow()}] ⚠️ Tidak ada saham yang lolos uji Kuanta hari ini.")