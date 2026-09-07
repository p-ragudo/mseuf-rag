from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.core.config import settings
from app.api.query import router as query_router

app = FastAPI()

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

app.include_router(query_router)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", 
        host=settings.SERVER_BIND_HOST, 
        port=settings.PORT, 
        reload=True
    )