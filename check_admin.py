import os
import asyncio
import db as db_module
from db import init_db
from routes.auth import get_password_hash
from datetime import datetime

async def check_admin():
    init_db()
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        raise RuntimeError("Missing ADMIN_EMAIL or ADMIN_PASSWORD environment variables")

    # Verificar se o usuário admin existe
    admin_user = await db_module.db.users.find_one({'email': admin_email})
    if admin_user:
        print(f'Usuário admin encontrado: {admin_user["email"]}')
        print(f'is_admin: {admin_user.get("is_admin", False)}')
        print(f'bankroll: {admin_user.get("bankroll", 0)}')
        
        # Se não é admin, atualizar para ser admin
        if not admin_user.get("is_admin", False):
            print("Atualizando usuário para admin...")
            result = await db_module.db.users.update_one(
                {'email': admin_email},
                {'$set': {'is_admin': True}}
            )
            print(f"Usuário atualizado para admin: {result.modified_count} documento(s) modificado(s)")
    else:
        print('Usuário admin NÃO encontrado')

        # Criar usuário admin
        hashed = get_password_hash(admin_password)
        doc = {
            'email': admin_email,
            'username': 'admin',
            'password_hash': hashed,
            'bankroll': 1000.0,
            'enabled_colors': ['red', 'black', 'white'],
            'enabled_patterns': [],
            'receive_alerts': True,
            'is_admin': True,
            'created_at': datetime.utcnow(),
        }
        result = await db_module.db.users.insert_one(doc)
        print(f'Usuário admin criado com ID: {result.inserted_id}')

if __name__ == "__main__":
    asyncio.run(check_admin())