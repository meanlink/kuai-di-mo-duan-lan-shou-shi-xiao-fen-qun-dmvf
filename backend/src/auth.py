import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import cache, session
from .models import User

SECRET = os.getenv('JWT_SECRET', 'pickup-demo-1044-only-change-in-production')
BEARER = HTTPBearer(auto_error=False)
ATTEMPTS = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""


def password_hash(password, salt=None):
    salt = os.urandom(16).hex() if salt is None else salt
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f'{salt}:{digest.hex()}'


def login(db, payload, client):
    key = f'login:{client}:{payload.username.lower()}'
    if cache.eval(ATTEMPTS, 1, key) > 12:
        raise HTTPException(429, '登录尝试过多，请一分钟后再试')
    user = db.get(User, payload.username)
    salt = user.password_hash.split(':')[0] if user else '00' * 16
    checked = password_hash(payload.password, salt)
    if not user or not hmac.compare_digest(checked, user.password_hash):
        raise HTTPException(401, '账号或密码不正确')
    cache.delete(key)
    token = jwt.encode(
        {'sub': user.username, 'exp': datetime.now(UTC) + timedelta(hours=8)}, SECRET, algorithm='HS256'
    )
    return {'token': token, 'username': user.username, 'role': user.role}


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(BEARER), db=Depends(session)):
    if credentials:
        try:
            payload = jwt.decode(credentials.credentials, SECRET, algorithms=['HS256'], options={'require': ['exp', 'sub']})
            user = db.get(User, payload['sub'])
            if user:
                return user
        except jwt.InvalidTokenError:
            pass
    raise HTTPException(401, '请重新登录')


def allow(*roles):
    def check(user=Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, '当前角色无权执行此操作')
        return user
    return check
