from datetime import datetime, date, time, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from core.database import async_session
from models.models import Room, Bed, Transaction
from states import BookingState
import keyboards as kb
from sqlalchemy import select, update, func
import pandas as pd
import os

router = Router()

# ==========================================
# PAROL VA AVTORIZATSIYA
# ==========================================
ADMIN_PASSWORD = "bekhostel26"

# Botni endi boshlaganlar uchun holat (State)
from aiogram.fsm.state import State, StatesGroup
class Auth(StatesGroup):
    waiting_for_password = State()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    await message.answer("🔒 Xush kelibsiz!\nIltimos, botdan foydalanish uchun kirish parolini kiriting:")
    await state.set_state(Auth.waiting_for_password)

@router.message(Auth.waiting_for_password)
async def check_password(message: Message, state: FSMContext):
    if message.text.strip() == ADMIN_PASSWORD:
        await message.answer("✅ Parol qabul qilindi. Tizimga xush kelibsiz!", reply_markup=kb.get_main_menu())
        await state.clear()
    else:
        # Parol xato bo'lsa, holat saqlanib qoladi va qayta kiritishni so'raydi
        await message.answer("❌ Noto'g'ri parol! Qaytadan urinib ko'ring:")

# ==========================================
# QOLGAN BARCHA AMALLAR
# ==========================================

@router.message(F.text == "🛏 Joy band qilish / Holat")
async def show_rooms(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        result = await session.execute(select(Room).order_by(Room.room_number))
        rooms = result.scalars().all()

    await message.answer("Qaysi xonani ko'rmoqchisiz?", reply_markup=kb.get_rooms_keyboard(rooms))
    await state.set_state(BookingState.choosing_room)

@router.callback_query(BookingState.choosing_room, F.data.startswith("room_"))
async def room_selected(callback: CallbackQuery, state: FSMContext):
    room_id = int(callback.data.split("_")[1])
    await state.update_data(room_id=room_id)

    async with async_session() as session:
        room_result = await session.execute(select(Room).where(Room.id == room_id))
        room = room_result.scalar_one()
        bed_result = await session.execute(select(Bed).where(Bed.room_id == room_id).order_by(Bed.bed_number))
        beds = bed_result.scalars().all()

    await callback.message.edit_text(
        f"🚪 <b>{room.room_number}-xona.</b>\n🔴 - band, 🟢 - bo'sh.\nQaysi joyni tanlaysiz?",
        reply_markup=kb.get_beds_keyboard(beds),
        parse_mode="HTML"
    )
    await state.set_state(BookingState.choosing_bed)

@router.callback_query(BookingState.choosing_bed, F.data == "back_to_rooms")
async def back_to_rooms_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await show_rooms(callback.message, state)

@router.callback_query(BookingState.choosing_bed, F.data.startswith("bed_"))
async def bed_selected(callback: CallbackQuery, state: FSMContext):
    bed_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        bed = await session.get(Bed, bed_id)
        room = await session.get(Room, bed.room_id)

        await state.update_data(
            bed_id=bed_id, room_number=room.room_number,
            bed_number=bed.bed_number,
            daily_price=bed.daily_price,
            monthly_price=bed.monthly_price,
            discount_percent=0
        )

        if bed.is_occupied:
            await state.update_data(old_date=bed.occupied_until.strftime("%d.%m.%Y"), guest_name=bed.guest_name)
            builder = InlineKeyboardBuilder()
            builder.button(text="➕ Uzaytirish", callback_data=f"extend_{bed.id}")
            builder.button(text="🛑 Bo'shatish", callback_data=f"release_{bed.id}")
            builder.button(text="🔙 Orqaga", callback_data="back_to_rooms")
            builder.adjust(2, 1)

            await callback.message.edit_text(
                f"⚠️ <b>{room.room_number}-xona, {bed.bed_number}-joy</b> ayni vaqtda <b>{bed.occupied_until.strftime('%d.%m.%Y')}</b> gacha BAND.\n"
                f"👤 Mijoz: <b>{bed.guest_name or 'Kiritilmagan'}</b>\n\nNima amal bajarasiz?",
                reply_markup=builder.as_markup(), parse_mode="HTML"
            )
            return

    await callback.message.delete()
    await callback.message.answer(
        f"✅ {room.room_number}-xona, {bed.bed_number}-joy.\n\n"
        f"👤 <b>Mijozning Ism-Familiyasini kiriting:</b>\n(Masalan: Alisher Valiyev)",
        parse_mode="HTML"
    )
    await state.set_state(BookingState.entering_name)

@router.message(BookingState.entering_name)
async def process_name(message: Message, state: FSMContext):
    guest_name = message.text.strip()
    await state.update_data(guest_name=guest_name)
    
    data = await state.get_data()
    monthly_price = data['monthly_price']
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🗓 1 oy ({monthly_price:,.0f} so'm)", callback_data="tariff_1_month")
    
    await message.answer(
        f"👤 Mijoz: {guest_name}\n\n"
        f"📅 Qaysi sanagacha turadi?\n(Qo'lda DD.MM.YYYY yozing yoki pastdagi tarifni tanlang)\nMasalan: 30.11.2026",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BookingState.entering_date)

def get_payment_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Naqd", callback_data="pay_Naqd")
    builder.button(text="📱 E-pay", callback_data="pay_E-pay") 
    builder.button(text="💳 Karta", callback_data="pay_Karta")
    builder.button(text="🎁 Chegirma kiritish", callback_data="add_discount")
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_booking"))
    builder.adjust(3, 1, 1)
    return builder.as_markup()

@router.callback_query(BookingState.entering_date, F.data == "tariff_1_month")
async def process_1_month_tariff(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    today = datetime.now().date()
    
    end_date = today + timedelta(days=30)
    days_count = 30
    total_sum = data['monthly_price']
    
    await state.update_data(end_date=end_date.strftime("%d.%m.%Y"), total_sum=total_sum, base_sum=total_sum)
    
    await callback.message.delete()
    await callback.message.answer(
        f"👤 Mijoz: <b>{data.get('guest_name', 'Noma\'lum')}</b>\n"
        f"📅 Kunlar: <b>{days_count} kun</b> (1 oy)\n"
        f"💰 Jami summa: <b>{total_sum:,.0f} so'm</b>\n\n"
        f"To'lov turini tanlang yoki chegirma kiriting:",
        reply_markup=get_payment_keyboard(), parse_mode="HTML"
    )
    await state.set_state(BookingState.choosing_payment)

@router.message(BookingState.entering_date)
async def process_date(message: Message, state: FSMContext):
    date_text = message.text.strip()
    try:
        end_date = datetime.strptime(date_text, "%d.%m.%Y").date()
        today = datetime.now().date()

        if end_date <= today:
            await message.answer("❌ Sana bugungi kundan keyin bo'lishi kerak. Qaytadan kiriting:")
            return

        days_count = (end_date - today).days
        data = await state.get_data()
        
        months = days_count // 30
        remaining_days = days_count % 30
        total_sum = (months * data['monthly_price']) + (remaining_days * data['daily_price'])

        await state.update_data(end_date=end_date.strftime("%d.%m.%Y"), total_sum=total_sum, base_sum=total_sum)

        await message.answer(
            f"👤 Mijoz: <b>{data.get('guest_name', 'Noma\'lum')}</b>\n"
            f"📅 Kunlar: <b>{days_count} kun</b>\n"
            f"💰 Jami summa: <b>{total_sum:,.0f} so'm</b>\n\n"
            f"To'lov turini tanlang yoki chegirma kiriting:",
            reply_markup=get_payment_keyboard(), parse_mode="HTML"
        )
        await state.set_state(BookingState.choosing_payment)
    except ValueError:
        await message.answer("❌ Xato! Sanani DD.MM.YYYY formatida yozing:")

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Amaliyot bekor qilindi.", reply_markup=kb.get_main_menu())

@router.callback_query(F.data.startswith("release_"))
async def release_bed(callback: CallbackQuery, state: FSMContext):
    bed_id = int(callback.data.split("_")[1])
    
    async with async_session() as session:
        bed = await session.get(Bed, bed_id)
        room = await session.get(Room, bed.room_id)
        
        tx_query = await session.execute(
            select(Transaction).where(
                Transaction.room_number == room.room_number,
                Transaction.bed_number == bed.bed_number,
                Transaction.amount > 0
            ).order_by(Transaction.id.desc()).limit(1)
        )
        last_tx = tx_query.scalar_one_or_none()
        today = datetime.now().date()
        
        if last_tx and bed.occupied_until and today < bed.occupied_until:
            start_date = last_tx.created_at.date()
            days_stayed = (today - start_date).days
            if days_stayed <= 0:
                days_stayed = 1 
                
            months = days_stayed // 30
            remaining_days = days_stayed % 30
            actual_cost = (months * bed.monthly_price) + (remaining_days * bed.daily_price)
            
            if last_tx.discount_percent > 0:
                actual_cost = actual_cost - (actual_cost * last_tx.discount_percent / 100)
                
            refund_amount = last_tx.amount - actual_cost
            
            if refund_amount > 0:
                await state.update_data(
                    release_bed_id=bed.id, 
                    refund_amount=refund_amount,
                    room_number=room.room_number,
                    bed_number=bed.bed_number,
                    guest_name=bed.guest_name,
                    payment_type=last_tx.payment_type
                )
                
                builder = InlineKeyboardBuilder()
                builder.button(text="✅ Ha, pulni qaytarish va bo'shatish", callback_data="confirm_early_release")
                builder.button(text="❌ Bekor qilish", callback_data="cancel_booking")
                builder.adjust(1)
                
                await callback.message.edit_text(
                    f"⚠️ <b>Mijoz muddatidan oldin chiqib ketyapti!</b>\n\n"
                    f"👤 Mijoz: {bed.guest_name}\n"
                    f"📅 Yashagan kunlari: <b>{days_stayed} kun</b> (To'lagan: {last_tx.created_at.strftime('%d.%m.%Y')})\n"
                    f"💰 Asl to'lagan summasi: {last_tx.amount:,.0f} so'm\n"
                    f"📉 Yashagan kuniga summa: {actual_cost:,.0f} so'm\n\n"
                    f"💵 <b>Kassadan qaytariladigan summa: {refund_amount:,.0f} so'm</b>\n\n"
                    f"Tasdiqlaysizmi? (Bu summa kassadan minus qilinadi)",
                    reply_markup=builder.as_markup(), parse_mode="HTML"
                )
                return

        bed.is_occupied = False
        bed.occupied_until = None
        bed.guest_name = None
        await session.commit()

    await callback.message.edit_text("✅ Joy muvaffaqiyatli bo'shatildi!", reply_markup=None)
    await callback.message.answer("Bosh menyu:", reply_markup=kb.get_main_menu())
    await state.clear()

@router.callback_query(F.data == "confirm_early_release")
async def confirm_early_release(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    async with async_session() as session:
        bed = await session.get(Bed, data['release_bed_id'])
        if bed:
            bed.is_occupied = False
            bed.occupied_until = None
            bed.guest_name = None
            
        new_tx = Transaction(
            room_number=data['room_number'],
            bed_number=data['bed_number'],
            guest_name=f"{data.get('guest_name', 'Noma\'lum')} (Qaytarildi)",
            amount=-data['refund_amount'], 
            discount_percent=0,
            payment_type=data['payment_type']
        )
        session.add(new_tx)
        await session.commit()
        
    await callback.message.edit_text(
        f"✅ <b>Joy bo'shatildi va pul hisob-kitob qilindi!</b>\n\n"
        f"Qaytarilgan summa: <b>{data['refund_amount']:,.0f} so'm</b> ({data['payment_type']})\n"
        f"Kassadan ayirib tashlandi.", parse_mode="HTML"
    )
    await callback.message.answer("Bosh menyu:", reply_markup=kb.get_main_menu())
    await state.clear()


@router.callback_query(F.data.startswith("extend_"))
async def ask_extend_date(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    monthly_price = data['monthly_price']
    
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🗓 +1 oy uzaytirish ({monthly_price:,.0f} so'm)", callback_data="extend_1_month")
    
    await callback.message.edit_text(
        f"📅 Joriy tugash sanasi: <b>{data['old_date']}</b>\n\n"
        f"Mijoz qaysi sanagacha uzaytirmoqchi?\n(Qo'lda yozing yoki +1 oylik tarifni tanlang)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(BookingState.extending_date)

@router.callback_query(BookingState.extending_date, F.data == "extend_1_month")
async def process_extend_1_month(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    old_end_date = datetime.strptime(data['old_date'], "%d.%m.%Y").date()
    
    new_end_date = old_end_date + timedelta(days=30)
    days_count = 30
    total_sum = data['monthly_price']
    
    await state.update_data(end_date=new_end_date.strftime("%d.%m.%Y"), total_sum=total_sum, base_sum=total_sum)
    
    await callback.message.delete()
    await callback.message.answer(
        f"📈 <b>Uzaytirish hisobi:</b>\n\n"
        f"Qo'shilgan kunlar: <b>{days_count} kun</b> (1 oy)\n"
        f"Qo'shimcha summa: <b>{total_sum:,.0f} so'm</b>\n\n"
        f"To'lov turini tanlang yoki chegirma kiriting:",
        reply_markup=get_payment_keyboard(), parse_mode="HTML"
    )
    await state.set_state(BookingState.choosing_payment)

@router.message(BookingState.extending_date)
async def process_extend_date(message: Message, state: FSMContext):
    date_text = message.text.strip()
    try:
        new_end_date = datetime.strptime(date_text, "%d.%m.%Y").date()
        data = await state.get_data()
        old_end_date = datetime.strptime(data['old_date'], "%d.%m.%Y").date()

        if new_end_date <= old_end_date:
            await message.answer(f"❌ Sana joriy tugash sanasidan ({data['old_date']}) keyin bo'lishi kerak!")
            return

        days_count = (new_end_date - old_end_date).days

        months = days_count // 30
        remaining_days = days_count % 30
        total_sum = (months * data['monthly_price']) + (remaining_days * data['daily_price'])

        await state.update_data(end_date=new_end_date.strftime("%d.%m.%Y"), total_sum=total_sum, base_sum=total_sum)

        await message.answer(
            f"Uzaytirish hisobi:\n\nQo'shilgan kunlar: <b>{days_count} kun</b>\nQo'shimcha summa: <b>{total_sum:,.0f} so'm</b>\n\nTo'lov turini tanlang yoki chegirma kiriting:",
            reply_markup=get_payment_keyboard(), parse_mode="HTML"
        )
        await state.set_state(BookingState.choosing_payment)
    except ValueError:
        await message.answer("❌ Xato! Sanani DD.MM.YYYY formatida yozing:")

@router.callback_query(BookingState.choosing_payment, F.data == "add_discount")
async def ask_discount(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("🎁 Chegirma foizini kiriting (Masalan, 10 yoki 15):")
    await state.set_state(BookingState.entering_discount)

@router.message(BookingState.entering_discount)
async def process_discount(message: Message, state: FSMContext):
    try:
        discount_percent = float(message.text.strip())
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError

        data = await state.get_data()
        base_sum = data['base_sum']
        new_total = base_sum - (base_sum * discount_percent / 100)

        await state.update_data(total_sum=new_total, discount_percent=discount_percent)

        await message.answer(
            f"✅ {discount_percent}% chegirma qo'llanildi.\n\n"
            f"Asl summa: <s>{base_sum:,.0f}</s> so'm\n"
            f"Chegirmali summa: <b>{new_total:,.0f} so'm</b>\n\n"
            f"To'lov turini tanlang:",
            reply_markup=get_payment_keyboard(), parse_mode="HTML"
        )
        await state.set_state(BookingState.choosing_payment)
    except ValueError:
        await message.answer("❌ Noto'g'ri qiymat. Faqat raqam kiriting (masalan, 10):")

@router.callback_query(BookingState.choosing_payment, F.data.startswith("pay_"))
async def finish_booking(callback: CallbackQuery, state: FSMContext):
    payment_type = callback.data.split("_")[1]
    data = await state.get_data()
    end_date_obj = datetime.strptime(data['end_date'], "%d.%m.%Y").date()

    async with async_session() as session:
        await session.execute(
            update(Bed).where(Bed.id == data['bed_id']).values(
                is_occupied=True, 
                occupied_until=end_date_obj,
                guest_name=data.get('guest_name', 'Noma\'lum')
            )
        )
        new_transaction = Transaction(
            room_number=data['room_number'],
            bed_number=data['bed_number'],
            guest_name=data.get('guest_name', 'Noma\'lum'),
            amount=data['total_sum'],
            discount_percent=data.get('discount_percent', 0),
            payment_type=payment_type
        )
        session.add(new_transaction)
        await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        f"✅ <b>Muvaffaqiyatli saqlandi!</b>\n"
        f"👤 Mijoz: {data.get('guest_name', 'Noma\'lum')}\n"
        f"🚪 Xona: {data['room_number']} | 🛏 Joy: {data['bed_number']}\n"
        f"📅 Muddat: {data['end_date']} gacha\n"
        f"🎁 Chegirma: {data.get('discount_percent', 0)}%\n"
        f"💰 To'lov: {data['total_sum']:,.0f} so'm ({payment_type})",
        parse_mode="HTML", reply_markup=kb.get_main_menu()
    )
    await state.clear()

def get_report_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 To'lovlar (Excel)", callback_data="export_transactions")
    builder.button(text="📁 Mijozlar (Excel)", callback_data="export_beds")
    builder.adjust(2)
    return builder.as_markup()

@router.message(F.text == "📊 Kassa hisoboti")
async def show_cash_report(message: Message):
    today = datetime.now().date()

    start_of_today = datetime.combine(today, time.min)
    start_of_month = datetime(today.year, today.month, 1)

    async with async_session() as session:
        today_query = await session.execute(
            select(Transaction.payment_type, func.sum(Transaction.amount))
            .where(Transaction.created_at >= start_of_today)
            .group_by(Transaction.payment_type)
        )
        today_data = dict(today_query.all())  

        month_query = await session.execute(
            select(Transaction.payment_type, func.sum(Transaction.amount))
            .where(Transaction.created_at >= start_of_month)
            .group_by(Transaction.payment_type)
        )
        month_data = dict(month_query.all())

    def format_money(amount):
        return f"{amount:,.0f} so'm" if amount else "0 so'm"

    today_total = sum(today_data.values())
    month_total = sum(month_data.values())

    report_text = (
        f"📊 <b>KASSA HISOBOTI</b>\n\n"
        f"📅 <b>BUGUN ({today.strftime('%d.%m.%Y')}):</b>\n"
        f"💵 Naqd: {format_money(today_data.get('Naqd', 0))}\n"
        f"📱 E-pay: {format_money(today_data.get('E-pay', 0))}\n"
        f"💳 Karta: {format_money(today_data.get('Karta', 0))}\n"
        f"➖ ➖ ➖ ➖ ➖\n"
        f"💰 <b>Jami bugun: {format_money(today_total)}</b>\n\n\n"

        f"📆 <b>SHU OY ({today.strftime('%B, %Y')}):</b>\n"
        f"💵 Naqd: {format_money(month_data.get('Naqd', 0))}\n"
        f"📱 E-pay: {format_money(month_data.get('E-pay', 0))}\n"
        f"💳 Karta: {format_money(month_data.get('Karta', 0))}\n"
        f"➖ ➖ ➖ ➖ ➖\n"
        f"💰 <b>Jami oy: {format_money(month_total)}</b>\n\n"
        f"👇 <i>Quyidagi tugmalar orqali Excel hisobotni yuklab olishingiz mumkin:</i>"
    )

    await message.answer(report_text, parse_mode="HTML", reply_markup=get_report_keyboard())

@router.callback_query(F.data == "export_transactions")
async def export_transactions_excel(callback: CallbackQuery):
    await callback.answer("Fayl tayyorlanmoqda...", show_alert=False)
    
    async with async_session() as session:
        result = await session.execute(
            select(Transaction.id, Transaction.guest_name, Transaction.room_number, 
                   Transaction.bed_number, Transaction.amount, Transaction.discount_percent, 
                   Transaction.payment_type, Transaction.created_at).order_by(Transaction.id.desc())
        )
        transactions = result.all()
        
    if not transactions:
        await callback.message.answer("Bazada to'lovlar mavjud emas.")
        return

    data = []
    for t in transactions:
        data.append({
            "ID": t.id,
            "Mijoz Ismi": t.guest_name,
            "Xona": t.room_number,
            "Joy": t.bed_number,
            "To'lov summasi": f"{t.amount:,.0f}",
            "Chegirma (%)": t.discount_percent,
            "To'lov turi": t.payment_type,
            "Sana/Vaqt": t.created_at.strftime("%d.%m.%Y %H:%M")
        })
        
    df = pd.DataFrame(data)
    file_name = f"Tolovlar_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
    df.to_excel(file_name, index=False, sheet_name="To'lovlar")
    
    await callback.message.answer_document(FSInputFile(file_name))
    os.remove(file_name) 

@router.callback_query(F.data == "export_beds")
async def export_beds_excel(callback: CallbackQuery):
    await callback.answer("Fayl tayyorlanmoqda...", show_alert=False)
    
    async with async_session() as session:
        result = await session.execute(
            select(Bed, Room).join(Room).where(Bed.is_occupied == True).order_by(Room.room_number, Bed.bed_number)
        )
        occupied_beds = result.all()
        
    if not occupied_beds:
        await callback.message.answer("Hozirda hostelda yashayotgan mijozlar yo'q.")
        return

    data = []
    for bed, room in occupied_beds:
        data.append({
            "Mijoz Ismi": bed.guest_name,
            "Xona": room.room_number,
            "Joy raqami": bed.bed_number,
            "Tugash sanasi": bed.occupied_until.strftime("%d.%m.%Y"),
            "Kunlik narx": f"{bed.daily_price:,.0f}",
            "Oylik narx": f"{bed.monthly_price:,.0f}"
        })
        
    df = pd.DataFrame(data)
    file_name = f"Mijozlar_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
    df.to_excel(file_name, index=False, sheet_name="Band joylar")
    
    await callback.message.answer_document(FSInputFile(file_name))
    os.remove(file_name)

class ChannelState(StatesGroup):
    waiting_for_channel = State()

class PriceState(StatesGroup):
    choosing_capacity = State()
    entering_daily = State()
    entering_monthly = State()

@router.message(F.text.contains("Sozlamalar"))
async def settings_menu(message: Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Kanalga e'lon ulash", callback_data="setup_channel")
    builder.button(text="💵 Narxlarni o'zgartirish", callback_data="change_prices")
    builder.adjust(1)
    await message.answer("Sozlamalar bo'limi:", reply_markup=builder.as_markup())

@router.callback_query(F.data == "change_prices")
async def ask_price_capacity(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        rooms_result = await session.execute(select(Room))
        rooms = rooms_result.scalars().all()
        capacities = set()
        for r in rooms:
            beds_count = await session.execute(select(func.count(Bed.id)).where(Bed.room_id == r.id))
            capacities.add(beds_count.scalar())
    
    builder = InlineKeyboardBuilder()
    for cap in sorted(capacities):
        builder.button(text=f"{cap} kishilik", callback_data=f"editprice_{cap}")
    builder.adjust(2)
    await callback.message.edit_text("Qaysi xonalar turining narxini o'zgartiramiz?", reply_markup=builder.as_markup())
    await state.set_state(PriceState.choosing_capacity)

@router.callback_query(PriceState.choosing_capacity, F.data.startswith("editprice_"))
async def ask_daily_price(callback: CallbackQuery, state: FSMContext):
    capacity = int(callback.data.split("_")[1])
    await state.update_data(target_capacity=capacity)
    await callback.message.edit_text(f"📝 {capacity} kishilik xonalar uchun yangi KUNLIK narxni kiriting (faqat raqamda):\nMasalan: 45000")
    await state.set_state(PriceState.entering_daily)

@router.message(PriceState.entering_daily)
async def ask_monthly_price(message: Message, state: FSMContext):
    try:
        daily_price = float(message.text.strip())
        await state.update_data(new_daily=daily_price)
        
        data = await state.get_data()
        capacity = data['target_capacity']
        await message.answer(f"✅ Kunlik narx: {daily_price:,.0f} so'm\n\nEndi {capacity} kishilik xonalar uchun yangi OYLIK narxni kiriting:\nMasalan: 1000000")
        await state.set_state(PriceState.entering_monthly)
    except ValueError:
        await message.answer("❌ Noto'g'ri qiymat! Faqat raqam kiriting (masalan, 45000):")

@router.message(PriceState.entering_monthly)
async def save_new_prices(message: Message, state: FSMContext):
    try:
        monthly_price = float(message.text.strip())
        data = await state.get_data()
        daily_price = data['new_daily']
        capacity = data['target_capacity']
        
        async with async_session() as session:
            rooms_result = await session.execute(select(Room))
            rooms = rooms_result.scalars().all()
            
            rooms_to_update = []
            for r in rooms:
                bc = await session.execute(select(func.count(Bed.id)).where(Bed.room_id == r.id))
                if bc.scalar() == capacity:
                    rooms_to_update.append(r.id)
            
            if rooms_to_update:
                await session.execute(
                    update(Bed)
                    .where(Bed.room_id.in_(rooms_to_update))
                    .values(daily_price=daily_price, monthly_price=monthly_price)
                )
                await session.commit()
                
        await message.answer(f"✅ <b>Muvaffaqiyatli o'zgartirildi!</b>\n\n{capacity} kishilik xonalar uchun yangi narxlar:\nKunlik: {daily_price:,.0f} so'm\nOylik: {monthly_price:,.0f} so'm", parse_mode="HTML", reply_markup=kb.get_main_menu())
        await state.clear()
    except ValueError:
        await message.answer("❌ Noto'g'ri qiymat! Faqat raqam kiriting (masalan, 1000000):")

@router.callback_query(F.data == "setup_channel")
async def ask_channel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Botni kanalingiz yoki guruhingizga administrator sifatida qo'shing (xabar yozish, o'chirish va PIN qilish huquqlari bilan).\n\nKeyin guruhning @username sini (yoki IDsini) yuboring:\nMasalan: @bekhostel_group")
    await state.set_state(ChannelState.waiting_for_channel)

@router.message(ChannelState.waiting_for_channel)
async def set_channel(message: Message, state: FSMContext):
    channel_id = message.text.strip()
    from channel_helper import save_channel_info, get_vacant_beds_text
    
    async with async_session() as session:
        text = await get_vacant_beds_text(session)
        
    try:
        msg = await message.bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
        try:
            await message.bot.pin_chat_message(chat_id=channel_id, message_id=msg.message_id)
        except Exception:
            pass # Pin qilish huquqi bo'lmasa qotmasligi uchun
            
        save_channel_info(channel_id, msg.message_id)
        await message.answer("✅ E'lon guruh/kanalga joylandi, PIN qilindi va ulandi!\nEndi u har soatda avtomat eski xabarni o'chirib, yangisini yuborib pin qilib turadi.")
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi. Bot guruhda admin ekanligiga va xabar yozish huquqiga ega ekanligiga ishonch hosil qiling.\nXato: {e}\nQaytadan urinib ko'ring:")
