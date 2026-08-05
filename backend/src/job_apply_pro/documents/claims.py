from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from job_apply_pro.domain.knowledge import (
    CandidateClaim,
    ClaimPermittedUse,
    ClaimType,
    ClaimVerificationStatus,
    DocumentExtraction,
    SensitivityLevel,
)
from job_apply_pro.domain.workflow import utc_now

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "typescript": ("typescript", "type script"),
    "javascript": ("javascript", "java script"),
    "react": ("react", "react.js", "reactjs"),
    "sql": ("sql", "sqlite", "postgresql", "mysql"),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure",),
    "docker": ("docker", "containerization"),
    "kubernetes": ("kubernetes", "k8s"),
    "network_engineering": ("network engineering", "network engineer"),
    "bgp": ("bgp", "border gateway protocol"),
    "automation": ("automation", "automated"),
    "playwright": ("playwright",),
    "fastapi": ("fastapi",),
}

MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

PERIOD_PATTERN = re.compile(
    r"(?P<start_month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(?P<start_year>19\d{2}|20\d{2})\s*(?:-|\u2013|\u2014|to)\s*"
    r"(?:(?P<end_month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(?P<end_year>19\d{2}|20\d{2})|(?P<present>Present|Current))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimProposal:
    canonical_key: str
    statement: str
    claim_type: ClaimType
    value: dict[str, object]
    source_location: str
    confidence: float
    sensitivity: SensitivityLevel
    start_date: date | None = None
    end_date: date | None = None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")[:100]


def _claim_id(source_id: str, key: str, location: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{key}:{location}".encode()).hexdigest()
    return f"claim-{digest[:29]}"


def _period(line: str) -> tuple[date, date] | None:
    match = PERIOD_PATTERN.search(line)
    if match is None:
        return None
    start = date(
        int(match.group("start_year")),
        MONTHS[match.group("start_month")[:3].casefold()],
        1,
    )
    if match.group("present"):
        today = date.today()
        end = date(today.year, today.month, 1)
    else:
        end = date(
            int(match.group("end_year")),
            MONTHS[match.group("end_month")[:3].casefold()],
            1,
        )
    return start, end if end >= start else start


def _skill_names(text: str) -> list[str]:
    lowered = text.casefold()
    return [
        skill
        for skill, aliases in SKILL_ALIASES.items()
        if any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in aliases)
    ]


def propose_claims(
    profile_id: str, evidence_source_id: str, extraction: DocumentExtraction
) -> list[CandidateClaim]:
    proposals: list[ClaimProposal] = []
    email_match = re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", extraction.plain_text)
    if email_match:
        email = email_match.group(0).rstrip(".,;:")
        proposals.append(
            ClaimProposal(
                canonical_key="contact.email",
                statement=f"Candidate email is {email}",
                claim_type=ClaimType.CONTACT,
                value={"email": email},
                source_location=f"character:{email_match.start()}",
                confidence=0.98,
                sensitivity=SensitivityLevel.PERSONAL,
            )
        )
    phone_match = re.search(
        r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", extraction.plain_text
    )
    if phone_match:
        phone = phone_match.group(0)
        proposals.append(
            ClaimProposal(
                canonical_key="contact.phone",
                statement=f"Candidate phone is {phone}",
                claim_type=ClaimType.CONTACT,
                value={"phone": phone},
                source_location=f"character:{phone_match.start()}",
                confidence=0.95,
                sensitivity=SensitivityLevel.PERSONAL,
            )
        )

    for block in extraction.blocks:
        location = f"block:{block.index}" + (f":page:{block.page}" if block.page else "")
        skills = _skill_names(block.text)
        for skill in skills:
            proposals.append(
                ClaimProposal(
                    canonical_key=f"skill.{skill}",
                    statement=f"Candidate has experience with {skill.replace('_', ' ')}",
                    claim_type=ClaimType.SKILL,
                    value={"skill": skill},
                    source_location=location,
                    confidence=0.75,
                    sensitivity=SensitivityLevel.PUBLIC,
                )
            )
        period = _period(block.text)
        if period is not None:
            start, end = period
            context = PERIOD_PATTERN.sub("", block.text).strip(" |-" + chr(0x2013) + chr(0x2014))[
                :300
            ]
            for skill in skills or ["general"]:
                key_suffix = hashlib.sha256(
                    f"{skill}:{start}:{end}:{context}".encode()
                ).hexdigest()[:12]
                proposals.append(
                    ClaimProposal(
                        canonical_key=f"experience.{skill}.{key_suffix}",
                        statement=(
                            f"Candidate used {skill.replace('_', ' ')} from "
                            f"{start.isoformat()} through {end.isoformat()}"
                        ),
                        claim_type=ClaimType.EXPERIENCE,
                        value={"skill": skill, "context": context},
                        source_location=location,
                        confidence=0.72,
                        sensitivity=SensitivityLevel.PUBLIC,
                        start_date=start,
                        end_date=end,
                    )
                )
        for certification in re.findall(
            r"\b(CCNA|CCNP|CCIE|PMP|CISSP|CompTIA\s+(?:A\+|Network\+|Security\+))\b",
            block.text,
            flags=re.IGNORECASE,
        ):
            normalized = certification.upper()
            proposals.append(
                ClaimProposal(
                    canonical_key=f"certification.{_slug(normalized)}",
                    statement=f"Candidate reports certification {normalized}",
                    claim_type=ClaimType.CERTIFICATION,
                    value={"certification": normalized},
                    source_location=location,
                    confidence=0.82,
                    sensitivity=SensitivityLevel.PUBLIC,
                )
            )

    unique: dict[tuple[str, str], ClaimProposal] = {}
    for proposal in proposals:
        unique.setdefault((proposal.canonical_key, proposal.source_location), proposal)
    now = utc_now()
    return [
        CandidateClaim(
            id=_claim_id(evidence_source_id, proposal.canonical_key, proposal.source_location),
            profile_id=profile_id,
            evidence_source_id=evidence_source_id,
            canonical_key=proposal.canonical_key,
            statement=proposal.statement,
            claim_type=proposal.claim_type,
            value=proposal.value,
            source_location=proposal.source_location,
            start_date=proposal.start_date,
            end_date=proposal.end_date,
            confidence=proposal.confidence,
            verification_status=ClaimVerificationStatus.PROPOSED,
            permitted_use=ClaimPermittedUse.PROFILE_ONLY,
            sensitivity=proposal.sensitivity,
            locked=False,
            created_at=now,
            updated_at=now,
        )
        for proposal in unique.values()
    ]
