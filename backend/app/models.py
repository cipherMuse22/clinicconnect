"""Import every model here so Base.metadata knows about all tables."""
from app.modules.accounts.models import Membership, Patient, Role, Staff, StaffBranch, StaffRole  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.branches.models import Branch  # noqa: F401
