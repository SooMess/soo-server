import asyncio
import websockets
import json
import sqlite3
from datetime import datetime

# База данных SQLite для хранения пользователей и сообщений
conn = sqlite3.connect('soo_messages.db')
c = conn.cursor()

# Создаем таблицы если их нет
c.execute('''CREATE TABLE IF NOT EXISTS users
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT UNIQUE,
              username TEXT UNIQUE,
              phone TEXT UNIQUE,
              created_at TIMESTAMP)''')

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
user_info = {}  # {user_id: {"username": ..., "phone": ...}}

async def handler(websocket):
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'register':
                # Регистрация нового пользователя
                phone = data['phone']
                username = data['username']
                user_id = f"user_{datetime.now().timestamp()}"
                
                # Сохраняем в БД
                c.execute("INSERT INTO users (user_id, username, phone, created_at) VALUES (?, ?, ?, ?)",
                         (user_id, username, phone, datetime.now()))
                conn.commit()
                
                user_info[user_id] = {"username": username, "phone": phone}
                connected_clients[user_id] = websocket
                
                await websocket.send(json.dumps({
                    'type': 'register_success',
                    'user_id': user_id,
                    'username': username
                }))
                print(f"Новый пользователь: {username} ({phone})")
                
            elif msg_type == 'login':
                # Вход по номеру телефона
                phone = data['phone']
                c.execute("SELECT user_id, username FROM users WHERE phone = ?", (phone,))
                user = c.fetchone()
                
                if user:
                    user_id, username = user
                    connected_clients[user_id] = websocket
                    if user_id not in user_info:
                        user_info[user_id] = {"username": username, "phone": phone}
                    
                    await websocket.send(json.dumps({
                        'type': 'login_success',
                        'user_id': user_id,
                        'username': username
                    }))
                    print(f"Вошел пользователь: {username}")
                else:
                    await websocket.send(json.dumps({
                        'type': 'login_failed',
                        'message': 'Пользователь не найден'
                    }))
                    
            elif msg_type == 'search_user':
                # Поиск пользователя по username
                search_username = data['username']
                c.execute("SELECT user_id, username FROM users WHERE username = ?", (search_username,))
                user = c.fetchone()
                
                if user:
                    user_id, username = user
                    await websocket.send(json.dumps({
                        'type': 'search_result',
                        'found': True,
                        'user_id': user_id,
                        'username': username
                    }))
                else:
                    await websocket.send(json.dumps({
                        'type': 'search_result',
                        'found': False
                    }))
                    
            elif msg_type == 'private_message':
                # Отправка личного сообщения
                from_user = data['from_user']
                to_user = data['to_user']
                message_text = data['message']
                
                # Сохраняем в БД
                c.execute("INSERT INTO messages (from_user, to_user, message, timestamp) VALUES (?, ?, ?, ?)",
                         (from_user, to_user, message_text, datetime.now()))
                conn.commit()
                
                # Отправляем получателю, если он онлайн
                if to_user in connected_clients:
                    await connected_clients[to_user].send(json.dumps({
                        'type': 'new_message',
                        'from_user': from_user,
                        'from_username': user_info[from_user]['username'],
                        'message': message_text,
                        'timestamp': str(datetime.now())
                    }))
                    
                # Подтверждение отправителю
                await websocket.send(json.dumps({
                    'type': 'message_sent',
                    'to_user': to_user,
                    'message': message_text
                }))
                
    except websockets.exceptions.ConnectionClosed:
        # Удаляем отключившегося клиента
        for user_id, ws in list(connected_clients.items()):
            if ws == websocket:
                del connected_clients[user_id]
                print(f"Пользователь {user_info.get(user_id, {}).get('username', user_id)} отключился")
                break

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("🚀 Сервер запущен на порту 8765!")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
