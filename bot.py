import os
import sqlite3
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

DB_PATH = os.environ.get("DB_PATH", "shopping.db")
BOT_TOKEN = os.environ.get("SHOPPING_BOT_TOKEN", "")

CATEGORIES = [
    ("🥦 Продукты",        "продукты"),
    ("🏠 Товары для дома", "дом"),
    ("💊 Аптека",          "аптека"),
    ("📦 Другое",          "другое"),
]

(
    MAIN_MENU,
    ADD_CATEGORY, ADD_ITEM, ADD_QTY,
    ADD_MORE_ITEM, ADD_MORE_QTY,
) = range(6)


# ── Keyboards ─────────────────────────────────────────────────
def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить"),      KeyboardButton("📋 Список")],
        [KeyboardButton("🛒 Иду в магазин"), KeyboardButton("📜 История")],
    ], resize_keyboard=True)

def back_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 Главное меню")]], resize_keyboard=True)

def category_kb():
    buttons = [[InlineKeyboardButton(label, callback_data=f"cat:{key}")] for label, key in CATEGORIES]
    return InlineKeyboardMarkup(buttons)

def after_add_kb(category: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Ещё в эту категорию", callback_data=f"more:{category}")],
        [InlineKeyboardButton("📂 Другая категория",    callback_data="cat_new")],
        [InlineKeyboardButton("🏠 В меню",              callback_data="go_home")],
    ])


# ── DB ────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT,
        category    TEXT,
        name        TEXT,
        qty         TEXT,
        added_date  TEXT,
        done        INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trips (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT,
        date        TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trip_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id     INTEGER,
        category    TEXT,
        name        TEXT,
        qty         TEXT,
        taken       INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_PATH)

def get_username(update: Update) -> str:
    return (update.effective_user.username or update.effective_user.first_name or "кто-то").lower()

def get_active_items():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, category, name, qty FROM items WHERE done=0 ORDER BY category, id")
    rows = c.fetchall()
    conn.close()
    return rows

def cat_label(key: str) -> str:
    for label, k in CATEGORIES:
        if k == key:
            return label
    return key


# ── Helpers ───────────────────────────────────────────────────
async def go_home(update: Update, text="🏠 Главное меню"):
    await update.message.reply_text(text, reply_markup=main_kb())

async def is_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message.text == "🔙 Главное меню":
        ctx.user_data.clear()
        await go_home(update)
        return True
    return False

def save_item(ctx, username):
    conn = get_db()
    conn.execute(
        "INSERT INTO items (username, category, name, qty, added_date) VALUES (?,?,?,?,?)",
        (username, ctx.user_data["category"], ctx.user_data["item_name"],
         ctx.user_data.get("qty", ""), date.today().isoformat())
    )
    conn.commit()
    conn.close()


# ── /start ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_active_items()
    count = len(items)
    text = (
        "🛒 *Список покупок*\n\n"
        f"{'📋 В списке: *' + str(count) + ' товаров*' if count else '📭 Список пуст — добавь первый товар!'}"
    )
    await update.message.reply_text(text, reply_markup=main_kb(), parse_mode="Markdown")
    return MAIN_MENU


# ── Router ────────────────────────────────────────────────────
async def menu_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "➕ Добавить":        return await add_start(update, ctx)
    elif text == "📋 Список":        await show_list(update, ctx)
    elif text == "🛒 Иду в магазин": return await shopping_start(update, ctx)
    elif text == "📜 История":       await show_history(update, ctx)
    return MAIN_MENU


# ── Добавить товар ────────────────────────────────────────────
async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "📂 *Выбери категорию:*",
        reply_markup=category_kb(), parse_mode="Markdown"
    )
    await update.message.reply_text("Или назад:", reply_markup=back_kb())
    return ADD_CATEGORY

async def add_category_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["category"] = query.data.replace("cat:", "")
    label = cat_label(ctx.user_data["category"])
    await query.edit_message_text(f"✅ {label}\n\n📝 Что купить? Напиши название:")
    return ADD_ITEM

async def add_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if await is_back(update, ctx): return MAIN_MENU
    ctx.user_data["item_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ *{ctx.user_data['item_name']}*\n\n"
        "📦 Количество или уточнение?\n"
        "_(например: `2 пачки`, `большая`, `х6` — или `-` пропустить)_",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    return ADD_QTY

async def add_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if await is_back(update, ctx): return MAIN_MENU
    qty = update.message.text.strip()
    if qty == "-": qty = ""
    ctx.user_data["qty"] = qty
    username = get_username(update)
    save_item(ctx, username)

    items = get_active_items()
    label = cat_label(ctx.user_data["category"])
    qty_text = f" — _{qty}_" if qty else ""
    category = ctx.user_data["category"]

    await update.message.reply_text(
        f"✅ Добавлено в *{label}*:\n"
        f"• {ctx.user_data['item_name']}{qty_text}\n\n"
        f"📋 Всего в списке: *{len(items)} товаров*\n\n"
        "Добавить ещё?",
        parse_mode="Markdown",
        reply_markup=after_add_kb(category)
    )
    return ADD_QTY  # stay here waiting for inline button


# ── Callbacks после добавления (внутри conversation) ──────────
async def after_add_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "go_home":
        ctx.user_data.clear()
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(query.message.chat_id, "🏠 Главное меню", reply_markup=main_kb())
        return MAIN_MENU

    elif data == "cat_new":
        ctx.user_data.clear()
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(
            query.message.chat_id, "📂 *Выбери категорию:*",
            reply_markup=category_kb(), parse_mode="Markdown"
        )
        return ADD_CATEGORY

    elif data.startswith("more:"):
        cat = data.replace("more:", "")
        ctx.user_data["category"] = cat
        ctx.user_data.pop("item_name", None)
        ctx.user_data.pop("qty", None)
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(
            query.message.chat_id,
            f"📝 Что ещё купить в *{cat_label(cat)}*?",
            parse_mode="Markdown"
        )
        return ADD_ITEM

    return MAIN_MENU


# ── Показать список ───────────────────────────────────────────
async def show_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_active_items()
    if not items:
        await update.message.reply_text("📭 Список пуст!", reply_markup=main_kb())
        return
    grouped = {}
    for iid, user, cat, name, qty in items:
        grouped.setdefault(cat, []).append((iid, user, name, qty))
    lines = ["📋 *Список покупок:*\n"]
    for cat, cat_items in grouped.items():
        lines.append(f"{cat_label(cat)}")
        for iid, user, name, qty in cat_items:
            qty_text = f" — {qty}" if qty else ""
            lines.append(f"  • {name}{qty_text}  _(@{user})_")
        lines.append("")
    lines.append(f"*Итого: {len(items)} товаров*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_kb())


# ── Поход в магазин ───────────────────────────────────────────
async def shopping_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_active_items()
    if not items:
        await update.message.reply_text("📭 Список пуст — нечего покупать!", reply_markup=main_kb())
        return MAIN_MENU

    username = get_username(update)
    conn = get_db()
    c = conn.cursor()
    conn.execute("INSERT INTO trips (username, date) VALUES (?,?)", (username, datetime.now().isoformat()))
    trip_id = c.lastrowid
    for iid, user, cat, name, qty in items:
        conn.execute(
            "INSERT INTO trip_items (trip_id, category, name, qty) VALUES (?,?,?,?)",
            (trip_id, cat, name, qty)
        )
    conn.commit(); conn.close()

    ctx.user_data["trip_id"] = trip_id
    await update.message.reply_text(
        f"🛒 *Поход в магазин!*\n@{username} пошёл за покупками\n\nОтмечай что взял:",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    await send_shopping_list(ctx, trip_id, chat_id=update.message.chat_id)
    return MAIN_MENU

async def send_shopping_list(ctx, trip_id: int, chat_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, category, name, qty, taken FROM trip_items WHERE trip_id=? ORDER BY category, id", (trip_id,))
    rows = c.fetchall()
    conn.close()

    grouped = {}
    for iid, cat, name, qty, taken in rows:
        grouped.setdefault(cat, []).append((iid, name, qty, taken))

    keyboard = []
    for cat, cat_items in grouped.items():
        keyboard.append([InlineKeyboardButton(f"── {cat_label(cat)} ──", callback_data="noop")])
        for iid, name, qty, taken in cat_items:
            qty_text = f" {qty}" if qty else ""
            label = f"✅ {name}{qty_text}" if taken else f"◻️ {name}{qty_text}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"toggle:{iid}:{trip_id}")])

    taken_count = sum(1 for row in rows if row[4])
    total_count = len(rows)
    keyboard.append([InlineKeyboardButton(
        f"🏁 Поход завершён ({taken_count}/{total_count})",
        callback_data=f"finish:{trip_id}"
    )])

    await ctx.bot.send_message(
        chat_id,
        f"🛒 *Список* — {taken_count}/{total_count} взято",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def shopping_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data.startswith("toggle:"):
        _, item_id, trip_id = data.split(":")
        item_id, trip_id = int(item_id), int(trip_id)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT taken FROM trip_items WHERE id=?", (item_id,))
        row = c.fetchone()
        if row:
            conn.execute("UPDATE trip_items SET taken=? WHERE id=?", (0 if row[0] else 1, item_id))
            conn.commit()
        conn.close()

        # Rebuild keyboard
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, category, name, qty, taken FROM trip_items WHERE trip_id=? ORDER BY category, id", (trip_id,))
        rows = c.fetchall()
        conn.close()

        grouped = {}
        for iid, cat, name, qty, taken in rows:
            grouped.setdefault(cat, []).append((iid, name, qty, taken))

        keyboard = []
        for cat, cat_items in grouped.items():
            keyboard.append([InlineKeyboardButton(f"── {cat_label(cat)} ──", callback_data="noop")])
            for iid, name, qty, taken in cat_items:
                qty_text = f" {qty}" if qty else ""
                label = f"✅ {name}{qty_text}" if taken else f"◻️ {name}{qty_text}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"toggle:{iid}:{trip_id}")])

        taken_count = sum(1 for row in rows if row[4])
        total_count = len(rows)
        keyboard.append([InlineKeyboardButton(
            f"🏁 Поход завершён ({taken_count}/{total_count})",
            callback_data=f"finish:{trip_id}"
        )])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("finish:"):
        trip_id = int(data.split(":")[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT name, category, taken FROM trip_items WHERE trip_id=?", (trip_id,))
        trip_items = c.fetchall()
        taken     = [(n, cat) for n, cat, t in trip_items if t == 1]
        not_taken = [(n, cat) for n, cat, t in trip_items if t == 0]
        for name, cat in taken:
            conn.execute("UPDATE items SET done=1 WHERE name=? AND category=? AND done=0", (name, cat))
        conn.commit(); conn.close()

        lines = ["🏁 *Поход завершён!*\n"]
        if taken:
            lines.append(f"✅ Куплено: *{len(taken)}*")
            for name, cat in taken:
                lines.append(f"  • {name}")
        if not_taken:
            lines.append(f"\n⏳ Осталось в списке: *{len(not_taken)}*")
            for name, cat in not_taken:
                lines.append(f"  • {name}")

        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
        await ctx.bot.send_message(query.message.chat_id, "🏠 Возвращайся!", reply_markup=main_kb())


# ── История ───────────────────────────────────────────────────
async def show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, date FROM trips ORDER BY id DESC LIMIT 10")
    trips = c.fetchall()
    conn.close()
    if not trips:
        await update.message.reply_text("📭 Походов ещё не было.", reply_markup=main_kb())
        return

    lines = ["📜 *История походов:*\n"]
    keyboard = []
    for tid, user, dt in trips:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(taken) FROM trip_items WHERE trip_id=?", (tid,))
        total, taken = c.fetchone()
        conn.close()
        taken = taken or 0
        d = dt[:10]
        lines.append(f"🛒 `{d}` @{user} — {taken}/{total} товаров")
        keyboard.append([InlineKeyboardButton(
            f"🛒 {d} — {taken}/{total} товаров",
            callback_data=f"hist:{tid}"
        )])

    await update.message.reply_text(
        "\n".join(lines) + "\n\nНажми на поход чтобы повторить товары:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def history_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    trip_id = int(query.data.replace("hist:", ""))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT category, name, qty FROM trip_items WHERE trip_id=? AND taken=1", (trip_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.answer("Нет купленных товаров в этом походе", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{cat_label(cat)} — {name}{' ('+qty+')' if qty else ''}",
            callback_data=f"readd:{cat}:{name}:{qty or ''}"
        )]
        for cat, name, qty in rows
    ]
    keyboard.append([InlineKeyboardButton("✅ Добавить все в список", callback_data=f"readd_all:{trip_id}")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def readd_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("readd_all:"):
        trip_id = int(data.split(":")[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT category, name, qty FROM trip_items WHERE trip_id=? AND taken=1", (trip_id,))
        rows = c.fetchall()
        username = get_username(update)
        for cat, name, qty in rows:
            conn.execute(
                "INSERT INTO items (username, category, name, qty, added_date) VALUES (?,?,?,?,?)",
                (username, cat, name, qty or "", date.today().isoformat())
            )
        conn.commit(); conn.close()
        await query.edit_message_text(f"✅ Добавлено *{len(rows)} товаров* в список!", parse_mode="Markdown")

    elif data.startswith("readd:"):
        parts = data.split(":", 3)
        cat, name, qty = parts[1], parts[2], parts[3] if len(parts) > 3 else ""
        username = get_username(update)
        conn = get_db()
        conn.execute(
            "INSERT INTO items (username, category, name, qty, added_date) VALUES (?,?,?,?,?)",
            (username, cat, name, qty, date.today().isoformat())
        )
        conn.commit(); conn.close()
        await query.answer(f"✅ {name} добавлен в список!", show_alert=False)


# ── cancel ────────────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await go_home(update, "❌ Отменено.")
    return MAIN_MENU


# ── main ──────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    menu_pattern = "^(➕ Добавить|📋 Список|🛒 Иду в магазин|📜 История)$"

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(menu_pattern), menu_router),
        ],
        states={
            MAIN_MENU: [
                MessageHandler(filters.Regex(menu_pattern), menu_router),
            ],
            ADD_CATEGORY: [
                CallbackQueryHandler(add_category_chosen, pattern="^cat:"),
                MessageHandler(filters.Regex("^🔙 Главное меню$"), cancel),
            ],
            ADD_ITEM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_item),
            ],
            ADD_QTY: [
                CallbackQueryHandler(after_add_callback, pattern="^(more:|cat_new|go_home)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_qty),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🔙 Главное меню$"), cancel),
        ],
        allow_reentry=True,
    )

    app.add_handler(CallbackQueryHandler(shopping_toggle, pattern="^(toggle:|finish:|noop)"))
    app.add_handler(CallbackQueryHandler(history_callback, pattern="^hist:"))
    app.add_handler(CallbackQueryHandler(readd_callback,   pattern="^readd"))
    app.add_handler(conv)

    print("🛒 Бот списка покупок запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
