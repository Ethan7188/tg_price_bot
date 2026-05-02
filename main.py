import os
import requests
import json
import math
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WATCH_FILE = "watch_list.json"
MAX_WATCHES_PER_USER = 10
WATCH_USAGE = (
    "用法：\n"
    "/watch btc 90000\n"
    "/watch btc above 90000\n"
    "/watch btc below 70000"
)
EDIT_WATCH_USAGE = "用法：/editwatch 1 above 90000"
WATCH_HELP_TEXT = (
    "价格提醒用法：\n"
    "/watch btc above 90000\n"
    "/watch btc below 70000\n"
    "/mywatch\n"
    "/unwatch 1\n"
    "/editwatch 1 above 90000\n"
    "/clearwatch"
)

SUPPORTED_COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "doge": "dogecoin",
    "bnb": "binancecoin",
}

SUPPORTED_SYMBOLS = ("btc", "eth", "sol", "bnb", "doge")
TOP_SYMBOLS = SUPPORTED_SYMBOLS


def normalize_watch_item(item):
    # 兼容旧提醒格式，并过滤明显损坏的数据。
    if not isinstance(item, dict):
        return None

    symbol = str(item.get("symbol", "")).lower()

    if symbol not in SUPPORTED_COINS:
        return None

    try:
        target_price = float(item["target_price"])
    except (KeyError, TypeError, ValueError):
        return None

    if not math.isfinite(target_price) or target_price <= 0:
        return None

    direction = str(item.get("direction", "above")).lower()

    if direction not in ("above", "below"):
        direction = "above"

    return {
        "symbol": symbol,
        "direction": direction,
        "target_price": target_price,
    }


def load_watch_list():
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            result = {}

            if not isinstance(data, dict):
                print("watch_list.json 格式不是对象，已忽略。")
                return {}

            for k, v in data.items():
                try:
                    chat_id = int(k)
                except ValueError:
                    print(f"跳过无效 chat_id：{k}")
                    continue

                items = v if isinstance(v, list) else [v]
                normalized_items = []

                for item in items:
                    normalized_item = normalize_watch_item(item)

                    if normalized_item:
                        normalized_items.append(normalized_item)

                if normalized_items:
                    result[chat_id] = normalized_items

            return result
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"watch_list.json 损坏，已忽略：{e}")
        return {}
    except Exception as e:
        print(f"加载 watch_list.json 失败，已忽略：{e}")
        return {}


def save_watch_list():
    with open(WATCH_FILE, "w", encoding="utf-8") as f:
        json.dump(watch_list, f, ensure_ascii=False, indent=2)


watch_list = load_watch_list()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "你好，我是币价查询机器人。\n\n"
        "可用命令：\n"
        "/price btc 查询单个币价\n"
        "/top 查询热门币价\n"
        "/coins 查看支持币种\n"
        "/watch btc above 90000 设置上涨提醒\n"
        "/watch btc below 70000 设置下跌提醒\n"
        "/mywatch 查看我的提醒\n"
        "/unwatch 1 删除指定提醒\n"
        "/editwatch 1 above 90000 修改提醒\n"
        "/clearwatch 清空所有提醒\n"
        "/watchhelp 查看提醒用法\n"
        "/status 查看机器人状态\n"
        "/ping 测试机器人在线状态"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "可用命令：\n"
        "/price btc 查询单个币价\n"
        "/top 查询热门币价\n"
        "/coins 查看支持币种\n"
        "/watch btc above 90000 设置上涨提醒\n"
        "/watch btc below 70000 设置下跌提醒\n"
        "/mywatch 查看我的提醒\n"
        "/unwatch 1 删除指定提醒\n"
        "/editwatch 1 above 90000 修改提醒\n"
        "/clearwatch 清空所有提醒\n"
        "/watchhelp 查看提醒用法\n"
        "/status 查看机器人状态\n"
        "/ping 测试机器人在线状态\n\n"
        "支持一次发送多行命令进行批量测试。"
    )


def format_usd_price(price_value):
    if price_value == int(price_value):
        return f"${price_value:,.0f}"

    return f"${price_value:,.6f}".rstrip("0").rstrip(".")


def format_target_price(price_value):
    return format_usd_price(price_value)


def format_supported_symbols():
    # 统一展示支持币种。
    return ", ".join(SUPPORTED_SYMBOLS)


def format_watch_operator(direction):
    if direction == "below":
        return "≤"

    return "≥"


def format_watch_item(item):
    # 统一格式化单条提醒。
    return (
        f"{item['symbol'].upper()} "
        f"{format_watch_operator(item.get('direction', 'above'))} "
        f"{format_target_price(item['target_price'])}"
    )


def parse_target_price(price_text):
    # 解析用户输入的目标价格。
    try:
        target_price = float(price_text)
    except ValueError:
        return None, "usage"

    if not math.isfinite(target_price):
        return None, "usage"

    if target_price <= 0:
        return None, "not_positive"

    return target_price, None


def watch_exists(items, symbol, direction, target_price):
    # 避免重复添加完全相同的提醒。
    return any(
        item["symbol"] == symbol
        and item.get("direction", "above") == direction
        and item["target_price"] == target_price
        for item in items
    )


def count_all_watches():
    # 统计所有用户提醒总数。
    return sum(len(items) for items in watch_list.values())


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


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    await msg.reply_text("pong ✅")


async def coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    await msg.reply_text(f"当前支持：\n{format_supported_symbols()}")


async def watchhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 单独展示提醒相关命令。
    msg = update.effective_message

    if msg is None:
        return

    await msg.reply_text(WATCH_HELP_TEXT)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 查看当前用户和机器人整体提醒状态。
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    user_watch_count = len(watch_list.get(chat_id, []))

    await msg.reply_text(
        "机器人在线 ✅\n"
        f"当前用户提醒数量：{user_watch_count}\n"
        f"全部用户提醒总数：{count_all_watches()}\n"
        f"支持币种数量：{len(SUPPORTED_SYMBOLS)}"
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    if not context.args:
        await msg.reply_text("请这样输入：/price btc")
        return

    symbol = context.args[0].lower()

    try:
        price_value = get_crypto_price(symbol)

        if price_value is None:
            await msg.reply_text(f"暂不支持这个币种，目前支持：{format_supported_symbols()}")
            return

        await msg.reply_text(f"{symbol.upper()} 当前价格：{format_usd_price(price_value)}")

    except Exception as e:
        await msg.reply_text(f"查询失败：{e}")


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    if len(context.args) == 2:
        direction = "above"
        target_price_text = context.args[1]
    elif len(context.args) == 3:
        direction = context.args[1].lower()
        target_price_text = context.args[2]
    else:
        await msg.reply_text(WATCH_USAGE)
        return

    symbol = context.args[0].lower()

    if symbol not in SUPPORTED_COINS:
        await msg.reply_text(f"暂不支持这个币种，目前支持：{format_supported_symbols()}")
        return

    if direction not in ("above", "below"):
        await msg.reply_text(WATCH_USAGE)
        return

    target_price, price_error = parse_target_price(target_price_text)

    if price_error == "usage":
        await msg.reply_text(WATCH_USAGE)
        return

    if price_error == "not_positive":
        await msg.reply_text("价格必须大于 0")
        return

    chat_id = update.effective_chat.id
    items = watch_list.setdefault(chat_id, [])

    if watch_exists(items, symbol, direction, target_price):
        await msg.reply_text("这条提醒已经存在。")
        return

    if len(items) >= MAX_WATCHES_PER_USER:
        await msg.reply_text("最多只能设置 10 条价格提醒，请先删除旧提醒。")
        return

    items.append({
        "symbol": symbol,
        "direction": direction,
        "target_price": target_price,
    })
    save_watch_list()

    await msg.reply_text(
        f"已添加提醒：{symbol.upper()} {format_watch_operator(direction)} "
        f"{format_target_price(target_price)}"
    )


async def mywatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    items = watch_list.get(chat_id)

    if not items:
        await msg.reply_text("你当前没有设置价格提醒。")
        return

    lines = [
        f"{index}. {format_watch_item(item)}"
        for index, item in enumerate(items, start=1)
    ]

    await msg.reply_text(
        "📌 我的价格提醒\n"
        + "\n".join(lines)
        + "\n\n使用 /unwatch 编号 删除提醒\n"
        "使用 /editwatch 编号 above/below 价格 修改提醒"
    )


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    if not context.args:
        await msg.reply_text("用法：/unwatch 2")
        return

    try:
        watch_index = int(context.args[0])
    except ValueError:
        await msg.reply_text("没有这个提醒编号。")
        return

    items = watch_list.get(chat_id)

    if not items:
        await msg.reply_text("没有这个提醒编号。")
        return

    if watch_index < 1 or watch_index > len(items):
        await msg.reply_text("没有这个提醒编号。")
        return

    removed_item = items.pop(watch_index - 1)

    if not items:
        del watch_list[chat_id]

    save_watch_list()
    await msg.reply_text(
        f"已取消提醒：{removed_item['symbol'].upper()} "
        f"{format_watch_operator(removed_item.get('direction', 'above'))} "
        f"{format_target_price(removed_item['target_price'])}"
    )


async def editwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 修改当前用户指定编号的提醒。
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    if len(context.args) != 3:
        await msg.reply_text(EDIT_WATCH_USAGE)
        return

    try:
        watch_index = int(context.args[0])
    except ValueError:
        await msg.reply_text("没有这个提醒编号。")
        return

    direction = context.args[1].lower()

    if direction not in ("above", "below"):
        await msg.reply_text(EDIT_WATCH_USAGE)
        return

    target_price, price_error = parse_target_price(context.args[2])

    if price_error == "usage":
        await msg.reply_text(EDIT_WATCH_USAGE)
        return

    if price_error == "not_positive":
        await msg.reply_text("价格必须大于 0")
        return

    items = watch_list.get(chat_id)

    if not items:
        await msg.reply_text("没有这个提醒编号。")
        return

    if watch_index < 1 or watch_index > len(items):
        await msg.reply_text("没有这个提醒编号。")
        return

    item = items[watch_index - 1]
    symbol = item["symbol"]

    duplicate_exists = any(
        index != watch_index - 1
        and other_item["symbol"] == symbol
        and other_item.get("direction", "above") == direction
        and other_item["target_price"] == target_price
        for index, other_item in enumerate(items)
    )

    if duplicate_exists:
        await msg.reply_text("这条提醒已经存在。")
        return

    item["direction"] = direction
    item["target_price"] = target_price
    save_watch_list()

    await msg.reply_text(f"已修改第 {watch_index} 条提醒：{format_watch_item(item)}")


async def clearwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = update.effective_chat.id

    if msg is None:
        return

    if not watch_list.get(chat_id):
        await msg.reply_text("你当前没有价格提醒。")
        return

    del watch_list[chat_id]
    save_watch_list()
    await msg.reply_text("已清空你的所有价格提醒。")


async def check_watch(context: ContextTypes.DEFAULT_TYPE):
    if not watch_list:
        return

    print("正在检查价格提醒...")

    symbols = sorted({
        item["symbol"].lower()
        for items in watch_list.values()
        for item in items
        if item["symbol"].lower() in SUPPORTED_COINS
    })

    if not symbols:
        print("价格检查跳过：没有需要检查的支持币种。")
        return

    symbol_text = ", ".join(symbols)

    try:
        price_cache = get_crypto_prices(symbols)
        print(f"本轮检查币种：{symbol_text}")

    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"

        if e.response is not None and e.response.status_code == 429:
            print(f"价格检查 API 失败：symbols={symbol_text}，status=429，原因：CoinGecko Too Many Requests")
        else:
            print(f"价格检查 API 失败：symbols={symbol_text}，status={status_code}，原因：{e}")
        return

    except Exception as e:
        print(f"价格检查 API 失败：symbols={symbol_text}，原因：{e}")
        return

    changed_any = False

    for chat_id, items in list(watch_list.items()):
        remaining_items = []
        changed = False

        for item in items:
            symbol = item["symbol"].lower()
            direction = str(item.get("direction", "above")).lower()

            if direction not in ("above", "below"):
                direction = "above"

            target_price = item["target_price"]
            current_price = price_cache.get(symbol)

            if current_price is None:
                print(f"价格检查失败：symbol={symbol}，原因：API 本轮没有返回价格")
                remaining_items.append(item)
                continue

            if (
                direction == "above" and current_price >= target_price
                or direction == "below" and current_price <= target_price
            ):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🚨 价格提醒触发\n"
                            f"{symbol.upper()} 当前价格 "
                            f"{format_usd_price(current_price)}，已达到 "
                            f"{format_watch_operator(direction)} "
                            f"{format_target_price(target_price)}"
                        )
                    )
                    print(f"提醒触发：chat_id={chat_id}，symbol={symbol}，direction={direction}")

                except Exception as send_err:
                    print(f"消息发送失败：chat_id={chat_id}，symbol={symbol}，原因：{send_err}")

                changed = True
            else:
                remaining_items.append(item)

        if changed:
            if remaining_items:
                watch_list[chat_id] = remaining_items
            else:
                del watch_list[chat_id]

            changed_any = True

    if changed_any:
        save_watch_list()


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if msg is None:
        return

    try:
        prices = get_crypto_prices(TOP_SYMBOLS)
        lines = [
            f"{symbol.upper()}：{format_usd_price(prices[symbol])}"
            for symbol in TOP_SYMBOLS
        ]
        await msg.reply_text("📊 热门币种价格\n" + "\n".join(lines))

    except Exception as e:
        await msg.reply_text(f"查询失败：{e}")


async def dispatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE, line):
    # 多行批量测试时，复用已有命令函数。
    msg = update.effective_message
    parts = line.split()

    if msg is None or not parts:
        return

    command_name = parts[0][1:].split("@", 1)[0].lower()
    command_handlers = {
        "ping": ping,
        "status": status,
        "coins": coins,
        "price": price,
        "top": top,
        "watch": watch,
        "mywatch": mywatch,
        "unwatch": unwatch,
        "editwatch": editwatch,
        "clearwatch": clearwatch,
        "watchhelp": watchhelp,
        "help": help_command,
    }
    handler = command_handlers.get(command_name)

    if handler is None:
        await msg.reply_text(f"不支持的命令：/{command_name}")
        return

    old_args = getattr(context, "args", None)
    context.args = parts[1:]

    try:
        await handler(update, context)
    except Exception as e:
        await msg.reply_text(f"执行 {parts[0]} 失败：{e}")
    finally:
        context.args = old_args


async def handle_multi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 处理一次发送多行命令的批量测试消息。
    msg = update.effective_message

    if msg is None or not msg.text:
        return

    lines = [
        line.strip()
        for line in msg.text.splitlines()
        if line.strip()
    ]

    if len(lines) < 2 or not all(line.startswith("/") for line in lines):
        return

    for line in lines:
        await dispatch_command(update, context, line)


def main():
    if not BOT_TOKEN:
        raise ValueError("没有找到 BOT_TOKEN，请检查 .env 文件")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"\n"), handle_multi_command))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("coins", coins))
    app.add_handler(CommandHandler("watchhelp", watchhelp))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("top", top))

    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("mywatch", mywatch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("editwatch", editwatch))
    app.add_handler(CommandHandler("clearwatch", clearwatch))
    app.job_queue.run_repeating(check_watch, interval=60, first=10)
    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
