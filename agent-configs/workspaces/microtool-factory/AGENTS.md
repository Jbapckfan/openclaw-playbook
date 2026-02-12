# Microtool Factory — Operating Instructions

## Mission

Rapidly scaffold complete, deployable healthcare microtools from specification files. Each tool is a self-contained FastAPI + Tailwind CSS application with Docker packaging, designed for hospital internal use by clinical staff who need simple, focused solutions at 3 AM.

## Input

A specification JSON file or freeform description of a healthcare microtool. Examples:
- "Build ShiftSBAR — a shift handoff tool using SBAR format for nursing staff"
- "Build PriorAuthPro — a prior authorization status tracker with insurance company lookup"
- "Build DischargeEZ — discharge instruction generator with medication reconciliation"
- "Build CMETrack — continuing medical education credit tracker with renewal alerts"
- "Build CallbackScript — patient callback script generator with clinical context"

### Spec JSON Format
```json
{
  "name": "ShiftSBAR",
  "slug": "shift-sbar",
  "description": "Nursing shift handoff tool using SBAR communication format",
  "models": [
    {
      "name": "Patient",
      "fields": [
        {"name": "mrn", "type": "str", "required": true, "description": "Medical record number"},
        {"name": "name", "type": "str", "required": true},
        {"name": "room", "type": "str", "required": true},
        {"name": "situation", "type": "str", "required": true},
        {"name": "background", "type": "str", "required": true},
        {"name": "assessment", "type": "str", "required": true},
        {"name": "recommendation", "type": "str", "required": true}
      ]
    }
  ],
  "endpoints": [
    {"method": "POST", "path": "/handoff", "description": "Create new SBAR handoff"},
    {"method": "GET", "path": "/handoffs/{shift_id}", "description": "Get handoffs for a shift"},
    {"method": "GET", "path": "/patient/{mrn}/history", "description": "Get handoff history for patient"}
  ],
  "features": ["form-validation", "pdf-export", "audit-log"]
}
```

## Process

1. **Parse specification** — Extract models, endpoints, features from spec JSON (or generate spec from freeform description)
2. **Generate Pydantic models** — Create type-safe data models with validation rules, HIPAA-appropriate field constraints
3. **Scaffold FastAPI backend** — Generate:
   - `main.py` — App initialization, CORS, middleware
   - `routes.py` — All endpoint handlers
   - `models.py` — Pydantic models
   - `database.py` — SQLite persistence (simple, no external DB dependency)
   - `auth.py` — Basic auth middleware (placeholder for hospital SSO integration)
4. **Scaffold frontend** — Generate:
   - `index.html` — Single-page app with Tailwind CSS
   - Mobile-responsive design (nurses use tablets and phones)
   - Large touch targets (minimum 44x44px — gloved hands)
   - High-contrast mode support (bright hospital lighting)
5. **Generate Dockerfile** — Multi-stage build, non-root user, health check endpoint
6. **Generate docker-compose.yml** — Complete stack with volume mounts for data persistence
7. **Write documentation**:
   - `README.md` — What it does, how to run it, API reference
   - `HIPAA-NOTES.md` — Data handling notes, audit logging, encryption requirements
8. **Smoke test** — Verify the generated project structure is complete and internally consistent

## Target Microtools

| Tool | Purpose | Primary User |
|------|---------|-------------|
| ShiftSBAR | Nursing shift handoff using SBAR format | Nurses |
| PriorAuthPro | Prior authorization tracking and status | Billing staff |
| DischargeEZ | Discharge instruction generation | Physicians, nurses |
| CMETrack | CME credit tracking with renewal alerts | All clinical staff |
| CallbackScript | Patient callback script generation | Front desk, nurses |

## HIPAA Compliance Notes

Every generated tool MUST include:
- **Audit logging**: Every data access logged with timestamp, user, action
- **No PHI in logs**: Log record IDs and actions, never patient names or MRNs in plain text
- **Session timeout**: Auto-logout after 15 minutes of inactivity
- **Password fields**: Never stored in plain text, always hashed
- **Data at rest**: SQLite database file should be on an encrypted volume (documented, not enforced by the tool)
- **HIPAA-NOTES.md**: Explicit documentation of what the tool does and doesn't handle regarding compliance

## Output Structure

```
~/jarvis/data/microtools/builds/{tool-slug}/
├── README.md
├── HIPAA-NOTES.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── backend/
│   ├── main.py
│   ├── routes.py
│   ├── models.py
│   ├── database.py
│   └── auth.py
├── frontend/
│   └── index.html
└── tests/
    └── test_api.py
```

## Error Handling

- If the spec JSON is malformed, attempt to fix obvious issues and confirm with the user
- If a requested feature is not in the template library, generate it from scratch and flag as "custom — review recommended"
- If model field types are ambiguous, default to `str` and add a validation TODO
- Never generate a tool without the HIPAA-NOTES.md — this is non-negotiable

## Escalation

- **Tools handling actual PHI**: Flag that this requires a formal HIPAA security assessment — the generated tool is a starting point, not a certified solution
- **Integration with hospital EHR/EMR**: Flag for manual integration work — HL7/FHIR interfaces are too complex for auto-generation
- **Multi-tenant requirements**: Flag — the default scaffold is single-tenant

## Data Storage

- Save spec files to `~/jarvis/data/microtools/specs/` as `{tool-slug}-spec.json`
- Save built projects to `~/jarvis/data/microtools/builds/{tool-slug}/`
- Maintain a build registry tracking tool versions and build dates
