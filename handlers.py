import os
import re
from datetime import datetime, time, timedelta
from html import escape

import pandas as pd
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload

import keyboards as kb
from core.database import async_session
from models.models import Room, Bed, Transaction
from states import BookingState


router = Router()

ADMIN_PASSWORD = "bekhostel26"


def normalize_phone(value):
    if not value:
        return None

    phone = re.sub(r"[\s()\-]", "", value)

    if re.fullmatch(r"[0-9]{9}", phone):
        phone = "+998" + phone
    elif re.fullmatch(r"998[0-9]{9}", phone):
        phone = "+" + phone

    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        return None

    return phone


def format_room_summary(rooms):
    total = sum(len(room.beds) for room in rooms)
    occupied = sum(
        bool(bed.is_occupied)
        for room in rooms
        for bed in room.beds
    )

    lines = [
        "🛏 Joylar holati",
        (
            f"Jami: {total} ta | 🔴 Band: {occupied} ta | "
            f"🟢 Bo'sh: {total - occupied} ta"
        ),
        "",
    ]

    for room in rooms:
        count = len(room.beds)
        busy = sum(bool(bed.is_occupied) for bed in room.beds)

        lines.append(
            f"🚪 {room.room_number}-xona: "
            f"jami {count} | 🔴 {busy} | 🟢 {count - busy}"
        )

    if not rooms:
        lines.append("Hozircha xonalar mavjud emas.")
    else:
        lines.extend(["", "Qaysi xonani ko'rmoqchisiz?"])

    return "\n".join(lines)


class Auth(StatesGroup):
    waiting_for_password = State()


class ChannelState(StatesGroup):
    waiting_for_channel = State()


class PriceState(StatesGroup):
    choosing_capacity = State()
    entering_daily = State()
    entering_monthly = State()


# KIRISH

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🔒 Xush kelibsiz!\n"
        "Iltimos, botdan foydalanish uchun kirish parolini kiriting:"
    )
    await state.set_state(Auth.waiting_for_password)


@router.message(Auth.waiting_for_password)
async def check_password(message: Message, state: FSMContext):
    if (message.text or "").strip() == ADMIN_PASSWORD:
        await message.answer(
            "✅ Parol qabul qilindi. Tizimga xush kelibsiz!",
            reply_markup=kb.get_main_menu(),
        )
        await state.clear()
    else:
        await message.answer(
            "❌ Noto'g'ri parol! Qaytadan urinib ko'ring:"
        )


# XONALAR VA JOYLAR

@router.message(F.text == "🛏 Joy band qilish / Holat")
async def show_rooms(message: Message, state: FSMContext):
    await state.clear()

    async with async_session() as session:
        result = await session.execute(
            select(Room)
            .options(selectinload(Room.beds))
            .order_by(Room.room_number)
        )
        rooms = result.scalars().all()

    await message.answer(
        format_room_summary(rooms),
        reply_markup=kb.get_rooms_keyboard(rooms),
    )
    await state.set_state(BookingState.choosing_room)


@router.callback_query(
    BookingState.choosing_room,
    F.data.startswith("room_"),
)
async def room_selected(callback: CallbackQuery, state: FSMContext):
    room_id = int(callback.data.split("_")[1])
    await state.update_data(room_id=room_id)

    async with async_session() as session:
        room_result = await session.execute(
            select(Room).where(Room.id == room_id)
        )
        room = room_result.scalar_one()

        bed_result = await session.execute(
            select(Bed)
            .where(Bed.room_id == room_id)
            .order_by(Bed.bed_number)
        )
        beds = bed_result.scalars().all()

    occupied = sum(bool(bed.is_occupied) for bed in beds)

    await callback.message.edit_text(
        f"🚪 <b>{room.room_number}-xona.</b>\n"
        f"Jami: {len(beds)} | 🔴 Band: {occupied} | "
        f"🟢 Bo'sh: {len(beds) - occupied}\n"
        f"Qaysi joyni tanlaysiz?",
        reply_markup=kb.get_beds_keyboard(beds),
        parse_mode="HTML",
    )
    await state.set_state(BookingState.choosing_bed)


@router.callback_query(
    BookingState.choosing_bed,
    F.data == "back_to_rooms",
)
async def back_to_rooms_handler(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.message.delete()
    await show_rooms(callback.message, state)


@router.callback_query(
    BookingState.choosing_bed,
    F.data.startswith("bed_"),
)
async def bed_selected(callback: CallbackQuery, state: FSMContext):
    bed_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        bed = await session.get(Bed, bed_id)
        room = await session.get(Room, bed.room_id)

        await state.update_data(
            bed_id=bed_id,
            room_number=room.room_number,
            bed_number=bed.bed_number,
            daily_price=bed.daily_price,
            monthly_price=bed.monthly_price,
            discount_percent=0,
        )

        if bed.is_occupied:
            old_date = (
                bed.occupied_until.strftime("%d.%m.%Y")
                if bed.occupied_until
                else None
            )

            await state.update_data(
                old_date=old_date,
                guest_name=bed.guest_name,
                guest_phone=bed.guest_phone,
            )

            builder = InlineKeyboardBuilder()
            builder.button(
                text="➕ Uzaytirish",
                callback_data=f"extend_{bed.id}",
            )
            builder.button(
                text="🛑 Bo'shatish",
                callback_data=f"release_{bed.id}",
            )
            builder.button(
                text="🔙 Orqaga",
                callback_data="back_to_rooms",
            )
            builder.adjust(2, 1)

            await callback.message.edit_text(
                f"⚠️ <b>{room.room_number}-xona, "
                f"{bed.bed_number}-joy</b> BAND.\n"
                f"📅 Tugash sanasi: "
                f"<b>{old_date or 'Sana kiritilmagan'}</b>\n"
                f"👤 Mijoz: "
                f"<b>{escape(bed.guest_name or 'Kiritilmagan')}</b>\n"
                f"📞 Telefon: "
                f"<b>{escape(bed.guest_phone or 'Kiritilmagan')}</b>\n\n"
                f"Nima amal bajarasiz?",
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )
            return

    await callback.message.delete()
    await callback.message.answer(
        f"✅ {room.room_number}-xona, {bed.bed_number}-joy.\n\n"
        f"👤 <b>Mijozning Ism-Familiyasini kiriting:</b>\n"
        f"(Masalan: Alisher Valiyev)",
        parse_mode="HTML",
    )
    await state.set_state(BookingState.entering_name)


# MIJOZ ISMI VA TELEFONI

@router.message(BookingState.entering_name)
async def process_name(message: Message, state: FSMContext):
    guest_name = (message.text or "").strip()

    if not guest_name:
        await message.answer(
            "❌ Mijozning ism-familiyasini matn bilan kiriting:"
        )
        return

    await state.update_data(guest_name=guest_name)

    await message.answer(
        "📞 Mijozning telefon raqamini kiriting:\n"
        "Masalan: +998901234567 yoki 901234567"
    )
    await state.set_state(BookingState.entering_phone)


@router.message(BookingState.entering_phone)
async def process_phone(message: Message, state: FSMContext):
    raw_phone = (
        message.contact.phone_number
        if message.contact
        else message.text
    )
    guest_phone = normalize_phone(raw_phone)

    if guest_phone is None:
        await message.answer(
            "❌ Telefon raqamini to'g'ri kiriting.\n"
            "Masalan: +998901234567 yoki 901234567"
        )
        return

    await state.update_data(guest_phone=guest_phone)

    data = await state.get_data()
    monthly_price = data["monthly_price"]

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🗓 1 oy ({monthly_price:,.0f} so'm)",
        callback_data="tariff_1_month",
    )

    await message.answer(
        f"👤 Mijoz: {escape(data['guest_name'])}\n"
        f"📞 Telefon: {guest_phone}\n\n"
        f"📅 Qaysi sanagacha turadi?\n"
        f"(Qo'lda DD.MM.YYYY yozing yoki pastdagi tarifni tanlang)\n"
        f"Masalan: 30.11.2026",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(BookingState.entering_date)


# SANA VA TO'LOV

def get_payment_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(text="💵 Naqd", callback_data="pay_Naqd")
    builder.button(text="📱 E-pay", callback_data="pay_E-pay")
    builder.button(text="💳 Karta", callback_data="pay_Karta")
    builder.button(
        text="🎁 Chegirma kiritish",
        callback_data="add_discount",
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data="cancel_booking",
        )
    )
    builder.adjust(3, 1, 1)
    return builder.as_markup()


@router.callback_query(
    BookingState.entering_date,
    F.data == "tariff_1_month",
)
async def process_1_month_tariff(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    today = datetime.now().date()

    end_date = today + timedelta(days=30)
    total_sum = data["monthly_price"]
    guest_name = escape(data.get("guest_name") or "Noma'lum")

    await state.update_data(
        end_date=end_date.strftime("%d.%m.%Y"),
        total_sum=total_sum,
        base_sum=total_sum,
    )

    await callback.message.delete()
    await callback.message.answer(
        f"👤 Mijoz: <b>{guest_name}</b>\n"
        f"📅 Kunlar: <b>30 kun</b> (1 oy)\n"
        f"💰 Jami summa: <b>{total_sum:,.0f} so'm</b>\n\n"
        f"To'lov turini tanlang yoki chegirma kiriting:",
        reply_markup=get_payment_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(BookingState.choosing_payment)


@router.message(BookingState.entering_date)
async def process_date(message: Message, state: FSMContext):
    date_text = (message.text or "").strip()

    try:
        end_date = datetime.strptime(date_text, "%d.%m.%Y").date()
        today = datetime.now().date()

        if end_date <= today:
            await message.answer(
                "❌ Sana bugungi kundan keyin bo'lishi kerak. "
                "Qaytadan kiriting:"
            )
            return

        days_count = (end_date - today).days
        data = await state.get_data()

        months = days_count // 30
        remaining_days = days_count % 30

        total_sum = (
            months * data["monthly_price"]
            + remaining_days * data["daily_price"]
        )

        await state.update_data(
            end_date=end_date.strftime("%d.%m.%Y"),
            total_sum=total_sum,
            base_sum=total_sum,
        )

        guest_name = escape(data.get("guest_name") or "Noma'lum")

        await message.answer(
            f"👤 Mijoz: <b>{guest_name}</b>\n"
            f"📅 Kunlar: <b>{days_count} kun</b>\n"
            f"💰 Jami summa: <b>{total_sum:,.0f} so'm</b>\n\n"
            f"To'lov turini tanlang yoki chegirma kiriting:",
            reply_markup=get_payment_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(BookingState.choosing_payment)

    except ValueError:
        await message.answer(
            "❌ Xato! Sanani DD.MM.YYYY formatida yozing:"
        )


@router.callback_query(F.data == "cancel_booking")
async def cancel_booking(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "❌ Amaliyot bekor qilindi.",
        reply_markup=kb.get_main_menu(),
    )


# JOYNI BO'SHATISH

@router.callback_query(F.data.startswith("release_"))
async def release_bed(callback: CallbackQuery, state: FSMContext):
    bed_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        bed = await session.get(Bed, bed_id)
        room = await session.get(Room, bed.room_id)

        tx_query = await session.execute(
            select(Transaction)
            .where(
                Transaction.room_number == room.room_number,
                Transaction.bed_number == bed.bed_number,
                Transaction.amount > 0,
            )
            .order_by(Transaction.id.desc())
            .limit(1)
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

            actual_cost = (
                months * bed.monthly_price
                + remaining_days * bed.daily_price
            )

            if last_tx.discount_percent > 0:
                actual_cost -= (
                    actual_cost * last_tx.discount_percent / 100
                )

            refund_amount = last_tx.amount - actual_cost

            if refund_amount > 0:
                await state.update_data(
                    release_bed_id=bed.id,
                    refund_amount=refund_amount,
                    room_number=room.room_number,
                    bed_number=bed.bed_number,
                    guest_name=bed.guest_name,
                    payment_type=last_tx.payment_type,
                )

                builder = InlineKeyboardBuilder()
                builder.button(
                    text="✅ Ha, pulni qaytarish va bo'shatish",
                    callback_data="confirm_early_release",
                )
                builder.button(
                    text="❌ Bekor qilish",
                    callback_data="cancel_booking",
                )
                builder.adjust(1)

                await callback.message.edit_text(
                    f"⚠️ <b>Mijoz muddatidan oldin chiqib ketyapti!</b>\n\n"
                    f"👤 Mijoz: {escape(bed.guest_name or 'Kiritilmagan')}\n"
                    f"📅 Yashagan kunlari: <b>{days_stayed} kun</b> "
                    f"(To'lagan: {last_tx.created_at.strftime('%d.%m.%Y')})\n"
                    f"💰 Asl to'lagan summasi: {last_tx.amount:,.0f} so'm\n"
                    f"📉 Yashagan kuniga summa: {actual_cost:,.0f} so'm\n\n"
                    f"💵 <b>Kassadan qaytariladigan summa: "
                    f"{refund_amount:,.0f} so'm</b>\n\n"
                    f"Tasdiqlaysizmi? (Bu summa kassadan minus qilinadi)",
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML",
                )
                return

        bed.is_occupied = False
        bed.occupied_until = None
        bed.guest_name = None
        bed.guest_phone = None

        await session.commit()

    await callback.message.edit_text(
        "✅ Joy muvaffaqiyatli bo'shatildi!",
        reply_markup=None,
    )
    await callback.message.answer(
        "Bosh menyu:",
        reply_markup=kb.get_main_menu(),
    )
    await state.clear()


@router.callback_query(F.data == "confirm_early_release")
async def confirm_early_release(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()

    async with async_session() as session:
        bed = await session.get(Bed, data["release_bed_id"])

        if bed:
            bed.is_occupied = False
            bed.occupied_until = None
            bed.guest_name = None
            bed.guest_phone = None

        guest_name = data.get("guest_name") or "Noma'lum"

        new_tx = Transaction(
            room_number=data["room_number"],
            bed_number=data["bed_number"],
            guest_name=f"{guest_name} (Qaytarildi)",
            amount=-data["refund_amount"],
            discount_percent=0,
            payment_type=data["payment_type"],
        )
        session.add(new_tx)
        await session.commit()

    await callback.message.edit_text(
        f"✅ <b>Joy bo'shatildi va pul hisob-kitob qilindi!</b>\n\n"
        f"Qaytarilgan summa: "
        f"<b>{data['refund_amount']:,.0f} so'm</b> "
        f"({data['payment_type']})\n"
        f"Kassadan ayirib tashlandi.",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Bosh menyu:",
        reply_markup=kb.get_main_menu(),
    )
    await state.clear()


# MUDDATNI UZAYTIRISH

# Faqat extend_1, extend_2 kabi joy IDlarini ushlaydi.
# extend_1_month tugmasini pastdagi alohida handler qabul qiladi.
@router.callback_query(F.data.regexp(r"^extend_\d+$"))
async def ask_extend_date(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()

    if not data.get("old_date"):
        await callback.answer(
            "Bu band joyning tugash sanasi bazada yo'q. "
            "Uzaytirishdan oldin asl sanani tiklash kerak.",
            show_alert=True,
        )
        return

    monthly_price = data["monthly_price"]

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🗓 +1 oy uzaytirish ({monthly_price:,.0f} so'm)",
        callback_data="extend_1_month",
    )

    await callback.message.edit_text(
        f"📅 Joriy tugash sanasi: <b>{data['old_date']}</b>\n\n"
        f"Mijoz qaysi sanagacha uzaytirmoqchi?\n"
        f"(Qo'lda yozing yoki +1 oylik tarifni tanlang)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(BookingState.extending_date)


@router.callback_query(
    BookingState.extending_date,
    F.data == "extend_1_month",
)
async def process_extend_1_month(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    old_end_date = datetime.strptime(
        data["old_date"],
        "%d.%m.%Y",
    ).date()

    new_end_date = old_end_date + timedelta(days=30)
    total_sum = data["monthly_price"]

    await state.update_data(
        end_date=new_end_date.strftime("%d.%m.%Y"),
        total_sum=total_sum,
        base_sum=total_sum,
    )

    await callback.message.delete()
    await callback.message.answer(
        f"📈 <b>Uzaytirish hisobi:</b>\n\n"
        f"Qo'shilgan kunlar: <b>30 kun</b> (1 oy)\n"
        f"Qo'shimcha summa: <b>{total_sum:,.0f} so'm</b>\n\n"
        f"To'lov turini tanlang yoki chegirma kiriting:",
        reply_markup=get_payment_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(BookingState.choosing_payment)


@router.message(BookingState.extending_date)
async def process_extend_date(message: Message, state: FSMContext):
    date_text = (message.text or "").strip()

    try:
        new_end_date = datetime.strptime(
            date_text,
            "%d.%m.%Y",
        ).date()

        data = await state.get_data()
        old_end_date = datetime.strptime(
            data["old_date"],
            "%d.%m.%Y",
        ).date()

        if new_end_date <= old_end_date:
            await message.answer(
                f"❌ Sana joriy tugash sanasidan "
                f"({data['old_date']}) keyin bo'lishi kerak!"
            )
            return

        days_count = (new_end_date - old_end_date).days
        months = days_count // 30
        remaining_days = days_count % 30

        total_sum = (
            months * data["monthly_price"]
            + remaining_days * data["daily_price"]
        )

        await state.update_data(
            end_date=new_end_date.strftime("%d.%m.%Y"),
            total_sum=total_sum,
            base_sum=total_sum,
        )

        await message.answer(
            f"Uzaytirish hisobi:\n\n"
            f"Qo'shilgan kunlar: <b>{days_count} kun</b>\n"
            f"Qo'shimcha summa: <b>{total_sum:,.0f} so'm</b>\n\n"
            f"To'lov turini tanlang yoki chegirma kiriting:",
            reply_markup=get_payment_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(BookingState.choosing_payment)

    except ValueError:
        await message.answer(
            "❌ Xato! Sanani DD.MM.YYYY formatida yozing:"
        )


# CHEGIRMA

@router.callback_query(
    BookingState.choosing_payment,
    F.data == "add_discount",
)
async def ask_discount(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer(
        "🎁 Chegirma foizini kiriting (Masalan, 10 yoki 15):"
    )
    await state.set_state(BookingState.entering_discount)


@router.message(BookingState.entering_discount)
async def process_discount(message: Message, state: FSMContext):
    try:
        discount_percent = float((message.text or "").strip())

        if discount_percent < 0 or discount_percent > 100:
            raise ValueError

        data = await state.get_data()
        base_sum = data["base_sum"]
        new_total = base_sum - (base_sum * discount_percent / 100)

        await state.update_data(
            total_sum=new_total,
            discount_percent=discount_percent,
        )

        await message.answer(
            f"✅ {discount_percent}% chegirma qo'llanildi.\n\n"
            f"Asl summa: <s>{base_sum:,.0f}</s> so'm\n"
            f"Chegirmali summa: <b>{new_total:,.0f} so'm</b>\n\n"
            f"To'lov turini tanlang:",
            reply_markup=get_payment_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(BookingState.choosing_payment)

    except ValueError:
        await message.answer(
            "❌ Noto'g'ri qiymat. Faqat raqam kiriting "
            "(masalan, 10):"
        )


# BAND QILISH YOKI UZAYTIRISHNI SAQLASH

@router.callback_query(
    BookingState.choosing_payment,
    F.data.startswith("pay_"),
)
async def finish_booking(callback: CallbackQuery, state: FSMContext):
    payment_type = callback.data.split("_")[1]
    data = await state.get_data()

    end_date_obj = datetime.strptime(
        data["end_date"],
        "%d.%m.%Y",
    ).date()

    guest_name = data.get("guest_name") or "Noma'lum"
    guest_phone = data.get("guest_phone")

    async with async_session() as session:
        await session.execute(
            update(Bed)
            .where(Bed.id == data["bed_id"])
            .values(
                is_occupied=True,
                occupied_until=end_date_obj,
                guest_name=guest_name,
                guest_phone=guest_phone,
            )
        )

        new_transaction = Transaction(
            room_number=data["room_number"],
            bed_number=data["bed_number"],
            guest_name=guest_name,
            amount=data["total_sum"],
            discount_percent=data.get("discount_percent", 0),
            payment_type=payment_type,
        )
        session.add(new_transaction)
        await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        f"✅ <b>Muvaffaqiyatli saqlandi!</b>\n"
        f"👤 Mijoz: {escape(guest_name)}\n"
        f"📞 Telefon: {escape(guest_phone or 'Kiritilmagan')}\n"
        f"🚪 Xona: {data['room_number']} | "
        f"🛏 Joy: {data['bed_number']}\n"
        f"📅 Muddat: {data['end_date']} gacha\n"
        f"🎁 Chegirma: {data.get('discount_percent', 0)}%\n"
        f"💰 To'lov: {data['total_sum']:,.0f} so'm ({payment_type})",
        parse_mode="HTML",
        reply_markup=kb.get_main_menu(),
    )
    await state.clear()


# KASSA HISOBOTI

def get_report_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📁 To'lovlar (Excel)",
        callback_data="export_transactions",
    )
    builder.button(
        text="📁 Mijozlar (Excel)",
        callback_data="export_beds",
    )
    builder.adjust(2)
    return builder.as_markup()


@router.message(F.text == "📊 Kassa hisoboti")
async def show_cash_report(message: Message):
    today = datetime.now().date()
    start_of_today = datetime.combine(today, time.min)
    start_of_month = datetime(today.year, today.month, 1)

    async with async_session() as session:
        today_query = await session.execute(
            select(
                Transaction.payment_type,
                func.sum(Transaction.amount),
            )
            .where(Transaction.created_at >= start_of_today)
            .group_by(Transaction.payment_type)
        )
        today_data = dict(today_query.all())

        month_query = await session.execute(
            select(
                Transaction.payment_type,
                func.sum(Transaction.amount),
            )
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
        f"👇 <i>Quyidagi tugmalar orqali Excel hisobotni "
        f"yuklab olishingiz mumkin:</i>"
    )

    await message.answer(
        report_text,
        parse_mode="HTML",
        reply_markup=get_report_keyboard(),
    )


# TO'LOVLAR EXCEL — TELEFON QO'SHILMAGAN

@router.callback_query(F.data == "export_transactions")
async def export_transactions_excel(callback: CallbackQuery):
    await callback.answer(
        "Fayl tayyorlanmoqda...",
        show_alert=False,
    )

    async with async_session() as session:
        result = await session.execute(
            select(
                Transaction.id,
                Transaction.guest_name,
                Transaction.room_number,
                Transaction.bed_number,
                Transaction.amount,
                Transaction.discount_percent,
                Transaction.payment_type,
                Transaction.created_at,
            ).order_by(Transaction.id.desc())
        )
        transactions = result.all()

    if not transactions:
        await callback.message.answer(
            "Bazada to'lovlar mavjud emas."
        )
        return

    data = []

    for transaction in transactions:
        data.append({
            "ID": transaction.id,
            "Mijoz Ismi": transaction.guest_name,
            "Xona": transaction.room_number,
            "Joy": transaction.bed_number,
            "To'lov summasi": f"{transaction.amount:,.0f}",
            "Chegirma (%)": transaction.discount_percent,
            "To'lov turi": transaction.payment_type,
            "Sana/Vaqt": transaction.created_at.strftime(
                "%d.%m.%Y %H:%M"
            ),
        })

    df = pd.DataFrame(data)
    file_name = (
        f"Tolovlar_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
    )
    df.to_excel(file_name, index=False, sheet_name="To'lovlar")

    await callback.message.answer_document(FSInputFile(file_name))
    os.remove(file_name)


# MIJOZLAR EXCEL — TELEFON QO'SHILGAN

@router.callback_query(F.data == "export_beds")
async def export_beds_excel(callback: CallbackQuery):
    await callback.answer(
        "Fayl tayyorlanmoqda...",
        show_alert=False,
    )

    async with async_session() as session:
        result = await session.execute(
            select(Bed, Room)
            .join(Room)
            .where(Bed.is_occupied == True)
            .order_by(Room.room_number, Bed.bed_number)
        )
        occupied_beds = result.all()

    if not occupied_beds:
        await callback.message.answer(
            "Hozirda hostelda yashayotgan mijozlar yo'q."
        )
        return

    data = []

    for bed, room in occupied_beds:
        data.append({
            "Mijoz Ismi": bed.guest_name,
            "Telefon raqami": bed.guest_phone or "Kiritilmagan",
            "Xona": room.room_number,
            "Joy raqami": bed.bed_number,
            "Tugash sanasi": (
                bed.occupied_until.strftime("%d.%m.%Y")
                if bed.occupied_until
                else "Kiritilmagan"
            ),
            "Kunlik narx": f"{bed.daily_price:,.0f}",
            "Oylik narx": f"{bed.monthly_price:,.0f}",
        })

    df = pd.DataFrame(data)
    file_name = (
        f"Mijozlar_{datetime.now().strftime('%d_%m_%Y')}.xlsx"
    )
    df.to_excel(file_name, index=False, sheet_name="Band joylar")

    await callback.message.answer_document(FSInputFile(file_name))
    os.remove(file_name)


# SOZLAMALAR

@router.message(F.text.contains("Sozlamalar"))
async def settings_menu(message: Message, state: FSMContext):
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(
        text="📢 Kanalga e'lon ulash",
        callback_data="setup_channel",
    )
    builder.button(
        text="💵 Narxlarni o'zgartirish",
        callback_data="change_prices",
    )
    builder.adjust(1)

    await message.answer(
        "Sozlamalar bo'limi:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "change_prices")
async def ask_price_capacity(
    callback: CallbackQuery,
    state: FSMContext,
):
    async with async_session() as session:
        rooms_result = await session.execute(select(Room))
        rooms = rooms_result.scalars().all()
        capacities = set()

        for room in rooms:
            beds_count = await session.execute(
                select(func.count(Bed.id))
                .where(Bed.room_id == room.id)
            )
            capacities.add(beds_count.scalar())

    builder = InlineKeyboardBuilder()

    for capacity in sorted(capacities):
        builder.button(
            text=f"{capacity} kishilik",
            callback_data=f"editprice_{capacity}",
        )

    builder.adjust(2)

    await callback.message.edit_text(
        "Qaysi xonalar turining narxini o'zgartiramiz?",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(PriceState.choosing_capacity)


@router.callback_query(
    PriceState.choosing_capacity,
    F.data.startswith("editprice_"),
)
async def ask_daily_price(
    callback: CallbackQuery,
    state: FSMContext,
):
    capacity = int(callback.data.split("_")[1])
    await state.update_data(target_capacity=capacity)

    await callback.message.edit_text(
        f"📝 {capacity} kishilik xonalar uchun yangi KUNLIK "
        f"narxni kiriting (faqat raqamda):\n"
        f"Masalan: 45000"
    )
    await state.set_state(PriceState.entering_daily)


@router.message(PriceState.entering_daily)
async def ask_monthly_price(message: Message, state: FSMContext):
    try:
        daily_price = float((message.text or "").strip())
        await state.update_data(new_daily=daily_price)

        data = await state.get_data()
        capacity = data["target_capacity"]

        await message.answer(
            f"✅ Kunlik narx: {daily_price:,.0f} so'm\n\n"
            f"Endi {capacity} kishilik xonalar uchun yangi "
            f"OYLIK narxni kiriting:\n"
            f"Masalan: 1000000"
        )
        await state.set_state(PriceState.entering_monthly)

    except ValueError:
        await message.answer(
            "❌ Noto'g'ri qiymat! Faqat raqam kiriting "
            "(masalan, 45000):"
        )


@router.message(PriceState.entering_monthly)
async def save_new_prices(message: Message, state: FSMContext):
    try:
        monthly_price = float((message.text or "").strip())
        data = await state.get_data()

        daily_price = data["new_daily"]
        capacity = data["target_capacity"]

        async with async_session() as session:
            rooms_result = await session.execute(select(Room))
            rooms = rooms_result.scalars().all()

            rooms_to_update = []

            for room in rooms:
                beds_count = await session.execute(
                    select(func.count(Bed.id))
                    .where(Bed.room_id == room.id)
                )

                if beds_count.scalar() == capacity:
                    rooms_to_update.append(room.id)

            if rooms_to_update:
                await session.execute(
                    update(Bed)
                    .where(Bed.room_id.in_(rooms_to_update))
                    .values(
                        daily_price=daily_price,
                        monthly_price=monthly_price,
                    )
                )
                await session.commit()

        await message.answer(
            f"✅ <b>Muvaffaqiyatli o'zgartirildi!</b>\n\n"
            f"{capacity} kishilik xonalar uchun yangi narxlar:\n"
            f"Kunlik: {daily_price:,.0f} so'm\n"
            f"Oylik: {monthly_price:,.0f} so'm",
            parse_mode="HTML",
            reply_markup=kb.get_main_menu(),
        )
        await state.clear()

    except ValueError:
        await message.answer(
            "❌ Noto'g'ri qiymat! Faqat raqam kiriting "
            "(masalan, 1000000):"
        )


# KANAL SOZLAMALARI

@router.callback_query(F.data == "setup_channel")
async def ask_channel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Botni kanalingiz yoki guruhingizga administrator "
        "sifatida qo'shing "
        "(xabar yozish, o'chirish va PIN qilish huquqlari bilan).\n\n"
        "Keyin guruhning @username sini (yoki IDsini) yuboring:\n"
        "Masalan: @bekhostel_group"
    )
    await state.set_state(ChannelState.waiting_for_channel)


@router.message(ChannelState.waiting_for_channel)
async def set_channel(message: Message, state: FSMContext):
    from channel_helper import (
        save_channel_info,
        get_vacant_beds_text,
    )

    channel_id = (message.text or "").strip()

    async with async_session() as session:
        text = await get_vacant_beds_text(session)

    try:
        msg = await message.bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode="HTML",
        )

        try:
            await message.bot.pin_chat_message(
                chat_id=channel_id,
                message_id=msg.message_id,
            )
        except Exception:
            pass

        save_channel_info(channel_id, msg.message_id)

        await message.answer(
            "✅ E'lon guruh/kanalga joylandi, PIN qilindi va ulandi!\n"
            "Endi u har soatda avtomat eski xabarni o'chirib, "
            "yangisini yuborib pin qilib turadi."
        )
        await state.clear()

    except Exception as error:
        await message.answer(
            "❌ Xatolik yuz berdi. Bot guruhda admin ekanligiga "
            "va xabar yozish huquqiga ega ekanligiga "
            "ishonch hosil qiling.\n"
            f"Xato: {error}\n"
            "Qaytadan urinib ko'ring:"
        )