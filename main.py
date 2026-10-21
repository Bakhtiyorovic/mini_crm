import asyncio
import os
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from handlers import router
from core.database import init_models, async_session
from models.models import Bed, Room
from sqlalchemy import select
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from channel_helper import get_channel_info, get_vacant_beds_text

load_dotenv()

# Admin ID ni .env fayldan chaqirib olamiz
ADMIN_ID = os.getenv("ADMIN_ID")


async def check_expired_beds(bot: Bot):
    today = datetime.now().date()
    async with async_session() as session:
        result = await session.execute(
            select(Bed, Room).join(Room).where(Bed.is_occupied == True, Bed.occupied_until < today)
        )
        expired_records = result.all()

        if expired_records:
            msg = "🔔 <b>Muddati tugagan va avtomat bo'shatilgan joylar:</b>\n\n"
            for bed, room in expired_records:
                bed.is_occupied = False
                bed.occupied_until = None
                bed.guest_name = None
                msg += f"🚪 {room.room_number}-xona, 🛏 {bed.bed_number}-joy\n"

            await session.commit()

            try:
                await bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="HTML")
            except Exception as e:
                print(f"Xabar yuborishda xatolik: {e}")


# KANALDAGI YOKI GURUHDAGI E'LONNI YANGILOVCHI FUNKSIYA
async def update_channel_post_task(bot: Bot):
    info = get_channel_info()
    if not info:
        return

    async with async_session() as session:
        text = await get_vacant_beds_text(session)

    chat_id = info.get('chat_id')
    old_msg_id = info.get('message_id')

    try:
        # 1. Eski xabarni o'chirish (guruh to'lib ketmasligi uchun)
        if old_msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
            except Exception:
                pass  # Agar foydalanuvchi yoki kimdir qo'lda o'chirib yuborgan bo'lsa xato bermaydi

        # 2. Yangi xabar yuborish
        msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

        # 3. Yangi xabarni PIN qilib qo'yish
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id)
        except Exception as e:
            print(f"Pin qilishda xatolik (Bot adminmas yoki huquqi yo'q): {e}")

        # 4. Keyingi soatda o'chira olishi uchun yangi ID ni saqlab qo'yish
        from channel_helper import save_channel_info
        save_channel_info(chat_id, msg.message_id)

    except Exception as e:
        print(f"Guruh/Kanalni yangilashda xatolik: {e}")


async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()

    dp.include_router(router)
    await init_models()

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    # 1. Tunda muddati o'tganlarni bo'shatish
    scheduler.add_job(check_expired_beds, trigger='cron', hour=0, minute=5, kwargs={'bot': bot})

    # 2. Har 1 soatda kanaldagi/guruhdagi e'lonni eski xabarni o'chirib, yangisini yuborib pin qilish
    scheduler.add_job(update_channel_post_task, trigger='interval', hours=1, kwargs={'bot': bot})

    scheduler.start()

    print("Bot va Avtomatik Scheduler ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())