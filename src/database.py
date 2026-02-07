from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    full_name = Column(String)
    farm_name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    photo_time = Column(String)
    voice_time = Column(String)
    landmark_count = Column(Integer)
    landmarks = relationship("Landmark", back_populates="owner")

class Landmark(Base):
    __tablename__ = 'landmarks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    label = Column(String)
    last_status = Column(String, default="Healthy")
    owner = relationship("User", back_populates="landmarks")
    entries = relationship("Entry", back_populates="landmark")

class Entry(Base):
    __tablename__ = 'entries'
    id = Column(Integer, primary_key=True, autoincrement=True)
    landmark_id = Column(Integer, ForeignKey('landmarks.id'))
    timestamp = Column(DateTime, default=datetime.utcnow)
    # Media
    img_wide = Column(String)
    img_close = Column(String)
    img_soil = Column(String)
    voice_path = Column(String)
    # Intelligence
    status = Column(String)
    weather_summary = Column(String)
    temp = Column(Float)
    humidity = Column(Integer)
    landmark = relationship("Landmark", back_populates="entries")

# --- SETUP ---
engine = create_engine('sqlite:///data/db/farm_diary.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# --- CRUD ---
def save_user_profile(data):
    session = Session()
    user = session.query(User).filter_by(id=data['id']).first()
    if not user:
        user = User(id=data['id'])
    
    user.full_name = data['name']
    user.farm_name = data['farm']
    user.latitude = data['lat']
    user.longitude = data['lon']
    user.photo_time = data['p_time']
    user.voice_time = data['v_time']
    user.landmark_count = data['l_count']
    
    session.merge(user)
    
    # Init Landmarks
    if session.query(Landmark).filter_by(user_id=data['id']).count() == 0:
        for i in range(1, data['l_count'] + 1):
            session.add(Landmark(user_id=data['id'], label=f"Spot {i}"))
            
    session.commit()
    session.close()

def get_user_profile(user_id):
    session = Session()
    user = session.query(User).filter_by(id=user_id).first()
    session.close()
    return user

def get_user_landmarks(user_id):
    session = Session()
    landmarks = session.query(Landmark).filter_by(user_id=user_id).all()
    session.close()
    return landmarks

def create_entry(user_id, landmark_id, images, status, weather_data):
    session = Session()
    
    entry = Entry(
        landmark_id=landmark_id,
        img_wide=images.get('wide'),
        img_close=images.get('close'),
        img_soil=images.get('soil'),
        status=status,
        weather_summary=weather_data.get('display_str', 'No Data'),
        temp=weather_data.get('temp'),
        humidity=weather_data.get('humidity')
    )
    
    lm = session.query(Landmark).filter_by(id=landmark_id).first()
    lm.last_status = status
    
    session.add(entry)
    session.commit()
    session.close()