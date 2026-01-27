import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def healthCheck():
    return {"status": "ok"}

def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()

