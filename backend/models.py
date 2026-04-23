from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey
from datetime import datetime
from database import Base
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    
    measurements = relationship("Measurement", back_populates="owner")

class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    filename = Column(String)
    page_num = Column(Integer)
    type = Column(String) # "distance" or "area"
    points = Column(JSON) # List of {x, y}
    result_text = Column(String)
    scale_label = Column(String)
    category_label = Column(String, nullable=True) # E.g., Bedroom, Bathroom, etc.
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="measurements")
