"""Routes using both direct raises and factory raises."""

from errors import HTTPException, app_error, build_value_error, http_exception
from fastapi import FastAPI

app = FastAPI()


@app.get("/direct")
def direct_raise():
    raise HTTPException(status_code=404, detail="not found")


@app.get("/factory")
def factory_raise():
    raise http_exception(500, "server error")


@app.get("/builtin-factory")
def builtin_factory_raise():
    raise build_value_error("bad value")


@app.get("/custom-factory")
def custom_factory_raise():
    raise app_error("something went wrong")
