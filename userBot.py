from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

from time import time
from dotenv import load_dotenv
import os
import asyncio
import re  # تم إضافة المكتبة الناقصة
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
MAX_MESSAGE_LENGTH = 160
MIN_SCORE = 3.5

MAX_FORWARDS_PER_SECOND = 2 # خفض السرعة قليلاً لتجنب الحظر
FORWARD_QUEUE_MAX_SIZE = 2000

# ====================== Ultra Smart Filter ======================
INTENT_WORDS = {"ابي", "ابغى", "محتاج", "احتاج", "اريد", "أريد", "بغيت", "بغى", "ابغي", "بغي"}
STUDY_WORDS  = {"واجب", "مشروع", "اسايمنت", "اسينمنت", "اسمنت", "assignment", "كويز", "اختبار", 
                "حل", "يحل", "تمرين", "فروض", "مادة", "محاضرة", "كورس"}
HELP_WORDS   = {"يساعد", "يسوي", "يشرح", "تكفون", "تساعدني", "من يسوي", "حد يحل"}

URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)

def normalize(text: str) -> str:
    if not text: return ""
    t = text.lower()
    # تنظيف مكررات الحروف (مثال: واااجب -> واجب)
    t = re.sub(r"(.)\1{2,}", r"\1", t)
    return t

def calculate_score(text: str) -> float:
    norm = normalize(text)
    if not norm or URL_PATTERN.search(norm): return 0.0

    words = norm.split()
    # حساب النقاط بناءً على الكلمات المفتاحية
    intent_score = sum(3.5 for w in words if any(x in w for x in INTENT_WORDS))
    study_score  = sum(2.0 for w in words if any(x in w for x in STUDY_WORDS))
    help_score   = sum(1.0 for w in words if any(x in w for x in HELP_WORDS))

    return intent_score + study_score + help_score

def smart_filter(text: str) -> bool:
    if not text or len(text.strip()) > MAX_MESSAGE_LENGTH:
        return False
    return calculate_score(text) >= MIN_SCORE

# ====================== إدارة العمليات ======================
forward_queue = deque()
cooldown = OrderedDict()
last_forward_time = 0.0

client = TelegramClient(StringSession(session), api_id, api_hash)

async def process_forward_queue():
    global last_forward_time
    while forward_queue:
        # التحكم في التدفق لتجنب الـ Flood
        now = time()
        delay = (1.0 / MAX_FORWARDS_PER_SECOND) - (now - last_forward_time)
        if delay > 0: await asyncio.sleep(delay)

        event = forward_queue.popleft()
        try:
            chat = await event.get_chat()
            chat_title = chat.title or "Private"
            
            # محاولة إنشاء رابط مباشر للرسالة
            msg_link = f"https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}"
            if getattr(chat, 'username', None):
                msg_link = f"https://t.me/{chat.username}/{event.message.id}"

            info = (
                f"🎯 **طلب جديد مستهدف**\n"
                f"👤 **المجموعة:** {chat_title}\n"
                f"🔗 **رابط الرسالة:** [اضغط هنا]({msg_link})\n"
                f"✍️ **النص:** `{event.text[:100]}...`"
            )

            await client.send_message("me", info, link_preview=False)
            # تحويل الرسالة الأصلية لضمان رؤية الصور أو الملفات المرفقة
            await client.forward_messages("me", event.message)
            
            last_forward_time = time()
            await asyncio.sleep(random.uniform(0.5, 1.5))

        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            print(f"Error: {e}")

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not event.text or not smart_filter(event.text): return

    # نظام التبريد (Cooldown) لكل مستخدم
    user_id = event.sender_id
    now = time()
    if user_id in cooldown and now - cooldown[user_id] < COOLDOWN_SECONDS: return
    
    cooldown[user_id] = now
    if len(cooldown) > MAX_CACHE_SIZE: cooldown.popitem(last=False)

    forward_queue.append(event)
    
    # تشغيل المعالج إذا لم يكن يعمل
    if not hasattr(client, 'is_processing') or client.is_processing.done():
        client.is_processing = asyncio.create_task(process_forward_queue())

async def main():
    await client.start()
    print("🚀 البوت يعمل الآن ويراقب الطلبات...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
