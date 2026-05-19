"""Dymphna VoIP Service — FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import engine, Base, AsyncSessionLocal
from .routers import extensions, calls, voicemail, sms, presence, push, admin
from .services import asterisk

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info('Dymphna VoIP service started')

    # Start Asterisk AMI event listener for real-time call CDR logging
    try:
        await asterisk.start_event_listener(AsyncSessionLocal)
        log.info('AMI event listener started')
    except Exception as exc:
        log.warning('AMI event listener failed to start (Asterisk not reachable?): %s', exc)

    yield

    await asterisk.stop_event_listener()
    await engine.dispose()
    log.info('Dymphna VoIP service stopped')


app = FastAPI(
    title='Dymphna VoIP Service',
    version='1.0.0',
    docs_url='/voip/docs',
    redoc_url='/voip/redoc',
    openapi_url='/voip/openapi.json',
    lifespan=lifespan,
)

# Tighten CORS to EHR origin + allow mobile app (no origin header on native)
_cors_origins = [o.strip() for o in settings.cors_origins.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r'.*',   # native apps send no origin header — allow through
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(extensions.router)
app.include_router(calls.router)
app.include_router(voicemail.router)
app.include_router(sms.router)
app.include_router(presence.router)
app.include_router(push.router)
app.include_router(admin.router)


@app.get('/voip/health')
async def health():
    return {'status': 'ok', 'service': 'dymphna-voip'}
