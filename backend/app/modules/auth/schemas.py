import re
from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator

PHONE_RE = re.compile(r"^\+?\d{9,15}$")
ID_RE = re.compile(r"^[A-Za-z0-9]{6,20}$")


class PatientRegister(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    id_number: str = Field(description="South African ID or passport number")
    date_of_birth: date
    email: EmailStr
    phone: str
    password: str = Field(min_length=8, max_length=128)
    consent: bool = Field(description="Must be true: patient accepted the privacy notice (POPIA)")

    @field_validator("id_number")
    @classmethod
    def check_id(cls, v: str) -> str:
        v = v.strip()
        if not ID_RE.match(v):
            raise ValueError("ID or passport number must be 6 to 20 letters or digits")
        return v.upper()

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v)
        if not PHONE_RE.match(v):
            raise ValueError("Phone number must be 9 to 15 digits, optionally starting with +")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def check_dob(cls, v: date) -> date:
        if v >= date.today():
            raise ValueError("Date of birth must be in the past")
        return v

    @field_validator("consent")
    @classmethod
    def check_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the privacy notice to register")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MembershipOut(BaseModel):
    membership_number: str
    qr_token: str
    issued_date: date
    status: str

    model_config = {"from_attributes": True}


class RegisterResponse(TokenResponse):
    membership: MembershipOut


class PatientOut(BaseModel):
    patient_id: int
    first_name: str
    last_name: str
    email: EmailStr
    phone: str

    model_config = {"from_attributes": True}
