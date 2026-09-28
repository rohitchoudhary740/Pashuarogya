"""SQLAlchemy models — one class per entity in PRD section 12."""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Float, Boolean, DateTime,
                        Date, Text, ForeignKey, UniqueConstraint)
from sqlalchemy.orm import relationship
from database import Base

# ------------------------------------------------------------------ locations
class Location(Base):
    """Village / block / district hierarchy with LGD-style codes."""
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    name_mr = Column(String)                    # Marathi name
    level = Column(String, nullable=False)      # district | block | village
    lgd_code = Column(String, unique=True)
    parent_id = Column(Integer, ForeignKey("locations.id"))
    lat = Column(Float)
    lon = Column(Float)
    parent = relationship("Location", remote_side=[id], backref="children")


# ---------------------------------------------------------------------- users
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    phone = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # farmer|field|vet|lab|block|district|state
    location_id = Column(Integer, ForeignKey("locations.id"))
    lang = Column(String, default="hi")     # Hindi default; mr/en selectable
    location = relationship("Location")


class Farmer(Base):
    __tablename__ = "farmers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    village_id = Column(Integer, ForeignKey("locations.id"))
    user = relationship("User")
    village = relationship("Location")


# -------------------------------------------------------------------- animals
class Animal(Base):
    __tablename__ = "animals"
    id = Column(Integer, primary_key=True)
    tag_id = Column(String, unique=True)        # Bharat Pashudhan style 12-digit
    species = Column(String, nullable=False)    # cattle|buffalo|goat|sheep|poultry
    breed = Column(String)
    sex = Column(String)
    age_months = Column(Integer)
    farmer_id = Column(Integer, ForeignKey("farmers.id"))
    village_id = Column(Integer, ForeignKey("locations.id"))
    farmer = relationship("Farmer", backref="animals")
    village = relationship("Location")


# ---------------------------------------------------------------- health data
class Case(Base):
    """A suspected/confirmed health event. Lifecycle per PRD section 9."""
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True)
    client_uuid = Column(String, unique=True)   # offline dedup key
    village_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    farmer_id = Column(Integer, ForeignKey("farmers.id"))
    animal_id = Column(Integer, ForeignKey("animals.id"))
    species = Column(String, nullable=False)
    breed = Column(String)                      # breed affected (historical trends)
    symptoms = Column(String, nullable=False)   # comma-joined syndrome codes
    affected_count = Column(Integer, default=1)
    dead_count = Column(Integer, default=0)
    onset_date = Column(Date)
    reported_at = Column(DateTime, default=datetime.utcnow)
    channel = Column(String, default="app")     # app|field|ivr|sms
    photo = Column(Text)                        # data-uri (demo scale)
    notes = Column(Text)
    lat = Column(Float)
    lon = Column(Float)
    # triage output
    triage_band = Column(String)                # high|medium|low
    triage_score = Column(Integer)
    suspected = Column(String)                  # top suspected disease keys
    zoonotic_flag = Column(Boolean, default=False)
    # workflow
    status = Column(String, default="REPORTED")
    assigned_to = Column(Integer, ForeignKey("users.id"))
    escalated_to = Column(String)               # block|district|state
    village = relationship("Location")
    farmer = relationship("Farmer")
    animal = relationship("Animal")


class Vaccination(Base):
    __tablename__ = "vaccinations"
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey("animals.id"))
    village_id = Column(Integer, ForeignKey("locations.id"))
    disease_key = Column(String, nullable=False)
    vaccine = Column(String)
    given_on = Column(Date)
    due_on = Column(Date)
    campaign = Column(String)


class Treatment(Base):
    __tablename__ = "treatments"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"))
    vet_id = Column(Integer, ForeignKey("users.id"))
    diagnosis = Column(String)
    treatment = Column(Text)
    given_at = Column(DateTime, default=datetime.utcnow)
    withdrawal_days = Column(Integer, default=0)   # milk/meat withdrawal (food safety)


class Sample(Base):
    __tablename__ = "samples"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)
    case_id = Column(Integer, ForeignKey("cases.id"))
    collected_by = Column(Integer, ForeignKey("users.id"))
    collected_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="COLLECTED")  # COLLECTED|DISPATCHED|RECEIVED|TESTING|RESULT
    lab_result = Column(String)                   # positive|negative|inconclusive
    result_disease = Column(String)
    result_at = Column(DateTime)
    case = relationship("Case", backref="samples")


# --------------------------------------------------------------- intelligence
class RiskScore(Base):
    __tablename__ = "risk_scores"
    id = Column(Integer, primary_key=True)
    village_id = Column(Integer, ForeignKey("locations.id"))
    computed_at = Column(DateTime, default=datetime.utcnow)
    score = Column(Integer)
    band = Column(String)                       # high|moderate|low
    reasons = Column(Text)                      # JSON list of reason strings
    breakdown = Column(Text)                    # JSON dict of signal->points
    __table_args__ = (UniqueConstraint("village_id", name="uq_risk_village"),)


class Outbreak(Base):
    __tablename__ = "outbreaks"
    id = Column(Integer, primary_key=True)
    center_village_id = Column(Integer, ForeignKey("locations.id"))
    suspected = Column(String)
    zone_village_ids = Column(Text)             # JSON list
    cases_7d = Column(Integer)
    expected = Column(Float)
    p_value = Column(Float)
    radius_km = Column(Float)
    zoonotic = Column(Boolean, default=False)
    status = Column(String, default="ACTIVE")   # ACTIVE|MONITORING|CLOSED
    detected_at = Column(DateTime, default=datetime.utcnow)
    center = relationship("Location")


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    kind = Column(String)                       # outbreak|onehealth|vaccination|advisory
    severity = Column(String)                   # high|medium|low
    title = Column(String)
    body = Column(Text)
    village_id = Column(Integer, ForeignKey("locations.id"))
    target_role = Column(String)                # farmer|vet|block|district|state|health
    lang = Column(String, default="en")
    created_at = Column(DateTime, default=datetime.utcnow)
    acknowledged = Column(Boolean, default=False)


class WeatherObservation(Base):
    __tablename__ = "weather_obs"
    id = Column(Integer, primary_key=True)
    village_id = Column(Integer, ForeignKey("locations.id"))
    observed_at = Column(DateTime, default=datetime.utcnow)
    temp_c = Column(Float)
    humidity = Column(Float)
    rain_mm = Column(Float)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer)
    action = Column(String)
    detail = Column(Text)


# ------------------------------------------------- closing-the-loop layer ---
class Claim(Base):
    """Compensation claim for livestock death — the incentive that makes
    farmers report instead of hide. The case record IS the evidence."""
    __tablename__ = "claims"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"))
    farmer_id = Column(Integer, ForeignKey("farmers.id"))
    animal_tag = Column(String)
    species = Column(String)
    amount = Column(Integer)                    # ₹, per govt schedule
    status = Column(String, default="FILED")    # FILED|UNDER_REVIEW|APPROVED|PAID|REJECTED
    filed_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime)
    note = Column(Text)
    case = relationship("Case")
    farmer = relationship("Farmer")


class Task(Base):
    """Government action queue — every alert carries an owner and an action."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    kind = Column(String)          # mvu_dispatch|ring_vaccination|sample_collection|verification
    title = Column(String)
    village_id = Column(Integer, ForeignKey("locations.id"))
    outbreak_id = Column(Integer, ForeignKey("outbreaks.id"))
    assigned_role = Column(String)              # vet|field|block|district
    status = Column(String, default="OPEN")     # OPEN|IN_PROGRESS|DONE
    created_at = Column(DateTime, default=datetime.utcnow)
    done_at = Column(DateTime)
    village = relationship("Location")


class Camp(Base):
    """Scheduled vaccination camp — planned by officials, visible to farmers."""
    __tablename__ = "camps"
    id = Column(Integer, primary_key=True)
    village_id = Column(Integer, ForeignKey("locations.id"))
    disease_key = Column(String)
    camp_date = Column(Date)
    name = Column(String)
    status = Column(String, default="SCHEDULED")  # SCHEDULED|COMPLETED|CANCELLED
    created_at = Column(DateTime, default=datetime.utcnow)
    village = relationship("Location")


class HealthCentre(Base):
    """A place a farmer can physically take an animal to, or call.

    Seeded from the public veterinary-institution pattern (dispensary → polyclinic
    → district lab) plus the 1962 mobile units. Phone numbers are deliberately NOT
    invented: everything routes through the real 1962 toll-free helpline, and the
    `phone` column is there for a department to fill in from its own directory.
    """
    __tablename__ = "health_centres"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    name_local = Column(String)                 # Hindi / Marathi name
    kind = Column(String)      # dispensary|polyclinic|hospital|mvu|lab|ai_centre
    village_id = Column(Integer, ForeignKey("locations.id"))   # nearest village
    block_id = Column(Integer, ForeignKey("locations.id"))
    lat = Column(Float)
    lon = Column(Float)
    phone = Column(String, default="1962")      # 1962 = the real state helpline
    timings = Column(String)
    services = Column(String)                   # comma-separated service codes
    is_24x7 = Column(Boolean, default=False)
