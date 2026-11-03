"""Typed, validated outputs for every council role (Pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["research_scientist", "microstructure_analyst", "behavioral_scientist", "macro_scenario_designer",
               "adversarial_researcher", "risk_researcher", "evaluation_scientist", "evolution_engineer"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=3, max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=8)  # metric keys / event refs


class ProposedExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str
    replicates: int = Field(ge=2, le=64)
    rationale: str = Field(max_length=400)


class RoleReport(BaseModel):
    """Every role must separate what it saw from what it guesses."""

    model_config = ConfigDict(extra="forbid")
    role: Role
    observations: list[Claim] = Field(default_factory=list, max_length=12)  # directly measured
    hypotheses: list[Claim] = Field(default_factory=list, max_length=8)  # testable explanations
    assumptions: list[Claim] = Field(default_factory=list, max_length=8)  # taken as given
    conclusions: list[Claim] = Field(default_factory=list, max_length=6)  # only what the evidence supports
    confidence: float = Field(ge=0, le=1)
    recommended_experiments: list[ProposedExperiment] = Field(default_factory=list, max_length=4)
    risks: list[str] = Field(default_factory=list, max_length=6)


class CodeEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(pattern=r"^src/evolutionx/[a-z_/]+\.py$")
    search: str = Field(min_length=1, max_length=4000)
    replace: str = Field(max_length=6000)


class CodeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9_\-]{3,60}$")
    title: str = Field(max_length=120)
    rationale: str = Field(max_length=1200)
    hypothesis: str = Field(max_length=600)
    edits: list[CodeEdit] = Field(min_length=1, max_length=6)


class GenomeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: str
    genomes: list[dict[str, float]] = Field(max_length=6)
    rationale: str = Field(max_length=600)
