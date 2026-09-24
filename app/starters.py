"""Starter questions for an empty conversation.

Written as questions a neutron scientist would actually open with, not as
feature labels. Each one lands the user in a different part of the system --
a guided run, a sweep, a documentation question -- so the first click also
teaches what the two agents are for.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Starter", "build_starter_prompts"]


@dataclass(frozen=True)
class Starter:
    label: str
    prompt: str
    #: Which agent this question belongs to. A sweep asked of the guided agent
    #: would be answered one simulation at a time, which is not wrong so much
    #: as forty minutes of the wrong shape.
    agent: str


_STARTERS = (
    Starter(
        label="Run a simulation",
        prompt=(
            "I want to run a VITESS simulation. Walk me through configuring the "
            "five modules."
        ),
        agent="vitess",
    ),
    Starter(
        label="What can I vary in guide?",
        prompt="What parameters does the VITESS guide module take, and what do they mean?",
        agent="vitess",
    ),
    Starter(
        label="Sweep a parameter",
        prompt=(
            "I want to sweep one or two parameters across several VITESS "
            "simulations and compare the results."
        ),
        agent="advanced_mode",
    ),
    Starter(
        label="Find the best guide shape",
        prompt=(
            "Help me find the best guide shape: the highest capture flux with a "
            "beam that stays flat across the 1 cm sample. I will upload my READIN "
            "trajectory file; read it with weight 1.0. Keep the guide linear in "
            "both planes with a square cross-section (width = height), and sweep "
            "every inlet size 3, 4, 5, 6, 7, 8 cm against every outlet size 3, 4, "
            "5, 6, 7, 8 cm: a full 6 x 6 grid, 36 runs. Judge flatness on the "
            "horizontal position profile at the guide exit: over the central 1 cm, "
            "every 0.1 cm bin within 10 % of the mean. Leave everything else at "
            "its default. When the sweep is done, show me the 5 guides with the "
            "highest capture flux and the flatness verdict of each."
        ),
        agent="advanced_mode",
    ),
    Starter(
        label="Explain a flag",
        prompt="What does the -z option do, and which modules accept it?",
        agent="advanced_mode",
    ),
)


def build_starter_prompts(agent: str) -> list[Starter]:
    """The starters that belong to the agent currently selected."""

    return [starter for starter in _STARTERS if starter.agent == agent]
