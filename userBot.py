from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

from time import time
from dotenv import load_dotenv
import os
import asyncio
from collections import OrderedDict, deque
import random

# ====================== تحميل الإعدادات ======================
load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session = os.getenv("SESSION")

# ====================== إعدادات النظام ======================
COOLDOWN_SECONDS = 60
MAX_CACHE_SIZE = 5000
MAX_MESSAGE_LENGTH = 160          # بدون مسافات
MIN_SCORE = 3.5                   # متوازن جداً (لا يضيع طلبات ولا يسمح بسبام)

MAX_FORWARDS_PER_SECOND = 3
FORWARD_QUEUE_MAX_SIZE = 2000

# ====================== Ultra Smart Weighted Scoring ======================
INTENT_WORDS = {"ابي", "ابغى", "محتاج", "احتاج", "اريد", "أريد", "بغيت", "بغى", "ابغي", "بغي"}
STUDY_WORDS  = {"واجب", "مشروع", "اسايمنت", "اسينمنت", "اسمنت", "assignment", "كويز", "اختبار", 
                "حل", "يحل", "تمرين", "فروض", "مادة", "محاضرة", "كورس", "كويزز", "امتحان"}
HELP_WORDS   = {"يساعد", "يسوي", "يشرح", "تكفون", "الله يخليك", "تساعدني", "من يسوي", "حد يحل", 
                "حد يسوي", "أحد يحل", "أحد يسوي", "يساعدني", "شرح", "حلول"}

URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)

def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    
    # تصحيحات إملائية خليجية متقدمة جداً
    replacements = {
        "ابغى": "ابي", "أبغى": "ابي", "ابغي": "ابي", "بغى": "ابي", "بغيت": "ابي", "بغي": "ابي",
        "اريد": "ابي", "أريد": "ابي", "اريدي": "ابي",
        "مساعده": "مساعدة", "مساعدةه": "مساعدة",
        "احب": "حل", "يحب": "يحل", "يحبب": "يحل", "يحلل": "يحل",
        "اسمنت": "اسايمنت", "اساينمنت": "اسايمنت", "اسينمنت": "اسايمنت", "اسينت": "اسايمنت",
        "واجبب": "واجب", "واجيب": "واجب", "مشروعج": "مشروع", "مشروج": "مشروع",
        "كويزز": "كويز", "كويززز": "كويز", "اختبارر": "اختبار",
        "تمرينن": "تمرين", "فروضض": "فروض", "محاضره": "محاضرة",
    }
    for old, new in replacements.items():
        t = t.replace(old, new)
    
    # تقليل التكرار الشديد (اااابي → ابي)
    t = re.sub(r"(.)\1{2,}", r"\1", t)
    return t

def get_clean_length(text: str) -> int:
    return len(text.replace(" ", "")) if text else 0

def calculate_score(text: str) -> float:
    norm = normalize(text)
    if not norm or URL_PATTERN.search(norm):
        return 0.0

    words = norm.split()
    intent_score = sum(3.5 for w in words if w in INTENT_WORDS)
    study_score  = sum(2.0 for w in words if w in STUDY_WORDS)
    help_score   = sum(1.0 for w in words if w in HELP_WORDS)

    total = intent_score + study_score + help_score

    # Bonus قوي جداً للرسائل القصيرة (الأكثر شيوعاً في طلبات الطلاب)
    if len(norm) < 30 and intent_score >= 3.5 and (study_score > 0 or help_score > 0):
        total += 5.0

    return total

def smart_filter(text: str) -> bool:
    """الفلتر الذكي النهائي (Ultra Smart)"""
    if not text or get_clean_length(text) > MAX_MESSAGE_LENGTH:
        return False
    
    score = calculate_score(text)
    return score >= MIN_SCORE


# ====================== الكاش والـ Queue ======================
forward_queue: deque = deque()
cooldown: OrderedDict = OrderedDict()
last_forward_time = 0.0
processing_task = None

client = TelegramClient(
    StringSession(session),
    api_id,
    api_hash,
    flood_sleep_threshold=60
)

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

# ====================== Handler + Queue ======================
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
            await asyncio.sleep(random.uniform(0.35, 0.85))

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

    print(f"✅ Ultra Smart Userbot شغال | فلتر ذكي جداً | MIN_SCORE={MIN_SCORE}")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
