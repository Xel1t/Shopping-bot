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

# States
WAIT_ITEM, WAIT_QTY = range(2)

MENU_PATTERN = "^(➕ Добавить|📋 Список|🛒 Иду в магазин|📜 История)$"
MENU_BUTTONS = {"➕ Добавить", "📋 Список", "🛒 Иду в магазин", "📜 История", "🔙 Главное меню"}


# ── Keyboards ─────────────────────────────────────────────────
def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Добавить"),      KeyboardButton("📋 Список")],
        [KeyboardButton("🛒 Иду в магазин"), KeyboardButton("📜 История")],
    ], resize_keyboard=True)

def back_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 Главное меню")]], resize_keyboard=True)

def category_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"cat:{key}")]
        for label, key in CATEGORIES
    ])

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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, category TEXT, name TEXT,
        qty TEXT, added_date TEXT, done INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trip_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER, category TEXT, name TEXT,
        qty TEXT, taken INTEGER DEFAULT 0
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
        if k == key: return label
    return key


# ── /start ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    items = get_active_items()
    count = len(items)
    text = "🛒 *Список покупок*\n\n" + (
        f"📋 В списке: *{count} товаров*" if count else "📭 Список пуст — добавь первый товар!"
    )
    await update.message.reply_text(text, reply_markup=main_kb(), parse_mode="Markdown")


# ── Главное меню — все кнопки ─────────────────────────────────
async def btn_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "📂 *Выбери категорию:*",
        reply_markup=category_kb(), parse_mode="Markdown"
    )

async def btn_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_active_items()
    if not items:
        await update.message.reply_text("📭 Список пуст!", reply_markup=main_kb())
        return
    grouped = {}
    for iid, user, cat, name, qty in items:
        grouped.setdefault(cat, []).append((iid, user, name, qty))
    lines = ["📋 Список покупок:\n"]
    keyboard = []
    for cat, cat_items in grouped.items():
        lines.append(cat_label(cat))
        for iid, user, name, qty in cat_items:
            qty_text = f" — {qty}" if qty else ""
            lines.append(f"  • {name}{qty_text}  (@{user})")
        lines.append("")
    lines.append(f"Итого: {len(items)} товаров")
    for cat, cat_items in grouped.items():
        for iid, user, name, qty in cat_items:
            qty_text = f" {qty}" if qty else ""
            keyboard.append([InlineKeyboardButton(
                f"🗑 {name}{qty_text}",
                callback_data=f"del_item:{iid}"
            )])
    await update.message.reply_text("\n".join(lines), reply_markup=main_kb())
    if keyboard:
        await update.message.reply_text(
            "Нажми чтобы удалить:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def btn_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_active_items()
    if not items:
        await update.message.reply_text("📭 Список пуст!", reply_markup=main_kb())
        return
    username = get_username(update)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO trips (username, date) VALUES (?,?)", (username, datetime.now().isoformat()))
    trip_id = cur.lastrowid
    for iid, user, cat, name, qty in items:
        cur.execute("INSERT INTO trip_items (trip_id, category, name, qty) VALUES (?,?,?,?)", (trip_id, cat, name, qty))
    conn.commit(); conn.close()

    await update.message.reply_text(
        f"🛒 Поход в магазин!\n@{username} пошёл за покупками\n\nОтмечай что взял:",
        reply_markup=main_kb()
    )
    # Build shopping list inline
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, category, name, qty, taken FROM trip_items WHERE trip_id=? ORDER BY category, id", (trip_id,))
    rows = cur.fetchall(); conn.close()
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
    taken_count = sum(1 for r in rows if r[4])
    keyboard.append([InlineKeyboardButton(
        f"🏁 Поход завершён ({taken_count}/{len(rows)})",
        callback_data=f"finish:{trip_id}"
    )])
    await update.message.reply_text(
        f"🛒 *Список* — {taken_count}/{len(rows)} взято",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def btn_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, date FROM trips ORDER BY id DESC LIMIT 10")
    trips = cur.fetchall(); conn.close()
    if not trips:
        await update.message.reply_text("📭 Походов ещё не было.", reply_markup=main_kb())
        return
    keyboard = []
    lines = ["📜 *История походов:*\n"]
    for tid, user, dt in trips:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(taken) FROM trip_items WHERE trip_id=?", (tid,))
        total, taken = cur.fetchone(); conn.close()
        taken = taken or 0
        d = dt[:10]
        lines.append(f"🛒 `{d}` @{user} — {taken}/{total} товаров")
        keyboard.append([InlineKeyboardButton(f"🛒 {d} — {taken}/{total} товаров", callback_data=f"hist:{tid}")])
    await update.message.reply_text(
        "\n".join(lines) + "\n\nНажми на поход чтобы повторить товары:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def btn_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("🏠 Главное меню", reply_markup=main_kb())


# ── Добавить: выбор категории → название → кол-во ─────────────
async def cat_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["category"] = query.data.replace("cat:", "")
    ctx.user_data["step"] = "wait_item"
    await query.edit_message_text(f"✅ {cat_label(ctx.user_data['category'])}\n\n📝 Что купить?")

async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Single text handler — step determined by user_data state."""
    text = update.message.text.strip()
    if text in MENU_BUTTONS:
        return  # handled by dedicated handlers

    step = ctx.user_data.get("step")

    if step == "wait_item":
        ctx.user_data["item_name"] = text
        ctx.user_data["step"] = "wait_qty"
        await update.message.reply_text(
            f"✅ *{text}*\n\n"
            "📦 Количество или уточнение?\n_(например: `2 пачки`, `большая` — или `-` пропустить)_",
            parse_mode="Markdown", reply_markup=back_kb()
        )

    elif step == "wait_qty":
        qty = text if text != "-" else ""
        username = get_username(update)
        conn = get_db()
        conn.execute(
            "INSERT INTO items (username, category, name, qty, added_date) VALUES (?,?,?,?,?)",
            (username, ctx.user_data["category"], ctx.user_data["item_name"], qty, date.today().isoformat())
        )
        conn.commit(); conn.close()
        items = get_active_items()
        label = cat_label(ctx.user_data["category"])
        item_name = ctx.user_data["item_name"]
        category = ctx.user_data["category"]
        qty_text = f" — _{qty}_" if qty else ""
        ctx.user_data["step"] = "wait_item"  # ready for next item
        ctx.user_data.pop("item_name", None)
        await update.message.reply_text(
            f"✅ Добавлено в *{label}*:\n"
            f"• {item_name}{qty_text}\n\n"
            f"📋 Всего в списке: *{len(items)} товаров*\n\nДобавить ещё?",
            parse_mode="Markdown",
            reply_markup=after_add_kb(category)
        )
    else:
        # Not in add flow — ignore or hint
        pass

async def after_add_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "go_home":
        ctx.user_data.clear()
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(query.message.chat_id, "🏠 Главное меню", reply_markup=main_kb())
    elif data == "cat_new":
        ctx.user_data.clear()
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(query.message.chat_id, "📂 *Выбери категорию:*",
                                   reply_markup=category_kb(), parse_mode="Markdown")
        # step will be set when category is chosen
    elif data.startswith("more:"):
        cat = data.replace("more:", "")
        ctx.user_data["category"] = cat
        ctx.user_data["step"] = "wait_item"
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(query.message.chat_id,
                                   f"📝 Что ещё в *{cat_label(cat)}*?", parse_mode="Markdown")


# ── Удалить из списка ─────────────────────────────────────────
async def del_item_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.replace("del_item:", ""))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, category FROM items WHERE id=?", (item_id,))
    row = cur.fetchone()
    if row:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
        deleted_name = row[0]
    else:
        await query.edit_message_text("❌ Не найдено.")
        conn.close()
        return
    conn.close()

    # Rebuild delete keyboard with remaining items
    items = get_active_items()
    if not items:
        await query.edit_message_text(f"🗑 {deleted_name} удалён\n\n📭 Список теперь пуст!")
        return

    keyboard = []
    for iid, user, cat, name, qty in items:
        qty_text = f" {qty}" if qty else ""
        keyboard.append([InlineKeyboardButton(f"🗑 {name}{qty_text}", callback_data=f"del_item:{iid}")])

    await query.edit_message_text(
        f"🗑 {deleted_name} удалён\n\nОсталось {len(items)} товаров. Удалить ещё?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Поход: toggle + finish ────────────────────────────────────
async def shopping_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop": return

    if data.startswith("toggle:"):
        _, item_id, trip_id = data.split(":")
        item_id, trip_id = int(item_id), int(trip_id)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT taken FROM trip_items WHERE id=?", (item_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE trip_items SET taken=? WHERE id=?", (0 if row[0] else 1, item_id))
            conn.commit()
        cur.execute("SELECT id, category, name, qty, taken FROM trip_items WHERE trip_id=? ORDER BY category, id", (trip_id,))
        rows = cur.fetchall(); conn.close()
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
        taken_count = sum(1 for r in rows if r[4])
        keyboard.append([InlineKeyboardButton(
            f"🏁 Поход завершён ({taken_count}/{len(rows)})",
            callback_data=f"finish:{trip_id}"
        )])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("finish:"):
        trip_id = int(data.split(":")[1])
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT name, category, taken FROM trip_items WHERE trip_id=?", (trip_id,))
        trip_items = cur.fetchall()
        taken     = [(n, cat) for n, cat, t in trip_items if t == 1]
        not_taken = [(n, cat) for n, cat, t in trip_items if t == 0]
        for name, cat in taken:
            cur.execute("UPDATE items SET done=1 WHERE name=? AND category=? AND done=0", (name, cat))
        conn.commit(); conn.close()
        lines = ["🏁 *Поход завершён!*\n"]
        if taken:
            lines.append(f"✅ Куплено: *{len(taken)}*")
            for name, cat in taken: lines.append(f"  • {name}")
        if not_taken:
            lines.append(f"\n⏳ Осталось: *{len(not_taken)}*")
            for name, cat in not_taken: lines.append(f"  • {name}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
        await ctx.bot.send_message(query.message.chat_id, "🏠 Возвращайся!", reply_markup=main_kb())


# ── История callbacks ─────────────────────────────────────────
async def history_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    trip_id = int(query.data.replace("hist:", ""))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT category, name, qty FROM trip_items WHERE trip_id=? AND taken=1", (trip_id,))
    rows = cur.fetchall(); conn.close()
    if not rows:
        await query.answer("Нет купленных товаров", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton(f"{cat_label(cat)} — {name}{' ('+qty+')' if qty else ''}",
                              callback_data=f"readd:{cat}:{name}:{qty or ''}")]
        for cat, name, qty in rows
    ]
    keyboard.append([InlineKeyboardButton("✅ Добавить все в список", callback_data=f"readd_all:{trip_id}")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def readd_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    username = get_username(update)
    if data.startswith("readd_all:"):
        trip_id = int(data.split(":")[1])
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT category, name, qty FROM trip_items WHERE trip_id=? AND taken=1", (trip_id,))
        rows = cur.fetchall()
        for cat, name, qty in rows:
            cur.execute("INSERT INTO items (username, category, name, qty, added_date) VALUES (?,?,?,?,?)",
                        (username, cat, name, qty or "", date.today().isoformat()))
        conn.commit(); conn.close()
        await query.edit_message_text(f"✅ Добавлено *{len(rows)} товаров* в список!", parse_mode="Markdown")
    elif data.startswith("readd:"):
        parts = data.split(":", 3)
        cat, name, qty = parts[1], parts[2], parts[3] if len(parts) > 3 else ""
        conn = get_db()
        conn.execute("INSERT INTO items (username, category, name, qty, added_date) VALUES (?,?,?,?,?)",
                     (username, cat, name, qty, date.today().isoformat()))
        conn.commit(); conn.close()
        await query.answer(f"✅ {name} добавлен!", show_alert=False)


# ── main ──────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Simple independent handlers — no ConversationHandler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^➕ Добавить$"), btn_add))
    app.add_handler(MessageHandler(filters.Regex("^📋 Список$"), btn_list))
    app.add_handler(MessageHandler(filters.Regex("^🛒 Иду в магазин$"), btn_shop))
    app.add_handler(MessageHandler(filters.Regex("^📜 История$"), btn_history))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Главное меню$"), btn_back))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(cat_chosen,     pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(after_add_cb,   pattern="^(more:|cat_new|go_home)"))
    app.add_handler(CallbackQueryHandler(del_item_cb,    pattern="^del_item:"))
    app.add_handler(CallbackQueryHandler(shopping_toggle, pattern="^(toggle:|finish:|noop)"))
    app.add_handler(CallbackQueryHandler(history_cb,     pattern="^hist:"))
    app.add_handler(CallbackQueryHandler(readd_cb,       pattern="^readd"))

    # Text input — single handler, step determined by user_data
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))

    print("🛒 Бот списка покупок запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
