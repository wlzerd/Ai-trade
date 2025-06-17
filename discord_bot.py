import os
import requests
import discord
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

class StockBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = StockBot()

@bot.tree.command(name="stock", description="Get latest closing price for a ticker")
@app_commands.describe(ticker="Ticker symbol (e.g. AAPL)")
async def stock(interaction: discord.Interaction, ticker: str):
    ticker = ticker.upper()
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev"
    params = {"adjusted": "true", "apiKey": POLYGON_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        result = data.get("results", [{}])[0]
        close = result.get("c")
        if close is None:
            await interaction.response.send_message(f"가격을 찾을 수 없습니다: {ticker}", ephemeral=True)
            return
        message = f"{ticker} 종가: {close}"
    except Exception as e:
        message = f"오류 발생: {e}"
    await interaction.response.send_message(message)

if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN not set")
    bot.run(TOKEN)
