import random
import re as _re
from datetime import date, timedelta
from typing import List, Dict, Optional, Any, Tuple

from models import (
    Journey, JourneyStep, StepType,
    Persona, Scenario, DataExtension, EntryFilter,
    PersonaTrace, StepTrace, StepStats, SimulationReport,
    PathStep, JourneyPath, PathEnumerationResult,
    EntryCheckResult, StepEvalResult,
)

MAX_STEPS = 200   # guard against infinite loops in path enumeration


# ── Date resolution ───────────────────────────────────────────────────────────

def _resolve_date(value: Any, sim_date: Optional[date] = None) -> Any:
    """Resolve special date tokens (Today, Today+N, Today-N) to ISO date strings."""
    if not isinstance(value, str):
        return value
    today = sim_date or date.today()
    v = value.strip()
    if v == "Today":
        return today.isoformat()
    m = _re.match(r'^Today([+-]\d+)$', v)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    return value


def _is_date_str(v: Any) -> bool:
    return isinstance(v, str) and bool(_re.match(r'^\d{4}-\d{2}-\d{2}$', v.strip()))


# ── Shared condition evaluator ────────────────────────────────────────────────

def _eval(condition: Dict[str, Any], attrs: Dict[str, Any], rng: Optional[random.Random] = None,
          sim_date: Optional[date] = None) -> bool:
    """
    Evaluate a decision-split condition against a persona's current attributes.

    Modes:
      probability  — True with that probability (needs rng). For engagement metrics.
      force_split  — attrs["_force_split"] == "yes"/"no" overrides everything.
      attribute    — field / operator / value comparison.
    """
    if not condition:
        return (rng.random() < 0.5) if rng else False

    # Hard override: scenario can set _force_split to pin a branch
    if "_force_split" in attrs:
        return attrs["_force_split"] == "yes"

    if "probability" in condition:
        if rng is None:
            # no rng → enumerate both branches; caller handles this
            raise ValueError("probability condition requires rng")
        return rng.random() < float(condition["probability"])

    field    = condition.get("field", "")
    operator = condition.get("operator", "equals")
    expected = condition.get("value")
    actual   = attrs.get(field)

    if operator == "equals":
        exp = _resolve_date(expected, sim_date)
        if actual is None:
            return exp is None
        return str(actual).strip().lower() == str(exp).strip().lower()
    if operator == "not_equals":
        exp = _resolve_date(expected, sim_date)
        return str(actual).strip().lower() != str(exp).strip().lower()
    if operator == "greater_than":
        exp = _resolve_date(expected, sim_date)
        if _is_date_str(actual) and _is_date_str(exp):
            return str(actual).strip() > str(exp).strip()
        try:   return float(actual) > float(exp)
        except: return False
    if operator == "less_than":
        exp = _resolve_date(expected, sim_date)
        if _is_date_str(actual) and _is_date_str(exp):
            return str(actual).strip() < str(exp).strip()
        try:   return float(actual) < float(exp)
        except: return False
    if operator == "contains":
        return str(expected).lower() in str(actual).lower() if actual else False
    if operator == "in":
        return actual in expected if isinstance(expected, list) else False
    if operator == "is_empty":
        return actual is None or actual == ""
    if operator == "is_not_empty":
        return actual is not None and actual != ""
    if operator == "email_opened":
        return bool(attrs.get("_email_opened", False))
    if operator == "email_clicked":
        return bool(attrs.get("_email_clicked", False))
    return False


# ── Entry criteria check ──────────────────────────────────────────────────────

def check_entry_criteria(persona: Persona, de: DataExtension,
                         sim_date: Optional[date] = None) -> EntryCheckResult:
    failures = []
    for f in de.entry_criteria:
        condition = {"field": f.field, "operator": f.operator, "value": f.value}
        try:
            passes = _eval(condition, persona.attributes, sim_date=sim_date)
        except Exception:
            passes = False
        if not passes:
            op_str = f.operator.replace("_", " ")
            if f.value is not None:
                resolved = _resolve_date(f.value, sim_date)
                if str(resolved) != str(f.value):
                    val_str = f" {f.value} (= {resolved})"
                else:
                    val_str = f" {f.value}"
            else:
                val_str = ""
            actual_val = persona.attributes.get(f.field)
            got_str = f"  ·  got: {actual_val!r}" if actual_val is not None else "  ·  got: (not set)"
            failures.append(f"{f.field} {op_str}{val_str}{got_str}")

    return EntryCheckResult(
        de_key=de.key,
        de_name=de.name,
        persona_id=persona.id,
        persona_name=persona.name,
        passes=len(failures) == 0,
        failures=failures,
    )


# ── Persona-based simulation ──────────────────────────────────────────────────

def _run_single(
    journey: Journey,
    persona: Persona,
    step_events: Optional[List[Dict]] = None,   # [{at_step_id, updates, description}]
    rng: Optional[random.Random] = None,
    sim_date: Optional[date] = None,
) -> Tuple[PersonaTrace, Dict[str, StepStats]]:
    """Traverse a journey for one persona. Returns (trace, step_stats_updates)."""

    step_map: Dict[str, JourneyStep] = {s.id: s for s in journey.steps}
    events_map: Dict[str, Dict] = {e["at_step_id"]: e for e in (step_events or [])}

    attrs = dict(persona.attributes)
    path: List[StepTrace] = []
    step_stats: Dict[str, StepStats] = {}
    exit_reason = "completed"
    goal_reached = False
    step_count = 0

    if not journey.steps:
        return PersonaTrace(
            persona_id=persona.id, persona_name=persona.name,
            path=[], exit_reason="no_steps", completed_goal=False,
        ), {}

    current_id: Optional[str] = journey.steps[0].id

    while current_id:
        if step_count >= MAX_STEPS:
            exit_reason = "max_steps_reached"
            break

        step = step_map.get(current_id)
        if not step:
            exit_reason = f"missing_step:{current_id}"
            break

        step_count += 1

        # Apply step event BEFORE evaluating this step
        data_change: Optional[Dict[str, Any]] = None
        if current_id in events_map:
            event = events_map[current_id]
            attrs.update(event["updates"])
            data_change = event["updates"]

        # Init stats
        if step.id not in step_stats:
            step_stats[step.id] = StepStats(
                step_id=step.id, step_name=step.name,
                step_type=step.type, entered=0, outcomes={},
            )
        step_stats[step.id].entered += 1

        outcome: str
        next_id: Optional[str]

        if step.type in (StepType.EMAIL, StepType.SMS, StepType.PUSH):
            outcome = "sent"
            next_id = step.next

        elif step.type == StepType.WAIT:
            d = step.config.get("duration", "?")
            u = step.config.get("unit", "days")
            outcome = f"waited_{d}_{u}"
            next_id = step.next

        elif step.type == StepType.DECISION_SPLIT:
            condition = step.config.get("condition", {})
            try:
                result = _eval(condition, attrs, rng, sim_date=sim_date)
            except ValueError:
                # probabilistic with no rng → default to False (no branch)
                result = False
            outcome = "yes" if result else "no"
            branches = step.next if isinstance(step.next, dict) else {}
            next_id = branches.get(outcome)

        elif step.type == StepType.UPDATE_DATA:
            updates = step.config.get("updates", {})
            attrs.update(updates)
            outcome = "updated"
            next_id = step.next

        elif step.type == StepType.EXIT:
            reason = step.config.get("reason", "exit")
            outcome = reason
            exit_reason = reason
            next_id = None

        else:
            outcome = "processed"
            next_id = step.next

        step_stats[step.id].outcomes[outcome] = step_stats[step.id].outcomes.get(outcome, 0) + 1

        path.append(StepTrace(
            step_id=step.id, step_name=step.name,
            type=step.type, outcome=outcome,
            data_change=data_change,
        ))

        if journey.goal and step.id == journey.goal:
            goal_reached = True

        current_id = next_id

    return PersonaTrace(
        persona_id=persona.id, persona_name=persona.name,
        path=path, exit_reason=exit_reason, completed_goal=goal_reached,
    ), step_stats


def simulate_journey(
    journey: Journey,
    personas: List[Persona],
    seed: Optional[int] = None,
    sim_date: Optional[date] = None,
) -> SimulationReport:
    rng = random.Random(seed)
    all_stats: Dict[str, StepStats] = {}
    traces: List[PersonaTrace] = []
    completed = 0

    for persona in personas:
        trace, stats = _run_single(journey, persona, rng=rng, sim_date=sim_date)
        if trace.completed_goal:
            completed += 1
        traces.append(trace)
        for sid, s in stats.items():
            if sid not in all_stats:
                all_stats[sid] = s
            else:
                all_stats[sid].entered += s.entered
                for k, v in s.outcomes.items():
                    all_stats[sid].outcomes[k] = all_stats[sid].outcomes.get(k, 0) + v

    total = len(personas)
    return SimulationReport(
        mode="persona",
        journey_id=journey.id,
        journey_name=journey.name,
        total_personas=total,
        completed=completed,
        completion_rate=round(completed / total, 3) if total > 0 else 0.0,
        step_stats=list(all_stats.values()),
        persona_traces=traces,
    )


def simulate_scenario(
    journey: Journey,
    persona: Persona,
    scenario: Scenario,
    sim_date: Optional[date] = None,
) -> SimulationReport:
    """Run one persona through a journey with specific mid-journey data changes."""
    # Apply initial overrides to persona attributes
    merged_attrs = {**persona.attributes, **scenario.initial_overrides}
    merged_persona = Persona(id=persona.id, name=persona.name, attributes=merged_attrs)

    step_events = [e.model_dump() for e in scenario.step_events]

    # No rng for scenario — conditions must be deterministic (attribute-based).
    # Probabilistic splits fall to "no" unless _force_split is set.
    trace, stats = _run_single(journey, merged_persona, step_events=step_events, rng=None,
                               sim_date=sim_date)

    return SimulationReport(
        mode="scenario",
        journey_id=journey.id,
        journey_name=journey.name,
        scenario_name=scenario.name,
        total_personas=1,
        completed=1 if trace.completed_goal else 0,
        completion_rate=1.0 if trace.completed_goal else 0.0,
        step_stats=list(stats.values()),
        persona_traces=[trace],
    )


# ── All-paths enumeration ─────────────────────────────────────────────────────

def enumerate_paths(journey: Journey) -> PathEnumerationResult:
    """
    DFS through the journey graph, branching at every decision split.
    Returns ALL unique paths from entry to any exit.
    Probabilistic conditions are treated as two branches (yes AND no).
    """
    step_map: Dict[str, JourneyStep] = {s.id: s for s in journey.steps}
    completed_paths: List[JourneyPath] = []
    path_counter = [0]

    def dfs(
        current_id: Optional[str],
        current_path: List[PathStep],
        conditions: List[str],
        visited: set,
    ):
        if not current_id:
            # Reached a null next — build terminal path
            exit_step = current_path[-1].step_name if current_path else "unknown"
            exit_reason = current_path[-1].outcome if current_path else "unknown"
            reaches_goal = any(
                s.step_id == journey.goal for s in current_path
            ) if journey.goal else False

            path_counter[0] += 1
            completed_paths.append(JourneyPath(
                path_id=path_counter[0],
                conditions=list(conditions),
                steps=list(current_path),
                exit_step=exit_step,
                exit_reason=exit_reason,
                reaches_goal=reaches_goal,
            ))
            return

        if current_id not in step_map:
            # Missing step — dead end
            path_counter[0] += 1
            completed_paths.append(JourneyPath(
                path_id=path_counter[0],
                conditions=list(conditions),
                steps=list(current_path),
                exit_step=f"missing:{current_id}",
                exit_reason="missing_step",
                reaches_goal=False,
            ))
            return

        if current_id in visited or len(current_path) >= MAX_STEPS:
            path_counter[0] += 1
            completed_paths.append(JourneyPath(
                path_id=path_counter[0],
                conditions=list(conditions),
                steps=list(current_path),
                exit_step="loop_or_max",
                exit_reason="loop_detected",
                reaches_goal=False,
            ))
            return

        step = step_map[current_id]
        new_visited = visited | {current_id}

        if step.type == StepType.DECISION_SPLIT:
            branches = step.next if isinstance(step.next, dict) else {}

            # YES branch
            yes_step = PathStep(step_id=step.id, step_name=step.name, type=step.type, outcome="yes")
            cond_label = _condition_label(step)
            dfs(branches.get("yes"), current_path + [yes_step],
                conditions + [f"{step.name} = YES  ({cond_label})"], new_visited)

            # NO branch
            no_step = PathStep(step_id=step.id, step_name=step.name, type=step.type, outcome="no")
            dfs(branches.get("no"), current_path + [no_step],
                conditions + [f"{step.name} = NO  ({cond_label})"], new_visited)

        elif step.type == StepType.EXIT:
            reason = step.config.get("reason", "exit")
            ps = PathStep(step_id=step.id, step_name=step.name, type=step.type, outcome=reason)
            reaches_goal = (journey.goal == step.id) if journey.goal else False
            path_counter[0] += 1
            completed_paths.append(JourneyPath(
                path_id=path_counter[0],
                conditions=list(conditions),
                steps=current_path + [ps],
                exit_step=step.name,
                exit_reason=reason,
                reaches_goal=reaches_goal,
            ))

        elif step.type == StepType.WAIT:
            d = step.config.get("duration", "?")
            u = step.config.get("unit", "days")
            outcome = f"waited_{d}_{u}"
            ps = PathStep(step_id=step.id, step_name=step.name, type=step.type, outcome=outcome)
            dfs(step.next, current_path + [ps], conditions, new_visited)

        else:
            ps = PathStep(step_id=step.id, step_name=step.name, type=step.type, outcome=step.type)
            dfs(step.next, current_path + [ps], conditions, new_visited)

    if journey.steps:
        dfs(journey.steps[0].id, [], [], set())

    return PathEnumerationResult(
        journey_id=journey.id,
        journey_name=journey.name,
        total_paths=len(completed_paths),
        paths=completed_paths,
    )


# ── Single-step evaluator (for step-by-step simulation) ───────────────────────

def evaluate_step(journey: Journey, step_id: str, attributes: Dict[str, Any],
                  sim_date: Optional[date] = None) -> Optional[StepEvalResult]:
    """
    Evaluate a single journey step given the contact's current attributes.
    Returns the outcome and the next step id, without advancing the journey.
    """
    step_map: Dict[str, JourneyStep] = {s.id: s for s in journey.steps}
    step = step_map.get(step_id)
    if not step:
        return None

    outcome: str
    next_id: Optional[str] = None
    condition_result: Optional[bool] = None
    condition_label: Optional[str] = None
    data_updates: Optional[Dict[str, Any]] = None
    wait_label: Optional[str] = None

    if step.type in (StepType.EMAIL, StepType.SMS, StepType.PUSH):
        outcome = "sent"
        next_id = step.next

    elif step.type == StepType.WAIT:
        d = step.config.get("duration", "?")
        u = step.config.get("unit", "days")
        outcome = f"waited_{d}_{u}"
        wait_label = f"{d} {u}"
        next_id = step.next

    elif step.type == StepType.DECISION_SPLIT:
        condition = step.config.get("condition", {})
        try:
            condition_result = _eval(condition, attributes, sim_date=sim_date)
        except ValueError:
            condition_result = False
        condition_label = _condition_label(step)
        outcome = "yes" if condition_result else "no"
        branches = step.next if isinstance(step.next, dict) else {}
        next_id = branches.get(outcome)

    elif step.type == StepType.UPDATE_DATA:
        data_updates = step.config.get("updates", {})
        outcome = "updated"
        next_id = step.next

    elif step.type == StepType.EXIT:
        outcome = step.config.get("reason", "exit")
        next_id = None

    else:
        outcome = "processed"
        next_id = step.next

    return StepEvalResult(
        step_id=step.id,
        step_name=step.name,
        step_type=step.type,
        outcome=outcome,
        next_step_id=next_id,
        condition_result=condition_result,
        condition_label=condition_label,
        data_updates=data_updates,
        wait_label=wait_label,
    )


def _condition_label(step: JourneyStep) -> str:
    c = step.config.get("condition", {})
    if "probability" in c:
        return f"probability {int(c['probability']*100)}%"
    field = c.get("field", "?")
    op    = c.get("operator", "equals")
    val   = c.get("value", "")
    if op == "email_opened":
        return "contact opened the email"
    if op == "email_clicked":
        return "contact clicked the email"
    return f"{field} {op} {val}"
