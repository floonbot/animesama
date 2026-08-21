from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    pseudo:   str = Field(..., min_length=1,  max_length=60)
    password: str = Field(..., min_length=1,  max_length=200)

    @field_validator("pseudo")
    @classmethod
    def pseudo_propre(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Le pseudo ne peut pas être vide")
        return v

    @field_validator("password")
    @classmethod
    def password_propre(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Le mot de passe ne peut pas être vide")
        return v

class AuthStatus(BaseModel):
    connected: bool
    username:  str | None = None
