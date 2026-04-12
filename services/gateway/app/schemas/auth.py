from pydantic import BaseModel


class TokenPayload(BaseModel):
    username: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str