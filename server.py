import asyncio
import websockets
import json
import sqlite3
import random
import smtplib
import hashlib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

# ============================================
# НАСТРОЙКИ EMAIL (из переменных окружения)
# ============================================

EMAIL_HOST = "smtp.gmail.com"  # или smtp.mail.ru, smtp.yandex.ru
EMAIL_PORT = 587
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')

# База данных
conn = sqlite3.connect('soo_messages.db')
c = conn.cursor()

# Создаем таблицы
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

connected_clients = {}  # {user_id: websocket}

# ============================================
# ФУНКЦИИ ДЛЯ EMAIL И КОДОВ
# ============================================

def generate_verification_code():
    """Генерирует 4-значный код подтверждения"""
    return str(random.randint(1000, 9999))

def hash_password(password):
    """Хеширует пароль"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256((password + salt).encode())
    return f"{salt}${hash_obj.hexdigest()}"

def verify_password(password, password_hash):
    """Проверяет пароль"""
    salt, hash_val = password_hash.split('$')
    check_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return check_hash == hash_val

def send_email_code(to_email, code):
    """Отправляет код подтверждения на email"""
    
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print(f"⚠️ Email не настроен. Код для {to_email}: {code}")
        return False
    
    try:
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
        
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"📧 Email отправлен на {to_email} с кодом {code}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отправки email: {e}")
        return False

# ============================================
# ОСНОВНОЙ ОБРАБОТЧИК
# ============================================

async def handler(websocket):
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type')
            
            print(f"\n📨 Получен запрос: {msg_type}")
            
            # 1️⃣ ПРОВЕРКА EMAIL ПРИ ВХОДЕ
            if msg_type == 'check_email':
                email = data['email']
                print(f"🔍 Проверка email: {email}")
                
                c.execute("SELECT user_id, username FROM users WHERE email = ?", (email,))
                user = c.fetchone()
                
                if user:
                    await websocket.send(json.dumps({
                        'type': 'email_exists',
                        'exists': True
                    }))
                    print(f"✅ Email {email} найден")
                else:
                    await websocket.send(json.dumps({
                        'type': 'email_exists',
                        'exists': False
                    }))
                    print(f"❌ Email {email} не найден")
            
            # 2️⃣ ОТПРАВКА КОДА НА EMAIL
            elif msg_type == 'send_code':
                email = data['email']
                code = generate_verification_code()
                print(f"📧 Генерация кода для {email}: {code}")
                
                c.execute("DELETE FROM verification_codes WHERE email = ?", (email,))
                expires = datetime.now().timestamp() + 300  # 5 минут
                c.execute("INSERT INTO verification_codes (email, code, expires_at) VALUES (?, ?, ?)",
                         (email, code, expires))
                conn.commit()
                
                email_sent = send_email_code(email, code)
                
                await websocket.send(json.dumps({
                    'type': 'code_sent',
                    'message': 'Код отправлен на email'
                }))
            
            # 3️⃣ ПРОВЕРКА КОДА
            elif msg_type == 'verify_code':
                email = data['email']
                code = data['code']
                print(f"🔐 Проверка кода для {email}: {code}")
                
                c.execute("SELECT code, expires_at FROM verification_codes WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
                result = c.fetchone()
                
                if result:
                    stored_code, expires_at = result
                    if datetime.now().timestamp() < expires_at and stored_code == code:
                        await websocket.send(json.dumps({
                            'type': 'code_valid',
                            'email': email
                        }))
                        print(f"✅ Код верный для {email}")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'code_invalid',
                            'message': 'Неверный или просроченный код'
                        }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'code_invalid',
                        'message': 'Код не найден'
                    }))
            
            # 4️⃣ СОЗДАНИЕ ПАРОЛЯ (для новых пользователей)
            elif msg_type == 'create_password':
                email = data['email']
                password = data['password']
                print(f"🔑 Создание пароля для {email}")
                
                # Временно храним пароль в сессии (email -> hash)
                password_hash = hash_password(password)
                
                await websocket.send(json.dumps({
                    'type': 'password_created',
                    'email': email,
                    'password_hash': password_hash
                }))
            
            # 5️⃣ ПОЛНАЯ РЕГИСТРАЦИЯ
            elif msg_type == 'complete_registration':
                email = data['email']
                username = data['username']
                password_hash = data['password_hash']
                first_name = data.get('first_name', '')
                last_name = data.get('last_name', '')
                
                print(f"📝 Регистрация: {username} ({email})")
                
                c.execute("SELECT username FROM users WHERE username = ?", (username,))
                if c.fetchone():
                    await websocket.send(json.dumps({
                        'type': 'register_failed',
                        'message': 'Имя пользователя уже занято'
                    }))
                    return
                
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
                print(f"🎉 Новый пользователь: {username}")
            
            # 6️⃣ ВХОД С ПАРОЛЕМ
            elif msg_type == 'login_with_password':
                email = data['email']
                password = data['password']
                print(f"🔓 Вход с паролем: {email}")
                
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
                        print(f"✅ Успешный вход: {username}")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'login_failed',
                            'message': 'Неверный пароль'
                        }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'login_failed',
                        'message': 'Пользователь не найден'
                    }))
            
            # 7️⃣ ПОИСК ПОЛЬЗОВАТЕЛЯ
            elif msg_type == 'search_user':
                search_username = data['username']
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
                else:
                    await websocket.send(json.dumps({
                        'type': 'search_result',
                        'found': False
                    }))
            
            # 8️⃣ ОТПРАВКА СООБЩЕНИЯ
            elif msg_type == 'private_message':
                from_user = data['from_user']
                to_user = data['to_user']
                message_text = data['message']
                
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
                
                await websocket.send(json.dumps({
                    'type': 'message_sent',
                    'to_user': to_user,
                    'message': message_text
                }))
                
    except websockets.exceptions.ConnectionClosed:
        for user_id, ws in list(connected_clients.items()):
            if ws == websocket:
                del connected_clients[user_id]
                break

# ============================================
# ЗАПУСК
# ============================================

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("=" * 50)
        print("🚀 Soo Messenger Server запущен!")
        print("📡 Порт: 8765")
        if EMAIL_ADDRESS and EMAIL_PASSWORD:
            print(f"📧 Email: {EMAIL_ADDRESS}")
        else:
            print("📧 Email: не настроен (коды в логах)")
        print("=" * 50)
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
