from pydantic import BaseModel, Field


class FichierBody(BaseModel):
    fichier: str = Field(..., min_length=1, max_length=2000)

class CoversBody(BaseModel):
    covers: dict = Field(default_factory=dict)

class TypesFavorisBody(BaseModel):
    urls: list[str] = Field(default_factory=list)
