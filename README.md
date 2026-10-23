# SFMC Journey Simulator (mc-journey-builder)

A local tool for Salesforce Marketing Cloud (SFMC) architects and admins to model, simulate and validate Journey Builder configurations before touching production.

The bundled data set describes **EduPath**, a fictional franchise education company with an HQ business unit and three regional child BUs (North, South, East). All business units, data extensions, journeys, automations, personas and contacts are invented for the demo.

## What it does

- Model Business Units, Data Extensions, Journeys and Automations in a web UI, or edit the raw JSON in the built-in JSON editor
- Simulate how a persona moves through a journey, step by step or in one run, with scheduled field changes (scenarios)
- Enumerate every possible path through a journey
- Check entry criteria against contact data; keep a list of contacts (manual or CSV import) and run live checks and live simulations on them
- Build journeys on a canvas builder; clone a whole BU (DEs, journeys, automations) with the BU wizard
- Ask "Alex", a Claude-powered SFMC consultant that knows the loaded org, and pin useful answers as notes

## Tech stack

- **Backend**: Python 3.10+, FastAPI, Pydantic. Data is plain JSON files in `data/`, no database.
- **AI**: Anthropic Claude (`claude-opus-4-6`) for the Alex chat. Optional: the simulator works without an API key; only the chat needs one.
- **Frontend**: a single `frontend/index.html` page using Tailwind, Alpine.js and marked from CDN, served by FastAPI.

## Setup

```bash
git clone https://github.com/Galaspis/mc-journey-builder.git
cd mc-journey-builder

cp .env.example .env            # put your ANTHROPIC_API_KEY in .env (optional)
pip install -r backend/requirements.txt

cd backend
uvicorn main:app --reload
```

Open the address the command prints in your browser.

## API

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/business-units`, `/api/data-extensions`, `/api/journeys`, `/api/automations`, `/api/personas`, `/api/scenarios`, `/api/contacts` | read / save each JSON data set |
| POST | `/api/simulate` | run personas through a journey |
| POST | `/api/simulate/scenario` | run a scenario (persona + step events) |
| POST | `/api/simulate/step` | evaluate one step (step mode) |
| GET | `/api/journeys/{id}/paths` | enumerate all paths |
| POST | `/api/check-entry` | check entry criteria for a persona |
| POST | `/api/live/check`, `/api/live/simulate` | checks and simulation on stored contacts |
| POST | `/api/alex/chat` | consultant chat |

## Project structure

```
backend/         FastAPI app (main.py), models, simulation engine, journey consultant helper
frontend/        index.html — the whole UI
data/            business_units, data_extensions, journeys, automations, personas, scenarios, contacts (JSON)
Design_Assets/   logo / background image served at /design-assets
.env.example     environment template
```

## Background

Built after working on multi-BU SFMC setups, where a safe sandbox to validate journey and automation logic before deploying was missing. The demo data mirrors the shape of such a setup (HQ sync, shared DEs, per-region segmentation automations and journeys) with fictional names.
