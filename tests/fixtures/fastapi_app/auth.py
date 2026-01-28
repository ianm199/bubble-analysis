from fastapi import HTTPException


def get_current_user():
    raise HTTPException(401, "Unauthorized")
