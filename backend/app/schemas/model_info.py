"""模型信息数据契约（M01/M03）"""
from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """GET /api/model/info 响应体"""
    model_name: str = "bert-base-chinese-ner"
    version: str = "v0.1"
    f1: float = Field(ge=0, le=1, description="实体级F1")
    train_samples: int = Field(ge=0, description="训练样本数（句级）")
    updated_at: str
