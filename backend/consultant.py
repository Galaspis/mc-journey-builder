import uuid
import datetime
import anthropic
from typing import Dict, List, Optional, Tuple

from models import JourneySpec

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Alex, a Senior Marketing Cloud Architect with 10+ years of experience
building enterprise-grade customer journeys in Salesforce Marketing Cloud (SFMC).
You are acting as a hands-on consultant helping the user design their journey.

YOUR ROLE
- Listen carefully to the user's requirements.
- Ask targeted clarifying questions (one or two at a time) when requirements are vague.
- Guide the user through all the components needed to build a complete journey.
- Once you have enough information, offer to generate the journey specification.

INFORMATION TO GATHER (cover all before offering to generate)
1. Journey Name & Goal — what business outcome is this trying to achieve?
2. Entry Source — how do contacts enter?
   • API Event (real-time trigger from website/app)
   • Salesforce Data (CRM sync — specify which object and filter, e.g. "Contacts where LastPurchaseDate < 90 days ago")
   • Scheduled (daily/weekly batch)
3. Contact Data Fields — what attributes will be used in decision splits?
   (e.g. member_tier: Gold/Silver/Bronze, email_opted_in: boolean, sms_opted_in: boolean)
4. Journey Steps in order:
   • Email sends (subject line, estimated open rate if known)
   • SMS sends (confirm opt-in field exists first)
   • Wait periods (duration + unit: minutes/hours/days/weeks)
   • Decision Splits (field name, operator, value — be specific)
   • Update Data steps if any
5. Re-entry — can the same contact re-enter the journey?
6. Exit criteria / what happens at the end of each branch

SFMC KNOWLEDGE TO APPLY
- Email open tracking sets a dynamic field `{step_id}_opened` (boolean) that can be checked in a later Decision Split.
- Decision splits can evaluate: contact attributes, engagement history, date conditions.
- Always confirm SMS opt-in field before recommending an SMS step.
- Salesforce Data entry: specify the SF object (Contact, Lead, Account) and the filter expression.

COMMUNICATION STYLE
- Be conversational but concise and professional.
- Use SFMC terminology correctly (Entry Source, Decision Split, Wait Activity, Data Extension).
- Never produce JSON or code in the chat — that is handled separately.
- When all information is gathered, say exactly:
  "I have enough information to generate your journey specification. Would you like me to generate it now?"
"""

# ── Session Management ────────────────────────────────────────────────────────

class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[Dict] = []
        self.ready_to_generate: bool = False
        self.journey_spec: Optional[JourneySpec] = None
        self.markdown: Optional[str] = None


_sessions: Dict[str, Session] = {}
_client = anthropic.Anthropic()

READY_PHRASES = [
    "i have enough information to generate",
    "ready to generate",
    "generate your journey specification",
    "generate the specification",
    "shall i generate",
    "would you like me to generate it",
]


def _get_or_create(session_id: Optional[str]) -> Session:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    sid = session_id or str(uuid.uuid4())
    session = Session(sid)
    _sessions[sid] = session
    return session


# ── Chat ──────────────────────────────────────────────────────────────────────

def chat(message: str, session_id: Optional[str] = None) -> Tuple[str, str, bool]:
    """Send a message and return (reply_text, session_id, ready_to_generate)."""
    session = _get_or_create(session_id)
    session.messages.append({"role": "user", "content": message})

    with _client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=session.messages,
    ) as stream:
        final = stream.get_final_message()

    reply = next((b.text for b in final.content if b.type == "text"), "")
    session.messages.append({"role": "assistant", "content": reply})

    ready = any(phrase in reply.lower() for phrase in READY_PHRASES)
    session.ready_to_generate = ready

    return reply, session.session_id, ready


# ── Spec Generation ───────────────────────────────────────────────────────────

_EXTRACT_TOOL = {
    "name": "generate_journey_spec",
    "description": "Generate a complete, structured Marketing Cloud journey specification from the conversation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "journey_name": {"type": "string", "description": "Short, descriptive journey name"},
            "description": {"type": "string", "description": "One-sentence description of the journey"},
            "goal": {"type": "string", "description": "Business goal / desired outcome"},
            "entry_source": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["api_event", "salesforce_data", "scheduled"],
                        "description": "Entry source type"
                    },
                    "object": {"type": "string", "description": "Salesforce object name, e.g. Contact"},
                    "event_name": {"type": "string", "description": "API Event name if applicable"},
                    "filter": {"type": "string", "description": "Entry filter expression"}
                },
                "required": ["type"],
                "additionalProperties": False
            },
            "re_entry": {"type": "boolean", "description": "Whether contacts can re-enter the journey"},
            "contact_data": {
                "type": "array",
                "description": "Data fields used in the journey (for simulation persona generation)",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["string", "boolean", "number", "date"]
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Possible values for string enum fields"
                        },
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                        "default": {}
                    },
                    "required": ["name", "type"],
                    "additionalProperties": False
                }
            },
            "steps": {
                "type": "array",
                "description": "Ordered list of journey steps",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique step ID, e.g. step_1, email_welcome"
                        },
                        "name": {"type": "string", "description": "Human-readable step name"},
                        "type": {
                            "type": "string",
                            "enum": ["email", "sms", "wait", "decision_split", "update_data", "exit"]
                        },
                        "config": {
                            "type": "object",
                            "description": (
                                "Step config. "
                                "email: {subject, from_address, open_rate (0-1)}. "
                                "sms: {message, response_rate (0-1)}. "
                                "wait: {duration, unit: minutes|hours|days|weeks}. "
                                "decision_split: {condition: {field, operator, value}, yes_label, no_label}. "
                                "Operators: equals, not_equals, in, not_in, greater_than, less_than, is_true, is_false."
                            ),
                            "additionalProperties": True
                        },
                        "next": {
                            "description": (
                                "For linear steps: next step ID string. "
                                "For decision_split: {\"yes\": \"step_id\", \"no\": \"step_id\"}. "
                                "Null for terminal steps."
                            )
                        }
                    },
                    "required": ["id", "name", "type"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["journey_name", "description", "goal", "entry_source", "steps"],
        "additionalProperties": False
    }
}


def generate_spec(session_id: str) -> Tuple[JourneySpec, str]:
    """Extract a structured JourneySpec from the conversation and generate Markdown docs."""
    if session_id not in _sessions:
        raise ValueError(f"Session '{session_id}' not found.")

    session = _sessions[session_id]

    extraction_messages = session.messages + [{
        "role": "user",
        "content": (
            "Based on our conversation, please use the generate_journey_spec tool to produce "
            "the complete journey specification. Make sure all steps have correct IDs, "
            "next pointers, and decision split conditions."
        )
    }]

    response = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        tools=[_EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "generate_journey_spec"},
        messages=extraction_messages,
    )

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        raise RuntimeError("Claude did not return a tool call.")

    spec = JourneySpec.model_validate(tool_block.input)
    markdown = _build_markdown(spec)

    session.journey_spec = spec
    session.markdown = markdown

    return spec, markdown


# ── Markdown Generator ────────────────────────────────────────────────────────

def _build_markdown(spec: JourneySpec) -> str:
    today = datetime.date.today().isoformat()
    entry = spec.entry_source

    lines = [
        f"# Journey Specification: {spec.journey_name}",
        f"",
        f"**Version:** {spec.version} &nbsp;&nbsp; **Generated:** {today}",
        f"",
        f"---",
        f"",
        f"## Overview",
        f"",
        f"**Goal:** {spec.goal}",
        f"",
        f"**Description:** {spec.description}",
        f"",
        f"---",
        f"",
        f"## Entry Configuration",
        f"",
        f"| Property | Value |",
        f"|----------|-------|",
        f"| Entry Source | {entry.type.value.replace('_', ' ').title()} |",
    ]

    if entry.object:
        lines.append(f"| Salesforce Object | `{entry.object}` |")
    if entry.event_name:
        lines.append(f"| API Event Name | `{entry.event_name}` |")
    if entry.filter:
        lines.append(f"| Filter Criteria | {entry.filter} |")
    lines.append(f"| Re-entry Allowed | {'Yes' if spec.re_entry else 'No'} |")

    if spec.contact_data:
        lines += [
            f"",
            f"---",
            f"",
            f"## Contact Data Fields",
            f"",
            f"| Field | Type | Possible Values |",
            f"|-------|------|-----------------|",
        ]
        for f in spec.contact_data:
            vals = ", ".join(f.values) if f.values else "—"
            lines.append(f"| `{f.name}` | {f.type} | {vals} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Journey Steps",
        f"",
    ]

    for i, step in enumerate(spec.steps, 1):
        lines.append(f"### Step {i}: {step.name}")
        lines.append(f"")
        lines.append(f"**Type:** `{step.type.value}`")
        lines.append(f"")

        if step.config:
            lines.append("**Configuration:**")
            lines.append("")
            for k, v in step.config.items():
                if isinstance(v, dict):
                    lines.append(f"- **{k.replace('_', ' ').title()}:**")
                    for ck, cv in v.items():
                        lines.append(f"  - `{ck}`: {cv}")
                else:
                    lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
            lines.append("")

        if step.next:
            if isinstance(step.next, str):
                lines.append(f"**Next Step:** `{step.next}`")
            elif isinstance(step.next, dict):
                lines.append("**Branches:**")
                for branch, target in step.next.items():
                    lines.append(f"- **{branch.upper()}** → `{target}`")
        lines.append("")

    lines += [
        "---",
        "",
        "*Generated by MC Journey Builder Consultant · Powered by Claude*",
    ]

    return "\n".join(lines)
