from fastapi import APIRouter, HTTPException, status, Depends, Response, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from datetime import datetime, timedelta
from typing import Optional
from pymongo import ReturnDocument
import db as db_module
from models.auth_models import UserIn, UserOut, Token
from auth_utils import get_password_hash, verify_password
from jwt_utils import create_access_token, decode_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_token_from_request(request: Request) -> Optional[str]:
    """Get token from Authorization header or cookie"""
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix

    # Try cookie
    token = request.cookies.get("access_token")
    if token:
        return token

    return None


@router.post("/register", response_model=UserOut)
async def register(user: UserIn):
    existing = await db_module.db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email já cadastrado")
    hashed = get_password_hash(user.password)
    
    # Check if this is the admin email
    is_admin = user.email == "dennisemannuel93@gmail.com"
    
    doc = {
        "email": user.email,
        "username": user.username,
        "password_hash": hashed,
        "bankroll": float(user.bankroll or 0.0),
        "enabled_colors": user.enabled_colors or ["red", "black", "white"],
        "enabled_patterns": user.enabled_patterns or [],
        "receive_alerts": user.receive_alerts if user.receive_alerts is not None else True,
        "is_admin": is_admin,
        "created_at": datetime.utcnow(),
    }
    res = await db_module.db.users.insert_one(doc)
    return UserOut(
        id=str(res.inserted_id), 
        email=user.email, 
        username=user.username, 
        bankroll=doc["bankroll"],
        enabled_colors=doc["enabled_colors"],
        enabled_patterns=doc["enabled_patterns"],
        receive_alerts=doc["receive_alerts"],
        is_admin=doc["is_admin"]
    )


@router.post("/login", response_model=Token)
async def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    # OAuth2PasswordRequestForm uses username as field; pass email in username
    user = await db_module.db.users.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    token = create_access_token({"sub": user["email"]})
    # Set cookie for session persistence
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,  # Prevent JavaScript access
        max_age=3600,   # 1 hour
        expires=3600,
        secure=False,   # Set to True in production with HTTPS
        samesite="lax"
    )
    return Token(access_token=token, token_type="bearer")


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logout realizado com sucesso"}


async def get_current_user(request: Request):
    token = await get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token não encontrado")
    try:
        payload = decode_access_token(token)
        email: Optional[str] = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = await db_module.db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")
    return user

async def get_admin_user(current_user: dict = Depends(get_current_user)):
    """Dependency to ensure user is admin"""
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado - apenas administradores")
    return current_user

@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {
        "email": current_user["email"], 
        "username": current_user.get("username"), 
        "bankroll": current_user.get("bankroll", 0),
        "enabled_colors": current_user.get("enabled_colors", ["red", "black", "white"]),
        "enabled_patterns": current_user.get("enabled_patterns", []),
        "receive_alerts": current_user.get("receive_alerts", True),
        "is_admin": current_user.get("is_admin", False)
    }


@router.get("/user/bankroll")
async def get_bankroll(current_user: dict = Depends(get_current_user)):
    return {"bankroll": float(current_user.get("bankroll", 0))}


@router.put("/user/bankroll")
async def set_bankroll(payload: dict, current_user: dict = Depends(get_current_user)):
    # payload expected: {"bankroll": 150}
    try:
        val = float(payload.get("bankroll", 0))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valor inválido para banca")
    await db_module.db.users.update_one({"email": current_user.get("email")}, {"$set": {"bankroll": val}})
    return {"bankroll": val}


@router.put("/preferences")
async def update_preferences(payload: dict, current_user: dict = Depends(get_current_user)):
    # payload expected: {"enabled_colors": ["red", "black"], "enabled_patterns": [], "receive_alerts": true}
    update_data = {}
    if "enabled_colors" in payload:
        update_data["enabled_colors"] = payload["enabled_colors"]
    if "enabled_patterns" in payload:
        update_data["enabled_patterns"] = payload["enabled_patterns"]
    if "receive_alerts" in payload:
        update_data["receive_alerts"] = payload["receive_alerts"]
    
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhuma preferência fornecida")
    
    result = await db_module.db.users.find_one_and_update(
        {"email": current_user.get("email")}, 
        {"$set": update_data}, 
        return_document=ReturnDocument.AFTER
    )
    if result:
        return {
            "enabled_colors": result.get("enabled_colors", ["red", "black", "white"]),
            "enabled_patterns": result.get("enabled_patterns", []),
            "receive_alerts": result.get("receive_alerts", True)
        }
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao atualizar preferências")

# Admin routes
@router.get("/admin")
async def admin_page(admin_user: dict = Depends(get_admin_user)):
    """Serve admin page - only for admins"""
    return {"message": "Welcome to admin panel", "admin_email": admin_user["email"]}

@router.get("/admin/users")
async def get_all_users(admin_user: dict = Depends(get_admin_user)):
    """Get all users - admin only"""
    users = await db_module.db.users.find({}, {"password_hash": 0}).to_list(length=None)
    
    # Convert MongoDB objects to JSON serializable format
    for user in users:
        if "_id" in user:
            user["_id"] = str(user["_id"])
        if "created_at" in user and user["created_at"]:
            user["created_at"] = user["created_at"].isoformat()
    
    return {"users": users, "total": len(users)}

@router.get("/admin/stats")
async def get_admin_stats(admin_user: dict = Depends(get_admin_user)):
    """Get database statistics - admin only"""
    total_users = await db_module.db.users.count_documents({})
    total_bankroll = await db_module.db.users.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$bankroll"}}}
    ]).to_list(length=1)
    
    total_bankroll_value = total_bankroll[0]["total"] if total_bankroll else 0
    
    return {
        "total_users": total_users,
        "total_bankroll": float(total_bankroll_value),
        "database_name": db_module.db.name
    }
