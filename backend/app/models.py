"""Import every model here so Base.metadata knows about all tables."""
from app.modules.accounts.models import Membership, Patient, Role, Staff, StaffBranch, StaffRole  # noqa: F401
from app.modules.appointments.models import Appointment, AppointmentSlot  # noqa: F401
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.branches.models import Branch, BranchHours  # noqa: F401
from app.modules.services.models import BranchService, Service  # noqa: F401
from app.modules.queue.models import QueueCounter, QueueEntry, VisitRecord  # noqa: F401,E402
