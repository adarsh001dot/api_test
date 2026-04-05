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
apis_col = db['apis']

# ==================== INITIALIZE DATABASE ====================
def init_db():
    # Create admin user if not exists
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
    
    # Create default settings if not exists
    if not settings_col.find_one({"type": "admin_settings"}):
        settings_col.insert_one({
            "type": "admin_settings",
            "owner_display": "@VIP_X_OFFICIAL",
            "channel": "https://t.me/WebBot_Lab",
            "default_daily_limit": 100,
            "default_expiry_days": 30,
            "updated_at": datetime.utcnow()
        })
    
    # Initialize APIs
    if apis_col.count_documents({}) == 0:
        default_apis = [
            {
                "name": "Vercel API",
                "url": "https://cyber-osint-tg-num.vercel.app/api/tginfo?key=Trail5&id={user_id}",
                "method": "GET",
                "status": "active",
                "priority": 1,
                "success_count": 0,
                "fail_count": 0,
                "last_checked": datetime.utcnow(),
                "added_by": "system",
                "notes": "Working API - Primary"
            },
            {
                "name": "Backup API",
                "url": "https://exploitsindia.site/api/telegram.php?exploits={user_id}",
                "method": "GET",
                "status": "active",
                "priority": 2,
                "success_count": 0,
                "fail_count": 0,
                "last_checked": datetime.utcnow(),
                "added_by": "system",
                "notes": "Backup API"
            }
        ]
        apis_col.insert_many(default_apis)
        print("✅ Default APIs initialized")
    
    print("✅ Database initialized")

init_db()

# ==================== TELEGRAM BOT FUNCTIONS ====================

def send_telegram_message(chat_id, text, parse_mode='HTML'):
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
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {"inline_keyboard": buttons}
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

def answer_callback(chat_id, callback_query_id, text):
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
    return user_id in TELEGRAM_ADMIN_IDS

# ==================== BOT STATE MANAGEMENT ====================

def set_user_state(user_id, state, data=None):
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
    state = bot_states_col.find_one({"user_id": user_id})
    if state:
        return state.get('state'), state.get('data', {})
    return None, {}

def clear_user_state(user_id):
    bot_states_col.delete_one({"user_id": user_id})

# ==================== API MANAGEMENT FUNCTIONS ====================

def test_api_health(api):
    """Test if an API is working"""
    try:
        test_user_id = "7459756974"
        url = api['url'].format(user_id=test_user_id)
        
        start_time = time.time()
        response = requests.get(url, timeout=10)
        response_time = (time.time() - start_time) * 1000
        
        if response.status_code == 200:
            data = response.json()
            # Handle multiple response formats
            if data.get("status") == "success" and data.get("data"):
                return {"working": True, "response_time": response_time, "status_code": response.status_code}
            elif data.get("success") == True and data.get("number"):
                return {"working": True, "response_time": response_time, "status_code": response.status_code}
        
        return {"working": False, "response_time": response_time, "status_code": response.status_code}
    except Exception as e:
        return {"working": False, "error": str(e)}

def get_active_apis():
    return list(apis_col.find({"status": "active"}).sort("priority", 1))

# ==================== UPDATED SEARCH FUNCTION - WITH RESPONSE TIME ====================

def search_telegram_id(user_id, start_time):
    """Search using active APIs with automatic failover - Returns formatted response"""
    
    active_apis = get_active_apis()
    
    if not active_apis:
        return {
            "status": "error",
            "code": 503,
            "message": "No active APIs available",
            "searched_userid": user_id
        }
    
    errors = []
    
    for api in active_apis:
        try:
            print(f"Trying API: {api['name']} for userid: {user_id}")
            url = api['url'].format(user_id=user_id)
            
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Update success count
                apis_col.update_one(
                    {"_id": api['_id']},
                    {"$inc": {"success_count": 1}, "$set": {"last_checked": datetime.utcnow()}}
                )
                
                # ===== HANDLE MULTIPLE RESPONSE FORMATS =====
                
                # Format 1: {"status":"success","data":{"country":"...","number":"..."}}
                if data.get("status") == "success" and data.get("data"):
                    return {
                        "status": "success",
                        "found": True,
                        "country": data["data"].get("country"),
                        "country_code": data["data"].get("country_code"),
                        "number": data["data"].get("number")
                    }
                
                # Format 2: {"success":true,"country":"India","number":"..."} (Vercel format)
                elif data.get("success") == True and data.get("number"):
                    return {
                        "status": "success",
                        "found": True,
                        "country": data.get("country"),
                        "country_code": data.get("country_code", "+91"),
                        "number": data.get("number")
                    }
                
                # Format 3: Direct fields
                elif data.get("number"):
                    return {
                        "status": "success",
                        "found": True,
                        "country": data.get("country", "Unknown"),
                        "country_code": data.get("country_code", "+91"),
                        "number": data.get("number")
                    }
            
            # Update fail count
            apis_col.update_one(
                {"_id": api['_id']},
                {"$inc": {"fail_count": 1}, "$set": {"last_checked": datetime.utcnow()}}
            )
            errors.append(f"{api['name']}: HTTP {response.status_code}")
            
        except Exception as e:
            errors.append(f"{api['name']}: {str(e)}")
            apis_col.update_one(
                {"_id": api['_id']},
                {"$inc": {"fail_count": 1}, "$set": {"last_checked": datetime.utcnow()}}
            )
    
    # If all APIs failed
    return {
        "status": "error",
        "code": 404,
        "message": "User ID not found in any database",
        "searched_userid": user_id
    }

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
                "message": "Missing key or userid parameter"
            }), 400
        
        key_data = keys_col.find_one({"key": api_key})
        
        if not key_data:
            return jsonify({
                "status": "error",
                "code": 401,
                "message": "Invalid API key"
            }), 401
        
        if key_data['expires_on'] < datetime.utcnow():
            return jsonify({
                "status": "error",
                "code": 403,
                "message": "API key has expired"
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
                "message": f"Daily search limit reached. Used {search_count}/{daily_limit} today"
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

# ==================== BOT COMMAND HANDLERS (simplified) ====================

def handle_start(chat_id, user_id):
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
        "/apis - Manage source APIs\n"
        "/logs - View recent logs\n"
        "/settings - Bot settings\n"
        "/help - Show help"
    )
    
    buttons = [
        [{"text": "📊 Statistics", "callback_data": "stats"}],
        [{"text": "🔑 Manage Keys", "callback_data": "list_keys"}],
        [{"text": "➕ Create Key", "callback_data": "create_key"}],
        [{"text": "🌐 Manage APIs", "callback_data": "list_apis"}],
        [{"text": "📋 Recent Logs", "callback_data": "logs"}],
        [{"text": "⚙️ Settings", "callback_data": "settings"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_stats(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    total_keys = keys_col.count_documents({})
    active_keys = keys_col.count_documents({"expires_on": {"$gt": datetime.utcnow()}})
    expired_keys = keys_col.count_documents({"expires_on": {"$lt": datetime.utcnow()}})
    
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_searches = api_logs_col.count_documents({"timestamp": {"$gte": today}})
    total_searches = api_logs_col.count_documents({})
    
    total_apis = apis_col.count_documents({})
    active_apis = apis_col.count_documents({"status": "active"})
    
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
        f"🌐 <b>APIs:</b>\n"
        f"├ Total: {total_apis}\n"
        f"└ Active: {active_apis}\n\n"
        f"👑 <b>Owner:</b> {owner}\n"
        f"📢 <b>Channel:</b> {channel}"
    )
    
    buttons = [
        [{"text": "🔄 Refresh", "callback_data": "stats"}],
        [{"text": "🔙 Back to Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_list_keys(chat_id, user_id, page=1):
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
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "creating_key", {})
    text = "➕ <b>Create New API Key</b>\n\nPlease enter owner name (e.g., @VIP_X_OFFICIAL):\nSend /cancel to abort."
    send_telegram_message(chat_id, text)

def handle_create_key_owner(chat_id, user_id, owner_name):
    state, data = get_user_state(user_id)
    if state != "creating_key":
        return
    
    data['owner_name'] = owner_name
    set_user_state(user_id, "creating_key_expiry", data)
    send_telegram_message(chat_id, "✅ Owner saved!\n\nEnter expiry days (e.g., 30):")

def handle_create_key_expiry(chat_id, user_id, expiry_days_str):
    state, data = get_user_state(user_id)
    if state != "creating_key_expiry":
        return
    
    try:
        expiry_days = int(expiry_days_str)
        if expiry_days <= 0:
            raise ValueError
        
        data['expiry_days'] = expiry_days
        set_user_state(user_id, "creating_key_limit", data)
        send_telegram_message(chat_id, f"✅ Expiry set to {expiry_days} days!\n\nEnter daily limit (e.g., 100):")
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number! Please enter a valid number:")

def handle_create_key_limit(chat_id, user_id, limit_str):
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
            "notes": "Created via Telegram Bot",
            "created_by": f"tg_{user_id}"
        }
        
        keys_col.insert_one(new_key)
        
        text = (
            f"✅ <b>Key Created Successfully!</b>\n\n"
            f"<b>Key:</b> <code>{key_value}</code>\n"
            f"<b>Owner:</b> {data['owner_name']}\n"
            f"<b>Expires:</b> {expires_on.strftime('%Y-%m-%d')}\n"
            f"<b>Daily Limit:</b> {daily_limit}/day"
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

def handle_list_apis(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    apis = list(apis_col.find().sort("priority", 1))
    
    if not apis:
        send_telegram_message(chat_id, "❌ No APIs configured!")
        return
    
    text = "🌐 <b>Configured APIs</b>\n\n"
    buttons = []
    
    for api in apis:
        status_emoji = "✅" if api['status'] == "active" else "❌"
        text += f"{status_emoji} <b>{api['name']}</b> (Priority: {api['priority']})\n"
        buttons.append([{"text": f"🔧 Manage {api['name']}", "callback_data": f"view_api_{api['_id']}"}])
    
    buttons.append([{"text": "➕ Add New API", "callback_data": "add_api"}])
    buttons.append([{"text": "🔄 Test All APIs", "callback_data": "test_all_apis"}])
    buttons.append([{"text": "🔙 Main Menu", "callback_data": "main_menu"}])
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_view_api(chat_id, user_id, api_id):
    if not is_admin(user_id):
        return
    
    try:
        api = apis_col.find_one({"_id": ObjectId(api_id)})
        if not api:
            send_telegram_message(chat_id, "❌ API not found!")
            return
        
        text = (
            f"🌐 <b>API Details</b>\n\n"
            f"<b>Name:</b> {api['name']}\n"
            f"<b>URL:</b> <code>{api['url']}</code>\n"
            f"<b>Status:</b> {'✅ Active' if api['status'] == 'active' else '❌ Inactive'}\n"
            f"<b>Priority:</b> {api['priority']}\n"
        )
        
        buttons = [
            [{"text": "🔄 Test Now", "callback_data": f"test_api_{api_id}"}],
            [{"text": "⬆️ Increase Priority", "callback_data": f"api_priority_up_{api_id}"}],
            [{"text": "⬇️ Decrease Priority", "callback_data": f"api_priority_down_{api_id}"}],
            [{"text": "🔄 Toggle Status", "callback_data": f"toggle_api_{api_id}"}],
            [{"text": "🗑️ Delete API", "callback_data": f"delete_api_{api_id}"}],
            [{"text": "🔙 Back to APIs", "callback_data": "list_apis"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_add_api_start(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    set_user_state(user_id, "adding_api", {})
    text = "➕ <b>Add New API</b>\n\nEnter API name:"
    send_telegram_message(chat_id, text)

def handle_add_api_name(chat_id, user_id, name):
    state, data = get_user_state(user_id)
    if state != "adding_api":
        return
    
    data['name'] = name
    set_user_state(user_id, "adding_api_url", data)
    send_telegram_message(chat_id, "✅ Name saved!\n\nEnter API URL (use {user_id} as placeholder):")

def handle_add_api_url(chat_id, user_id, url):
    state, data = get_user_state(user_id)
    if state != "adding_api_url":
        return
    
    data['url'] = url
    set_user_state(user_id, "adding_api_priority", data)
    send_telegram_message(chat_id, "✅ URL saved!\n\nEnter priority (1-100, lower = higher priority):")

def handle_add_api_priority(chat_id, user_id, priority_str):
    state, data = get_user_state(user_id)
    if state != "adding_api_priority":
        return
    
    try:
        priority = int(priority_str)
        
        new_api = {
            "name": data['name'],
            "url": data['url'],
            "method": "GET",
            "status": "active",
            "priority": priority,
            "success_count": 0,
            "fail_count": 0,
            "last_checked": datetime.utcnow(),
            "added_by": f"tg_{user_id}",
            "notes": "Added via Telegram Bot",
            "created_at": datetime.utcnow()
        }
        
        apis_col.insert_one(new_api)
        
        text = f"✅ <b>API Added Successfully!</b>\n\nName: {data['name']}\nPriority: {priority}"
        
        buttons = [
            [{"text": "🌐 View All APIs", "callback_data": "list_apis"}],
            [{"text": "➕ Add Another", "callback_data": "add_api"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        clear_user_state(user_id)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid priority! Please enter a number:")

def handle_test_api(chat_id, user_id, api_id):
    if not is_admin(user_id):
        return
    
    try:
        api = apis_col.find_one({"_id": ObjectId(api_id)})
        if not api:
            send_telegram_message(chat_id, "❌ API not found!")
            return
        
        send_telegram_message(chat_id, f"🔄 Testing API: {api['name']}...")
        
        test_result = test_api_health(api)
        
        if test_result['working']:
            apis_col.update_one(
                {"_id": ObjectId(api_id)},
                {"$set": {"status": "active", "last_checked": datetime.utcnow()}}
            )
            text = f"✅ <b>API is WORKING!</b>\n\nResponse Time: {test_result['response_time']:.0f}ms"
        else:
            apis_col.update_one(
                {"_id": ObjectId(api_id)},
                {"$set": {"status": "inactive", "last_checked": datetime.utcnow()}}
            )
            text = f"❌ <b>API is NOT working!</b>\n\nError: {test_result.get('error', 'Unknown')}"
        
        buttons = [
            [{"text": "🔄 Test Again", "callback_data": f"test_api_{api_id}"}],
            [{"text": "🔙 Back to API", "callback_data": f"view_api_{api_id}"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_toggle_api(chat_id, user_id, api_id):
    if not is_admin(user_id):
        return
    
    try:
        api = apis_col.find_one({"_id": ObjectId(api_id)})
        if not api:
            send_telegram_message(chat_id, "❌ API not found!")
            return
        
        new_status = "inactive" if api['status'] == "active" else "active"
        apis_col.update_one({"_id": ObjectId(api_id)}, {"$set": {"status": new_status}})
        
        send_telegram_message(chat_id, f"✅ API status changed to: {new_status}")
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_delete_api(chat_id, user_id, api_id):
    if not is_admin(user_id):
        return
    
    try:
        api = apis_col.find_one({"_id": ObjectId(api_id)})
        if not api:
            send_telegram_message(chat_id, "❌ API not found!")
            return
        
        text = f"⚠️ <b>Delete API?</b>\n\nName: {api['name']}\n\nAre you sure?"
        
        buttons = [
            [{"text": "✅ Yes, Delete", "callback_data": f"confirm_delete_api_{api_id}"}],
            [{"text": "❌ No, Cancel", "callback_data": f"view_api_{api_id}"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_confirm_delete_api(chat_id, user_id, api_id):
    if not is_admin(user_id):
        return
    
    try:
        api = apis_col.find_one({"_id": ObjectId(api_id)})
        if api:
            api_name = api['name']
            apis_col.delete_one({"_id": ObjectId(api_id)})
            text = f"✅ API '{api_name}' deleted successfully!"
        else:
            text = "❌ API not found!"
        
        buttons = [
            [{"text": "🌐 View All APIs", "callback_data": "list_apis"}],
            [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_api_priority(chat_id, user_id, api_id, direction):
    if not is_admin(user_id):
        return
    
    try:
        api = apis_col.find_one({"_id": ObjectId(api_id)})
        if not api:
            send_telegram_message(chat_id, "❌ API not found!")
            return
        
        current = api.get('priority', 10)
        new = current - 1 if direction == "up" else current + 1
        
        if new < 1:
            new = 1
        if new > 100:
            new = 100
        
        apis_col.update_one({"_id": ObjectId(api_id)}, {"$set": {"priority": new}})
        
        send_telegram_message(chat_id, f"✅ Priority changed from {current} to {new}")
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_test_all_apis(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    send_telegram_message(chat_id, "🔄 Testing all APIs...")
    
    apis = list(apis_col.find())
    results = []
    
    for api in apis:
        test_result = test_api_health(api)
        status = "✅" if test_result['working'] else "❌"
        results.append(f"{status} {api['name']}")
        
        apis_col.update_one(
            {"_id": api['_id']},
            {"$set": {"status": "active" if test_result['working'] else "inactive", "last_checked": datetime.utcnow()}}
        )
    
    text = "📊 <b>API Test Results</b>\n\n" + "\n".join(results)
    
    buttons = [
        [{"text": "🔄 Test Again", "callback_data": "test_all_apis"}],
        [{"text": "🌐 View APIs", "callback_data": "list_apis"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_all_logs(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    logs = list(api_logs_col.find().sort("timestamp", -1).limit(10))
    
    if not logs:
        text = "📋 No logs found!"
    else:
        text = "📋 <b>Recent API Logs</b>\n\n"
        for log in logs:
            time_str = log['timestamp'].strftime('%H:%M')
            text += f"🕒 {time_str} - Key: {log['key'][:4]}... - User: {log['user_id']}\n"
    
    buttons = [
        [{"text": "🔄 Refresh", "callback_data": "logs"}],
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_help(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    text = (
        "🤖 <b>Bot Commands</b>\n\n"
        "/start - Main menu\n"
        "/stats - Statistics\n"
        "/keys - Manage keys\n"
        "/createkey - Create key\n"
        "/apis - Manage APIs\n"
        "/logs - View logs\n"
        "/settings - Settings\n"
        "/help - This help"
    )
    
    buttons = [[{"text": "🔙 Main Menu", "callback_data": "main_menu"}]]
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_settings(chat_id, user_id):
    if not is_admin(user_id):
        return
    
    settings = settings_col.find_one({"type": "admin_settings"}) or {}
    
    text = (
        "⚙️ <b>Settings</b>\n\n"
        f"👑 Owner: {settings.get('owner_display', '@VIP_X_OFFICIAL')}\n"
        f"📢 Channel: {settings.get('channel', 'https://t.me/WebBot_Lab')}"
    )
    
    buttons = [
        [{"text": "✏️ Edit Owner", "callback_data": "edit_owner"}],
        [{"text": "✏️ Edit Channel", "callback_data": "edit_channel"}],
        [{"text": "🔙 Main Menu", "callback_data": "main_menu"}]
    ]
    
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_edit_owner_start(chat_id, user_id):
    set_user_state(user_id, "editing_owner", {})
    send_telegram_message(chat_id, "📝 Send new owner name:")

def handle_edit_owner(chat_id, user_id, owner_name):
    state, data = get_user_state(user_id)
    if state != "editing_owner":
        return
    
    settings_col.update_one(
        {"type": "admin_settings"},
        {"$set": {"owner_display": owner_name}},
        upsert=True
    )
    
    send_telegram_message(chat_id, f"✅ Owner updated to: {owner_name}")
    clear_user_state(user_id)

def handle_edit_channel_start(chat_id, user_id):
    set_user_state(user_id, "editing_channel", {})
    send_telegram_message(chat_id, "📝 Send new channel URL:")

def handle_edit_channel(chat_id, user_id, channel):
    state, data = get_user_state(user_id)
    if state != "editing_channel":
        return
    
    settings_col.update_one(
        {"type": "admin_settings"},
        {"$set": {"channel": channel}},
        upsert=True
    )
    
    send_telegram_message(chat_id, f"✅ Channel updated to: {channel}")
    clear_user_state(user_id)

def handle_cancel(chat_id, user_id):
    state, data = get_user_state(user_id)
    if state:
        clear_user_state(user_id)
        text = "✅ Operation cancelled."
    else:
        text = "❌ No active operation."
    
    buttons = [[{"text": "🔙 Main Menu", "callback_data": "main_menu"}]]
    send_telegram_with_keyboard(chat_id, text, buttons)

def handle_extend_key(chat_id, user_id, key_id):
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        set_user_state(user_id, f"extending_key_{key_id}", {})
        send_telegram_message(chat_id, f"⏱️ Enter days to extend:")
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_extend_key_days(chat_id, user_id, key_id, days_str):
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
        keys_col.update_one({"_id": ObjectId(key_id)}, {"$set": {"expires_on": new_expiry}})
        
        send_telegram_message(chat_id, f"✅ Key extended by {days} days!")
        clear_user_state(user_id)
        
    except ValueError:
        send_telegram_message(chat_id, "❌ Invalid number!")

def handle_delete_key(chat_id, user_id, key_id):
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        text = f"⚠️ Delete key <code>{key['key']}</code>?"
        buttons = [
            [{"text": "✅ Yes", "callback_data": f"confirm_delete_{key_id}"}],
            [{"text": "❌ No", "callback_data": f"view_key_{key_id}"}]
        ]
        
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_confirm_delete(chat_id, user_id, key_id):
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if key:
            keys_col.delete_one({"_id": ObjectId(key_id)})
            api_logs_col.delete_many({"key": key['key']})
            text = f"✅ Key deleted!"
        else:
            text = "❌ Key not found!"
        
        buttons = [[{"text": "🔑 View Keys", "callback_data": "list_keys"}]]
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

def handle_key_logs(chat_id, user_id, key_id):
    if not is_admin(user_id):
        return
    
    try:
        key = keys_col.find_one({"_id": ObjectId(key_id)})
        if not key:
            send_telegram_message(chat_id, "❌ Key not found!")
            return
        
        logs = list(api_logs_col.find({"key": key['key']}).sort("timestamp", -1).limit(5))
        
        if not logs:
            text = f"📋 No logs for key {key['key']}"
        else:
            text = f"📋 <b>Logs for {key['key']}</b>\n\n"
            for log in logs:
                text += f"🕒 {log['timestamp'].strftime('%H:%M')} - User: {log['user_id']}\n"
        
        buttons = [[{"text": "🔙 Back", "callback_data": f"view_key_{key_id}"}]]
        send_telegram_with_keyboard(chat_id, text, buttons)
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error: {str(e)}")

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
                <div class="feature"><h4>🔑 Key Management</h4><p>Create and manage API keys</p></div>
                <div class="feature"><h4>⚡ Rate Limiting</h4><p>Daily limits per key</p></div>
                <div class="feature"><h4>👑 Owner</h4><p>@VIP_X_OFFICIAL</p></div>
                <div class="feature"><h4>🤖 Telegram Bot</h4><p>Full admin control</p></div>
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
    start_time = time.time()
    user_id = request.args.get('userid')
    api_key = request.args.get('key')
    
    # Get search result
    search_result = search_telegram_id(user_id, start_time)
    
    # Calculate response time
    response_time_ms = (time.time() - start_time) * 1000
    
    # Get key info
    key_data = request.key_data
    created_at = key_data.get('created_at')
    expires_on = key_data.get('expires_on')
    daily_limit = request.daily_limit
    searches_today = request.search_count - 1  # Current search not counted yet
    
    # Calculate remaining time
    now = datetime.utcnow()
    days_remaining = (expires_on - now).days
    hours_remaining = int((expires_on - now).seconds / 3600)
    
    # Get owner and channel info
    settings = settings_col.find_one({"type": "admin_settings"}) or {}
    owner_name = settings.get('owner_display', '@VIP_X_OFFICIAL')
    channel = settings.get('channel', 'https://t.me/WebBot_Lab')
    
    # Prepare response
    if search_result.get('status') == 'success':
        response = {
            "status": "success",
            "code": 200,
            "request_id": request.request_id,
            "response_time": f"{response_time_ms:.0f}ms",
            "searched_userid": user_id,
            "data": {
                "found": search_result.get('found', True),
                "country": search_result.get('country', 'Unknown'),
                "country_code": search_result.get('country_code', '+91'),
                "number": search_result.get('number', 'N/A')
            },
            "key_info": {
                "key": api_key,
                "created_at": created_at.strftime('%Y-%m-%d %H:%M:%S') if created_at else 'N/A',
                "expires_on": expires_on.strftime('%Y-%m-%d %H:%M:%S') if expires_on else 'N/A',
                "days_remaining": days_remaining,
                "hours_remaining": hours_remaining,
                "daily_limit": daily_limit,
                "searches_today": searches_today,
                "searches_remaining": daily_limit - searches_today
            },
            "owner": {
                "name": owner_name,
                "channel": channel
            }
        }
        return jsonify(response), 200
    else:
        response = {
            "status": "error",
            "code": search_result.get('code', 404),
            "request_id": request.request_id,
            "response_time": f"{response_time_ms:.0f}ms",
            "searched_userid": user_id,
            "message": search_result.get('message', 'User ID not found'),
            "key_info": {
                "key": api_key,
                "created_at": created_at.strftime('%Y-%m-%d %H:%M:%S') if created_at else 'N/A',
                "expires_on": expires_on.strftime('%Y-%m-%d %H:%M:%S') if expires_on else 'N/A',
                "days_remaining": days_remaining,
                "hours_remaining": hours_remaining,
                "daily_limit": daily_limit,
                "searches_today": searches_today,
                "searches_remaining": daily_limit - searches_today
            },
            "owner": {
                "name": owner_name,
                "channel": channel
            }
        }
        return jsonify(response), response['code']

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    try:
        update = request.json
        
        if 'callback_query' in update:
            callback = update['callback_query']
            callback_id = callback['id']
            chat_id = callback['message']['chat']['id']
            user_id = callback['from']['id']
            data = callback['data']
            
            answer_callback(chat_id, callback_id, "Processing...")
            
            # Main menu
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
            elif data == "list_apis":
                handle_list_apis(chat_id, user_id)
            elif data.startswith("view_api_"):
                api_id = data.replace("view_api_", "")
                handle_view_api(chat_id, user_id, api_id)
            elif data == "add_api":
                handle_add_api_start(chat_id, user_id)
            elif data.startswith("test_api_"):
                api_id = data.replace("test_api_", "")
                handle_test_api(chat_id, user_id, api_id)
            elif data.startswith("toggle_api_"):
                api_id = data.replace("toggle_api_", "")
                handle_toggle_api(chat_id, user_id, api_id)
            elif data.startswith("delete_api_"):
                api_id = data.replace("delete_api_", "")
                handle_delete_api(chat_id, user_id, api_id)
            elif data.startswith("confirm_delete_api_"):
                api_id = data.replace("confirm_delete_api_", "")
                handle_confirm_delete_api(chat_id, user_id, api_id)
            elif data.startswith("api_priority_up_"):
                api_id = data.replace("api_priority_up_", "")
                handle_api_priority(chat_id, user_id, api_id, "up")
            elif data.startswith("api_priority_down_"):
                api_id = data.replace("api_priority_down_", "")
                handle_api_priority(chat_id, user_id, api_id, "down")
            elif data == "test_all_apis":
                handle_test_all_apis(chat_id, user_id)
            elif data == "logs":
                handle_all_logs(chat_id, user_id)
            elif data == "settings":
                handle_settings(chat_id, user_id)
            elif data == "edit_owner":
                handle_edit_owner_start(chat_id, user_id)
            elif data == "edit_channel":
                handle_edit_channel_start(chat_id, user_id)
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
        
        elif 'message' in update:
            msg = update['message']
            chat_id = msg['chat']['id']
            user_id = msg['from']['id']
            
            if not is_admin(user_id):
                send_telegram_message(chat_id, "❌ Unauthorized!")
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
                elif text.startswith('/apis'):
                    handle_list_apis(chat_id, user_id)
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
                    elif state == "adding_api":
                        handle_add_api_name(chat_id, user_id, text)
                    elif state == "adding_api_url":
                        handle_add_api_url(chat_id, user_id, text)
                    elif state == "adding_api_priority":
                        handle_add_api_priority(chat_id, user_id, text)
                    elif state and state.startswith("extending_key_"):
                        key_id = state.replace("extending_key_", "")
                        handle_extend_key_days(chat_id, user_id, key_id, text)
                    elif state == "editing_owner":
                        handle_edit_owner(chat_id, user_id, text)
                    elif state == "editing_channel":
                        handle_edit_channel(chat_id, user_id, text)
                    else:
                        send_telegram_message(chat_id, "❌ Unknown command. Use /start")
        
        return jsonify({"ok": True})
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False}), 500

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
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
    return jsonify({
        "status": "healthy",
        "time": datetime.utcnow().isoformat(),
        "active_apis": apis_col.count_documents({"status": "active"}),
        "total_keys": keys_col.count_documents({})
    })

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 60)
    print("🤖 Telegram Bot Admin Panel - RESPONSE FORMAT UPDATED")
    print("=" * 60)
    print(f"\n✅ Features:")
    print("   ✅ New response format as requested")
    print("   ✅ Multiple API response formats supported")
    print("   ✅ Vercel API format fixed")
    print("   ✅ Dynamic API Management")
    print("   ✅ Automatic Failover")
    print("   ✅ Key Management")
    print("   ✅ Rate Limiting")
    print("   ✅ Telegram Bot Control")
    print("\n🌐 Server starting on port:", PORT)
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=PORT)
