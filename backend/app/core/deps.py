import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.modules.accounts.models import Patient, Staff

bearer = HTTPBearer(auto_error=False)

_401 = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


def _claims(creds: HTTPAuthorizationCredentials | None, expected_type: str) -> int:
    if creds is None:
        raise _401
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise _401
    if claims.get("typ") != expected_type:
        raise _401
    return int(claims["sub"])


def get_current_patient(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> Patient:
    patient = db.get(Patient, _claims(creds, "patient"))
    if patient is None or patient.account_status != "active":
        raise _401
    return patient


def get_current_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> Staff:
    staff = db.get(Staff, _claims(creds, "staff"))
    if staff is None or staff.account_status != "active":
        raise _401
    return staff


def require_roles(*allowed: str):
    """Backend RBAC (NFR-003). Roles are read from the database on every request."""

    def checker(staff: Staff = Depends(get_current_staff)) -> Staff:
        if not set(staff.role_names) & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return staff

    return checker
