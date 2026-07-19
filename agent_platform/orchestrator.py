"""Multi-agent orchestration.

Two collaboration modes:

  cross_review
    One agent (the builder) drafts a solution. Every other agent independently
    reviews it and returns a verdict (APPROVE / REQUEST_CHANGES + comments).
    If any reviewer requests changes, the builder revises, incorporating all
    feedback. This repeats until every reviewer approves or `rounds` is reached.

  ensemble
    Every agent independently drafts its own solution. Then each agent
    cross-reviews the *other* agents' drafts. Finally a synthesizer agent
    merges the strongest elements into one consolidated solution.

Both modes persist every intermediate step to the DB so the UI can show the
full collaboration transcript, including who reviewed whom.
"""

import time

import db
import providers


def _log(run_id, round_, agent, role, kind, content, approved=None):
    db.add_step(
        run_id=run_id,
        round=round_,
        agent_id=agent["id"] if agent else None,
        agent_name=agent["name"] if agent else "system",
        role=role,
        kind=kind,
        content=content,
        approved=(None if approved is None else int(approved)),
    )


def _is_approved(review_text: str) -> bool:
    head = review_text.strip().upper()
    # Look at the first ~200 chars for a verdict marker.
    window = head[:200]
    if "REQUEST_CHANGES" in window or "REQUEST CHANGES" in window:
        return False
    if "VERDICT: APPROVE" in window or "APPROVED" in window or window.startswith("APPROVE"):
        return True
    # Heuristic fallback.
    return "approve" in review_text.lower() and "request" not in review_text.lower()[:120]


def _builder_prompt(task):
    return [
        {
            "role": "system",
            "content": (
                "You are a senior engineer collaborating with peer AI agents. "
                "Produce a concrete, correct, well-structured solution. Prefer "
                "working code with brief explanation. Be precise."
            ),
        },
        {
            "role": "user",
            "content": f"Task: {task['title']}\n\n{task['prompt']}\n\nProduce your best solution.",
        },
    ]


def _review_prompt(task, draft, reviewer_name, round_):
    return [
        {
            "role": "system",
            "content": (
                "You are a meticulous peer reviewer. Critically double-check a "
                "colleague's solution for correctness, edge cases, security and "
                "clarity. Start your reply with exactly one line: "
                "'VERDICT: APPROVE' or 'VERDICT: REQUEST_CHANGES', then give "
                "specific, actionable comments."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Review round {round_}. Task: {task['title']}\n\n{task['prompt']}\n\n"
                f"Solution to review:\n---\n{draft}\n---\n\n"
                f"Double-check this work as {reviewer_name} and give your verdict."
            ),
        },
    ]


def _revise_prompt(task, draft, reviews, round_):
    joined = "\n\n".join(f"Reviewer {i+1}:\n{r}" for i, r in enumerate(reviews))
    return [
        {
            "role": "system",
            "content": (
                "You are the builder revising your solution based on peer review. "
                "Address every valid concern. Output the full revised solution."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task: {task['title']}\n\n{task['prompt']}\n\n"
                f"Your previous draft (revision round {round_}):\n---\n{draft}\n---\n\n"
                f"Peer review feedback:\n{joined}\n\n"
                "Produce the improved solution."
            ),
        },
    ]


def _synthesis_prompt(task, drafts, reviews):
    parts = []
    for i, d in enumerate(drafts):
        parts.append(f"Candidate {i+1} (by {d['agent']['name']}):\n{d['text']}")
    review_txt = "\n\n".join(reviews)
    return [
        {
            "role": "system",
            "content": (
                "You are the synthesizer. Merge the strongest, most correct "
                "elements of several candidate solutions and the peer reviews into "
                "one consolidated final solution. Resolve conflicts explicitly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task: {task['title']}\n\n{task['prompt']}\n\n"
                + "\n\n".join(parts)
                + f"\n\nPeer reviews:\n{review_txt}\n\n"
                "Synthesize and merge into the best final solution."
            ),
        },
    ]


def run_cross_review(run_id, task, agents, rounds):
    builder = agents[0]
    reviewers = agents[1:] or [agents[0]]

    _log(run_id, 0, None, "system", "note",
         f"Cross-review: builder={builder['name']}; "
         f"reviewers={', '.join(a['name'] for a in reviewers)}; max rounds={rounds}.")

    draft = providers.chat(builder, _builder_prompt(task))
    _log(run_id, 1, builder, "builder", "draft", draft)

    for rnd in range(1, rounds + 1):
        reviews, all_ok = [], True
        for reviewer in reviewers:
            review = providers.chat(reviewer, _review_prompt(task, draft, reviewer["name"], rnd))
            ok = _is_approved(review)
            all_ok = all_ok and ok
            reviews.append(review)
            _log(run_id, rnd, reviewer, "reviewer", "review", review, approved=ok)

        if all_ok:
            _log(run_id, rnd, None, "system", "note",
                 f"All reviewers approved in round {rnd}. Converged.")
            break

        if rnd == rounds:
            _log(run_id, rnd, None, "system", "note",
                 "Reached max rounds with outstanding review comments.")
            break

        draft = providers.chat(builder, _revise_prompt(task, draft, reviews, rnd))
        _log(run_id, rnd + 1, builder, "builder", "revision", draft)

    return draft


def run_ensemble(run_id, task, agents, rounds):
    _log(run_id, 0, None, "system", "note",
         f"Ensemble: {len(agents)} agents each draft, then cross-review, then synthesize.")

    drafts = []
    for agent in agents:
        text = providers.chat(agent, _builder_prompt(task))
        drafts.append({"agent": agent, "text": text})
        _log(run_id, 1, agent, "builder", "draft", text)

    reviews = []
    for i, agent in enumerate(agents):
        # Each agent reviews the next agent's draft (round-robin cross-check).
        target = drafts[(i + 1) % len(drafts)]
        review = providers.chat(
            agent,
            _review_prompt(task, target["text"], agent["name"], 1),
        )
        ok = _is_approved(review)
        reviews.append(f"{agent['name']} reviewing {target['agent']['name']}:\n{review}")
        _log(run_id, 2, agent, "reviewer", "review",
             f"Reviewing {target['agent']['name']}'s draft:\n{review}", approved=ok)

    synthesizer = agents[0]
    final = providers.chat(synthesizer, _synthesis_prompt(task, drafts, reviews))
    _log(run_id, 3, synthesizer, "synthesizer", "synthesis", final)
    return final


def execute_run(run_id):
    """Entry point invoked on a background thread."""
    run = db.get_run(run_id)
    if not run:
        return
    task = db.get_task(run["task_id"])
    import json
    agent_ids = json.loads(run["agent_ids"] or "[]")
    agents = [db.get_agent(a) for a in agent_ids]
    agents = [a for a in agents if a]

    db.update_run(run_id, status="running")
    try:
        if not agents:
            raise ValueError("No agents assigned to this run.")
        if run["mode"] == "ensemble":
            result = run_ensemble(run_id, task, agents, run["rounds"])
        else:
            result = run_cross_review(run_id, task, agents, run["rounds"])
        db.update_run(run_id, status="done", result=result, finished_at=time.time())
    except Exception as exc:
        _log(run_id, 99, None, "system", "note", f"Run failed: {exc}")
        db.update_run(run_id, status="error", error=str(exc), finished_at=time.time())
