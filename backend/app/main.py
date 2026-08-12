from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
import os

load_dotenv()

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

@app.get("/api/query")
def read_root():
    return {"status": "connected to backend"}

HOST = os.getenv("HOST")
PORT = int(os.getenv("PORT"))

if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)