import sqlite3
import os

# Путь к файлу базы данных
DB_PATH = "soo_messages.db"

print("=" * 50)
print("🧹 ОЧИСТКА БАЗЫ ДАННЫХ")
print("=" * 50)

# Проверяем, существует ли файл БД
if os.path.exists(DB_PATH):
    print(f"📁 Найден файл БД: {DB_PATH}")
    
    try:
        # Подключаемся к БД
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Получаем список таблиц
        c.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = c.fetchall()
        
        print(f"📊 Найдено таблиц: {len(tables)}")
        
        # Очищаем каждую таблицу
        for table in tables:
            table_name = table[0]
            if table_name != "sqlite_sequence":  # Не очищаем системную таблицу
                c.execute(f"DELETE FROM {table_name}")
                print(f"   ✅ Таблица '{table_name}' очищена")
        
        # Сбрасываем автоинкремент
        c.execute("DELETE FROM sqlite_sequence")
        
        conn.commit()
        conn.close()
        
        print("=" * 50)
        print("✅ БАЗА ДАННЫХ УСПЕШНО ОЧИЩЕНА!")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ Ошибка при очистке: {e}")
else:
    print(f"❌ Файл БД не найден: {DB_PATH}")
    print("   Возможно, база еще не создана или находится в другом месте.")

print("\n🔄 Теперь верни обратно свой рабочий server.py и перезапусти сервер!")
