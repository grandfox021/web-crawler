from fastapi import FastAPI
import uvicorn

from api.routes import router
from api.channels import router as channels_router


app = FastAPI()

app.include_router(router)
app.include_router(channels_router)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )