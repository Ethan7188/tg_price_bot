import os
import requests
import json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WATCH_FILE = "watch_list.json"


def load_watch_list():
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_watch_list():
    with open(WATCH_FILE, "w", encoding="utf-8") as f:
        json.dump(watch_list, f, ensure_ascii=False, indent=2)


watch_list = load_watch_list()

SUPPORTED_COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "doge": "dogecoin",
    "bnb": "binancecoin",
}

TOP_SYMBOLS = ("btc", "eth", "sol", "bnb", "doge")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "你好，我是币价查询机器人。\n\n"
        "可用命令：\n"
        "/price btc\n"
        "/price eth\n"
        "/price sol\n"
        "/price doge\n"
        "/price bnb\n"
        "/top\n"
        "/help"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "使用方法：\n"
        "/price btc 查询 BTC 价格\n"
        "/price eth 查询 ETH 价格\n"
        "/price sol 查询 SOL 价格\n"
        "/price doge 查询 DOGE 价格\n"
        "/price bnb 查询 BNB 价格\n"
        "/top 查询热门币种价格"
    )


def format_usd_price(price_value):
    if price_value >= 1:
        return f"${price_value:,.2f}".rstrip("0").rstrip(".")

    return f"${price_value:,.8f}".rstrip("0").rstrip(".")


def get_crypto_prices(symbols):
    coin_ids = [SUPPORTED_COINS[symbol] for symbol in symbols]

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": "usd",
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()
    return {
        symbol: data[coin_id]["usd"]
        for symbol, coin_id in zip(symbols, coin_ids)
    }


def get_crypto_price(symbol: str):
    symbol = symbol.lower()
    coin_id = SUPPORTED_COINS.get(symbol)

    if not coin_id:
        return None

    return get_crypto_prices([symbol])[symbol]


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    if not context.args:
        await msg.reply_text("请这样输入：/price btc")
        return

    symbol = context.args[0]

    try:
        price_value = get_crypto_price(symbol)

        if price_value is None:
            await msg.reply_text("暂不支持这个币种，目前支持：btc、eth、sol、doge、bnb")
            return

        await msg.reply_text(f"{symbol.upper()} 当前价格：{format_usd_price(price_value)}")

    except Exception as e:
        await msg.reply_text(f"查询失败：{e}")

async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    if len(context.args) != 2:
        await msg.reply_text("用法：/watch btc 95000")
        return

    symbol = context.args[0].lower()

    try:
        target_price = float(context.args[1])
    except ValueError:
        await msg.reply_text("目标价格必须是数字，例如：/watch btc 95000")
        return

    chat_id = update.effective_chat.id

    watch_list[chat_id] = {
    "symbol": symbol,
    "target_price": target_price,
    }
    save_watch_list()

    await msg.reply_text(f"已设置提醒：{symbol.upper()} ≥ ${target_price}")
async def mywatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    item = watch_list.get(chat_id)

    if not item:
        await msg.reply_text("你当前没有设置价格提醒。")
        return

    symbol = item["symbol"]
    target_price = item["target_price"]

    await msg.reply_text(
        f"你当前的提醒：\n"
        f"{symbol.upper()} ≥ ${target_price}"
    )


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    if chat_id in watch_list:
        del watch_list[chat_id]
        save_watch_list()
        await msg.reply_text("已取消你的价格提醒。")
    else:
        await msg.reply_text("你当前没有可取消的价格提醒。")


async def check_watch(context: ContextTypes.DEFAULT_TYPE):
    print("正在检查价格提醒...", watch_list)

    for chat_id, item in list(watch_list.items()):
        symbol = item["symbol"]
        target_price = item["target_price"]

        try:
            current_price = get_crypto_price(symbol)
            print(symbol, current_price, target_price)

            if current_price >= target_price:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"价格提醒：{symbol.upper()} 当前 ${current_price}，已达到目标 ${target_price}"
                    )
                    print("消息发送成功")

                except Exception as send_err:
                    print("消息发送失败：", send_err)

                del watch_list[chat_id]
                save_watch_list()

        except Exception as e:
            print("检查失败：", e)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    try:
        prices = get_crypto_prices(TOP_SYMBOLS)
        lines = [
            f"{symbol.upper()}: {format_usd_price(prices[symbol])}"
            for symbol in TOP_SYMBOLS
        ]
        await msg.reply_text("\n".join(lines))

    except Exception as e:
        await msg.reply_text(f"查询失败：{e}")


def main():
    if not BOT_TOKEN:
        raise ValueError("没有找到 BOT_TOKEN，请检查 .env 文件")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("top", top))

    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("mywatch", mywatch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.job_queue.run_repeating(check_watch, interval=10, first=5)
    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
