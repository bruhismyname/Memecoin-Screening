import numpy as np
import pandas as pd
import requests
import time
from typing import List, Dict, Tuple
from datetime import datetime

class MemecoinScalper:
    def __init__(self):
        self.base_url = "https://api.dexscreener.com/latest"
        self.timeframe = "1m"
        self.price_history = []
        self.volume_history = []
        self.prev_ema9 = None
        self.prev_ema21 = None
    
    def initialize_price_history(self, contract_address: str):
        """Inisialisasi price history di awal."""
        print("Collect initial data...", end='', flush=True)
        for _ in range(21):  # Minimal data untuk EMA21
            df = self.get_price_data(contract_address, silent=True)
            if not df.empty:
                self.price_history.append(df['close'].iloc[0])
            time.sleep(1)
        print(" Finish!\n")
        
    def get_price_data(self, contract_address: str, silent: bool = False) -> pd.DataFrame:
        """Mengambil data harga dari DEX Screener."""
        try:
            url = f"{self.base_url}/dex/tokens/{contract_address}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if 'pairs' not in data or not data['pairs']:
                return pd.DataFrame()

            solana_pairs = [p for p in data['pairs'] if p['chainId'] == 'solana']
            if not solana_pairs:
                return pd.DataFrame()
                
            solana_pairs.sort(key=lambda x: float(x.get('volume', {}).get('h24', 0)), reverse=True)
            pair = solana_pairs[0]
            
            # Extract transactions safely
            txns = pair.get('txns', {})
            buy_orders = int(txns.get('buys', 0)) if isinstance(txns, dict) else 0
            sell_orders = int(txns.get('sells', 0)) if isinstance(txns, dict) else 0
            
            df = pd.DataFrame({
                'timestamp': [datetime.now()],
                'close': [float(pair.get('priceUsd', 0))],
                'volume': [float(pair.get('volume', {}).get('h24', 0))],
                'liquidity': [float(pair.get('liquidity', {}).get('usd', 0))],
                'price_change': [float(pair.get('priceChange', {}).get('h24', 0))],
                'symbol': [pair.get('baseToken', {}).get('symbol', 'UNKNOWN')],
                'dex': [pair.get('dexId', 'UNKNOWN')],
                'buy_orders': [buy_orders],
                'sell_orders': [sell_orders]
            })

            if not silent:
                print(f"✅ Managed to find {df['symbol'].iloc[0]} at {df['dex'].iloc[0]}")
            return df
            
        except Exception as e:
            if not silent:
                print(f"⚠️ Error: {str(e)}")
            return pd.DataFrame()

    def calculate_bollinger_bands(self, prices: List[float]) -> Tuple[float, float, float]:
        """Menghitung Bollinger Bands."""
        if len(prices) < self.bollinger_period:
            return 0, 0, 0
            
        prices_series = pd.Series(prices)
        sma = prices_series.rolling(window=self.bollinger_period).mean().iloc[-1]
        std = prices_series.rolling(window=self.bollinger_period).std().iloc[-1]
        
        upper = sma + (self.bollinger_std * std)
        lower = sma - (self.bollinger_std * std)
        
        return upper, sma, lower

    def analyze_signals(self, df: pd.DataFrame) -> Dict:
        if df.empty:
            return {"status": "NO_DATA"}

        current_price = df['close'].iloc[0]
        self.price_history.append(current_price)

        if len(self.price_history) > 100:
            self.price_history = self.price_history[-100:]

        # Calculate indicators
        prices_series = pd.Series(self.price_history)
        
        # Pastikan tidak ada nilai NaN dalam prices_series
        prices_series = prices_series.dropna()

        # Hitung EMA
        ema9 = prices_series.ewm(span=9, adjust=False).mean()
        ema21 = prices_series.ewm(span=21, adjust=False).mean()

        # Hitung RSI
        if len(prices_series) > 14:
            delta = prices_series.diff()
            gain = (delta.where(delta > 0, 0)).fillna(0)
            loss = (-delta.where(delta < 0, 0)).fillna(0)

            avg_gain = gain.ewm(com=13, adjust=False).mean()
            avg_loss = loss.ewm(com=13, adjust=False).mean()

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        else:
            rsi = pd.Series([np.nan] * len(prices_series))

        # Calculate Bollinger Bands
        sma20 = prices_series.rolling(window=20).mean()
        std20 = prices_series.rolling(window=20).std()
        upper_band = sma20 + (std20 * 2)
        lower_band = sma20 - (std20 * 2)

        # Market Data
        buy_orders = df['buy_orders'].iloc[0]
        sell_orders = df['sell_orders'].iloc[0]

        signals = {
            "token": df['symbol'].iloc[0],
            "dex": df['dex'].iloc[0],
            "price": current_price,
            "price_usd": f"${current_price:.8f}",
            "volume_24h": df['volume'].iloc[0],
            "liquidity": df['liquidity'].iloc[0],
            "price_change": df['price_change'].iloc[0],
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "ema9": ema9.iloc[-1],
            "ema21": ema21.iloc[-1],
            "rsi": rsi.iloc[-1] if not rsi.isna().all() else "N/A",
            "upper_band": upper_band.iloc[-1],
            "middle_band": sma20.iloc[-1],
            "lower_band": lower_band.iloc[-1],
            "conditions": {},
            "signals": []
        }

        # 1. EMA Cross
        if self.prev_ema9 is not None and self.prev_ema21 is not None:
            if ema9.iloc[-1] > ema21.iloc[-1] and self.prev_ema9 <= self.prev_ema21:
                signals["signals"].append("🟢 GOLDEN CROSS: EMA 9 crossed above EMA 21")
                signals["conditions"]["ema_cross"] = "GOLDEN_CROSS"
            elif ema9.iloc[-1] < ema21.iloc[-1] and self.prev_ema9 >= self.prev_ema21:
                signals["signals"].append("🔴 DEATH CROSS: EMA 9 crossed below EMA 21")
                signals["conditions"]["ema_cross"] = "DEATH_CROSS"

        # 2. RSI
        if rsi.iloc[-1] < 30:
            signals["signals"].append(f"🟢 RSI OVERSOLD ({rsi.iloc[-1]:.2f})")
            signals["conditions"]["rsi"] = "OVERSOLD"
        elif rsi.iloc[-1] > 70:
            signals["signals"].append(f"🔴 RSI OVERBOUGHT ({rsi.iloc[-1]:.2f})")
            signals["conditions"]["rsi"] = "OVERBOUGHT"

        # 3. Bollinger Bands
        if current_price <= lower_band.iloc[-1] * 1.01:  # Harga lebih dekat dengan lower band (toleransi ±1%)
            signals["signals"].append("🟢 Price near Lower Bollinger Band")
            signals["conditions"]["bb"] = "TOUCH_LOWER"
        elif current_price >= upper_band.iloc[-1] * 0.99:  # Harga lebih dekat dengan upper band (toleransi ±1%)
            signals["signals"].append("🔴 Price near Upper Bollinger Band")
            signals["conditions"]["bb"] = "TOUCH_UPPER"

        # 4. Buy/Sell Orders
        if buy_orders > sell_orders:
            signals["signals"].append("📈 Buy Orders > Sell Orders")
            signals["conditions"]["order_flow"] = "BULLISH"
        else:
            signals["signals"].append("📉 Sell Orders > Buy Orders")
            signals["conditions"]["order_flow"] = "BEARISH"

        # Generate Trading Recommendation
        buy_conditions = (
            signals["conditions"].get("ema_cross") == "GOLDEN_CROSS" or
            signals["conditions"].get("rsi") == "OVERSOLD" or
            signals["conditions"].get("bb") == "TOUCH_LOWER"
        )

        sell_conditions = (
            signals["conditions"].get("ema_cross") == "DEATH_CROSS" or
            signals["conditions"].get("rsi") == "OVERBOUGHT" or
            signals["conditions"].get("bb") == "TOUCH_UPPER"
        )

        if buy_conditions:
            matched_conditions = []
            if signals["conditions"].get("ema_cross") == "GOLDEN_CROSS":
                matched_conditions.append("Golden Cross")
            if signals["conditions"].get("rsi") == "OVERSOLD":
                matched_conditions.append("RSI Oversold")
            if signals["conditions"].get("bb") == "TOUCH_LOWER":
                matched_conditions.append("Lower BB Touch")
            
            signals["recommendation"] = {
                "action": "BUY",
                "entry_price": current_price,
                "take_profit": current_price * 1.03,  # Take Profit 3%
                "stop_loss": current_price * 0.99,  # Stop Loss -1%
                "conditions_met": matched_conditions
            }

        elif sell_conditions:
            matched_conditions = []
            if signals["conditions"].get("ema_cross") == "DEATH_CROSS":
                matched_conditions.append("Death Cross")
            if signals["conditions"].get("rsi") == "OVERBOUGHT":
                matched_conditions.append("RSI Overbought")
            if signals["conditions"].get("bb") == "TOUCH_UPPER":
                matched_conditions.append("Upper BB Touch")
            
            signals["recommendation"] = {
                "action": "SELL",
                "current_price": current_price,
                "conditions_met": matched_conditions
            }
        
        else:
            # Jika tidak ada kondisi untuk BUY atau SELL, beri pesan Market Bearish & Tidak Likuid
            signals["recommendation"] = {
                "action": "Market Bearish & Tidak Likuid",
                "conditions_met": ", ".join(list(signals["conditions"].keys()))
            }

        return signals


    def run_scalping_bot(self):
        print("=== Memecoin Screening Bot by Rajwaa ===")
        print("Timeframe: 1 minute")
        print("Strategy: EMA Cross + RSI + Bollinger Bands")
        contract_address = input("Masukkan contract address memecoin: ").strip()
        
        if not contract_address:
            print("⚠️ Contract address tidak boleh kosong!")
            return

        print("\nStart Analysis...")
        self.initialize_price_history(contract_address)

        try:
            while True:
                print("="*50)
                print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                
                df = self.get_price_data(contract_address)
                signals = self.analyze_signals(df)
                
                if signals.get("status") == "NO_DATA":
                    print("⚠️ Data tidak tersedia, coba lagi nanti.")
                else:
                    print(f"\n💰 PRICE ACTION:")
                    print(f"Token: {signals['token']} (on {signals['dex']})")
                    print(f"Price: {signals['price_usd']}")
                    print(f"24h Change: {signals['price_change']:.1f}%")
                    
                    print(f"\n📊 INDICATORS STATUS:")
                    print(f"EMA9: {signals['ema9']:.8f}")
                    print(f"EMA21: {signals['ema21']:.8f}")
                    # Set RSI default jika tidak bisa dihitung
                    rsi_value = np.nan if signals["rsi"] == "N/A" else float(signals["rsi"])
                    print(f"RSI: {rsi_value:.2f}" if not np.isnan(rsi_value) else "RSI: Data tidak cukup untuk dihitung")
                    print(f"BB Upper: {signals['upper_band']:.8f}")
                    print(f"BB Lower: {signals['lower_band']:.8f}")
                    
                    print(f"\n📈 MARKET DATA:")
                    print(f"Volume: ${signals['volume_24h']:,.2f}")
                    print(f"Liquidity: ${signals['liquidity']:,.2f}")
                    print(f"Buy Orders: {signals['buy_orders']:,}")
                    print(f"Sell Orders: {signals['sell_orders']:,}")
                    
                    if signals['recommendation']:
                        rec = signals['recommendation']
                        if rec["action"] == "BUY":
                            print("\n💫 TRADING RECOMMENDATION:")
                            print(f"Action: {rec['action']}")
                            print(f"Entry: ${rec['entry_price']:.8f}")
                            print(f"Take Profit (3%): ${rec['take_profit']:.8f}")
                            print(f"Stop Loss (-1%): ${rec['stop_loss']:.8f}")
                            print(f"Conditions Met: {', '.join(rec['conditions_met'])}")
                        
                        elif rec["action"] == "Market Bearish & Illiquid":
                            print("\nMarket Bearish & Tidak Likuid")
                            print(f"Conditions Met: {rec['conditions_met']}")
                        else:
                            print("\n😴 No active signals")
                
                time.sleep(60)
                
        except KeyboardInterrupt:
            print("\nBot dihentikan oleh user.")

def main():
    bot = MemecoinScalper()
    bot.run_scalping_bot()

if __name__ == "__main__":
    main()