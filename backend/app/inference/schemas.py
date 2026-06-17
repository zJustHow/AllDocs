from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]


class RerankPassage(BaseModel):
    text: str
    index_text: str | None = None


class RerankRequest(BaseModel):
    query: str
    passages: list[RerankPassage] = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)


class RerankItem(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    items: list[RerankItem]
