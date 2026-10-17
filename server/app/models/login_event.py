"""SQLAlchemy model for `login_events`: who tried to sign in to an account, and from where.

Only attempts against an existing account are recorded (a made-up email is not stored), and only the
basics: time, address, browser/app string, and whether it worked. Shown to the account owner on the
Security page so a stranger's attempts, or a login from a new device, do not go unnoticed.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # A successful login from an address + client never seen before on this account.
    new_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
