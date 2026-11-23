from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patient"

    patient_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    id_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    account_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    consent_given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    privacy_notice_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    membership: Mapped["Membership"] = relationship(back_populates="patient", uselist=False)


class Membership(Base):
    __tablename__ = "membership"

    membership_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id"), unique=True, nullable=False)
    membership_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    patient: Mapped[Patient] = relationship(back_populates="membership")


class Role(Base):
    __tablename__ = "role"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class Staff(Base):
    __tablename__ = "staff"

    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    account_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    roles: Mapped[list["StaffRole"]] = relationship(back_populates="staff", cascade="all, delete-orphan")
    branches: Mapped[list["StaffBranch"]] = relationship(back_populates="staff", cascade="all, delete-orphan")

    @property
    def role_names(self) -> list[str]:
        return [sr.role.role_name for sr in self.roles]

    @property
    def branch_ids(self) -> list[int]:
        return [sb.branch_id for sb in self.branches]


class StaffRole(Base):
    __tablename__ = "staff_role"
    __table_args__ = (UniqueConstraint("staff_id", "role_id"),)

    staff_role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.role_id"), nullable=False)

    staff: Mapped[Staff] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class StaffBranch(Base):
    __tablename__ = "staff_branch"
    __table_args__ = (UniqueConstraint("staff_id", "branch_id"),)

    staff_branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), nullable=False)

    staff: Mapped[Staff] = relationship(back_populates="branches")
