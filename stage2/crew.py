"""MONITOR Problem 2: deterministic six-node review crew.

The implementation is dependency-free and keeps durable memory across cycles.
It accepts an Atlas-compatible detector and optional hub/gateway HTTP endpoints.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class ReviewReport:
    cut: int
    protocol_version: int
    findings: List[dict] = field(default_factory=list)
    queries: List[dict] = field(default_factory=list)
    deviations: List[dict] = field(default_factory=list)
    escalations: List[dict] = field(default_factory=list)
    trace: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cut": self.cut,
            "protocol_version": self.protocol_version,
            "findings": self.findings,
            "queries": self.queries,
            "deviations": self.deviations,
            "escalations": self.escalations,
            "trace": self.trace,
        }


class ReviewCrew:
    """Six-node MONITOR workflow with cross-cycle duplicate prevention."""

    def __init__(self, hub_url: str, gateway_url: str, team_key: str, atlas: Any):
        self.hub_url = hub_url.rstrip("/")
        self.gateway_url = gateway_url.rstrip("/")
        self.team_key = team_key
        self.atlas = atlas
        self.raised_queries: Set[Tuple[str, str, int]] = set()
        self.made_escalations: Set[Tuple[str, str]] = set()
        self.rejected: Set[Tuple[str, str]] = set()
        self.subject_cycles: Dict[str, int] = {}
        self.site_issues: Dict[str, int] = {}
        self.history: List[dict] = []

    def _trace(self, report: ReviewReport, node: str, decision: str, **extra: Any) -> None:
        item = {"node": node, "decision": decision}
        item.update(extra)
        report.trace.append(item)

    def _post(self, base: str, path: str, payload: dict) -> Optional[dict]:
        if not base:
            return None
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            base + path,
            data=data,
            headers={"Content-Type": "application/json", "X-Team-Key": self.team_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except Exception:
            return None

    def _detect(self, cut: int, protocol_version: int, report: ReviewReport) -> List[dict]:
        # Rebuild the graph at every cycle so amendment changes are visible.
        try:
            self.atlas.graph.build(cut=cut)
        except Exception as exc:
            self._trace(report, "detect", "graph_rebuild_failed", error=str(exc))
        findings: List[dict] = []
        detector = getattr(self.atlas, "detect_findings", None)
        if callable(detector):
            findings = detector(cut=cut, protocol_version=protocol_version) or []
        self._trace(report, "detect", "completed", count=len(findings), cut=cut, protocol_version=protocol_version)
        return findings

    def _medical_review(self, findings: List[dict], report: ReviewReport) -> List[dict]:
        escalations = []
        for finding in findings:
            code = str(finding.get("code", ""))
            subject = str(finding.get("usubjid", ""))
            severity = str(finding.get("severity", "")).upper()
            key = (code, subject)
            if key in self.rejected:
                continue
            if severity in {"CRITICAL", "SERIOUS", "HIGH"} or code in {"SAE_MISCODED", "SERIOUS_AE"}:
                if key not in self.made_escalations:
                    escalation = dict(finding)
                    escalation.setdefault("alternatives", ["Escalate for medical monitor decision", "Keep under monitoring"])
                    escalations.append(escalation)
                    self.made_escalations.add(key)
            self._trace(report, "medical_review", "reviewed", code=code, usubjid=subject, severity=severity)
        self._trace(report, "medical_review", "completed", escalations=len(escalations))
        return escalations

    def _data_manager(self, findings: List[dict], cut: int, report: ReviewReport) -> List[dict]:
        queries = []
        for finding in findings:
            if not finding.get("data_problem"):
                continue
            subject = str(finding.get("usubjid", ""))
            domain = str(finding.get("domain", ""))
            seq = int(finding.get("seq", 0) or 0)
            key = (subject, domain, seq)
            if key in self.raised_queries:
                continue
            query = {
                "usubjid": subject,
                "domain": domain,
                "seq": seq,
                "cut": cut,
                "text": finding.get("query_text") or finding.get("rationale", "Please verify this record against source."),
            }
            self.raised_queries.add(key)
            queries.append(query)
            self._post(self.hub_url, "/queries", query)
        self._trace(report, "data_manager", "completed", queries=len(queries))
        return queries

    def _compliance(self, findings: List[dict], protocol_version: int, report: ReviewReport) -> List[dict]:
        deviations = [f for f in findings if f.get("compliance_deviation")]
        self._trace(report, "compliance", "completed", protocol_version=protocol_version, deviations=len(deviations))
        return deviations

    def _human_gate(self, escalations: List[dict], report: ReviewReport) -> List[dict]:
        pending = []
        for escalation in escalations:
            payload = dict(escalation)
            response = self._post(self.gateway_url, "/escalations", payload)
            if response:
                payload["monitor_response"] = response
            pending.append(payload)
        self._trace(report, "human_gate", "completed", pending=len(pending))
        return pending

    def _execute(self, report: ReviewReport) -> None:
        self._trace(report, "execute", "cycle_complete", findings=len(report.findings), queries=len(report.queries), escalations=len(report.escalations), deviations=len(report.deviations))
        self.history.append(report.to_dict())

    def run_cycle(self, cut: int, protocol_version: int) -> ReviewReport:
        report = ReviewReport(cut=cut, protocol_version=protocol_version)
        report.findings = self._detect(cut, protocol_version, report)
        for finding in report.findings:
            subject = str(finding.get("usubjid", ""))
            if subject:
                self.subject_cycles[subject] = self.subject_cycles.get(subject, 0) + 1
            site = str(finding.get("site", ""))
            if site:
                self.site_issues[site] = self.site_issues.get(site, 0) + 1
        drafts = self._medical_review(report.findings, report)
        report.queries = self._data_manager(report.findings, cut, report)
        report.deviations = self._compliance(report.findings, protocol_version, report)
        report.escalations = self._human_gate(drafts, report)
        self._execute(report)
        return report
