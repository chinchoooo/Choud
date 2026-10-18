"""SQLAlchemy model for `instance_settings`: a few switches that belong to the whole server.

Today that is only whether public share links are switched on (the kill switch an administrator can
flip without touching `.env` or restarting anything).
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InstanceSetting(Base):
    __tablename__ = "instance_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False, default="")
