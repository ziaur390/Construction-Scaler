from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey
from datetime import datetime
from database import Base

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
