from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

from time import time
from dotenv import load_dotenv
import os
import asyncio
from collections import OrderedDict, deque
import random

# ====================== تحميل env ======================
load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session = os.getenv("SESSION")

# ====================== إعدادات ======================
COOLDOWN_SECONDS = 60
MAX_CACHE_SIZE = 5000
MAX_MESSAGE_LENGTH = 150
MIN_SCORE = 4

MAX_FORWARDS_PER_SECOND = 3
FORWARD_QUEUE_MAX_SIZE = 2000

# ====================== الكاش ======================
forward_queue: deque = deque()
cooldown: OrderedDict = OrderedDict()
last_forward_time = 0.0
processing_task = None

# ====================== العميل ======================
client = TelegramClient(
    StringSession(session),
    api_id,
    api_hash,
    flood_sleep_threshold=60
)

# ====================== فلترة ======================
def smart_filter(text):
    return len(text) > 0

# ====================== معالجة الرسائل ======================
async def should_process(event):
    if event.out or not event.text:
        return None

    if not smart_filter(event.text):
        return None

    user_id = event.sender_id
    if user_id is None:
        return None

    now = time()

    if user_id in cooldown and now - cooldown[user_id] < COOLDOWN_SECONDS:
        return None

    cooldown[user_id] = now
    cooldown.move_to_end(user_id)

    if len(cooldown) > MAX_CACHE_SIZE:
        cooldown.popitem(last=False)

    return event

# ====================== استقبال الرسائل ======================
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    result = await should_process(event)
    if not result:
        return

    if len(forward_queue) >= FORWARD_QUEUE_MAX_SIZE:
        print("⚠️ Queue ممتلئة")
        return

    forward_queue.append(result)

    global processing_task
    if not processing_task or processing_task.done():
        processing_task = asyncio.create_task(process_forward_queue())

# ====================== المعالجة ======================
async def process_forward_queue():
    global last_forward_time, processing_task
    processing_task = asyncio.current_task()

    while forward_queue:
        now = time()

        delay = 1.0 / MAX_FORWARDS_PER_SECOND - (now - last_forward_time)
        if delay > 0:
            await asyncio.sleep(delay)

        event = forward_queue.popleft()

        try:
            await client.forward_messages(
                entity="me",
                messages=event.message.id,
                from_peer=event.chat_id
            )
            last_forward_time = time()

            await asyncio.sleep(random.uniform(0.3, 0.8))

        except FloodWaitError as e:
            print(f"🚨 FloodWait: {e.seconds} ثانية")
            await asyncio.sleep(e.seconds + 2)
            forward_queue.appendleft(event)

        except Exception as e:
            print(f"❌ خطأ: {e}")
            await asyncio.sleep(3)
            forward_queue.appendleft(event)

    processing_task = None

# ====================== تشغيل ======================
async def main():
    await client.connect()

    if not await client.is_user_authorized():
        print("❌ SESSION غير صالح")
        return

    print(f"✅ Userbot شغال | Speed: {MAX_FORWARDS_PER_SECOND}/sec")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
