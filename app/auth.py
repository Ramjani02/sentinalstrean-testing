from jose import jwt
from app.config import SECRET_KEY
from datetime import datetime, timedelta

ALGORITHM = "HS256"

def create_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(hours=1)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
