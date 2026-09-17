from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.core.config import settings
from app.routes.auth import router as auth_router
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.database import engine, Base
import app.models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown (nothing needed here yet, but this is where cleanup goes)

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


@app.get("/api/query")
def read_root():
    return {"status": "connected to backend"}

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", 
        host=settings.SERVER_BIND_HOST, 
        port=settings.PORT, 
        reload=True
    )