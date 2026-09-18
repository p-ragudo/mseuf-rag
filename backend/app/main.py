import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api.v1.query import router as query_router
from app.core.config import settings
from app.core.database import engine, Base
import app.models
from app.routes.auth import router as auth_router
from app.utils.telegram_bot import start_telegram_bot_listener

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Start telegram bot background worker
    poller_task = asyncio.create_task(start_telegram_bot_listener())
    
    yield
    # Cancel gracefully on shutdown
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(query_router)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", 
        host=settings.SERVER_BIND_HOST, 
        port=settings.PORT, 
        reload=True
    )