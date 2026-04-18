from telethon import TelegramClient, events
from time import time

from dotenv import load_dotenv
import os
import re
import asyncio
from collections import OrderedDict, deque
from telethon.errors import FloodWaitError

# ====================== إعدادات ======================



# تحميل ملف .env
load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")

COOLDOWN_SECONDS = 45
MAX_CACHE_SIZE = 5000          # زدنا للضغط العالي
MAX_MESSAGE_LENGTH = 150
MIN_SCORE = 4

MAX_FORWARDS_PER_SECOND = 8    # أنصح بخفضه إلى 6-8 للأمان
FORWARD_QUEUE_MAX_SIZE = 8000

# ====================== Weighted Scoring ======================
# (نفس الكود السابق بدون تغيير - normalize + calculate_score + smart_filter)

# ====================== الكاش والـ Queue ======================
forward_queue: deque = deque()
cooldown: OrderedDict = OrderedDict()
last_forward_time = 0.0
processing_task = None

client = TelegramClient(
    "session", 
    api_id, 
    api_hash,
    flood_sleep_threshold=60   # Telethon ينام تلقائياً للـ Flood أقل من 60 ثانية
)

async def should_process(event):
    if event.out or not event.text:
        return None
    if not smart_filter(event.text):
        return None

    # استخدام sender_id مباشرة (أسرع وأقل استهلاك)
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

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    result = await should_process(event)
    if not result:
        return

    if len(forward_queue) >= FORWARD_QUEUE_MAX_SIZE:
        print(f"⚠️ Queue ممتلئة ({len(forward_queue)}), تم تجاهل رسالة")
        return

    forward_queue.append(result)

    global processing_task
    if not processing_task or processing_task.done():
        processing_task = asyncio.create_task(process_forward_queue())

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
            await event.forward_to("me")
            last_forward_time = time()
        except FloodWaitError as e:
            print(f"🚨 FloodWaitError: انتظر {e.seconds} ثانية")
            await asyncio.sleep(e.seconds + 2)   # +2 ثواني احتياط
            forward_queue.appendleft(event)      # إعادة للمقدمة
        except Exception as e:
            print(f"❌ خطأ غير متوقع أثناء forward: {e}")
            await asyncio.sleep(3)
            if len(forward_queue) < FORWARD_QUEUE_MAX_SIZE:
                forward_queue.appendleft(event)

    processing_task = None

async def main():
    await client.start()
    print(f"✅ High-Load Userbot جاهز | Forward Rate: {MAX_FORWARDS_PER_SECOND}/ثانية | Queue Max: {FORWARD_QUEUE_MAX_SIZE}")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
