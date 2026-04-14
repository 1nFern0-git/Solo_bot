import json

from typing import Any

from pydantic import BaseModel, Field, model_validator


_MAX_BLOCK_DATA_SIZE = 256 * 1024


class WebBlockBase(BaseModel):
    type: str = Field(..., max_length=64)
    order: int
    data: dict[str, Any]

    @model_validator(mode="after")
    def _check_data_size(self) -> "WebBlockBase":
        if len(json.dumps(self.data, ensure_ascii=False)) > _MAX_BLOCK_DATA_SIZE:
            raise ValueError(f"Размер data блока не должен превышать {_MAX_BLOCK_DATA_SIZE // 1024} КБ")
        return self


class WebBlockResponse(WebBlockBase):
    id: str

    class Config:
        from_attributes = True


class WebTheme(BaseModel):
    tokens: dict[str, Any]


class WebPageVariantSummary(BaseModel):
    key: str = Field(..., max_length=64)
    name: str = Field(..., max_length=255)
    is_active: bool = False


class WebPageResponse(BaseModel):
    slug: str
    blocks: list[WebBlockResponse]
    theme: WebTheme | None = None
    variant_key: str = "default"
    active_variant_key: str = "default"
    variants: list[WebPageVariantSummary] = Field(default_factory=list)


class WebPageUpdate(BaseModel):
    blocks: list[WebBlockBase]
    theme: WebTheme | None = None


class WebPageVariantCreate(BaseModel):
    key: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    from_variant_key: str | None = Field(default=None, max_length=64)


class WebPageVariantUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    make_active: bool | None = None


class WebPageVariantsResponse(BaseModel):
    slug: str
    active_variant_key: str = "default"
    current_variant_key: str = "default"
    variants: list[WebPageVariantSummary] = Field(default_factory=list)


class WebUploadResponse(BaseModel):
    url: str


class FlowStepConfig(BaseModel):
    provider_ids: list[str] | None = None
    tariff_group_code: str | None = None
    tariff_ids: list[int] | None = None
    display_mode: str | None = None
    skippable: bool = False
    auto_advance_if_single: bool = False


class FlowStepSchema(BaseModel):
    id: str = Field(..., max_length=64)
    type: str = Field(..., max_length=32)
    label: str = Field(..., max_length=255)
    label_en: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    page_slug: str | None = Field(default=None, max_length=64)
    config: FlowStepConfig = Field(default_factory=FlowStepConfig)


class FlowDefinitionSchema(BaseModel):
    id: str = Field(..., max_length=64)
    name: str = Field(..., max_length=255)
    steps: list[FlowStepSchema] = Field(default_factory=list)
    version: int = 1


class FlowDefinitionResponse(FlowDefinitionSchema):
    pass


class FlowDefinitionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    steps: list[FlowStepSchema] = Field(default_factory=list)
