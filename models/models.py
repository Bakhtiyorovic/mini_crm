from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Float
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class Room(Base):
    __tablename__ = 'rooms'

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_number = Column(Integer, unique=True, nullable=False)

    beds = relationship("Bed", back_populates="room", cascade="all, delete-orphan")


class Bed(Base):
    __tablename__ = 'beds'

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey('rooms.id'))
    bed_number = Column(Integer, nullable=False)
    daily_price = Column(Float, nullable=False)
    monthly_price = Column(Float, nullable=False)
    guest_name = Column(String, nullable=True)

    is_occupied = Column(Boolean, default=False)
    occupied_until = Column(Date, nullable=True)

    room = relationship("Room", back_populates="beds")


class Transaction(Base):
    __tablename__ = 'transactions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_number = Column(Integer)
    bed_number = Column(Integer)
    guest_name = Column(String, nullable=True)

    amount = Column(Float, nullable=False)
    discount_percent = Column(Float, default=0.0)
    payment_type = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.now)