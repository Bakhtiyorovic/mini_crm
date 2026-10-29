import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from sqlalchemy import select

from channel_helper import (
    get_channel_info,
    get_vacant_beds_text,
    save_channel_info,
)
from core.database import init_models, async_session
from handlers import router
from models.models import Bed, Room


load_dotenv()

ADMIN_ID = os.getenv("ADMIN_ID")


async def check_expired_beds(bot: Bot):
    today = datetime.now().date()

    async with async_session() as session:
        result = await session.execute(
            select(Bed, Room)
            .join(Room)
            .where(
                Bed.is_occupied == True,
                Bed.occupied_until < today,
            )
        )
        expired_records = result.all()

        if expired_records:
            msg = (
                "🔔 <b>Muddati tugagan va avtomat "
                "bo'shatilgan joylar:</b>\n\n"
            )

            for bed, room in expired_records:
                bed.is_occupied = False
                bed.occupied_until = None
                bed.guest_name = None
                bed.guest_phone = None

                msg += (
                    f"🚪 {room.room_number}-xona, "
                    f"🛏 {bed.bed_number}-joy\n"
                )

            await session.commit()

            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=msg,
                    parse_mode="HTML",
                )
            except Exception as error:
                print(f"Xabar yuborishda xatolik: {error}")


async def update_channel_post_task(bot: Bot):
    info = get_channel_info()

    if not info:
        return

    async with async_session() as session:
        text = await get_vacant_beds_text(session)

    chat_id = info.get("chat_id")
    old_msg_id = info.get("message_id")

    try:
        if old_msg_id:
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=old_msg_id,
                )
            except Exception:
                pass

        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )

        try:
            await bot.pin_chat_message(
                chat_id=chat_id,
                message_id=msg.message_id,
            )
        except Exception as error:
            print(
                "Pin qilishda xatolik "
                f"(Bot adminmas yoki huquqi yo'q): {error}"
            )

        save_channel_info(chat_id, msg.message_id)

    except Exception as error:
        print(f"Guruh/Kanalni yangilashda xatolik: {error}")


async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()

    dp.include_router(router)
    await init_models()

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    scheduler.add_job(
        check_expired_beds,
        trigger="cron",
        hour=0,
        minute=5,
        kwargs={"bot": bot},
    )

    scheduler.add_job(
        update_channel_post_task,
        trigger="interval",
        hours=1,
        kwargs={"bot": bot},
    )

    scheduler.start()

    print("Bot va Avtomatik Scheduler ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())