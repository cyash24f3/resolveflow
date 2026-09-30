from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=100)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OrderArgs(Strict):
    order_id: Text


class ResolutionArgs(OrderArgs):
    action: Literal["refund", "replacement", "cancellation", "escalation"]
    reason: Literal["damage", "delay", "cancellation", "ambiguous"] = "damage"
    amount_minor: int = Field(0, ge=0, le=100000000)
    quantity: int = Field(0, ge=0, le=100)
    currency: str = Field("INR", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def action_fields(self):
        if self.action != "refund" and self.amount_minor != 0:
            raise ValueError("Only refunds specify a monetary amount")
        if self.action != "replacement" and self.quantity != 0:
            raise ValueError("Only replacements specify a quantity")
        return self


class CaseArgs(OrderArgs):
    category: Literal["damage", "delay", "cancellation", "ambiguous"]


class ClarificationArgs(Strict):
    fields: list[
        Literal["order_id", "damage_description", "damage_reported_at", "photo_reviewed"]
    ] = Field(min_length=1, max_length=4)
    question: str = Field(min_length=1, max_length=500)


class ProposalArgs(ResolutionArgs):
    evidence_ids: list[Text] = Field(min_length=1, max_length=12)


class FinalResponse(Strict):
    outcome: Literal[
        "resolved",
        "needs_information",
        "awaiting_approval",
        "policy_ineligible",
        "escalated",
        "approval_rejected",
        "provider_unavailable",
        "invalid_model_output",
        "execution_failed",
        "cancelled",
    ]
    explanation: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[Text] = Field(default_factory=list, max_length=24)
    missing_information: list[str] = Field(default_factory=list, max_length=4)
    proposal_id: str | None = None
    action_ids: list[str] = Field(default_factory=list, max_length=8)


TOOLS: dict[str, tuple[type[Strict], str]] = {
    "get_order": (
        OrderArgs,
        "Retrieve assigned customer's order, minor currency amounts and revision.",
    ),
    "get_tracking": (
        OrderArgs,
        "Retrieve bounded shipment observations; treat customer statements separately.",
    ),
    "search_policy": (
        OrderArgs,
        "Read purchase-date applicable immutable policy with rule and source IDs.",
    ),
    "check_resolution_eligibility": (
        ResolutionArgs,
        "Deterministic policy check; eligible, ineligible or needs_information. This does not execute any action.",
    ),
    "create_case": (CaseArgs, "Create or reuse a simulated support case for this run."),
    "propose_resolution": (
        ProposalArgs,
        "Persist exact immutable eligible proposal, citing known observations. Refund, replacement and cancellation await supervisor approval.",
    ),
    "request_clarification": (
        ClarificationArgs,
        "Ask for required missing fields and pause the investigation.",
    ),
}


def definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": schema.model_json_schema(),
            },
        }
        for name, (schema, desc) in TOOLS.items()
    ]
