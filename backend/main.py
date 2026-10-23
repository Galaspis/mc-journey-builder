import json
import os
from datetime import date as date_type
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import anthropic as anthropic_sdk
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import (
    BusinessUnit, DataExtension, Journey, Automation, Persona, Scenario,
    SimulateRequest, ScenarioRunRequest, SimulationReport,
    PathEnumerationResult, EntryCheckRequest, EntryCheckResult,
    DEEligibility, LiveCheckRequest, LiveCheckResult, LiveSimulateRequest,
    Contact, StepEvalRequest, StepEvalResult,
)
from simulator import simulate_journey, simulate_scenario, enumerate_paths, check_entry_criteria, evaluate_step


def _parse_sim_date(s: Optional[str]) -> Optional[date_type]:
    if not s:
        return None
    try:
        return date_type.fromisoformat(s)
    except ValueError:
        return None

BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="SFMC Journey Simulator")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.mount("/design-assets", StaticFiles(directory=str(BASE_DIR / "Design_Assets")), name="design-assets")


@app.get("/")
def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(filename: str) -> Any:
    path = DATA_DIR / filename
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _save(filename: str, data: Any):
    (DATA_DIR / filename).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _get_journey(journey_id: str) -> dict:
    j = next((j for j in _load("journeys.json") if j["id"] == journey_id), None)
    if not j:
        raise HTTPException(404, f"Journey '{journey_id}' not found")
    return j


def _get_personas(persona_ids: List[str]) -> List[Persona]:
    personas = [Persona(**p) for p in _load("personas.json") if p["id"] in persona_ids]
    if not personas:
        raise HTTPException(400, "No matching personas found")
    return personas


# ── Business Units ────────────────────────────────────────────────────────────

@app.get("/api/business-units", response_model=List[BusinessUnit])
def get_business_units():
    return _load("business_units.json")

@app.post("/api/business-units")
def save_business_units(items: List[BusinessUnit]):
    _save("business_units.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Data Extensions ───────────────────────────────────────────────────────────

@app.get("/api/data-extensions", response_model=List[DataExtension])
def get_data_extensions():
    return _load("data_extensions.json")

@app.post("/api/data-extensions")
def save_data_extensions(items: List[DataExtension]):
    _save("data_extensions.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Journeys ──────────────────────────────────────────────────────────────────

@app.get("/api/journeys", response_model=List[Journey])
def get_journeys():
    return _load("journeys.json")

@app.post("/api/journeys")
def save_journeys(items: List[Journey]):
    _save("journeys.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Automations ───────────────────────────────────────────────────────────────

@app.get("/api/automations", response_model=List[Automation])
def get_automations():
    return _load("automations.json")

@app.post("/api/automations")
def save_automations(items: List[Automation]):
    _save("automations.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Personas ──────────────────────────────────────────────────────────────────

@app.get("/api/personas", response_model=List[Persona])
def get_personas():
    return _load("personas.json")

@app.post("/api/personas")
def save_personas(items: List[Persona]):
    _save("personas.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Scenarios ─────────────────────────────────────────────────────────────────

@app.get("/api/scenarios", response_model=List[Scenario])
def get_scenarios():
    return _load("scenarios.json")

@app.post("/api/scenarios")
def save_scenarios(items: List[Scenario]):
    _save("scenarios.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Simulate: personas ────────────────────────────────────────────────────────

@app.post("/api/simulate", response_model=SimulationReport)
def simulate(req: SimulateRequest):
    journey  = Journey(**_get_journey(req.journey_id))
    personas = _get_personas(req.persona_ids)
    return simulate_journey(journey, personas, seed=req.seed)


# ── Simulate: scenario ────────────────────────────────────────────────────────

@app.post("/api/simulate/scenario", response_model=SimulationReport)
def run_scenario(req: ScenarioRunRequest):
    scenarios_raw = _load("scenarios.json")
    sc_data = next((s for s in scenarios_raw if s["id"] == req.scenario_id), None)
    if not sc_data:
        raise HTTPException(404, f"Scenario '{req.scenario_id}' not found")

    scenario = Scenario(**sc_data)
    journey  = Journey(**_get_journey(scenario.journey_id))
    personas = _get_personas([scenario.persona_id])
    return simulate_scenario(journey, personas[0], scenario)


# ── Simulate: enumerate all paths ─────────────────────────────────────────────

@app.get("/api/journeys/{journey_id}/paths", response_model=PathEnumerationResult)
def get_all_paths(journey_id: str):
    journey = Journey(**_get_journey(journey_id))
    return enumerate_paths(journey)


# ── Entry criteria check ──────────────────────────────────────────────────────

@app.post("/api/check-entry", response_model=EntryCheckResult)
def check_entry(req: EntryCheckRequest):
    des = _load("data_extensions.json")
    de_data = next((d for d in des if d["key"] == req.de_key), None)
    if not de_data:
        raise HTTPException(404, f"Data Extension '{req.de_key}' not found")

    personas = _load("personas.json")
    persona_data = next((p for p in personas if p["id"] == req.persona_id), None)
    if not persona_data:
        raise HTTPException(404, f"Persona '{req.persona_id}' not found")

    return check_entry_criteria(Persona(**persona_data), DataExtension(**de_data))


# ── Live Contact Simulator ────────────────────────────────────────────────────

@app.post("/api/live/check", response_model=LiveCheckResult)
def live_check(req: LiveCheckRequest):
    des = _load("data_extensions.json")
    journeys_raw = _load("journeys.json")
    sim_date = _parse_sim_date(req.sim_date)

    # Build de_key → journey lookup
    de_to_journey: dict = {}
    for j in journeys_raw:
        de_key = j.get("entry_source", {}).get("de_key")
        if de_key:
            de_to_journey[de_key] = j

    temp_persona = Persona(id="_live", name="Live Contact", attributes=req.attributes)

    matching: List[DEEligibility] = []
    non_matching: List[DEEligibility] = []

    for de_data in des:
        # Filter by BU when requested
        if req.business_unit_id and de_data.get("business_unit_id") != req.business_unit_id:
            continue
        # Skip DEs with no entry criteria (raw sync DEs)
        if not de_data.get("entry_criteria"):
            continue

        de = DataExtension(**de_data)
        result = check_entry_criteria(temp_persona, de, sim_date=sim_date)
        j = de_to_journey.get(de.key)

        item = DEEligibility(
            de_key=de.key,
            de_name=de.name,
            business_unit_id=de.business_unit_id,
            journey_id=j["id"] if j else None,
            journey_name=j["name"] if j else None,
            re_entry=j.get("re_entry", False) if j else False,
            passes=result.passes,
            failures=result.failures,
        )
        (matching if result.passes else non_matching).append(item)

    return LiveCheckResult(matching=matching, non_matching=non_matching)


@app.post("/api/live/simulate", response_model=SimulationReport)
def live_simulate(req: LiveSimulateRequest):
    journey = Journey(**_get_journey(req.journey_id))
    persona = Persona(id="_live", name="Live Contact", attributes=req.attributes)
    sim_date = _parse_sim_date(req.sim_date)
    return simulate_journey(journey, [persona], seed=42, sim_date=sim_date)


# ── Step-by-step simulation ───────────────────────────────────────────────────

@app.post("/api/simulate/step", response_model=StepEvalResult)
def simulate_step(req: StepEvalRequest):
    journey = Journey(**_get_journey(req.journey_id))
    sim_date = _parse_sim_date(req.sim_date)
    result = evaluate_step(journey, req.step_id, req.attributes, sim_date=sim_date)
    if result is None:
        raise HTTPException(404, f"Step '{req.step_id}' not found in journey '{req.journey_id}'")
    return result


# ── Contacts (mini CRM) ───────────────────────────────────────────────────────

@app.get("/api/contacts", response_model=List[Contact])
def get_contacts():
    return _load("contacts.json")

@app.post("/api/contacts")
def save_contacts(items: List[Contact]):
    _save("contacts.json", [i.model_dump() for i in items])
    return {"ok": True}


# ── Alex Bot ──────────────────────────────────────────────────────────────────

class AlexMessage(BaseModel):
    role: str
    content: str

class AlexChatRequest(BaseModel):
    messages: List[AlexMessage]

@app.post("/api/alex/chat")
async def alex_chat(req: AlexChatRequest):
    messages = req.messages
    if not messages:
        raise HTTPException(400, "messages required")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured. Set it in your environment."}

    bus   = _load("business_units.json")
    des   = _load("data_extensions.json")
    journeys = _load("journeys.json")
    autos = _load("automations.json")

    de_summary = [
        {"key": d["key"], "name": d["name"], "bu": d["business_unit_id"],
         "criteria_count": len(d.get("entry_criteria", []))}
        for d in des
    ]
    journey_summary = [
        {"id": j["id"], "name": j["name"], "bu": j["business_unit_id"],
         "entry_de": j.get("entry_source", {}).get("de_key", ""),
         "steps": len(j.get("steps", []))}
        for j in journeys
    ]
    auto_summary = [
        {"key": a["key"], "name": a["name"], "schedule": a.get("schedule", ""),
         "bu": a.get("business_unit_id", ""), "steps": len(a.get("steps", []))}
        for a in autos
    ]

    system_prompt = f"""You are Alex, a Salesforce Marketing Cloud (SFMC) consultant embedded inside the EduPath SFMC Journey Simulator tool.

## Your expertise
You are a master of SFMC: Journey Builder, Automation Studio, Data Extensions, Email Studio, Contact Builder, MobileConnect, and SFMC best practices. You understand segmentation SQL, AMPscript, SSJS, and marketing automation design patterns.

## EduPath org structure
EduPath, a fictional franchise education company.
- Parent BU (HQ): manages Salesforce sync, parent segmentation, shared subscribers
- Child BUs: South (bu_south), North (bu_north), East (bu_east) — each runs their own student & franchisee journeys

**Business Units:**
{json.dumps(bus, indent=2)}

**Data Extensions ({len(des)} total — summary):**
{json.dumps(de_summary, indent=2)}

**Journeys ({len(journeys)} total — summary):**
{json.dumps(journey_summary, indent=2)}

**Automations ({len(autos)} total):**
{json.dumps(auto_summary, indent=2)}

## Automation data flow
1. Salesforce Sync → lead_salesforce / contact_salesforce (HQ)
2. HQ Segmentation automation → parent_all_leads → journey-specific DEs (HQ level)
3. HQ Subscribers automation → demo_subscribers + shared subscriber DEs
4. Region child automations (SO/NO/EA) → region entry DEs → journeys fire

## Your role
Help the user understand their SFMC setup, debug issues, design new journeys, explain automation dependencies, and suggest improvements. Be concise and practical. Answer in the same language the user writes in (English or Hebrew)."""

    try:
        client = anthropic_sdk.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return {"content": response.content[0].text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
