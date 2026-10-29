# app/schemas/__init__.py
"""`schemas.X` namespace (routers use `from app import schemas`)."""
from app.schemas.base import *  # noqa: F401,F403
from app.schemas.user import *  # noqa: F401,F403
from app.schemas.role import *  # noqa: F401,F403
from app.schemas.permission import *  # noqa: F401,F403
from app.schemas.api_key import *  # noqa: F401,F403
from app.schemas.event import *  # noqa: F401,F403
from app.schemas.analytics import *  # noqa: F401,F403
from app.schemas.audit import *  # noqa: F401,F403
