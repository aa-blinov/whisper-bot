import sys

from huey.bin.huey_consumer import consumer_main

if __name__ == "__main__":
    sys.path.insert(0, "/app")
    sys.argv = ["huey_consumer.py", "huey_tasks.huey"]
    consumer_main()
