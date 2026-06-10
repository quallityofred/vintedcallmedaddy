from pydantic import BaseModel, Field

class MonitorDryRunRequest(BaseModel):
    max_domains: int = Field(default=1, ge=1, le=8)
    max_items_per_domain: int = Field(default=10, ge=1, le=120)
    domain: str | None = None
    domains: list[str] | None = None
    source: str = "hydration"
    sample_limit: int = Field(default=10, ge=0, le=20)
    include_media_diagnostics: bool = False

class MonitorFullCycleDryRunRequest(BaseModel):
    domain: str | None = None
    domains: list[str] | None = None
    max_domains: int = Field(default=8, ge=1, le=8)
    max_items_per_domain: int = Field(default=96, ge=1, le=120)
    include_samples: bool = True
    sample_limit: int = Field(default=10, ge=0, le=20)
    include_media_diagnostics: bool = False
    media_diag_max_items: int = Field(default=10, ge=1, le=20)
    media_diag_max_chunks: int = Field(default=20, ge=1, le=50)
    dry_run: bool = True

class MonitorBaselineRequest(BaseModel):
    domain: str | None = None
    domains: list[str] | None = None
    max_domains: int = Field(default=1, ge=1, le=8)
    max_items_per_domain: int = Field(default=96, ge=1, le=120)
    dry_run: bool = True
    sample_limit: int = Field(default=10, ge=0, le=20)
    activate_after: bool = False # for start-with-baseline
