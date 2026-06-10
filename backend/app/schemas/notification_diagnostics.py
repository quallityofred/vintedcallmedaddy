from pydantic import BaseModel, Field

class NotificationProcessRequest(BaseModel):
    dry_run: bool = Field(default=True)
    monitor_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=200)
    sample_limit: int = Field(default=10, ge=0, le=20)
