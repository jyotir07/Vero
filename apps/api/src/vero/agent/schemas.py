"""What the agent is allowed to say.

One shape, deliberately narrow: a tool to call, its arguments, and why. There is no
field for a target state, because choosing where the application goes next is the state
machine's job. The model cannot ask for something the schema cannot express.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
