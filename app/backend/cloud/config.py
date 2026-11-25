from dataclasses import dataclass, field
import os
from typing import Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CloudSettings:
    database_url: str = field(repr=False)
    session_signing_key: bytes = field(repr=False)
    frontend_origins: tuple[str, ...]
    environment: str = 'production'

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None):
        values = os.environ if environ is None else environ
        database_url = values.get('DATABASE_URL', '').strip()
        if not database_url.startswith('postgresql+asyncpg://'):
            raise ValueError('DATABASE_URL must use postgresql+asyncpg')
        secret = values.get('SESSION_SIGNING_KEY', '').encode('utf-8')
        if len(secret) < 32:
            raise ValueError('SESSION_SIGNING_KEY must contain at least 32 bytes')
        origins = tuple(x.strip().rstrip('/') for x in values.get('FRONTEND_ORIGINS', '').split(',') if x.strip())
        if not origins or '*' in origins:
            raise ValueError('FRONTEND_ORIGINS must list exact origins; wildcard is forbidden')
        environment = values.get('APP_ENV', 'production').strip().lower()
        if environment not in {'development', 'test', 'staging', 'production'}:
            raise ValueError('APP_ENV must be development, test, staging, or production')
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in ({'http', 'https'} if environment in {'development', 'test'} else {'https'}):
                raise ValueError('FRONTEND_ORIGINS must use HTTPS outside local development and tests')
            if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError('FRONTEND_ORIGINS entries must be exact origins without paths or credentials')
        return cls(database_url, secret, origins, environment)
