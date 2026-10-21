from aiogram.fsm.state import State, StatesGroup

class BookingState(StatesGroup):
    choosing_room = State()
    choosing_bed = State()
    entering_name = State()
    entering_date = State()
    choosing_payment = State()
    entering_discount = State()  # Chegirma foizini kiritish uchun
    extending_date = State()  # Uzaytirish sanasini kiritish uchun