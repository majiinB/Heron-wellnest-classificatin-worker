from fastapi import FastAPI
from app.routes.classification_route import router

app = FastAPI(title="Classification Worker")

app.include_router(router)

@app.get("/")
async def root():
    return {"status": "ok"}

# if(env.ENVIRONMENT != "production"):
#     @app.on_event("startup")
#     async def startup_event():
#         import threading
#         thread = threading.Thread(target=start_worker, daemon=True)
#         thread.start()
#         print("✅ Pub/Sub worker started in background")