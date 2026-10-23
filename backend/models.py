from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Literal
from enum import Enum


# ── SFMC Config ───────────────────────────────────────────────────────────────

class BusinessUnit(BaseModel):
    id: str
    name: str
    description: str = ""
    parent_id: Optional[str] = None


class DEField(BaseModel):
    name: str
    type: Literal["Text", "Number", "Boolean", "Date", "EmailAddress", "Decimal", "Phone"]
    is_primary_key: bool = False
    is_required: bool = False
    default_value: Optional[Any] = None


class EntryFilter(BaseModel):
    """A single condition controlling who qualifies to enter a Data Extension."""
    field: str
    operator: str   # equals, not_equals, greater_than, less_than, contains, in, is_empty, is_not_empty
    value: Optional[Any] = None


class DataExtension(BaseModel):
    name: str
    key: str
    description: str = ""
    business_unit_id: str
    entry_criteria: List[EntryFilter] = []   # filters that decide who lands in this DE
    fields: List[DEField]
    sample_rows: List[Dict[str, Any]] = []


class AutomationStep(BaseModel):
    type: str
    name: str
    description: str = ""
    query: Optional[str] = None
    source: Optional[str] = None
    target_de: Optional[str] = None


class Automation(BaseModel):
    name: str
    key: str
    layer: str = ""
    description: str = ""
    business_unit_id: str
    schedule: Optional[str] = None
    steps: List[AutomationStep] = []


# ── Journeys ──────────────────────────────────────────────────────────────────

class StepType(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WAIT = "wait"
    DECISION_SPLIT = "decision_split"
    UPDATE_DATA = "update_data"
    PUSH = "push"
    EXIT = "exit"


class JourneyStep(BaseModel):
    id: str
    name: str
    type: StepType
    config: Dict[str, Any] = {}
    # str  → next step id (linear)
    # dict → {"yes": step_id, "no": step_id} (decision split)
    # None → terminal
    next: Optional[Any] = None


class Journey(BaseModel):
    id: str
    name: str
    description: str = ""
    business_unit_id: str
    entry_source: Dict[str, Any] = {}
    re_entry: bool = False
    goal: Optional[str] = None
    steps: List[JourneyStep]


# ── Personas ──────────────────────────────────────────────────────────────────

class Persona(BaseModel):
    id: str
    name: str
    attributes: Dict[str, Any]


# ── Scenarios ─────────────────────────────────────────────────────────────────

class StepEvent(BaseModel):
    """A data change that happens at (before) a specific step during simulation."""
    at_step_id: str
    description: str = ""
    updates: Dict[str, Any]


class Scenario(BaseModel):
    id: str
    name: str
    description: str = ""
    journey_id: str
    persona_id: str
    initial_overrides: Dict[str, Any] = {}   # override persona attributes at entry
    step_events: List[StepEvent] = []        # data changes mid-journey


# ── Simulation: persona-based ─────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    journey_id: str
    persona_ids: List[str]
    seed: Optional[int] = None


class ScenarioRunRequest(BaseModel):
    scenario_id: str


class StepTrace(BaseModel):
    step_id: str
    step_name: str
    type: str
    outcome: str
    data_change: Optional[Dict[str, Any]] = None   # set when a step_event fired here


class PersonaTrace(BaseModel):
    persona_id: str
    persona_name: str
    path: List[StepTrace]
    exit_reason: str
    completed_goal: bool


class StepStats(BaseModel):
    step_id: str
    step_name: str
    step_type: str
    entered: int
    outcomes: Dict[str, int] = {}


class SimulationReport(BaseModel):
    mode: str = "persona"   # "persona" | "scenario"
    journey_id: str
    journey_name: str
    scenario_name: Optional[str] = None
    total_personas: int
    completed: int
    completion_rate: float
    step_stats: List[StepStats]
    persona_traces: List[PersonaTrace]


# ── Simulation: all-paths enumeration ────────────────────────────────────────

class PathStep(BaseModel):
    step_id: str
    step_name: str
    type: str
    outcome: str          # "sent", "yes", "no", "waited_N_days", etc.


class JourneyPath(BaseModel):
    path_id: int
    conditions: List[str]   # human-readable list of decision outcomes that led here
    steps: List[PathStep]
    exit_step: str
    exit_reason: str
    reaches_goal: bool


class PathEnumerationResult(BaseModel):
    journey_id: str
    journey_name: str
    total_paths: int
    paths: List[JourneyPath]


# ── Entry criteria check ──────────────────────────────────────────────────────

class EntryCheckRequest(BaseModel):
    de_key: str
    persona_id: str


class EntryCheckResult(BaseModel):
    de_key: str
    de_name: str
    persona_id: str
    persona_name: str
    passes: bool
    failures: List[str]   # list of conditions that were NOT met


# ── Live Contact Simulator ────────────────────────────────────────────────────

class DEEligibility(BaseModel):
    de_key: str
    de_name: str
    business_unit_id: str
    journey_id: Optional[str] = None
    journey_name: Optional[str] = None
    re_entry: bool = False
    passes: bool
    failures: List[str] = []


class LiveCheckRequest(BaseModel):
    attributes: Dict[str, Any]
    business_unit_id: Optional[str] = None   # if set, filter to this BU only
    sim_date: Optional[str] = None           # ISO date string, overrides today


class LiveCheckResult(BaseModel):
    matching: List[DEEligibility]
    non_matching: List[DEEligibility]


class LiveSimulateRequest(BaseModel):
    journey_id: str
    attributes: Dict[str, Any]
    sim_date: Optional[str] = None


# ── Step-by-step simulation ───────────────────────────────────────────────────

class StepEvalRequest(BaseModel):
    journey_id: str
    step_id: str
    attributes: Dict[str, Any] = {}
    sim_date: Optional[str] = None


class StepEvalResult(BaseModel):
    step_id: str
    step_name: str
    step_type: str
    outcome: str
    next_step_id: Optional[str] = None
    condition_result: Optional[bool] = None     # for decision_split only
    condition_label: Optional[str] = None       # human-readable condition
    data_updates: Optional[Dict[str, Any]] = None  # for update_data steps
    wait_label: Optional[str] = None            # for wait steps


# ── Contacts (mini CRM) ───────────────────────────────────────────────────────

class Contact(BaseModel):
    id: str
    name: str
    email: str = ""
    business_unit_id: str
    record_type: str          # "Student" | "Franchisee"
    attributes: Dict[str, Any] = {}
    notes: str = ""
