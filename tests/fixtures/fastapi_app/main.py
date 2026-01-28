from fastapi import Depends, FastAPI, HTTPException

from auth import get_current_user

app = FastAPI()


@app.get("/items/{item_id}")
def get_item(item_id: int, user=Depends(get_current_user)):
    if item_id < 0:
        raise HTTPException(404, "Not found")
    return {"id": item_id}


@app.post("/items")
def create_item(user=Depends(get_current_user)):
    return {"id": 1}
