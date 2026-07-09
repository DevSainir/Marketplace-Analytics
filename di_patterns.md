# Dependency Injection (DI) & Clean Architecture Patterns

To preserve Clean Architecture boundaries, all global dependencies live in `src/core/deps.py`. Domain-specific dependencies are defined within their respective modules, isolating route invocation from data access setup.

## 1. Core Shared Dependencies (`src/core/deps.py`)
```python
from typing import AsyncGenerator, Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import AsyncSessionLocal

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Global async generator for SQLAlchemy database sessions.
    Handles automatic context opening and closing.
    """
    async with AsyncSessionLocal() as session:
        yield session

# Global Reusable Type Dependency for all domain repositories
DbSession = Annotated[AsyncSession, Depends(get_db)]
```

## 2. Module Dependencies (src/modules/monitoring/dependencies.py)
```python
from typing import Annotated
from fastapi import Depends
from src.core.deps import DbSession
from src.modules.monitoring.repos import AnalyticsRepository
from src.modules.monitoring.services import AnalyticsService

def get_analytics_repo(session: DbSession) -> AnalyticsRepository:
    """Initializes the repository with the global async DB session."""
    return AnalyticsRepository(session)

AnalyticsRepoDep = Annotated[AnalyticsRepository, Depends(get_analytics_repo)]

def get_analytics_service(repo: AnalyticsRepoDep) -> AnalyticsService:
    """Injects the initialized repository into the domain service layer."""
    return AnalyticsService(repo)

# Exported clean dependency type for the presentation layer
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
```

## 3. Router Interface Layer (src/modules/monitoring/routers.py)
```python
from fastapi import APIRouter, status
from src.modules.monitoring.dependencies import AnalyticsServiceDep
from src.modules.monitoring.schemas import FunnelResponseSchema

router = APIRouter(prefix="/v1/analytics", tags=["Analytics"])

@router.get(
    "/funnel/{sku}",
    response_model=FunnelResponseSchema,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized access token"},
        404: {"description": "SKU data metrics not found"}
    }
)
async def get_market_funnel(
    sku: int,
    service: AnalyticsServiceDep
):
    """
    Exposes the API boundary endpoint for fetching normalized sales metrics.
    Strictly accepts parameters and delegates business execution down to the service layer.
    """
    return await service.get_cleaned_funnel(sku)
```
