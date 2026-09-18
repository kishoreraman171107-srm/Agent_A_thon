"""
ATLAS Problem 1 – Starter schemas.
These dataclasses define the official contract between the evaluation harness and solutions.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class RecordRef:
    """Pointer to a single source record in the study dataset or document."""
    domain: str                       # e.g. "LB", "AE", "DM", "EX", "CM", "MH", "SV", "DS", "DOC"
    usubjid: Optional[str] = None     # unique subject identifier (None if domain=="DOC")
    seq: Optional[int] = None         # sequence number within domain (LBSEQ, AESEQ, etc.)
    document: Optional[str] = None    # for domain=="DOC": e.g. "lab-manual", "protocol_v1"
    section: Optional[str] = None     # for domain=="DOC": e.g. "units", "§7"

    def to_dict(self) -> dict:
        if self.domain == "DOC":
            d = {"domain": self.domain}
            if self.document is not None:
                d["document"] = self.document
            if self.section is not None:
                d["section"] = self.section
            return d
        
        d = {"domain": self.domain, "usubjid": self.usubjid or ""}
        if self.seq is not None:
            d["seq"] = self.seq
        return d


@dataclass
class Question:
    """A single question posed by the harness."""
    question_id: str
    kind: str = "lookup"              # "count" | "lookup" | "finding" | "trap"
    question: str = ""                # question text
    category: Optional[str] = None    # alias for kind
    protocol_section: Optional[str] = None
    requires_temporal: bool = False
    domain_hint: Optional[str] = None
    
    def __post_init__(self):
        if self.category and not self.kind:
            self.kind = self.category
        elif not self.category and self.kind:
            self.category = self.kind
        if not self.question_id and hasattr(self, 'id'):
            self.question_id = getattr(self, 'id')

    @property
    def id(self) -> str:
        return self.question_id


@dataclass
class Answer:
    """The system's response to a Question."""
    question_id: str
    answer: Any                       # int for count, list/str for lookup/finding, [] for trap
    text: str = ""                    # narrative response / sentence
    evidence: List[RecordRef] = field(default_factory=list)
    confidence: float = 0.85          # honest calibrated confidence (0.0 – 1.0)
    steps_used: int = 1
    tokens_used: int = 0
    reasoning: Optional[str] = None

    def __post_init__(self):
        if self.reasoning and not self.text:
            self.text = self.reasoning
        elif self.text and not self.reasoning:
            self.reasoning = self.text

    def to_dict(self) -> dict:
        ev_list = []
        for e in self.evidence:
            if hasattr(e, "to_dict"):
                ev_list.append(e.to_dict())
            elif isinstance(e, dict):
                ev_list.append(e)
        return {
            "question_id": self.question_id,
            "answer": self.answer,
            "text": self.text or (self.reasoning or ""),
            "evidence": ev_list,
            "confidence": round(float(self.confidence), 4),
            "steps_used": int(self.steps_used),
            "tokens_used": int(self.tokens_used),
        }


@dataclass
class GraphStats:
    """Metadata returned by StudyGraph.build()."""
    nodes: int
    edges: int
    subjects: int
    ms: int                           # build duration in milliseconds
    cut: Optional[int] = None         # study cut version

    def to_dict(self) -> dict:
        return {
            "nodes": int(self.nodes),
            "edges": int(self.edges),
            "subjects": int(self.subjects),
            "ms": int(self.ms),
            "cut": self.cut,
        }
