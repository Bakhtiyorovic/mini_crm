import json
import os
from sqlalchemy import select
from models.models import Room, Bed
from datetime import datetime

SETTINGS_FILE = "settings.json"

def get_channel_info():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_channel_info(chat_id, message_id):
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"chat_id": chat_id, "message_id": message_id}, f)

async def get_vacant_beds_text(session):
    rooms_result = await session.execute(select(Room).order_by(Room.room_number))
    rooms = rooms_result.scalars().all()
    
    text = "🏨 <b>HOSTELDAGI BO'SH JOYLAR RO'YXATI</b>\n\n"
    capacity_groups = {}
    
    for room in rooms:
        beds_result = await session.execute(select(Bed).where(Bed.room_id == room.id))
        all_beds = beds_result.scalars().all()
        capacity = len(all_beds)
        
        vacant_beds = [b for b in all_beds if not b.is_occupied]
        if not vacant_beds:
            continue
            
        if capacity not in capacity_groups:
            capacity_groups[capacity] = []
            
        for vb in vacant_beds:
            capacity_groups[capacity].append({
                "room": room.room_number,
                "bed": vb.bed_number,
                "daily": vb.daily_price,
                "monthly": vb.monthly_price
            })
    
    if not capacity_groups:
        return "🏨 Barcha joylar band qilingan! Hozircha bo'sh joylar yo'q. 🚫"
        
    for cap in sorted(capacity_groups.keys()):
        beds = capacity_groups[cap]
        text += f"🔹 <b>{cap} KISHILIK XONALAR:</b>\n"
        text += f"💸 Narxi: {beds[0]['monthly']:,.0f} so'm/oy, {beds[0]['daily']:,.0f} so'm/kun\n"
        
        room_beds = {}
        for b in beds:
            if b['room'] not in room_beds:
                room_beds[b['room']] = []
            room_beds[b['room']].append(str(b['bed']))
        
        for r_num, b_nums in room_beds.items():
            text += f"🚪 <b>{r_num}-xona:</b> {', '.join(b_nums)}-joylar\n"
        text += "\n"
        
    text += f"📞 <b>Murojaat uchun:</b> +998991230103\n"
    text += f"🕒 <i>Yangilangan vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
    return text
