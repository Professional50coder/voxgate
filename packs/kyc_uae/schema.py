from datetime import date
from pydantic import BaseModel, field_validator

VALID_SOF = {"salary", "business_income", "investments", "inheritance", "crypto_trading", "other"}
VALID_PRODUCTS = {"spot_trading", "derivatives", "custody"}
VALID_RESIDENCY = {"uae_resident", "non_resident"}

class Schema(BaseModel):
    full_name: str
    dob: str                      # ISO date string
    nationality: str              # ISO alpha-2
    residency_status: str
    source_of_funds: str
    product: str

    @field_validator("dob")
    @classmethod
    def dob_plausible(cls, v):
        d = date.fromisoformat(v)
        age = (date.today() - d).days / 365.25
        if not 18 <= age <= 100:
            raise ValueError("age must be 18-100")
        return v

    @field_validator("full_name")
    @classmethod
    def name_plausible(cls, v):
        if len(v.split()) < 2:
            raise ValueError("need given and family name")
        return v

    @field_validator("residency_status")
    @classmethod
    def res_valid(cls, v):
        if v not in VALID_RESIDENCY: raise ValueError(f"one of {VALID_RESIDENCY}")
        return v

    @field_validator("source_of_funds")
    @classmethod
    def sof_valid(cls, v):
        if v not in VALID_SOF: raise ValueError(f"one of {VALID_SOF}")
        return v

    @field_validator("product")
    @classmethod
    def product_valid(cls, v):
        if v not in VALID_PRODUCTS: raise ValueError(f"one of {VALID_PRODUCTS}")
        return v

REASK_HINTS = {
    "full_name": "Could you spell your full name for me, please?",
    "dob": "Could you give me your date of birth again — day, month and year?",
    "nationality": "Which country issued your passport?",
    "residency_status": "Are you a UAE resident, or applying from abroad?",
    "source_of_funds": "What is the main source of the funds you will use?",
    "product": "Which product are you applying for — spot trading, derivatives, or custody?",
}
