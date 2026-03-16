import asyncio
import websockets
import json
import sqlite3
import random
import hashlib
import secrets
import os
import sys
import traceback
from datetime import datetime

# ============================================
# ЛОГИРОВАНИЕ
# ============================================

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {level}: {msg}")
    sys.stdout.flush()

log("🚀 SERVER STARTING UP...")

# ============================================
# БАЗА ДАННЫХ
# ============================================

conn = sqlite3.connect('soo_messages.db')
c = conn.cursor()

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

connected_clients = {}

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def generate_verification_code():
    return str(random.randint(1000, 9999))

def hash_password(password):
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256((password + salt).encode())
    return f"{salt}${hash_obj.hexdigest()}"

def verify_password(password, password_hash):
    try:
        salt, hash_val = password_hash.split('$')
        check_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return check_hash == hash_val
    except:
        return False

def show_code_in_logs(to_email, code):
    """Вместо отправки email просто показываем код в логах"""
    log(f"🔑 КОД ПОДТВЕРЖДЕНИЯ для {to_email}: {code}")
    log(f"⚠️ Введите этот код в приложении для продолжения")
    return True

# ============================================
# ОСНОВНОЙ ОБРАБОТЧИК
# ============================================

async def handler(websocket):
    client_id = id(websocket)
    log(f"🔌 New client connected")
    
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'check_email':
                email = data['email']
                c.execute("SELECT user_id, username FROM users WHERE email = ?", (email,))
                user = c.fetchone()
                
                await websocket.send(json.dumps({
                    'type': 'email_exists',
                    'exists': user is not None
                }))
                
            elif msg_type == 'send_code':
                email = data['email']
                code = generate_verification_code()
                
                # Удаляем старые коды
                c.execute("DELETE FROM verification_codes WHERE email = ?", (email,))
                
                # Сохраняем новый код
                expires = datetime.now().timestamp() + 300
                c.execute("INSERT INTO verification_codes (email, code, expires_at) VALUES (?, ?, ?)",
                         (email, code, expires))
                conn.commit()
                
                # ПОКАЗЫВАЕМ КОД В ЛОГАХ
                show_code_in_logs(email, code)
                
                await websocket.send(json.dumps({
                    'type': 'code_sent',
                    'message': 'Код отправлен (проверьте логи Render)'
                }))
                
            elif msg_type == 'verify_code':
                email = data['email']
                code = data['code']
                
                c.execute("SELECT code, expires_at FROM verification_codes WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
                result = c.fetchone()
                
                if result:
                    stored_code, expires_at = result
                    if datetime.now().timestamp() < expires_at and stored_code == code:
                        await websocket.send(json.dumps({
                            'type': 'code_valid',
                            'email': email
                        }))
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
                    
            elif msg_type == 'create_password':
                email = data['email']
                password = data['password']
                password_hash = hash_password(password)
                
                await websocket.send(json.dumps({
                    'type': 'password_created',
                    'email': email,
                    'password_hash': password_hash
                }))
                
            elif msg_type == 'complete_registration':
                email = data['email']
                username = data['username']
                password_hash = data['password_hash']
                first_name = data.get('first_name', '')
                last_name = data.get('last_name', '')
                
                # Проверяем, не занят ли username
                c.execute("SELECT username FROM users WHERE username = ?", (username,))
                if c.fetchone():
                    await websocket.send(json.dumps({
                        'type': 'register_failed',
                        'message': 'Имя пользователя уже занято'
                    }))
                    return
                
                # Проверяем, не занят ли email
                c.execute("SELECT email FROM users WHERE email = ?", (email,))
                if c.fetchone():
                    await websocket.send(json.dumps({
                        'type': 'register_failed',
                        'message': 'Этот email уже зарегистрирован'
                    }))
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
                
            elif msg_type == 'login_with_password':
                email = data['email']
                password = data['password']
                
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
        log(f"👋 Client disconnected")
        for user_id, ws in list(connected_clients.items()):
            if ws == websocket:
                del connected_clients[user_id]
                break

# ============================================
# ЗАПУСК
# ============================================

async def main():
    port = 8765
    async with websockets.serve(handler, "0.0.0.0", port):
        log("=" * 60)
        log("🚀 SERVER STARTED SUCCESSFULLY!")
        log("📡 Коды подтверждения будут показываться в логах")
        log("=" * 60)
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
