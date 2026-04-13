from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EdgeConditionSchema(BaseModel):
    field: str
    operator: str
    value: Any = None


class FlowEdgeSchema(BaseModel):
    id: str
    source: str
    target: str
    condition: EdgeConditionSchema | None = None
    label: str | None = None
    priority: int | None = None


class FlowNodeSchema(BaseModel):
    id: str
    type: str
    label: str
    label_en: str | None = None
    enabled: bool = True
    page_slug: str | None = None
    config: dict = {}
    position: dict


class FlowResponse(BaseModel):
    id: str
    name: str
    nodes: list[FlowNodeSchema]
    edges: list[FlowEdgeSchema]
    entry_node_id: str | None
    version: int


class FlowUpdate(BaseModel):
    name: str | None = None
    nodes: list[FlowNodeSchema]
    edges: list[FlowEdgeSchema]
    entry_node_id: str | None = None


class FlowCreate(BaseModel):
    id: str
    name: str
    nodes: list[FlowNodeSchema] = []
    edges: list[FlowEdgeSchema] = []
    entry_node_id: str | None = None
