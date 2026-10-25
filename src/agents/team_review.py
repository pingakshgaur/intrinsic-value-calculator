"""
Independent Research Review Lead's team. Runs after every other team.

    Research Validation Analyst   checks every finding against the evidence
                                  rules; findings that fail are not allowed
                                  to move the valuation
    Bull Case Analyst             the strongest honest case FOR the stock
    Bear Case Analyst             the strongest honest case AGAINST it

Validation runs first so that Bull and Bear argue only from findings that
passed. Conviction (0..1) from Bull and Bear tilts the scenario
probabilities in the formula; their narratives go in the report.
"""

from agents import settings as S
from agents.base import Agent, Evidence, cited, clamp

LEAD = "review_lead"


def _evidence_ok(e, rules):
    age = e.age_days()
    if not e.source:
        return False, "no source"
    if rules["require_url"] and e.kind in ("news", "filing") and not e.url:
        return False, "no URL"
    if age is not None:
        limit = rules["news_age"] if e.kind == "news" else rules["data_age"]
        if age > limit:
            return False, f"{age} days old"
        if age < -400:
            return False, "dated in the future"
    return True, ""


# ==================================================================== 17
class ResearchValidationAnalyst(Agent):
    KEY = "research_validation_analyst"
    NAME = "Research Validation Analyst"
    LEAD = LEAD
    ROLE = "Enforces the evidence rules on every other analyst's finding."

    def analyse(self, ctx, f):
        rules = {
            "require_url": bool(S.get("agents.validation.require_source_url", True)),
            "news_age": S.num("agents.validation.max_news_age_days", 30),
            "data_age": S.num("agents.validation.max_evidence_age_days", 400),
            "min_sources": int(S.num("agents.validation.min_sources_for_claim", 1)),
        }
        checked = passed = ok_status = 0
        problems = []
        for fd in ctx.findings.values():
            if fd.lead == LEAD:
                continue
            checked += 1
            if fd.status != "ok":
                fd.validated = False
                continue
            ok_status += 1
            good = []
            for e in fd.evidence:
                ok, why = _evidence_ok(e, rules)
                if ok:
                    good.append(e)
            if len(good) >= rules["min_sources"]:
                fd.validated = True
                passed += 1
                # red flags must point at surviving evidence when they cite any
                ids = {e.id for e in good}
                kept = []
                for fl in fd.flags:
                    if "[E" in fl and not any(i in fl for i in ids):
                        problems.append(f"{fd.agent}: flag dropped, its evidence failed validation - {fl[:80]}")
                        continue
                    kept.append(fl)
                fd.flags = kept
            else:
                fd.validated = False
                problems.append(f"{fd.agent}: no evidence passed the rules ({len(fd.evidence)} offered)")

        # cross-check: the price the valuation used vs. the live tape
        live, used = ctx.last_price, ctx.base.get("price")
        if live and used and abs(live / used - 1) > 0.02:
            problems.append(f"price mismatch: valuation used {used:.2f}, latest close {live:.2f}")

        coverage = ok_status / checked if checked else 0.0
        rate = passed / checked if checked else 0.0
        f.signals.update({
            "checked": checked, "passed": passed, "coverage": coverage, "pass_rate": rate,
            "problems": problems,
        })
        f.evidence.append(Evidence(source="Validation of this run's findings",
                                   title=f"{passed}/{checked} findings passed", date=ctx.shared.get("as_of", ""),
                                   kind="derived"))
        f.notes.extend(problems[:10])
        f.score = 0.0  # validation does not take a side
        f.confidence = 1.0
        f.summary = (
            f"{passed} of {checked} findings met the evidence rules; "
            f"{ok_status} analysts produced usable output."
            + (f" {len(problems)} issue(s) logged." if problems else "")
        )


def _side(ctx, positive):
    """Validated findings ranked by how hard they push one way."""
    rows = []
    for fd in ctx.findings.values():
        if fd.lead == LEAD or not fd.validated:
            continue
        push = fd.score * fd.confidence
        if (push > 0.05) if positive else (push < -0.05):
            rows.append((abs(push), fd))
    rows.sort(key=lambda r: -r[0])
    return rows


class _CaseAnalyst(Agent):
    POSITIVE = True
    USES_LLM = True

    def analyse(self, ctx, f):
        rows = _side(ctx, self.POSITIVE)
        # red flags are always part of the bear case, whatever the scores say
        flags = [fl for fd in ctx.findings.values() if fd.validated for fl in fd.flags]
        total_w = sum(fd.confidence for fd in ctx.findings.values() if fd.validated and fd.lead != LEAD) or 1.0
        strength = sum(p for p, _ in rows) / total_w
        if not self.POSITIVE:
            strength += 0.15 * len(flags)
        conviction = clamp(strength * 1.5, 0, 1)

        points = [{"text": f"{fd.agent.replace('_', ' ')}: {fd.summary}", "evidence": [e.id for e in fd.evidence[:2]]}
                  for _, fd in rows[:6]]
        if not self.POSITIVE:
            points += [{"text": fl, "evidence": []} for fl in flags[:5]]
        for _, fd in rows[:6]:
            f.evidence.extend(fd.evidence[:2])
        if not f.evidence and points:
            f.evidence.append(Evidence(source="Validated findings", title=f"{len(points)} points",
                                       date=ctx.shared.get("as_of", ""), kind="derived"))

        side = "bull" if self.POSITIVE else "bear"
        thesis = None
        if points:
            lines = "\n".join(f"- {p['text']} {p['evidence']}" for p in points)
            v = ctx.base
            reply = self.ask_llm(
                "smart",
                f"You are the {side} case analyst on an Indian equity research team. "
                f"Write the strongest HONEST {side} case using only the validated points "
                "given; do not invent facts or numbers. 3-5 claims, each citing evidence "
                "ids from the points (an empty list is allowed only for red flags). Also "
                "give the single thing that would most clearly prove this case wrong. "
                '{"thesis":str,"claims":[{"text":str,"evidence":[id]}],"invalidated_if":str}',
                f"Company: {ctx.name} ({ctx.sector})\nPrice {v.get('price')}, Hybrid value "
                f"{v.get('hybrid')}\nValidated points:\n{lines}",
                max_tokens=700,
            )
            if isinstance(reply, dict) and reply.get("thesis"):
                f.used_llm = True
                ev_all = [e for _, fd in rows for e in fd.evidence]
                claims, dropped = cited(reply.get("claims"), ev_all)
                if not self.POSITIVE:
                    claims += [{"text": c.get("text", ""), "evidence": []} for c in (reply.get("claims") or [])
                               if isinstance(c, dict) and not c.get("evidence") and any(
                                   (c.get("text") or "")[:30].lower() in fl.lower() for fl in flags)]
                thesis = {
                    "thesis": str(reply["thesis"])[:800],
                    "claims": claims,
                    "invalidated_if": str(reply.get("invalidated_if", ""))[:300],
                }
                if dropped:
                    f.notes.append(f"{dropped} uncited claim(s) removed from the {side} case")
        if thesis is None:
            thesis = {
                "thesis": (f"The {side} case rests on {len(points)} validated point(s)." if points
                           else f"No validated evidence supports a {side} case."),
                "claims": points,
                "invalidated_if": "",
            }
        f.signals.update({"conviction": conviction, "points": len(points), "case": thesis})
        f.score = conviction if self.POSITIVE else -conviction
        f.confidence = min(1.0, 0.3 + 0.1 * len(points))
        f.summary = f"{side.title()} conviction {conviction:.2f} from {len(points)} point(s). {thesis['thesis'][:220]}"


# ==================================================================== 15
class BullCaseAnalyst(_CaseAnalyst):
    KEY = "bull_case_analyst"
    NAME = "Bull Case Analyst"
    LEAD = LEAD
    ROLE = "Builds the strongest honest case for the stock."
    POSITIVE = True


# ==================================================================== 16
class BearCaseAnalyst(_CaseAnalyst):
    KEY = "bear_case_analyst"
    NAME = "Bear Case Analyst"
    LEAD = LEAD
    ROLE = "Builds the strongest honest case against the stock."
    POSITIVE = False


TEAM = [ResearchValidationAnalyst, BullCaseAnalyst, BearCaseAnalyst]
