#!/usr/bin/env python
import asyncio
import websockets
import os
import signal
import http

connected_clients = set()

async def handler(websocket):
    connected_clients.add(websocket)
    print(f"Новый клиент! Всего: {len(connected_clients)}")
    
    try:
        async for message in websocket:
            print(f"Сообщение: {message}")
            for client in connected_clients:
                if client != websocket:
                    await client.send(message)
    except websockets.exceptions.ConnectionClosed:
        print("Клиент отключился")
    finally:
        connected_clients.remove(websocket)
        print(f"Клиент удален. Осталось: {len(connected_clients)}")

async def health_check(path, request_headers):
    """Health check для Render - чтобы сервер не думали что он умер"""
    if path == "/healthz":
        return http.HTTPStatus.OK, [], b"OK\n"

async def main():
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    
    # Render сам дает порт через переменную окружения PORT [citation:6]
    port = int(os.environ.get("PORT", 8765))
    
    async with websockets.serve(
        handler,
        host="0.0.0.0",  # ВАЖНО: слушаем все интерфейсы [citation:6]
        port=port,
        process_request=health_check
    ):
        print(f"🚀 Сервер запущен на порту {port}!")
        await stop

if __name__ == "__main__":
    asyncio.run(main())