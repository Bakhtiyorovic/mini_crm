import asyncio
import sys
import os

# Asosiy papka importlarini ko'ra olishi uchun yo'lni qo'shamiz
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import async_session, init_models
from models.models import Room, Bed

ROOMS_DATA = {
    101: 12, 102: 12, 103: 12, 104: 12, 105: 6,
    106: 4, 107: 4, 108: 10, 109: 6, 110: 4,
    111: 4, 112: 4, 201: 6, 202: 4, 203: 4,
    204: 4, 206: 14, 207: 14, 208: 4, 209: 4,
    210: 6, 211: 6, 212: 6, 213: 8
}


async def seed_data():
    await init_models()
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Room))
        if result.scalars().first():
            print("Baza allaqachon to'ldirilgan!")
            return

        total_beds_created = 0
        for room_num, beds_count in ROOMS_DATA.items():
            room = Room(room_number=room_num)
            session.add(room)
            await session.flush()

            # Xona sig'imiga qarab narxlarni belgilash
            if beds_count in [4, 6]:
                d_price = 60000.0  # 60 ming so'm kuniga
                m_price = 1200000.0  # 1.2 mln oyiga
            else:
                d_price = 45000.0  # 45 ming so'm kuniga
                m_price = 1000000.0  # 1 mln oyiga

            for bed_num in range(1, beds_count + 1):
                bed = Bed(
                    room_id=room.id,
                    bed_number=bed_num,
                    daily_price=d_price,
                    monthly_price=m_price,
                    is_occupied=False
                )
                session.add(bed)
                total_beds_created += 1

        await session.commit()
        print(f"Muvaffaqiyatli saqlandi: {len(ROOMS_DATA)} ta xona va {total_beds_created} ta joy!")


if __name__ == "__main__":
    asyncio.run(seed_data())