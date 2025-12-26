from fastapi import APIRouter, HTTPException, status, Depends, Response, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from datetime import datetime, timedelta
from typing import Optional
from pymongo import ReturnDocument
import db as db_module
import time
from models.auth_models import UserIn, UserOut, Token
from auth_utils import get_password_hash, verify_password
from jwt_utils import create_access_token, decode_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Fuso horário de Brasília (UTC-3)
try:
    from zoneinfo import ZoneInfo
    BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    # Fallback quando tzdata não está instalado ou ZoneInfo não funciona
    from datetime import timezone
    BRAZIL_TZ = timezone(timedelta(hours=-3))

def get_brazil_time():
    """Retorna a hora atual no fuso horário de Brasília"""
    return datetime.now(BRAZIL_TZ)

async def log_user_activity(user_email: str, action: str, details: str = "", request: Request = None):
    """Registra atividade do usuário no MongoDB para auditoria"""
    try:
        if db_module.db is None:
            return
        
        brazil_now = get_brazil_time()
        
        log_doc = {
            "email": user_email,
            "action": action,  # login, logout, page_access, config_change, admin_action
            "details": details,
            "ip": request.client.host if request and request.client else "unknown",
            "userAgent": request.headers.get("user-agent", "unknown") if request else "unknown",
            "timestamp": int(time.time() * 1000),
            "datetime": brazil_now.replace(tzinfo=None)  # Salvar sem timezone info para MongoDB
        }
        
        await db_module.db.activity_logs.insert_one(log_doc)
    except Exception as e:
        print(f"Erro ao registrar log de atividade: {e}")




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
        "created_at": get_brazil_time().replace(tzinfo=None),
        "last_login": get_brazil_time().replace(tzinfo=None),
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
async def login(request: Request, response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    # OAuth2PasswordRequestForm uses username as field; pass email in username
    user = await db_module.db.users.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password_hash")):
        # Log failed attempt
        await log_user_activity(form_data.username, "login_failed", "Credenciais inválidas", request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    # Update last_login
    await db_module.db.users.update_one(
        {"email": user["email"]},
        {"$set": {"last_login": get_brazil_time().replace(tzinfo=None)}}
    )
    token = create_access_token({"sub": user["email"]})
    # Log successful login
    await log_user_activity(user["email"], "login", "Login bem-sucedido", request)
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
        "max_attempts": current_user.get("max_attempts", 3),  # 2 ou 3 tentativas
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
    # payload expected: {"enabled_colors": [...], "enabled_patterns": [], "receive_alerts": true, "max_attempts": 3}
    update_data = {}
    if "enabled_colors" in payload:
        update_data["enabled_colors"] = payload["enabled_colors"]
    if "enabled_patterns" in payload:
        update_data["enabled_patterns"] = payload["enabled_patterns"]
    if "receive_alerts" in payload:
        update_data["receive_alerts"] = payload["receive_alerts"]
    if "max_attempts" in payload:
        # Validar que seja 2 ou 3
        max_att = int(payload["max_attempts"])
        if max_att in [2, 3]:
            update_data["max_attempts"] = max_att
    
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
            "receive_alerts": result.get("receive_alerts", True),
            "max_attempts": result.get("max_attempts", 3)
        }
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao atualizar preferências")

# Admin routes
@router.get("/admin/stats")
async def admin_stats(admin_user: dict = Depends(get_admin_user)):
    total_users = await db_module.db.users.count_documents({})
    total_bankroll = await db_module.db.users.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$bankroll"}}}
    ]).to_list(length=1)
    total_bankroll_value = total_bankroll[0]["total"] if total_bankroll else 0
    
    # Estatísticas de sinais (últimos 30 dias)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    cutoff_ts = int(cutoff.timestamp() * 1000)
    
    try:
        signals = await db_module.db.signal_history.find({"createdAt": {"$gte": cutoff_ts}}).to_list(length=10000)
        total_signals = len(signals)
        wins = sum(1 for s in signals if s.get("result") == "win")
        signal_rate = round((wins / total_signals * 100), 2) if total_signals > 0 else 0
    except Exception:
        total_signals = 0
        wins = 0
        signal_rate = 0
    
    # Usuários ativos (últimas 24h)
    active_cutoff = datetime.utcnow() - timedelta(hours=24)
    try:
        active_users = await db_module.db.users.count_documents({"last_login": {"$gte": active_cutoff}})
    except Exception:
        active_users = 0
    
    # Total de logs
    try:
        total_logs = await db_module.db.activity_logs.count_documents({})
    except Exception:
        total_logs = 0
    
    return {
        "total_users": total_users,
        "total_bankroll": float(total_bankroll_value),
        "database_name": db_module.db.name,
        "total_signals_30d": total_signals,
        "wins_30d": wins,
        "signal_rate_30d": signal_rate,
        "active_users_24h": active_users,
        "total_logs": total_logs
    }

@router.get("/admin/users")
async def admin_users(admin_user: dict = Depends(get_admin_user)):
    projection = {
        "email": 1,
        "username": 1,
        "bankroll": 1,
        "enabled_colors": 1,
        "enabled_patterns": 1,
        "receive_alerts": 1,
        "is_admin": 1,
        "created_at": 1,
        "last_login": 1,
        "_id": 0,
    }
    users = await db_module.db.users.find({}, projection).to_list(length=None)
    def _normalize(u):
        return {
            "email": u.get("email"),
            "username": u.get("username"),
            "bankroll": float(u.get("bankroll", 0)),
            "enabled_colors": u.get("enabled_colors", []),
            "enabled_patterns": u.get("enabled_patterns", []),
            "receive_alerts": bool(u.get("receive_alerts", True)),
            "is_admin": bool(u.get("is_admin", False)),
            "created_at": u.get("created_at"),
            "last_login": u.get("last_login"),
        }
    return {"users": [ _normalize(u) for u in users ]}

@router.get("/admin/logs")
async def admin_logs(admin_user: dict = Depends(get_admin_user), page: int = 1, limit: int = 50, action: str = None):
    """Retorna logs de atividade com paginação e filtro opcional"""
    try:
        query = {}
        if action:
            query["action"] = action
        
        # Contar total
        total = await db_module.db.activity_logs.count_documents(query)
        
        # Buscar com paginação
        skip = (page - 1) * limit
        logs = await db_module.db.activity_logs.find(query).sort("timestamp", -1).skip(skip).limit(limit).to_list(length=limit)
        
        # Formatar para JSON
        formatted = []
        for log in logs:
            formatted.append({
                "email": log.get("email"),
                "action": log.get("action"),
                "details": log.get("details"),
                "ip": log.get("ip"),
                "userAgent": log.get("userAgent", "")[:50] + "..." if len(log.get("userAgent", "")) > 50 else log.get("userAgent", ""),
                "timestamp": log.get("timestamp"),
                "datetime": log.get("datetime").isoformat() if log.get("datetime") else None
            })
        
        return {
            "ok": True,
            "data": formatted,
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": (total + limit - 1) // limit if limit > 0 else 1
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "data": [], "total": 0}

