from pydantic import BaseModel, EmailStr
from typing import Optional

class UserIn(BaseModel):
    email: EmailStr
    password: str
    username: Optional[str] = None
    bankroll: Optional[float] = 0.0

class UserOut(BaseModel):
    id: str
    email: EmailStr
    username: Optional[str] = None
    bankroll: Optional[float] = 0.0

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
