import os
import yfinance as yf
import pandas as pd
from supabase import create_client, Client

# --- 1. SETUP & KUNCI RAHASIA ---
# Pastikan Anda sudah mengatur variable environment, atau ganti langsung dengan string "url_anda" dan "key_anda" untuk sementara
SUPABASE_URL = os.getenv("SUPABASE_URL", "MASUKKAN_URL_SUPABASE_ANDA_DI_SINI")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "MASUKKAN_KEY_SUPABASE_ANDA_DI_SINI")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# DAFTAR SAHAM (Sama seperti di fetcher)
SHARIA_STOCKS = ["ADRO", "AKRA", "ANTM", "BRIS", "BRPT", "CPIN", "EXCL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ITMG", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SMGR", "TLKM", "UNTR", "UNVR", "ACES", "AMRT", "ASII", "TPIA"]
US_STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "LLY", "JPM", "V", "MA", "UNH", "HD", "PG", "COST", "JNJ", "NFLX", "AMD", "CRM"]

def fetch_and_seed_10_years(stock_list, is_indonesia=True):
    for raw_symbol in stock_list:
        symbol = f"{raw_symbol}.JK" if is_indonesia else raw_symbol
        print(f"🔄 Mengunduh histori 10 tahun untuk {symbol}...")
        
        try:
            # Tarik data 10 tahun
            df = yf.download(symbol, period="10y", auto_adjust=True, progress=False)
            
            if df.empty:
                print(f"⚠️ Data kosong untuk {symbol}. Lewati.")
                continue

            # Perbaiki MultiIndex jika ada (Bawaan yfinance terbaru)
            if isinstance(df.columns, pd.MultiIndex): 
                df.columns = df.columns.get_level_values(0)
            
            # Ubah index Date menjadi kolom biasa
            df.reset_index(inplace=True)
            
            records = []
            for _, row in df.iterrows():
                # Abaikan baris yang harganya NaN (biasanya hari libur tapi terekam)
                if pd.isna(row['Close']): continue
                
                records.append({
                    "symbol": raw_symbol, # Simpan TANPA .JK agar seragam dengan aplikasi
                    "date": row['Date'].strftime('%Y-%m-%d'),
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": int(row['Volume']) if pd.notna(row['Volume']) else 0
                })

            # --- TEKNIK CHUNKING (PENGIRIMAN BERTAHAP) ---
            # Data 10 tahun = ~2500 baris. Supabase bisa error jika dikirim sekaligus.
            # Kita potong-potong menjadi paket berisi 500 baris.
            chunk_size = 500
            for i in range(0, len(records), chunk_size):
                chunk = records[i:i + chunk_size]
                # Gunakan UPSERT: Jika tanggal sudah ada, update harganya. Jika belum, tambah baru.
                supabase.table('historical_prices').upsert(chunk).execute()
                
            print(f"✅ Sukses! {len(records)} hari perdagangan {symbol} tersimpan di Supabase.")
            
        except Exception as e:
            print(f"❌ Error memproses {symbol}: {e}")

if __name__ == "__main__":
    print("🚀 MEMULAI PROSES INJEKSI DATA HISTORIS MASAL...")
    print("-" * 50)
    
    print("📦 TAHAP 1: Pasar Saham Syariah Indonesia (JII30)")
    fetch_and_seed_10_years(SHARIA_STOCKS, is_indonesia=True)
    
    print("\n📦 TAHAP 2: Pasar Wall Street (US Big Caps)")
    fetch_and_seed_10_years(US_STOCKS, is_indonesia=False)
    
    print("-" * 50)
    print("🎉 SELURUH DATA BERHASIL DI-SEEDING KE DATABASE!")
