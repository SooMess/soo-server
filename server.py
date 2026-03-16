import asyncio
import websockets
import json
import sqlite3
import random
from datetime import datetime

# База данных
conn = sqlite3.connect('soo_messages.db')
c = conn.cursor()

# Создаем таблицы если их нет
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

def generate_verification_code():
    """Генерирует 4-значный код подтверждения"""
    return str(random.randint(1000, 9999))

async def handler(websocket):
    """Основной обработчик всех сообщений от клиентов"""
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type')
            
            print(f"📨 Получен запрос: {msg_type}")
            
            # 1️⃣ ПРОВЕРКА СУЩЕСТВОВАНИЯ НОМЕРА
            if msg_type == 'check_phone':
                phone = data['phone']
                print(f"🔍 Проверка номера: {phone}")
                
                c.execute("SELECT user_id, username FROM users WHERE phone = ?", (phone,))
                user = c.fetchone()
                
                if user:
                    await websocket.send(json.dumps({
                        'type': 'phone_exists',
                        'exists': True
                    }))
                    print(f"✅ Номер {phone} найден")
                else:
                    await websocket.send(json.dumps({
                        'type': 'phone_exists',
                        'exists': False
                    }))
                    print(f"❌ Номер {phone} не найден")
            
            # 2️⃣ ОТПРАВКА КОДА ПОДТВЕРЖДЕНИЯ
            elif msg_type == 'send_code':
                phone = data['phone']
                code = generate_verification_code()
                print(f"📱 Генерация кода для {phone}: {code}")
                
                # Удаляем старые коды для этого номера
                c.execute("DELETE FROM verification_codes WHERE phone = ?", (phone,))
                
                # Сохраняем новый код
                expires = datetime.now().timestamp() + 300  # 5 минут
                c.execute("INSERT INTO verification_codes (phone, code, expires_at) VALUES (?, ?, ?)",
                         (phone, code, expires))
                conn.commit()
                
                print(f"✅ Код {code} сохранен для {phone}")
                
                await websocket.send(json.dumps({
                    'type': 'code_sent',
                    'message': 'Код отправлен'
                }))
            
            # 3️⃣ ПРОВЕРКА КОДА
            elif msg_type == 'verify_code':
                phone = data['phone']
                code = data['code']
                print(f"🔐 Проверка кода для {phone}: {code}")
                
                c.execute("SELECT code, expires_at FROM verification_codes WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,))
                result = c.fetchone()
                
                if result:
                    stored_code, expires_at = result
                    print(f"   Найден код: {stored_code}, истекает: {expires_at}")
                    
                    if datetime.now().timestamp() < expires_at and stored_code == code:
                        await websocket.send(json.dumps({
                            'type': 'code_valid',
                            'phone': phone
                        }))
                        print(f"✅ Код верный для {phone}")
                    else:
                        await websocket.send(json.dumps({
                            'type': 'code_invalid',
                            'message': 'Неверный или просроченный код'
                        }))
                        print(f"❌ Неверный код для {phone}")
                else:
                    await websocket.send(json.dumps({
                        'type': 'code_invalid',
                        'message': 'Код не найден'
                    }))
                    print(f"❌ Код для {phone} не найден")
            
            # 4️⃣ РЕГИСТРАЦИЯ НОВОГО ПОЛЬЗОВАТЕЛЯ
            elif msg_type == 'register':
                phone = data['phone']
                username = data['username']
                first_name = data.get('first_name', '')
                last_name = data.get('last_name', '')
                
                print(f"📝 Регистрация: {username} ({phone})")
                
                # Проверяем, не занят ли username
                c.execute("SELECT username FROM users WHERE username = ?", (username,))
                if c.fetchone():
                    await websocket.send(json.dumps({
                        'type': 'register_failed',
                        'message': 'Имя пользователя уже занято'
                    }))
                    print(f"❌ Username {username} уже занят")
                    return
                
                # Проверяем, не занят ли телефон
                c.execute("SELECT phone FROM users WHERE phone = ?", (phone,))
                if c.fetchone():
                    await websocket.send(json.dumps({
                        'type': 'register_failed',
                        'message': 'Этот номер уже зарегистрирован'
                    }))
                    print(f"❌ Телефон {phone} уже зарегистрирован")
                    return
                
                # Создаем пользователя
                user_id = f"user_{int(datetime.now().timestamp())}"
                c.execute("INSERT INTO users (user_id, phone, username, first_name, last_name, verified, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                         (user_id, phone, username, first_name, last_name, datetime.now()))
                conn.commit()
                
                connected_clients[user_id] = websocket
                
                await websocket.send(json.dumps({
                    'type': 'register_success',
                    'user_id': user_id,
                    'username': username
                }))
                print(f"🎉 Новый пользователь: {username} ({phone})")
            
            # 5️⃣ ВХОД ПО НОМЕРУ ТЕЛЕФОНА
            elif msg_type == 'login':
                phone = data['phone']
                print(f"🔓 Попытка входа: {phone}")
                
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
                    print(f"✅ Успешный вход: {username}")
                else:
                    await websocket.send(json.dumps({
                        'type': 'login_failed',
                        'message': 'Пользователь не найден'
                    }))
                    print(f"❌ Пользователь с номером {phone} не найден")
            
            # 6️⃣ ПОИСК ПОЛЬЗОВАТЕЛЯ ПО USERNAME
            elif msg_type == 'search_user':
                search_username = data['username']
                print(f"🔍 Поиск пользователя: {search_username}")
                
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
                    print(f"✅ Найден пользователь: {username}")
                else:
                    await websocket.send(json.dumps({
                        'type': 'search_result',
                        'found': False
                    }))
                    print(f"❌ Пользователь {search_username} не найден")
            
            # 7️⃣ ОТПРАВКА ЛИЧНОГО СООБЩЕНИЯ
            elif msg_type == 'private_message':
                from_user = data['from_user']
                to_user = data['to_user']
                message_text = data['message']
                
                print(f"💬 Сообщение от {from_user} к {to_user}: {message_text[:20]}...")
                
                # Сохраняем в БД
                c.execute("INSERT INTO messages (from_user, to_user, message, timestamp) VALUES (?, ?, ?, ?)",
                         (from_user, to_user, message_text, datetime.now()))
                conn.commit()
                
                # Отправляем получателю, если он онлайн
                if to_user in connected_clients:
                    await connected_clients[to_user].send(json.dumps({
                        'type': 'new_message',
                        'from_user': from_user,
                        'message': message_text,
                        'timestamp': str(datetime.now())
                    }))
                    print(f"✅ Сообщение доставлено {to_user}")
                else:
                    print(f"⚠️ Пользователь {to_user} не в сети")
                
                # Подтверждение отправителю
                await websocket.send(json.dumps({
                    'type': 'message_sent',
                    'to_user': to_user,
                    'message': message_text
                }))
                
    except websockets.exceptions.ConnectionClosed:
        print("👋 Клиент отключился")
        # Удаляем отключившегося клиента
        for user_id, ws in list(connected_clients.items()):
            if ws == websocket:
                del connected_clients[user_id]
                print(f"   Пользователь {user_id} удален")
                break

async def main():
    """Запуск сервера"""
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("=" * 50)
        print("🚀 Soo Messenger Server запущен!")
        print("📡 Порт: 8765")
        print("💾 База данных: soo_messages.db")
        print("=" * 50)
        await asyncio.Future()  # Работаем вечно

if __name__ == "__main__":
    asyncio.run(main())
