from typing import TypedDict, List, Dict, Any


class TemplateSuggestion(TypedDict):
    template: str
    score: float
    rationale: str
    examples: List[Dict[str, Any]]
    metrics: Dict[str, float]


class TemplateMetadata(TypedDict, total=False):
    version: int
    created_at: str
    updated_at: str
    usage_count: int
    avg_score: float
    category: str
    source: str


class TemplateEntry(TypedDict):
    content: str
    metadata: TemplateMetadata
    scores: List[Dict[str, float]]
    variants: List[Dict[str, Any]]
