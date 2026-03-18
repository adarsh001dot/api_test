from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from functools import wraps
from datetime import datetime, timedelta
import requests
import uuid
import os
import logging
from bson.objectid import ObjectId
import threading
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
TELEGRAM_ADMIN_IDS = [int(id.strip()) for id in os.environ.get('TELEGRAM_ADMIN_IDS', '123456789').split(',')]
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb+srv://nikilsaxena843_db_user:3gF2wyT4IjsFt0cY@vipbot.puv6gfk.mongodb.net/?appName=vipbot')
PORT = int(os.environ.get('PORT', 5000))

# MongoDB Configuration
app.config["MONGO_URI"] = MONGODB_URI
mongo = PyMongo(app)
bcrypt = Bcrypt(app)

# Database
db = mongo.cx['API_CLONE']

# Collections
keys_col = db['keys']
api_logs_col = db['api_logs']
settings_col = db['settings']
users_col = db['users']
bot_states_col = db['bot_states']

# Initialize default admin
def init_db():
    if not users_col.find_one({"role": "admin"}):
        admin_user = {
            "username": "admin",
            "password": bcrypt.generate_password_hash("admin123").decode('utf-8'),
            "role": "admin",
            "owner_name": "@VIP_X_OFFICIAL",
            "channel": "https://t.me/WebBot_Lab",
            "created_at": datetime.utcnow()
        }
        users_col.insert_one(admin_user)
        
        settings_col.update_one(
            {"type": "admin_settings"},
            {"$set": {
                "owner_display": "@VIP_X_OFFICIAL",
                "channel": "https://t.me/WebBot_Lab",
                "default_daily_limit": 100,
                "default_expiry_days": 30,
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
        print("✅ Database initialized with default admin")

init_db()

# ==================== TELEGRAM BOT FUNCTIONS ====================

def send_telegram_message(chat_id, text, parse_mode='HTML'):
    """Send message to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram send error: {e}")
        return None

def send_telegram_with_keyboard(chat_id, text, buttons, parse_mode='HTML'):
    """Send message with inline keyboard"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    keyboard = {
        "inline_keyboard": buttons
    }
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'reply_markup': keyboard
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram keyboard error: {e}")
        return None

def edit_telegram_message(chat_id, message_id, text, buttons=None, parse_mode='HTML'):
    """Edit existing message"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': parse_mode
    }
    
    if buttons:
        payload['reply_markup'] = {"inline_keyboard": buttons}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram edit error: {e}")
        return None

def answer_callback(chat_id, callback_query_id, text):
    """Answer callback query"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {
        'callback_query_id': callback_query_id,
        'text': text,
        'show_alert': False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Callback answer error: {e}")

def is_admin(user_id):
    """Check if user is admin"""
    return user_id in TELEGRAM_ADMIN_IDS

# ==================== BOT STATE MANAGEMENT ====================

def set_user_state(user_id, state, data=None):
    """Set user's bot state"""
    bot_states_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "state": state,
            "data": data or {},
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )

def get_user_state(user_id):
    """Get user's bot state"""
    state = bot_states_col.find_one({"user_id": user_id})
    if state:
        return state.get('state'), state.get('data', {})
    return None, {}

def clear_user_state(user_id):
    """Clear user's bot state"""
    bot_states_col.delete_one({"user_id": user_id})

# ==================== BOT COMMAND HANDLERS ====================

def handle_start(chat_id, user_id):
    """Handle /start command"""
    if not is_admin(user_id):
        send_telegram_message(chat_id, "❌ Unauthorized! You are not an admin.")
        return
    
    text = (
        "🤖 <b>API Admin Bot</b>\n\n"
        "Welcome to the Admin Panel!\n\n"
        "📊 <b>Commands:</b>\n"
        "/start - Show this menu\n"
        "/stats - View API statistics\n"
        "/keys - Manage API keys\n"
        "/createkey - Create new API key\n"
        "/logs - View recent logs\n"
        "/settings - Bot settings\n"
        "/help - Show help"
    )
    
    buttons = [
        [{"text": "📊 Statistics", "callback_data": "stats"}],
        [{"text": "🔑 Manage Keys", "callback_data": "list_keys"}],
        [{"text": "➕ Create Key", "callback_data": "create_key"}],
        [{"text": "📋 Recent Logs", "callback_data": "logs"}],
        [{"text": "⚙️ Settings", "callback_data": "settings"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_stats(chat_id, user_id):
    """Handle /stats command"""
    if not is_admin(user_id):
        return
    
    total_keys = keys_col.count_documents({})
    active_keys = keys_col.count_documents({"expires_on": {"$gt": datetime.utcnow()}})
    expired_keys = keys_col.count_documents({"expires_on": {"$lt": datetime.utcnow()}})
    
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_searches = api_logs_col.count_documents({"timestamp": {"$gte": today}})
    total_searches = api_logs_col.count_documents({})
    
    settings = settings_col.find_one({"type": "admin_settings"}) or {}
    channel = settings.get('channel', 'https://t.me/WebBot_Lab')
    owner = settings.get('owner_display', '@VIP_X_OFFICIAL')
    
    text = (
        f"📊 <b>API Statistics</b>\n\n"
        f"🔑 <b>Keys:</b>\n"
        f"├ Total: {total_keys}\n"
        f"├ Active: {active_keys}\n"
        f"└ Expired: {expired_keys}\n\n"
        f"📈 <b>Searches:</b>\n"
        f"├ Today: {today_searches}\n"
        f"└ Total: {total_searches}\n\n"
        f"👑 <b>Owner:</b> {owner}\n"
        f"📢 <b>Channel:</b> {channel}"
    )
    
    buttons = [
        [{"text": "🔄 Refresh", "callback_data": "stats"}],
        [{"text": "🔙 Back to Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_list_keys(chat_id, user_id, page=1):
    """Handle /keys command - List all keys with pagination"""
    if not is_admin(user_id):
        return
    
    per_page = 5
    total_keys = keys_col.count_documents({})
    total_pages = (total_keys + per_page - 1) // per_page
    
    skip = (page - 1) * per_page
    keys = list(keys_col.find().sort("created_at", -1).skip(skip).limit(per_page))
    
    if not keys:
        send_telegram_message(chat_id, "❌ No keys found!")
        return
    
    text = f"🔑 <b>API Keys (Page {page}/{total_pages})</b>\n\n"
    
    buttons = []
    
    for idx, key in enumerate(keys, 1):
        status = "✅ Active" if key['expires_on'] > datetime.utcnow() else "❌ Expired"
        expires = key['expires_on'].strftime('%Y-%m-%d')
        limit = key.get('daily_limit', 100)
        
        text += (
            f"{idx}. <code>{key['key']}</code>\n"
            f"   ├ Owner: {key.get('owner_name', '@VIP_X_OFFICIAL')}\n"
            f"   ├ Expires: {expires}\n"
            f"   ├ Limit: {limit}/day\n"
            f"   └ Status: {status}\n\n"
        )
        
        buttons.append([{"text": f"🔧 Manage {key['key'][:4]}...", "callback_data": f"view_key_{key['_id']}"}])
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append({"text": "⬅️ Prev", "callback_data": f"keys_page_{page-1}"})
    if page < total_pages:
        nav_buttons.append({"text": "Next ➡️", "callback_data": f"keys_page_{page+1}"})
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([{"text": "➕ Create New Key", "callback_data": "create_key"}])
    buttons.append([{"text": "🔙 Back to Menu", "callback_data": "main_menu"}])
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_view_key(chat_id, user_id, key_id):
    """View single key details"""
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        days_remaining = (key['expires_on'] - datetime.utcnow()).days
        status = "✅ Active" if days_remaining > 0 else "❌ Expired"
        
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_searches = api_logs_col.count_documents({
            "key": key['key'],
            "timestamp": {"$gte": today}
        })
        
        total_searches = api_logs_col.count_documents({"key": key['key']})
        
        text = (
            f"🔑 <b>Key Details</b>\n\n"
            f"<b>Key:</b> <code>{key['key']}</code>\n"
            f"<b>Owner:</b> {key.get('owner_name', '@VIP_X_OFFICIAL')}\n"
            f"<b>Created:</b> {key['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"<b>Expires:</b> {key['expires_on'].strftime('%Y-%m-%d')}\n"
            f"<b>Days Left:</b> {days_remaining}\n"
            f"<b>Daily Limit:</b> {key.get('daily_limit', 100)}/day\n"
            f"<b>Today's Searches:</b> {today_searches}\n"
            f"<b>Total Searches:</b> {total_searches}\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Notes:</b> {key.get('notes', 'No notes')}\n"
        )
        
        buttons = [
            [{"text": "✏️ Edit Owner", "callback_data": f"edit_key_owner_{key_id}"}],
            [{"text": "⏱️ Extend Expiry", "callback_data": f"extend_key_{key_id}"}],
            [{"text": "📊 View Logs", "callback_data": f"key_logs_{key_id}"}],
            [{"text": "🗑️ Delete Key", "callback_data": f"delete_key_{key_id}"}],
            [{"text": "🔙 Back to Keys", "callback_data": "list_keys"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_create_key_start(chat_id, user_id):
    """Start create key process"""
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "creating_key", {})
    
    text = (
        "➕ <b>Create New API Key</b>\n\n"
        "Please enter the following details:\n\n"
        "1️⃣ <b>Owner Name</b> (e.g., @VIP_X_OFFICIAL)\n"
        "Send /cancel to abort."
    )
    
    send_telegram_message(chat_id, text)

def handle_create_key_owner(chat_id, user_id, owner_name):
    """Handle owner name input"""
    state, data = get_user_state(user_id)
    
    if state != "creating_key":
        return
    
    data['owner_name'] = owner_name
    set_user_state(user_id, "creating_key_expiry", data)
    
    text = (
        "✅ Owner name saved!\n\n"
        "2️⃣ <b>Expiry Days</b>\n"
        "How many days should this key last?\n"
        "(e.g., 30, 60, 90, 365)"
    )
    
    send_telegram_message(chat_id, text)

def handle_create_key_expiry(chat_id, user_id, expiry_days_str):
    """Handle expiry days input"""
    state, data = get_user_state(user_id)
    
    if state != "creating_key_expiry":
        return
    
    try:
        expiry_days = int(expiry_days_str)
        if expiry_days <= 0:
            raise ValueError
        
        data['expiry_days'] = expiry_days
        set_user_state(user_id, "creating_key_limit", data)
        
        text = (
            f"✅ Expiry set to {expiry_days} days!\n\n"
            "3️⃣ <b>Daily Search Limit</b>\n"
            "How many searches per day?\n"
            "(e.g., 100, 500, 1000, 999999 for unlimited)"
        )
        
        send_telegram_message(chat_id, text)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number! Please enter a valid number:")

def handle_create_key_limit(chat_id, user_id, limit_str):
    """Handle daily limit input and create key"""
    state, data = get_user_state(user_id)
    
    if state != "creating_key_limit":
        return
    
    try:
        daily_limit = int(limit_str)
        if daily_limit <= 0:
            raise ValueError
        
        key_value = str(uuid.uuid4())[:8].upper()
        expires_on = datetime.utcnow() + timedelta(days=data['expiry_days'])
        
        new_key = {
            "key": key_value,
            "owner_name": data['owner_name'],
            "created_at": datetime.utcnow(),
            "expires_on": expires_on,
            "daily_limit": daily_limit,
            "is_active": True,
            "notes": f"Created via Telegram Bot",
            "created_by": f"tg_{user_id}"
        }
        
        keys_col.insert_one(new_key)
        
        text = (
            f"✅ <b>Key Created Successfully!</b>\n\n"
            f"<b>Key:</b> <code>{key_value}</code>\n"
            f"<b>Owner:</b> {data['owner_name']}\n"
            f"<b>Expires:</b> {expires_on.strftime('%Y-%m-%d')}\n"
            f"<b>Daily Limit:</b> {daily_limit}/day\n\n"
            f"📋 Copy your key: <code>{key_value}</code>"
        )
        
        buttons = [
            [{"text": "🔑 View All Keys", "callback_data": "list_keys"}],
            [{"text": "➕ Create Another", "callback_data": "create_key"}],
            [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        clear_user_state(user_id)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number! Please enter a valid number:")

def handle_extend_key(chat_id, user_id, key_id):
    """Start extend key process"""
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        set_user_state(user_id, f"extending_key_{key_id}", {})
        
        text = (
            f"⏱️ <b>Extend Key Expiry</b>\n\n"
            f"Key: <code>{key['key']}</code>\n"
            f"Current Expiry: {key['expires_on'].strftime('%Y-%m-%d')}\n\n"
            f"Send number of days to extend (e.g., 30):\n"
            f"Send /cancel to abort."
        )
        
        send_telegram_message(chat_id, text)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_extend_key_days(chat_id, user_id, key_id, days_str):
    """Handle extend days input"""
    try:
        days = int(days_str)
        if days <= 0:
            raise ValueError
        
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            clear_user_state(user_id)
            return
        
        new_expiry = key['expires_on'] + timedelta(days=days)
        
        keys_col.update_one(
            {"_id": ObjectId(key_id)},
            {"$set": {"expires_on": new_expiry}}
        )
        
        text = (
            f"✅ <b>Key Extended Successfully!</b>\n\n"
            f"Key: <code>{key['key']}</code>\n"
            f"New Expiry: {new_expiry.strftime('%Y-%m-%d')}\n"
            f"Extended by: {days} days"
        )
        
        buttons = [
            [{"text": "🔑 View Key", "callback_data": f"view_key_{key_id}"}],
            [{"text": "🔙 Back to Keys", "callback_data": "list_keys"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        clear_user_state(user_id)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number! Please enter a valid number:")

def handle_delete_key(chat_id, user_id, key_id):
    """Delete key confirmation"""
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        text = (
            f"⚠️ <b>Delete Key?</b>\n\n"
            f"Key: <code>{key['key']}</code>\n"
            f"Owner: {key.get('owner_name', '@VIP_X_OFFICIAL')}\n\n"
            f"Are you sure you want to delete this key?\n"
            f"This action cannot be undone!"
        )
        
        buttons = [
            [{"text": "✅ Yes, Delete", "callback_data": f"confirm_delete_{key_id}"}],
            [{"text": "❌ No, Cancel", "callback_data": f"view_key_{key_id}"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_confirm_delete(chat_id, user_id, key_id):
    """Confirm and delete key"""
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if key:
            key_value = key['key']
            keys_col.delete_one({"_id": ObjectId(key_id)})
            api_logs_col.delete_many({"key": key_value})
            
            text = f"✅ Key <code>{key_value}</code> deleted successfully!"
        else:
            text = "❌ Key not found!"
        
        buttons = [
            [{"text": "🔑 View All Keys", "callback_data": "list_keys"}],
            [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_key_logs(chat_id, user_id, key_id):
    """View logs for specific key"""
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        logs = list(api_logs_col.find({"key": key['key']})
                    .sort("timestamp", -1)
                    .limit(10))
        
        if not logs:
            text = f"📋 No logs found for key <code>{key['key']}</code>"
        else:
            text = f"📋 <b>Recent Logs for {key['key']}</b>\n\n"
            
            for log in logs:
                time_str = log['timestamp'].strftime('%Y-%m-%d %H:%M')
                text += f"🕒 {time_str} - User: {log['user_id']}\n"
        
        buttons = [
            [{"text": "🔑 View Key", "callback_data": f"view_key_{key_id}"}],
            [{"text": "🔙 Back to Keys", "callback_data": "list_keys"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_all_logs(chat_id, user_id):
    """View all recent logs"""
    if not is_admin(user_id):
        return
    
    logs = list(api_logs_col.find().sort("timestamp", -1).limit(10))
    
    if not logs:
        text = "📋 No logs found!"
    else:
        text = "📋 <b>Recent API Logs (Last 10)</b>\n\n"
        
        for log in logs:
            time_str = log['timestamp'].strftime('%Y-%m-%d %H:%M')
            text += f"🕒 {time_str}\n"
            text += f"├ Key: <code>{log['key'][:8]}...</code>\n"
            text += f"├ User: {log['user_id']}\n"
            text += f"└ IP: {log['ip_address']}\n\n"
    
    buttons = [
        [{"text": "🔄 Refresh", "callback_data": "logs"}],
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_settings(chat_id, user_id):
    """View and edit settings"""
    if not is_admin(user_id):
        return
    
    settings = settings_col.find_one({"type": "admin_settings"}) or {}
    
    text = (
        "⚙️ <b>Bot Settings</b>\n\n"
        f"👑 <b>Owner:</b> {settings.get('owner_display', '@VIP_X_OFFICIAL')}\n"
        f"📢 <b>Channel:</b> {settings.get('channel', 'https://t.me/WebBot_Lab')}\n"
        f"📊 <b>Default Daily Limit:</b> {settings.get('default_daily_limit', 100)}\n"
        f"⏱️ <b>Default Expiry:</b> {settings.get('default_expiry_days', 30)} days\n"
    )
    
    buttons = [
        [{"text": "✏️ Edit Owner", "callback_data": "edit_owner"}],
        [{"text": "✏️ Edit Channel", "callback_data": "edit_channel"}],
        [{"text": "✏️ Edit Default Limit", "callback_data": "edit_default_limit"}],
        [{"text": "✏️ Edit Default Expiry", "callback_data": "edit_default_expiry"}],
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_edit_owner_start(chat_id, user_id):
    """Start edit owner process"""
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "editing_owner", {})
    send_telegram_message(chat_id, "📝 Send new owner name (e.g., @VIP_X_OFFICIAL):")

def handle_edit_owner(chat_id, user_id, owner_name):
    """Handle owner edit"""
    state, data = get_user_state(user_id)
    
    if state != "editing_owner":
        return
    
    settings_col.update_one(
        {"type": "admin_settings"},
        {"$set": {"owner_display": owner_name}},
        upsert=True
    )
    
    text = f"✅ Owner name updated to: {owner_name}"
    
    buttons = [
        [{"text": "⚙️ Back to Settings", "callback_data": "settings"}],
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)
    clear_user_state(user_id)

def handle_edit_channel_start(chat_id, user_id):
    """Start edit channel process"""
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "editing_channel", {})
    send_telegram_message(chat_id, "📝 Send new channel URL:")

def handle_edit_channel(chat_id, user_id, channel):
    """Handle channel edit"""
    state, data = get_user_state(user_id)
    
    if state != "editing_channel":
        return
    
    settings_col.update_one(
        {"type": "admin_settings"},
        {"$set": {"channel": channel}},
        upsert=True
    )
    
    text = f"✅ Channel updated to: {channel}"
    
    buttons = [
        [{"text": "⚙️ Back to Settings", "callback_data": "settings"}],
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)
    clear_user_state(user_id)

def handle_edit_default_limit_start(chat_id, user_id):
    """Start edit default limit process"""
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "editing_default_limit", {})
    send_telegram_message(chat_id, "📝 Send new default daily limit (e.g., 100):")

def handle_edit_default_limit(chat_id, user_id, limit_str):
    """Handle default limit edit"""
    state, data = get_user_state(user_id)
    
    if state != "editing_default_limit":
        return
    
    try:
        limit = int(limit_str)
        if limit <= 0:
            raise ValueError
        
        settings_col.update_one(
            {"type": "admin_settings"},
            {"$set": {"default_daily_limit": limit}},
            upsert=True
        )
        
        text = f"✅ Default daily limit updated to: {limit}"
        
        buttons = [
            [{"text": "⚙️ Back to Settings", "callback_data": "settings"}],
            [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        clear_user_state(user_id)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number! Please enter a valid number:")

def handle_edit_default_expiry_start(chat_id, user_id):
    """Start edit default expiry process"""
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "editing_default_expiry", {})
    send_telegram_message(chat_id, "📝 Send new default expiry days (e.g., 30):")

def handle_edit_default_expiry(chat_id, user_id, days_str):
    """Handle default expiry edit"""
    state, data = get_user_state(user_id)
    
    if state != "editing_default_expiry":
        return
    
    try:
        days = int(days_str)
        if days <= 0:
            raise ValueError
        
        settings_col.update_one(
            {"type": "admin_settings"},
            {"$set": {"default_expiry_days": days}},
            upsert=True
        )
        
        text = f"✅ Default expiry days updated to: {days}"
        
        buttons = [
            [{"text": "⚙️ Back to Settings", "callback_data": "settings"}],
            [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        clear_user_state(user_id)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number! Please enter a valid number:")

def handle_help(chat_id, user_id):
    """Handle /help command"""
    if not is_admin(user_id):
        return
    
    text = (
        "🤖 <b>Bot Commands</b>\n\n"
        "<b>Basic Commands:</b>\n"
        "/start - Show main menu\n"
        "/stats - View API statistics\n"
        "/keys - List all API keys\n"
        "/createkey - Create new key\n"
        "/logs - View recent logs\n"
        "/settings - Bot settings\n"
        "/help - Show this help\n\n"
        "<b>Navigation:</b>\n"
        "• Use buttons to navigate\n"
        "• Click on keys to manage them\n"
        "• Use /cancel to cancel any operation"
    )
    
    buttons = [
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_cancel(chat_id, user_id):
    """Handle /cancel command"""
    state, data = get_user_state(user_id)
    
    if state:
        clear_user_state(user_id)
        text = "✅ Operation cancelled. Use /start for main menu."
    else:
        text = "❌ No active operation to cancel."
    
    buttons = [
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

# ==================== API KEY VALIDATION DECORATOR ====================

def validate_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.args.get('key')
        user_id = request.args.get('userid')
        
        if not api_key or not user_id:
            return jsonify({
                "status": "error",
                "code": 400,
                "message": "Missing key or userid parameter",
                "owner": "@VIP_X_OFFICIAL",
                "channel": "https://t.me/WebBot_Lab"
            }), 400
        
        key_data = keys_col.find_one({"key": api_key})
        
        if not key_data:
            return jsonify({
                "status": "error",
                "code": 401,
                "message": "Invalid API key",
                "owner": "@VIP_X_OFFICIAL",
                "channel": "https://t.me/WebBot_Lab"
            }), 401
        
        if key_data['expires_on'] < datetime.utcnow():
            return jsonify({
                "status": "error",
                "code": 403,
                "message": "API key has expired",
                "owner": "@VIP_X_OFFICIAL",
                "channel": "https://t.me/WebBot_Lab"
            }), 403
        
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        
        search_count = api_logs_col.count_documents({
            "key": api_key,
            "timestamp": {"$gte": today, "$lt": tomorrow}
        })
        
        daily_limit = key_data.get('daily_limit', 100)
        
        if search_count >= daily_limit:
            return jsonify({
                "status": "error",
                "code": 429,
                "message": f"Daily search limit reached. Used {search_count}/{daily_limit} today",
                "owner": "@VIP_X_OFFICIAL",
                "channel": "https://t.me/WebBot_Lab"
            }), 429
        
        request_id = str(uuid.uuid4())
        api_logs_col.insert_one({
            "request_id": request_id,
            "key": api_key,
            "key_owner": key_data.get('owner_name', '@VIP_X_OFFICIAL'),
            "user_id": user_id,
            "timestamp": datetime.utcnow(),
            "ip_address": request.remote_addr,
            "user_agent": request.user_agent.string
        })
        
        request.key_data = key_data
        request.search_count = search_count + 1
        request.daily_limit = daily_limit
        request.request_id = request_id
        
        return f(*args, **kwargs)
    return decorated_function

# ==================== SEARCH FUNCTION ====================

def search_telegram_id(user_id):
    """Search using both APIs and return the best result"""
    results = []
    
    # API 1
    try:
        response1 = requests.get(
            f"https://tg-2-num-api-org.vercel.app/api/search?userid={user_id}",
            timeout=10
        )
        if response1.status_code == 200:
            data1 = response1.json()
            if data1.get("status") == "success" and data1.get("data"):
                results.append({
                    "source": "API 1",
                    "status": "success",
                    "data": data1.get("data"),
                    "response_time": data1.get("response_time", "N/A")
                })
    except Exception as e:
        print(f"API 1 error: {str(e)}")
    
    # API 2
    try:
        response2 = requests.get(
            f"https://z4x-telegram-to-number-api.onrender.com/search?key=Z4X-ERO8MSL9-Silent&userid={user_id}",
            timeout=10
        )
        if response2.status_code == 200:
            data2 = response2.json()
            if data2.get("status") == "success" and data2.get("data"):
                results.append({
                    "source": "API 2",
                    "status": "success",
                    "data": data2.get("data"),
                    "response_time": data2.get("response_time", "N/A")
                })
    except Exception as e:
        print(f"API 2 error: {str(e)}")
    
    settings = settings_col.find_one({"type": "admin_settings"}) or {}
    channel = settings.get('channel', 'https://t.me/WebBot_Lab')
    
    for result in results:
        if result.get("status") == "success" and result.get("data"):
            key_data = request.key_data
            search_count = request.search_count
            daily_limit = request.daily_limit
            
            expires_on = key_data['expires_on']
            days_remaining = (expires_on - datetime.utcnow()).days
            hours_remaining = ((expires_on - datetime.utcnow()).seconds // 3600)
            
            response = {
                "status": "success",
                "code": 200,
                "searched_userid": user_id,
                "response_time": result.get("response_time", "N/A"),
                "data": {
                    "found": True,
                    "country": result["data"].get("country"),
                    "country_code": result["data"].get("country_code"),
                    "number": result["data"].get("number")
                },
                "owner": {
                    "name": "@VIP_X_OFFICIAL",
                    "channel": channel
                },
                "key_info": {
                    "key": request.args.get('key'),
                    "created_at": key_data.get('created_at').strftime("%Y-%m-%d %H:%M:%S") if key_data.get('created_at') else "N/A",
                    "expires_on": key_data.get('expires_on').strftime("%Y-%m-%d %H:%M:%S"),
                    "days_remaining": days_remaining,
                    "hours_remaining": hours_remaining,
                    "daily_limit": daily_limit,
                    "searches_today": search_count,
                    "searches_remaining": daily_limit - search_count
                },
                "request_id": request.request_id
            }
            return jsonify(response)
    
    return jsonify({
        "status": "error",
        "code": 404,
        "message": "User ID not found in any database",
        "searched_userid": user_id,
        "owner": "@VIP_X_OFFICIAL",
        "channel": channel
    }), 404

# ==================== PUBLIC ROUTES ====================

@app.route('/')
def home():
    settings = settings_col.find_one({"type": "admin_settings"}) or {}
    channel = settings.get('channel', 'https://t.me/WebBot_Lab')
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram to Number API</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 40px;
                max-width: 800px;
                width: 100%;
            }}
            h1 {{ color: #333; margin-bottom: 10px; }}
            .owner-badge {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; padding: 10px 20px; border-radius: 50px;
                display: inline-block; margin-bottom: 30px; font-weight: bold;
            }}
            .endpoint {{
                background: #f5f5f5; border-radius: 10px; padding: 20px; margin: 20px 0;
            }}
            code {{
                background: #333; color: #fff; padding: 5px 10px; border-radius: 5px;
                display: block; margin: 10px 0;
            }}
            .features {{
                display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px; margin: 30px 0;
            }}
            .feature {{
                background: #f9f9f9; padding: 20px; border-radius: 10px; text-align: center;
            }}
            .feature h4 {{ color: #667eea; margin-bottom: 10px; }}
            .bot-link {{
                text-align: center; margin-top: 30px;
            }}
            .bot-link a {{
                background: #667eea; color: white; text-decoration: none;
                padding: 10px 30px; border-radius: 50px; display: inline-block;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Telegram to Number API</h1>
            <div class="owner-badge">Owner: @VIP_X_OFFICIAL</div>
            
            <div class="endpoint">
                <h3>🔍 API Endpoint</h3>
                <code>GET /api/search?key=YOUR_KEY&userid=TELEGRAM_ID</code>
                <p>Search for phone number by Telegram User ID</p>
            </div>
            
            <div class="features">
                <div class="feature">
                    <h4>🔑 Key Management</h4>
                    <p>Create and manage API keys with custom expiry</p>
                </div>
                <div class="feature">
                    <h4>⚡ Rate Limiting</h4>
                    <p>Set daily search limits per key</p>
                </div>
                <div class="feature">
                    <h4>👑 Owner</h4>
                    <p>@VIP_X_OFFICIAL</p>
                </div>
                <div class="feature">
                    <h4>🤖 Telegram Bot</h4>
                    <p>Full admin control via Telegram</p>
                </div>
            </div>
            
            <div class="bot-link">
                <a href="https://t.me/WebBot_Lab" target="_blank">🤖 Admin Bot</a>
            </div>
            
            <p style="text-align: center; margin-top: 20px;">
                Channel: <a href="{channel}" target="_blank">{channel}</a>
            </p>
        </div>
    </body>
    </html>
    '''

@app.route('/api/search', methods=['GET'])
@validate_api_key
def search_api():
    user_id = request.args.get('userid')
    return search_telegram_id(user_id)

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram updates"""
    try:
        update = request.json
        
        # Handle callback queries
        if 'callback_query' in update:
            callback = update['callback_query']
            callback_id = callback['id']
            chat_id = callback['message']['chat']['id']
            message_id = callback['message']['message_id']
            user_id = callback['from']['id']
            data = callback['data']
            
            answer_callback(chat_id, callback_id, "Processing...")
            
            if data == "main_menu":
                handle_start(chat_id, user_id)
            elif data == "stats":
                handle_stats(chat_id, user_id)
            elif data == "list_keys":
                handle_list_keys(chat_id, user_id)
            elif data.startswith("keys_page_"):
                page = int(data.replace("keys_page_", ""))
                handle_list_keys(chat_id, user_id, page)
            elif data.startswith("view_key_"):
                key_id = data.replace("view_key_", "")
                handle_view_key(chat_id, user_id, key_id)
            elif data == "create_key":
                handle_create_key_start(chat_id, user_id)
            elif data == "logs":
                handle_all_logs(chat_id, user_id)
            elif data == "settings":
                handle_settings(chat_id, user_id)
            elif data == "edit_owner":
                handle_edit_owner_start(chat_id, user_id)
            elif data == "edit_channel":
                handle_edit_channel_start(chat_id, user_id)
            elif data == "edit_default_limit":
                handle_edit_default_limit_start(chat_id, user_id)
            elif data == "edit_default_expiry":
                handle_edit_default_expiry_start(chat_id, user_id)
            elif data.startswith("extend_key_"):
                key_id = data.replace("extend_key_", "")
                handle_extend_key(chat_id, user_id, key_id)
            elif data.startswith("delete_key_"):
                key_id = data.replace("delete_key_", "")
                handle_delete_key(chat_id, user_id, key_id)
            elif data.startswith("confirm_delete_"):
                key_id = data.replace("confirm_delete_", "")
                handle_confirm_delete(chat_id, user_id, key_id)
            elif data.startswith("key_logs_"):
                key_id = data.replace("key_logs_", "")
                handle_key_logs(chat_id, user_id, key_id)
            
            return jsonify({"ok": True})
        
        # Handle messages
        elif 'message' in update:
            msg = update['message']
            chat_id = msg['chat']['id']
            user_id = msg['from']['id']
            
            if not is_admin(user_id):
                send_telegram_message(chat_id, "❌ Unauthorized! You are not an admin.")
                return jsonify({"ok": True})
            
            if 'text' in msg:
                text = msg['text']
                
                if text.startswith('/start'):
                    handle_start(chat_id, user_id)
                elif text.startswith('/stats'):
                    handle_stats(chat_id, user_id)
                elif text.startswith('/keys'):
                    handle_list_keys(chat_id, user_id)
                elif text.startswith('/createkey'):
                    handle_create_key_start(chat_id, user_id)
                elif text.startswith('/logs'):
                    handle_all_logs(chat_id, user_id)
                elif text.startswith('/settings'):
                    handle_settings(chat_id, user_id)
                elif text.startswith('/help'):
                    handle_help(chat_id, user_id)
                elif text.startswith('/cancel'):
                    handle_cancel(chat_id, user_id)
                else:
                    state, data = get_user_state(user_id)
                    
                    if state == "creating_key":
                        handle_create_key_owner(chat_id, user_id, text)
                    elif state == "creating_key_expiry":
                        handle_create_key_expiry(chat_id, user_id, text)
                    elif state == "creating_key_limit":
                        handle_create_key_limit(chat_id, user_id, text)
                    elif state and state.startswith("extending_key_"):
                        key_id = state.replace("extending_key_", "")
                        handle_extend_key_days(chat_id, user_id, key_id, text)
                    elif state == "editing_owner":
                        handle_edit_owner(chat_id, user_id, text)
                    elif state == "editing_channel":
                        handle_edit_channel(chat_id, user_id, text)
                    elif state == "editing_default_limit":
                        handle_edit_default_limit(chat_id, user_id, text)
                    elif state == "editing_default_expiry":
                        handle_edit_default_expiry(chat_id, user_id, text)
                    else:
                        send_telegram_message(chat_id, "❌ Unknown command. Use /start")
        
        return jsonify({"ok": True})
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False}), 500

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    """Set Telegram webhook"""
    webhook_url = request.url_root.rstrip('/') + '/webhook'
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    response = requests.post(url, json={'url': webhook_url})
    return jsonify({
        "status": "Webhook set",
        "url": webhook_url,
        "response": response.json()
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "time": datetime.utcnow().isoformat()})

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 60)
    print("🤖 Telegram Bot Admin Panel - Heroku Ready (FULL VERSION)")
    print("=" * 60)
    print(f"\n📊 Features Included:")
    print("   ✅ Key Management (Create, Edit, Delete, Extend)")
    print("   ✅ Rate Limiting (Per key daily limits)")
    print("   ✅ Statistics (Keys, Searches)")
    print("   ✅ Logs (View all API calls)")
    print("   ✅ Settings (Owner, Channel, Defaults)")
    print("   ✅ Pagination (For large key lists)")
    print("   ✅ State Management (Multi-step operations)")
    print("   ✅ Admin Authorization")
    print("\n🌐 Server Information:")
    print(f"   📱 Port: {PORT}")
    print(f"   📋 Health Check: /health")
    print(f"   🤖 Webhook URL: /webhook")
    print(f"   🔗 Set Webhook: /setwebhook")
    print("\n✅ After deployment, visit:")
    print(f"   https://your-app.herokuapp.com/setwebhook - To set webhook")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=PORT)