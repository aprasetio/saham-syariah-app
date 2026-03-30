import os
import numpy as np
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

# --- 1. SETUP & KUNCI RAHASIA ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
IDX_API_KEY = os.getenv("IDX_API_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# DAFTAR SAHAM
SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]
# 20 Saham Raksasa Wall Street (Bisa Anda tambah/ubah nanti)
US_STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "LLY", "JPM", "V", "MA", "UNH", "HD", "PG", "COST", "JNJ", "NFLX", "AMD", "CRM"]

# --- 2. FUNGSI TEKNIKAL (TETAP SAMA) ---
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

def get_benchmark_data(ticker):
    try:
        bm = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
        if isinstance(bm.columns, pd.MultiIndex): bm.columns = bm.columns.get_level_values(0)
        bm.columns = [str(c).capitalize() for c in bm.columns]
        return bm[['Close']].rename(columns={'Close': 'BM_Close'})
    except: return pd.DataFrame()

def get_target_date(df):
    return df.index[-1].strftime('%Y-%m-%d')

# --- 3. MESIN UTAMA (DIBUNGKUS DALAM FUNGSI AGAR BISA DIPAKAI 2 PASAR) ---
def run_screener(market_name, stock_list, benchmark_ticker, table_name, use_goapi=False):
    print(f"\n[{datetime.now(timezone.utc)}] 🚀 Memulai Scan & AI Predictor untuk {market_name}...")
    
    bm_df = get_benchmark_data(benchmark_ticker)
    
    # Tambahkan .JK hanya jika pasar Indonesia (use_goapi = True)
    tickers = [f"{s}.JK" if use_goapi else s for s in stock_list]
    price_data = yf.download(tickers, period="2y", group_by='ticker', auto_adjust=True, progress=False, threads=True) 

    raw_data_list = []

    for t in tickers:
        try:
            df = price_data[t].copy() if len(tickers) > 1 else price_data.copy()
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).capitalize() for c in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]

            df = df[df['Volume'] > 0]
            if df.empty or len(df) < 50: continue

            # Filter volume: 5 Juta untuk IDX, 1 Juta untuk Wall Street
            min_vol = 5000000 if use_goapi else 1000000
            if df['Volume'].iloc[-1] < min_vol: continue

            target_date = get_target_date(df)

            df['Rsi'] = df.ta.rsi(length=14)
            macd = df.ta.macd(fast=12, slow=26, signal=9)
            bbands = df.ta.bbands(length=20, std=2)
            
            to_concat = [df]
            if macd is not None: to_concat.append(macd)
            if bbands is not None: to_concat.append(bbands)
            df = pd.concat(to_concat, axis=1)

            df['SMA20'] = df.ta.sma(length=20); df['SMA50'] = df.ta.sma(length=50)
            df['SMA100'] = df.ta.sma(length=100); df['EMA200'] = df.ta.ema(length=200)
            df['ATR'] = df.ta.atr(length=14)

            donchian = df.ta.donchian(lower_length=20, upper_length=20)
            if donchian is not None: df = pd.concat([df, donchian], axis=1)

            high_low_diff = df['High'] - df['Low']
            high_low_diff = high_low_diff.replace(0, 0.0001)
            ad = ((2 * df['Close'] - df['High'] - df['Low']) / high_low_diff) * df['Volume']
            df['CMF'] = ad.fillna(0).rolling(window=20).sum() / df['Volume'].rolling(window=20).sum()
            df['Ret_1'] = df['Close'].pct_change() 

            if not bm_df.empty:
                df = df.join(bm_df, how='left')
                df['BM_Close'] = df['BM_Close'].ffill()
                df['Stock_Ret_20'] = (df['Close'] - df['Close'].shift(20)) / df['Close'].shift(20)
                df['BM_Ret_20'] = (df['BM_Close'] - df['BM_Close'].shift(20)) / df['BM_Close'].shift(20)

            # Fitur AI (KNN) Tetap Utuh
            prob_up = 0.5
            try:
                df['Target_Besok'] = (df['Close'].shift(-1) > df['Close']).astype(int)
                ml_df = df[['Rsi', 'CMF', 'Ret_1', 'Target_Besok']].dropna()
                if len(ml_df) > 100: 
                    X = ml_df[['Rsi', 'CMF', 'Ret_1']]
                    y = ml_df['Target_Besok']
                    scaler = StandardScaler()
                    X_scaled = scaler.fit_transform(X)
                    knn = KNeighborsClassifier(n_neighbors=5)
                    knn.fit(X_scaled, y)
                    today_features = pd.DataFrame({'Rsi': [df['Rsi'].iloc[-1]], 'CMF': [df['CMF'].iloc[-1]], 'Ret_1': [df['Ret_1'].iloc[-1]]})
                    today_scaled = scaler.transform(today_features)
                    prob_up = knn.predict_proba(today_scaled)[0][1]
            except: pass

            curr, prev = df.iloc[-1], df.iloc[-2]
            close, volume, atr = curr['Close'], curr['Volume'], curr.get('ATR', 0)
            ret_20 = curr.get('Stock_Ret_20', 0) 

            score = 0; reasons = []
            if curr['Close'] > curr.get('EMA200', 0): score += 1; reasons.append("📈 Uptrend")
            if ret_20 > curr.get('BM_Ret_20', 0): score += 1.5; reasons.append("🌟 Market Beat")
            if curr.get('CMF', 0) > 0.1: score += 2; reasons.append("🐳 CMF")
            if curr.get('Rsi', 50) < 35: score += 2; reasons.append("💎 RSI")
            
            dcu = curr.get('DCU_20_20', 0)
            if pd.notna(dcu) and dcu > 0 and curr['Close'] >= (dcu * 0.99):
                score += 1.5; reasons.append("🚀 Breakout DC")
            
            if prob_up >= 0.7: score += 2.0; reasons.append(f"🤖 AI Bullish ({int(prob_up*100)}%)")
            
            s_candle, p_candle = check_candlestick_patterns(curr, prev)
            score += s_candle
            reasons.extend(p_candle)

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
                else: mom_6m = 0; vol_6m = 999
            except: mom_6m = 0; vol_6m = 999

            raw_data_list.append({
                'symbol': t.replace(".JK", ""), 'close': close, 'volume': volume, 
                'atr': atr, 'target_date': target_date, 'wyckoff': wyckoff, 
                'base_score': score, 'reasons': reasons, 'ret_20': ret_20,
                'mom_6m': mom_6m, 'vol_6m': vol_6m, 'bp_ratio': bp_ratio, 'sector': sector
            })
        except Exception as e:
            pass

    # Ranking Cross-Sectional Tetap Utuh
    results = []
    if raw_data_list:
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
                final_score += 2.0; reasons.append(f"🔄 Rebound {row['sector'][:8]}") 

            wyckoff = row['wyckoff']
            rec = "WAIT"
            if final_score >= 4.5 or "Accumulation" in wyckoff: rec = "✅ BUY"
            if final_score >= 8.0: rec = "💎 STRONG BUY"

            if final_score < 3.5 and "Accumulation" not in wyckoff:
                continue 

            target_date = row['target_date']
            close, volume, atr = row['close'], row['volume'], row['atr']
            net_foreign, avg_buy_price, power_pct = 0, 0, 0

            # Logika GoAPI HANYA nyala untuk saham Indonesia
            if use_goapi:
                try:
                    url_broker = f"https://api.goapi.io/stock/idx/{symbol}/broker_summary?date={target_date}&investor=FOREIGN"
                    res_broker = requests.get(url_broker, headers={'accept': 'application/json', 'X-API-KEY': IDX_API_KEY}, timeout=10)
                    if res_broker.status_code == 200:
                        data = res_broker.json().get('data', {}).get('results', [])
                        buy_val = sum(b['value'] for b in data if b['side'] == 'BUY')
                        buy_lot = sum(b['lot'] for b in data if b['side'] == 'BUY')
                        sell_val = sum(b['value'] for b in data if b['side'] == 'SELL')
                        net_foreign = buy_val - sell_val
                        if buy_lot > 0: avg_buy_price = buy_val / (buy_lot * 100)
                        if (close * volume) > 0: power_pct = (abs(net_foreign) / (close * volume)) * 100
                except: pass
                
                # Syarat Lolos Asing (Hanya Berlaku di Indo)
                if net_foreign <= 0: continue

            target_profit = close + (3.0 * atr) if atr > 0 else close * 1.1
            stop_loss = close - (1.5 * atr) if atr > 0 else close * 0.9

            # Format Harga: JII30 Rupiah (Int), Wall Street Dollar (2 Desimal)
            format_harga = lambda x: int(x) if use_goapi else round(float(x), 2)

            results.append({
                "fetch_date": target_date,
                "kode": symbol,
                "harga": format_harga(close),
                "tp": format_harga(target_profit),
                "sl": format_harga(stop_loss),
                "fase": wyckoff,
                "power_asing": float(power_pct),
                "modal_asing": int(avg_buy_price) if use_goapi else 0,
                "status": rec,
                "katalis": ", ".join(reasons)
            })
            print(f"✅ LOLOS ({market_name}): {symbol} | Katalis: {', '.join(reasons)}")

    # Fitur "CASH IS KING" Tetap Utuh
    if not results:
        wib_date = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime('%Y-%m-%d')
        results.append({
            "fetch_date": wib_date, "kode": "CASH", "harga": 0, "tp": 0, "sl": 0,
            "fase": "Wait & See", "power_asing": 0.0, "modal_asing": 0,
            "status": "🛡️ CASH IS KING", "katalis": "Market rawan rontok! Tidak ada saham yang lolos hari ini."
        })
        print(f"⚠️ Mode CASH IS KING aktif untuk {market_name}.")

    try:
        supabase.table(table_name).delete().neq('id', 0).execute()
    except: pass

    supabase.table(table_name).insert(results).execute()
    print(f"[{datetime.now(timezone.utc)}] 🎉 Sukses menyimpan ke tabel: {table_name}")

# --- 4. EKSEKUSI JADWAL CRON (SMART SCHEDULER) ---
if __name__ == "__main__":
    # Cek jam saat robot berjalan (dalam waktu UTC)
    current_utc_hour = datetime.now(timezone.utc).hour

    # SHIFT 1: Sekitar jam 19:00 WIB (Sama dengan 12:00 UTC)
    if 10 <= current_utc_hour <= 15:
        print("🕒 Mode Shift 1 (Malam): Mengeksekusi Pasar Indonesia...")
        run_screener("JII30 (Indonesia)", SHARIA_STOCKS, "^JKSE", "jii30_daily_data", use_goapi=True)

    # SHIFT 2: Sekitar jam 05:00 WIB (Sama dengan 22:00 UTC)
    elif 20 <= current_utc_hour <= 23 or 0 <= current_utc_hour <= 2:
        print("🕒 Mode Shift 2 (Pagi): Mengeksekusi Pasar Wall Street...")
        run_screener("Wall Street (US)", US_STOCKS, "^GSPC", "us_daily_data", use_goapi=False)

    # MANUAL RUN: Jika Anda menekan tombol "Run workflow" secara manual di GitHub
    else:
        print("🕒 Mode Manual: Mengeksekusi Kedua Pasar secara berurutan...")
        run_screener("JII30 (Indonesia)", SHARIA_STOCKS, "^JKSE", "jii30_daily_data", use_goapi=True)
        run_screener("Wall Street (US)", US_STOCKS, "^GSPC", "us_daily_data", use_goapi=False)