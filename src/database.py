from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, date, timedelta
from collections import defaultdict

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

class EveningSummary(Base):
    """Track evening voice summaries separately"""
    __tablename__ = 'evening_summaries'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    date = Column(Date, default=date.today)
    voice_path = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

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
        voice_path=images.get('voice_path'),  # Add voice path support
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

def save_evening_summary(user_id, voice_path):
    """Save evening voice summary with date tracking"""
    session = Session()
    
    summary = EveningSummary(
        user_id=user_id,
        voice_path=voice_path,
        date=date.today()
    )
    
    session.add(summary)
    session.commit()
    session.close()

def get_all_users():
    """Fetches all users to restore schedules on startup."""
    session = Session()
    users = session.query(User).all()
    session.close()
    return users

# --- HISTORY QUERIES ---
def get_entries_by_date_range(user_id, start_date, end_date):
    """
    Get all entries for a user within a date range, grouped by date.
    Returns: dict with dates as keys and entry data as values
    """
    session = Session()
    
    # Get user's landmarks
    landmarks = session.query(Landmark).filter_by(user_id=user_id).all()
    landmark_ids = [lm.id for lm in landmarks]
    
    if not landmark_ids:
        session.close()
        return {}
    
    # Convert dates to datetime for comparison
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    
    # Query entries
    entries = session.query(Entry).filter(
        Entry.landmark_id.in_(landmark_ids),
        Entry.timestamp >= start_dt,
        Entry.timestamp <= end_dt
    ).order_by(Entry.timestamp.desc()).all()
    
    # Query evening summaries
    evening_summaries = session.query(EveningSummary).filter(
        EveningSummary.user_id == user_id,
        EveningSummary.date >= start_date,
        EveningSummary.date <= end_date
    ).all()
    
    # Group by date
    result = defaultdict(lambda: {'entries': [], 'has_evening_summary': False})
    
    for entry in entries:
        entry_date = entry.timestamp.date().strftime('%Y-%m-%d')
        result[entry_date]['entries'].append({
            'landmark_name': entry.landmark.label,
            'status': entry.status,
            'has_note': bool(entry.voice_path),
            'timestamp': entry.timestamp
        })
    
    for summary in evening_summaries:
        summary_date = summary.date.strftime('%Y-%m-%d')
        result[summary_date]['has_evening_summary'] = True
    
    session.close()
    return dict(result)

def get_entries_for_date(user_id, date_str):
    """
    Get all entries for a specific date with full details including file paths
    """
    session = Session()
    
    # Parse date
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date, datetime.max.time())
    
    # Get user's landmarks
    landmarks = session.query(Landmark).filter_by(user_id=user_id).all()
    landmark_ids = [lm.id for lm in landmarks]
    
    if not landmark_ids:
        session.close()
        return []
    
    # Query entries with eager loading of landmark relationship
    entries = session.query(Entry).filter(
        Entry.landmark_id.in_(landmark_ids),
        Entry.timestamp >= start_dt,
        Entry.timestamp <= end_dt
    ).all()
    
    # Don't close session yet - we need the relationships
    return entries

def get_daily_completion_stats(user_id, days=30):
    """
    Get completion statistics for the last N days
    Returns: dict with completion percentages and streaks
    """
    session = Session()
    
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        session.close()
        return None
    
    total_landmarks = user.landmark_count
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    entries_by_date = get_entries_by_date_range(user_id, start_date, end_date)
    
    stats = {
        'total_days': days,
        'days_with_entries': len(entries_by_date),
        'perfect_days': 0,  # Days with all landmarks + evening summary
        'current_streak': 0,
        'longest_streak': 0
    }
    
    # Calculate perfect days
    for date_str, data in entries_by_date.items():
        if len(data['entries']) == total_landmarks and data['has_evening_summary']:
            stats['perfect_days'] += 1
    
    # Calculate streaks
    current_streak = 0
    longest_streak = 0
    current_date = end_date
    
    for i in range(days):
        check_date = (current_date - timedelta(days=i)).strftime('%Y-%m-%d')
        if check_date in entries_by_date:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            if i == 0:  # Today has no entry, current streak is 0
                current_streak = 0
            else:
                break  # Current streak broken
    
    stats['current_streak'] = current_streak
    stats['longest_streak'] = longest_streak
    
    session.close()
    return stats