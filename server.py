import asyncio
import websockets
import json
import sqlite3
import random
from datetime import datetime

# База данных
conn = sqlite3.connect('soo_messages.db')
c = conn.cursor()

# Создаем таблицы
c.execute('''CREATE TABLE IF NOT EXISTS users
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT UNIQUE,
              phone TEXT UNIQUE,
              username TEXT UNIQUE,
              first_name TEXT,
              last_name TEXT,
              verified BOOLEAN DEFAULT 0,
              created_at TIMESTAMP)''')

c.execute('''CREATE TABLE IF NOT EXISTS verification_codes
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              phone TEXT,
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
temp_sessions = {}  # {phone: {"code": ..., "expires": ...}}

def generate_verification_code():
    return str(random.randint(1000, 9999))

async def handler(websocket):
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'send_code':
                # Отправка кода подтверждения на номер
                phone = data['phone']
                code = generate_verification_code()
                
                # Сохраняем код в БД (в реальном проекте тут отправка SMS)
                expires = datetime.now().timestamp() + 300  # 5 минут
                c.execute("INSERT INTO verification_codes (phone, code, expires_at) VALUES (?, ?, ?)",
                         (phone, code, expires))
                conn.commit()
                
                print(f"Код для {phone}: {code}")  # В консоль для теста
                
                await websocket.send(json.dumps({
                    'type': 'code_sent',
                    'message': 'Код отправлен'
                }))
                
            elif msg_type == 'verify_code':
                # Проверка кода
                phone = data['phone']
                code = data['code']
                
                c.execute("SELECT code, expires_at FROM verification_codes WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,))
                result = c.fetchone()
                
                if result:
                    stored_code, expires_at = result
                    if datetime.now().timestamp() < expires_at and stored_code == code:
                        await websocket.send(json.dumps({
                            'type': 'code_valid',
                            'phone': phone
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
                    
            elif msg_type == 'register':
                # Завершение регистрации
                phone = data['phone']
                username = data['username']
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
                
                # Создаем пользователя
                user_id = f"user_{int(datetime.now().timestamp())}"
                c.execute("INSERT INTO users (user_id, phone, username, first_name, last_name, verified, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                         (user_id, phone, username, first_name, last_name, datetime.now()))
                conn.commit()
                
                await websocket.send(json.dumps({
                    'type': 'register_success',
                    'user_id': user_id,
                    'username': username
                }))
                print(f"Новый пользователь: {username} ({phone})")
                
            elif msg_type == 'login':
                # Вход по номеру телефона
                phone = data['phone']
                c.execute("SELECT user_id, username, first_name, last_name FROM users WHERE phone = ? AND verified = 1", (phone,))
                user = c.fetchone()
                
                if user:
                    user_id, username, first_name, last_name = user
                    connected_clients[user_id] = websocket
                    
                    await websocket.send(json.dumps({
                        'type': 'login_success',
                        'user_id': user_id,
                        'username': username,
                        'first_name': first_name,
                        'last_name': last_name
                    }))
                    print(f"Вошел пользователь: {username}")
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
        for user_id, ws in list(connected_clients.items()):
            if ws == websocket:
                del connected_clients[user_id]
                print(f"Пользователь отключился")
                break

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("🚀 Сервер запущен на порту 8765!")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
