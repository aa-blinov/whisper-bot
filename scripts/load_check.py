"""Проверка поведения под нагрузкой: параллельные клиенты через очередь.

    python load_check.py [--file data/_test/sample.mp3] [--clients 8] [--duration 12]
"""

import argparse
import asyncio
import os
import shutil
import time

import redis

from app.config import Settings
from app.container import build_services


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/_test/sample.mp3")
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--duration", type=int, default=12)
    args = parser.parse_args()

    settings = Settings.from_env()
    services = build_services(settings)
    base = "data/_test/load"
    os.makedirs(base, exist_ok=True)

    # История пишется с внешним ключом: берём существующего пользователя,
    # иначе Postgres отвергает каждую вставку и засоряет лог.
    from app.infra import database

    known = database.list_users(settings.database_url)
    user_id = known[0].user_id if known else 111
    if not known:
        database.add_user(settings.database_url, user_id, first_name="Load check")

    files = []
    for index in range(args.clients):
        path = f"{base}/r{index}.mp3"
        shutil.copy(args.file, path)
        files.append(path)

    async def one(path: str) -> tuple[float, bool]:
        started = time.time()
        transcript = await services.transcription.transcribe(
            path, "voice", "ru", args.duration
        )
        elapsed = time.time() - started
        if transcript:
            services.stats.record(user_id, elapsed, "voice", transcript.text, "ru")
        return elapsed, transcript is not None

    client = redis.Redis(
        host=settings.redis_host, port=settings.redis_port, db=settings.redis_db
    )
    before = len(client.keys("huey*"))

    lags: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        while not stop.is_set():
            started = time.time()
            await asyncio.sleep(0.05)
            lags.append(time.time() - started - 0.05)

    tick = asyncio.create_task(ticker())
    started_all = time.time()
    results = await asyncio.gather(*(one(path) for path in files))
    wall = time.time() - started_all
    stop.set()
    await tick

    keys = client.keys("huey*")
    print(f"file: {args.file}, clients: {len(files)}")
    print(f"wall: {wall:.2f} s")
    print("latencies:", [round(item[0], 2) for item in results])
    print("ok:", sum(1 for item in results if item[1]), "/", len(results))
    print(f"event loop max lag: {max(lags) * 1000:.1f} ms")
    print(f"redis huey keys: {before} -> {len(keys)}")


if __name__ == "__main__":
    asyncio.run(main())
