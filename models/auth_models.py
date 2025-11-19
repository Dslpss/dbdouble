from pydantic import BaseModel, EmailStr
from typing import Optional, List

class UserIn(BaseModel):
    email: EmailStr
    password: str
    username: Optional[str] = None
    bankroll: Optional[float] = 0.0
    # Alert preferences
    enabled_colors: Optional[List[str]] = ["red", "black", "white"]  # Colors to receive alerts for
    enabled_patterns: Optional[List[str]] = []  # Specific patterns (empty = all)
    receive_alerts: Optional[bool] = True  # Whether to receive alerts at all
    is_admin: Optional[bool] = False  # Admin access flag

class UserOut(BaseModel):
    id: str
    email: EmailStr
    username: Optional[str] = None
    bankroll: Optional[float] = 0.0
    # Alert preferences
    enabled_colors: Optional[List[str]] = ["red", "black", "white"]
    enabled_patterns: Optional[List[str]] = []
    receive_alerts: Optional[bool] = True
    is_admin: Optional[bool] = False

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
