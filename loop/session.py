"""Within-session persistence: a play session that accumulates across loops.

The core loop (``loop/core.py``) is *stateless per call* — :meth:`Mirror.step`
takes a prior :class:`PlayerState` and returns the next one, and the worked
example threads that state turn-to-turn inside a single function call. That is
enough to *run* a loop, but not to *persist* one: nothing owns the running state
across the boundaries a real play session crosses (a paused turn, a reloaded
page, a separate process). Without an owner, every loop would start from a blank
mirror, no adaptation could accumulate, and loop 3 would look exactly like loop
1 — the personalization the thesis bets on (``docs/THESIS.md``) would never get
off the ground.

:class:`Session` is that owner. It

1. holds the accumulated :class:`PlayerState`,
2. advances it exactly one loop at a time — ``adapt`` the scene from the
   accumulated state, ``step`` it, then fold the new state back in, and
3. serializes the whole thing to a plain dict / JSON (and to disk) so a session
   saved after loop *n* resumes — even in another process — with loops *1..n*
   intact, ``announced`` patterns included.

Because the adaptation engine reads *only* from that accumulated state, a
resumed loop's content — its adapted choice order, its ranked prediction, and
its visible "Mirror noticed…" reflection — is **provably a function of the loops
that came before it**. ``loop/tests/test_session.py`` pins that down: loop 3's
reflection cites the in-game evidence from loops 1 and 2, and a non-persisting
control shows the same loop 3 reflecting *nothing* — which is what makes the
claim falsifiable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .core import Choice, Mirror, PlayerState, Scene, Turn

#: Bump when the persisted shape changes incompatibly. Loading an unknown
#: version fails loudly rather than silently mis-restoring a session.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PlayedLoop:
    """The record of one played loop, kept for persistence and audit.

    Captures the *content the player was actually shown* this loop — the scene
    as offered (post-adaptation choice order), the Mirror's ranked prediction,
    the choice made, and the rendered reflection if one fired this loop — so a
    later loop's dependence on earlier ones can be inspected directly, not just
    asserted in prose.
    """

    loop_number: int  # 1-based: the nth loop of the session
    scene_id: str
    declared_order: tuple[str, ...]  # choice ids as the scene declared them
    offered_order: tuple[str, ...]  # choice ids as the Mirror offered them (post-adapt)
    predicted_actions: tuple[str, ...]
    actual_action: str
    reflection: str | None  # the rendered "Mirror noticed…" line, if it fired

    @property
    def adapted(self) -> bool:
        """True when the Mirror re-ordered this scene from accumulated state.

        On loop 1 (no history) this is always False; it can only become True
        because earlier loops moved a tendency — i.e. it is itself evidence that
        the loop reflects the ones before it.
        """
        return self.offered_order != self.declared_order


# --- (de)serialization of the core types -------------------------------------
# Kept here rather than on the core dataclasses so loop/core.py stays a pure,
# dependency-free statement of the loop's shape. JSON has no tuples, so every
# round-trip re-tuples on the way back in.


def _choice_to_dict(choice: Choice) -> dict:
    return {
        "id": choice.id,
        "text": choice.text,
        "tendency": choice.tendency,
        "evidence": choice.evidence,
    }


def _choice_from_dict(data: dict) -> Choice:
    return Choice(
        id=data["id"],
        text=data["text"],
        tendency=data["tendency"],
        evidence=data["evidence"],
    )


def _state_to_dict(state: PlayerState) -> dict:
    return {
        "history": [
            {"scene_id": turn.scene_id, "choice": _choice_to_dict(turn.choice)}
            for turn in state.history
        ],
        # sorted so the serialized form is stable/diffable; order is irrelevant
        # because it restores into a frozenset.
        "announced": sorted(state.announced),
    }


def _state_from_dict(data: dict) -> PlayerState:
    history = tuple(
        Turn(scene_id=turn["scene_id"], choice=_choice_from_dict(turn["choice"]))
        for turn in data["history"]
    )
    return PlayerState(history=history, announced=frozenset(data["announced"]))


def _loop_to_dict(loop: PlayedLoop) -> dict:
    return {
        "loop_number": loop.loop_number,
        "scene_id": loop.scene_id,
        "declared_order": list(loop.declared_order),
        "offered_order": list(loop.offered_order),
        "predicted_actions": list(loop.predicted_actions),
        "actual_action": loop.actual_action,
        "reflection": loop.reflection,
    }


def _loop_from_dict(data: dict) -> PlayedLoop:
    return PlayedLoop(
        loop_number=data["loop_number"],
        scene_id=data["scene_id"],
        declared_order=tuple(data["declared_order"]),
        offered_order=tuple(data["offered_order"]),
        predicted_actions=tuple(data["predicted_actions"]),
        actual_action=data["actual_action"],
        reflection=data["reflection"],
    )


class Session:
    """A persistent play session: the owner of state across loops.

    Construct a fresh session, drive it one loop at a time with :meth:`play`,
    and persist/resume it with :meth:`to_dict` / :meth:`from_dict` (or the JSON
    and disk wrappers). The accumulated :class:`PlayerState` is the single thing
    that carries a player's history forward, so every adaptation a later loop
    shows is grounded in the loops already stored here.
    """

    def __init__(
        self,
        session_id: str = "session",
        *,
        mirror: Mirror | None = None,
        state: PlayerState | None = None,
        loops: list[PlayedLoop] | tuple[PlayedLoop, ...] | None = None,
    ) -> None:
        self.session_id = session_id
        self.mirror = mirror if mirror is not None else Mirror()
        self.state = state if state is not None else PlayerState()
        self.loops: list[PlayedLoop] = list(loops) if loops is not None else []

    @property
    def loop_count(self) -> int:
        """How many loops this session has accumulated."""
        return self.state.turn_count

    def play(self, scene: Scene, choice_id: str) -> PlayedLoop:
        """Advance the session by exactly one loop and persist the result.

        Runs the full turn against the *accumulated* state — adapt the scene so
        the predicted option leads, step it to get the prediction/reflection,
        then **fold the new state back into the session** so the next loop sees
        this one. Returns the :class:`PlayedLoop` content the player was shown.
        """
        offered = self.mirror.adapt(self.state, scene)
        result = self.mirror.step(self.state, offered, choice_id)
        self.state = result.state  # the persistence step: accumulate, don't discard
        record = PlayedLoop(
            loop_number=self.state.turn_count,
            scene_id=scene.id,
            declared_order=tuple(c.id for c in scene.choices),
            offered_order=tuple(c.id for c in offered.choices),
            predicted_actions=result.predicted_actions,
            actual_action=result.actual_action,
            reflection=result.reflection.render() if result.reflection else None,
        )
        self.loops.append(record)
        return record

    # --- persistence ---------------------------------------------------------

    def to_dict(self) -> dict:
        """A JSON-serializable snapshot of the whole session.

        Includes the Mirror's ``notice_threshold`` and the accumulated state
        (history *and* the ``announced`` set) so a restored session behaves
        identically — it won't re-notice a pattern it already surfaced.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "notice_threshold": self.mirror.notice_threshold,
            "state": _state_to_dict(self.state),
            "loops": [_loop_to_dict(loop) for loop in self.loops],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """Rebuild a session from :meth:`to_dict` output.

        Restores the accumulated state exactly, so the next :meth:`play` adapts
        from loops *1..n* even though they were played elsewhere/earlier.
        """
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported session schema version {version!r} "
                f"(this build writes/reads v{SCHEMA_VERSION})"
            )
        return cls(
            session_id=data["session_id"],
            mirror=Mirror(notice_threshold=data["notice_threshold"]),
            state=_state_from_dict(data["state"]),
            loops=[_loop_from_dict(loop) for loop in data["loops"]],
        )

    def to_json(self) -> str:
        """Serialize to an indented, key-sorted JSON string."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Session":
        """Rebuild a session from a JSON string written by :meth:`to_json`."""
        return cls.from_dict(json.loads(text))

    def save(self, path: str | Path) -> None:
        """Persist the session to ``path`` as JSON."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Session":
        """Resume a session previously written by :meth:`save`."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def demo() -> str:  # pragma: no cover - exercised via the public API in tests
    """A runnable proof that loop 3 reflects loops 1-2 across a save/restore.

    Plays two kind choices, persists the session to a JSON string, restores it
    into a brand-new :class:`Session` (fresh :class:`Mirror`), then plays loop 3
    and shows that its reflection cites the acts from loops 1 and 2.
    """
    from .example import CORRIDOR, INTAKE, RECORDS

    live = Session(session_id="demo")
    live.play(INTAKE, "c_reassure")  # loop 1
    live.play(RECORDS, "c_close")  # loop 2

    # Persist after loop 2 and resume in a completely separate object.
    resumed = Session.from_json(live.to_json())
    restored_loops = resumed.loop_count  # history that came back from JSON
    loop3 = resumed.play(CORRIDOR, "c_help")  # loop 3, played after restore

    lines = [
        "Loops 1-2 played, session serialized to JSON, then restored.",
        f"Resumed session came back with {restored_loops} loops of history.",
        "",
        "Loop 3 content (played only after the restore):",
        f"  {loop3.reflection}",
    ]
    return "\n".join(lines)


def main() -> int:  # pragma: no cover - thin CLI wrapper
    print(demo())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
