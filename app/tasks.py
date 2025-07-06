from huey import RedisHuey

huey = RedisHuey("whisper-bot", host="redis", port=6379, db=0, results=True)
