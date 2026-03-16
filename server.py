import asyncio
import websockets
import json
import sqlite3
import random
import smtplib
import hashlib
import secrets
import os
import sys
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============================================
# МАКСИМАЛЬНО ПОДРОБНОЕ ЛОГИРОВАНИЕ
# ============================================

def log(msg, level="INFO"):
    """Функция для логирования с временем"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {level}: {msg}")
    sys.stdout.flush()  # Принудительно сбрасываем буфер

log("🚀 SERVER STARTING UP...")
log(f"Python version: {sys.version}")
log(f"Current directory: {os.getcwd()}")

# ============================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ============================================

EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')

log(f"EMAIL_ADDRESS: {'SET' if EMAIL_ADDRESS else 'NOT SET'}")
log(f"EMAIL_PASSWORD: {'SET' if EMAIL_PASSWORD else 'NOT SET'}")

# ============================================
# БАЗА ДАННЫХ
# ============================================

try:
    conn = sqlite3.connect('soo_messages.db')
    c = conn.cursor()
    log("✅ Database connected successfully")
except Exception as e:
    log(f"❌ Database connection failed: {e}", "ERROR")

# Создаем таблицы
try:
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT UNIQUE,
                  email TEXT UNIQUE,
                  username TEXT UNIQUE,
                  password_hash TEXT,
                  first_name TEXT,
                  last_name TEXT,
                  verified BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS verification_codes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT,
                  code TEXT,
                  expires_at TIMESTAMP,
                  attempts INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  from_user TEXT,
                  to_user TEXT,
                  message TEXT,
                  timestamp TIMESTAMP,
                  delivered BOOLEAN DEFAULT 0,
                  read BOOLEAN DEFAULT 0)''')
    conn.commit()
    log("✅ Tables created/verified successfully")
except Exception as e:
    log(f"❌ Table creation failed: {e}", "ERROR")

connected_clients = {}

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def generate_verification_code():
    code = str(random.randint(1000, 9999))
    log(f"🔢 Generated code: {code}")
    return code

def hash_password(password):
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256((password + salt).encode())
    return f"{salt}${hash_obj.hexdigest()}"

def verify_password(password, password_hash):
    try:
        salt, hash_val = password_hash.split('$')
        check_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return check_hash == hash_val
    except Exception as e:
        log(f"❌ Password verification error: {e}", "ERROR")
        return False

def send_email_code(to_email, code):
    log(f"📧 Attempting to send email to {to_email} with code {code}")
    
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        log("❌ Email credentials not configured", "ERROR")
        return False
    
    try:
        # Создаем письмо
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = "Код подтверждения Soo Messenger"
        
        body = f"""
        <html>
          <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #6200EE;">Soo Messenger</h2>
            <p>Ваш код подтверждения:</p>
            <h1 style="font-size: 32px; background: #f0f0f0; padding: 10px; text-align: center;">{code}</h1>
            <p>Код действителен 5 минут.</p>
          </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        log(f"📧 Connecting to SMTP server {EMAIL_HOST}:{EMAIL_PORT}...")
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=30)
        server.set_debuglevel(1)  # Включаем подробный лог SMTP
        server.starttls()
        log("📧 TLS started")
        
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        log("📧 Login successful")
        
        server.send_message(msg)
        log("📧 Message sent successfully")
        
        server.quit()
        log(f"✅ Email sent to {to_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        log(f"❌ SMTP Authentication Error: {e}", "ERROR")
        log("   Check your EMAIL_PASSWORD - it must be an App Password, not your regular password")
        return False
    except smtplib.SMTPException as e:
        log(f"❌ SMTP Error: {e}", "ERROR")
        return False
    except Exception as e:
        log(f"❌ Unexpected email error: {e}", "ERROR")
        log(traceback.format_exc())
        return False

# ============================================
# ОСНОВНОЙ ОБРАБОТЧИК WEBSOCKET
# ============================================

async def handler(websocket):
    client_id = id(websocket)
    log(f"🔌 New client connected (ID: {client_id})")
    
    try:
        async for message in websocket:
            log(f"📨 Received raw message: {message}")
            
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                log(f"📦 Parsed message type: {msg_type}")
                
                # 1️⃣ ПРОВЕРКА EMAIL
                if msg_type == 'check_email':
                    email = data['email']
                    log(f"🔍 Checking email: {email}")
                    
                    c.execute("SELECT user_id, username FROM users WHERE email = ?", (email,))
                    user = c.fetchone()
                    
                    if user:
                        await websocket.send(json.dumps({
                            'type': 'email_exists',
                            'exists': True
                        }))
                        log(f"✅ Email {email} exists")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'email_exists',
                            'exists': False
                        }))
                        log(f"❌ Email {email} not found")
                
                # 2️⃣ ОТПРАВКА КОДА
                elif msg_type == 'send_code':
                    email = data['email']
                    code = generate_verification_code()
                    log(f"📧 Processing send_code for {email} with code {code}")
                    
                    # Удаляем старые коды
                    c.execute("DELETE FROM verification_codes WHERE email = ?", (email,))
                    log(f"🗑️ Deleted old codes for {email}")
                    
                    # Сохраняем новый код
                    expires = datetime.now().timestamp() + 300
                    c.execute("INSERT INTO verification_codes (email, code, expires_at) VALUES (?, ?, ?)",
                             (email, code, expires))
                    conn.commit()
                    log(f"💾 Saved new code for {email}, expires at {expires}")
                    
                    # Отправляем email
                    email_sent = send_email_code(email, code)
                    
                    response = {
                        'type': 'code_sent',
                        'message': 'Код отправлен на email' if email_sent else 'Код сгенерирован (режим отладки)'
                    }
                    await websocket.send(json.dumps(response))
                    log(f"📤 Sent response to client: {response}")
                
                # 3️⃣ ПРОВЕРКА КОДА
                elif msg_type == 'verify_code':
                    email = data['email']
                    code = data['code']
                    log(f"🔐 Verifying code for {email}: {code}")
                    
                    c.execute("SELECT code, expires_at FROM verification_codes WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
                    result = c.fetchone()
                    
                    if result:
                        stored_code, expires_at = result
                        log(f"   Found stored code: {stored_code}, expires: {expires_at}")
                        
                        if datetime.now().timestamp() < expires_at and stored_code == code:
                            await websocket.send(json.dumps({
                                'type': 'code_valid',
                                'email': email
                            }))
                            log(f"✅ Code valid for {email}")
                        else:
                            await websocket.send(json.dumps({
                                'type': 'code_invalid',
                                'message': 'Неверный или просроченный код'
                            }))
                            log(f"❌ Invalid or expired code for {email}")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'code_invalid',
                            'message': 'Код не найден'
                        }))
                        log(f"❌ No code found for {email}")
                
                # 4️⃣ СОЗДАНИЕ ПАРОЛЯ
                elif msg_type == 'create_password':
                    email = data['email']
                    password = data['password']
                    log(f"🔑 Creating password for {email}")
                    
                    password_hash = hash_password(password)
                    
                    await websocket.send(json.dumps({
                        'type': 'password_created',
                        'email': email,
                        'password_hash': password_hash
                    }))
                    log(f"✅ Password created for {email}")
                
                # 5️⃣ ЗАВЕРШЕНИЕ РЕГИСТРАЦИИ
                elif msg_type == 'complete_registration':
                    email = data['email']
                    username = data['username']
                    password_hash = data['password_hash']
                    first_name = data.get('first_name', '')
                    last_name = data.get('last_name', '')
                    
                    log(f"📝 Completing registration for {username} ({email})")
                    
                    # Проверяем username
                    c.execute("SELECT username FROM users WHERE username = ?", (username,))
                    if c.fetchone():
                        await websocket.send(json.dumps({
                            'type': 'register_failed',
                            'message': 'Имя пользователя уже занято'
                        }))
                        log(f"❌ Username {username} already taken")
                        return
                    
                    # Проверяем email
                    c.execute("SELECT email FROM users WHERE email = ?", (email,))
                    if c.fetchone():
                        await websocket.send(json.dumps({
                            'type': 'register_failed',
                            'message': 'Этот email уже зарегистрирован'
                        }))
                        log(f"❌ Email {email} already registered")
                        return
                    
                    # Создаем пользователя
                    user_id = f"user_{int(datetime.now().timestamp())}"
                    c.execute("INSERT INTO users (user_id, email, username, password_hash, first_name, last_name, verified, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                             (user_id, email, username, password_hash, first_name, last_name, datetime.now()))
                    conn.commit()
                    
                    connected_clients[user_id] = websocket
                    
                    await websocket.send(json.dumps({
                        'type': 'register_success',
                        'user_id': user_id,
                        'username': username
                    }))
                    log(f"🎉 New user registered: {username}")
                
                # 6️⃣ ВХОД С ПАРОЛЕМ
                elif msg_type == 'login_with_password':
                    email = data['email']
                    password = data['password']
                    log(f"🔓 Login attempt for {email}")
                    
                    c.execute("SELECT user_id, username, password_hash, first_name, last_name FROM users WHERE email = ?", (email,))
                    user = c.fetchone()
                    
                    if user:
                        user_id, username, password_hash, first_name, last_name = user
                        if verify_password(password, password_hash):
                            connected_clients[user_id] = websocket
                            await websocket.send(json.dumps({
                                'type': 'login_success',
                                'user_id': user_id,
                                'username': username,
                                'first_name': first_name,
                                'last_name': last_name
                            }))
                            log(f"✅ Login successful: {username}")
                        else:
                            await websocket.send(json.dumps({
                                'type': 'login_failed',
                                'message': 'Неверный пароль'
                            }))
                            log(f"❌ Wrong password for {email}")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'login_failed',
                            'message': 'Пользователь не найден'
                        }))
                        log(f"❌ User not found: {email}")
                
                # 7️⃣ ПОИСК ПОЛЬЗОВАТЕЛЯ
                elif msg_type == 'search_user':
                    search_username = data['username']
                    log(f"🔍 Searching for user: {search_username}")
                    
                    c.execute("SELECT user_id, username, first_name, last_name FROM users WHERE username = ?", (search_username,))
                    user = c.fetchone()
                    
                    if user:
                        user_id, username, first_name, last_name = user
                        await websocket.send(json.dumps({
                            'type': 'search_result',
                            'found': True,
                            'user_id': user_id,
                            'username': username,
                            'first_name': first_name,
                            'last_name': last_name
                        }))
                        log(f"✅ Found user: {username}")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'search_result',
                            'found': False
                        }))
                        log(f"❌ User {search_username} not found")
                
                # 8️⃣ ОТПРАВКА СООБЩЕНИЯ
                elif msg_type == 'private_message':
                    from_user = data['from_user']
                    to_user = data['to_user']
                    message_text = data['message']
                    
                    log(f"💬 Message from {from_user} to {to_user}")
                    
                    c.execute("INSERT INTO messages (from_user, to_user, message, timestamp) VALUES (?, ?, ?, ?)",
                             (from_user, to_user, message_text, datetime.now()))
                    conn.commit()
                    
                    if to_user in connected_clients:
                        await connected_clients[to_user].send(json.dumps({
                            'type': 'new_message',
                            'from_user': from_user,
                            'message': message_text,
                            'timestamp': str(datetime.now())
                        }))
                        log(f"✅ Message delivered to {to_user}")
                    
                    await websocket.send(json.dumps({
                        'type': 'message_sent',
                        'to_user': to_user,
                        'message': message_text
                    }))
                
                else:
                    log(f"⚠️ Unknown message type: {msg_type}", "WARNING")
                    
            except json.JSONDecodeError as e:
                log(f"❌ Failed to parse JSON: {e}", "ERROR")
            except Exception as e:
                log(f"❌ Error processing message: {e}", "ERROR")
                log(traceback.format_exc())
                
    except websockets.exceptions.ConnectionClosed:
        log(f"👋 Client {client_id} disconnected normally")
    except Exception as e:
        log(f"❌ Unexpected connection error: {e}", "ERROR")
        log(traceback.format_exc())
    finally:
        # Удаляем клиента из connected_clients
        for user_id, ws in list(connected_clients.items()):
            if ws == websocket:
                del connected_clients[user_id]
                log(f"🗑️ Removed user {user_id} from connected clients")
                break

# ============================================
# ЗАПУСК СЕРВЕРА
# ============================================

async def main():
    port = 8765
    log(f"📡 Starting server on port {port}...")
    
    try:
        async with websockets.serve(handler, "0.0.0.0", port):
            log("=" * 60)
            log("🚀 SERVER STARTED SUCCESSFULLY!")
            log(f"📡 Port: {port}")
            log(f"📧 Email: {'CONFIGURED' if EMAIL_ADDRESS and EMAIL_PASSWORD else 'NOT CONFIGURED'}")
            log(f"💾 Database: soo_messages.db")
            log("=" * 60)
            await asyncio.Future()  # Работаем вечно
    except Exception as e:
        log(f"❌ Failed to start server: {e}", "ERROR")
        log(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("👋 Server stopped by user")
    except Exception as e:
        log(f"❌ Fatal error: {e}", "ERROR")
        log(traceback.format_exc())
