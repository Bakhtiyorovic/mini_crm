from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🛏 Joy band qilish / Holat")],
        [KeyboardButton(text="📊 Kassa hisoboti"), KeyboardButton(text="⚙️ Sozlamalar")] #
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_rooms_keyboard(rooms) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for room in rooms:
        builder.button(text=f"{room.room_number}", callback_data=f"room_{room.id}")
    builder.adjust(4)
    return builder.as_markup()

def get_beds_keyboard(beds) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for bed in beds:
        status = "🔴" if bed.is_occupied else "🟢"
        builder.button(text=f"{status} {bed.bed_number}", callback_data=f"bed_{bed.id}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_rooms"))
    return builder.as_markup()