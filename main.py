from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import sprint_report, test_iterations

app = FastAPI()

# Allow requests from your frontend
origins = [
    "http://localhost:3000",  # or "*" to allow all origins (not recommended for prod)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],  # Allow all headers
)
# app.include_router(test_iterations.router, prefix="/test-iterations")

@app.get("/")
def health_check():
    return {"status": "OK"}

app.include_router(sprint_report.router, prefix="/sprint-report")
# app.include_router(test_iterations.router, prefix="/test-iterations")