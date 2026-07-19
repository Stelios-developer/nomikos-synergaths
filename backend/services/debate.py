"""
Debate Agents — two agents argue OPPOSING, document-grounded positions on
the same question across multiple rounds of DIRECT rebuttal, followed by
a Judge agent that rules on which side is better supported by the
evidence.

This is a different multi-agent shape than the Advisory Panel
(services/advisory_panel.py): the Panel runs three independent parallel
opinions that never read each other. A debate is adversarial and
iterative — each side explicitly reads and responds to the OTHER side's
previous argument, round over round, the way a real debate works.
Within a single round, both sides still run CONCURRENTLY (each only
needs the opponent's PREVIOUS round, never their current one, so there's
no dependency between them within a round) — reusing the same
ThreadPoolExecutor pattern as the Advisory Panel for the same underlying
reason: neither side has an information advantage over the other at any
given round.

Design note on grounding: both personas still inherit the same
document-only constraint as the main RAG system prompt (see
services/llm.SYSTEM_PROMPT) — only the *interpretive angle* differs
(favorable-but-grounded vs. cautious-but-grounded), never the
evidentiary bar. Letting either side argue beyond what the documents
actually support would turn this into theater, not a useful feature.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.retrieval import hybrid_search
from services.llm import generate_with_system, complete
from services.observability import submit_with_context
from services.session_scope import DEFAULT_SESSION_ID

MAX_ROUNDS = 2

_GROUNDING_RULES = (
    "Απάντα ΜΟΝΟ βάσει των παρακάτω αποσπασμάτων εγγράφων (chunks). Αν κάτι δεν "
    "βρίσκεται σε αυτά, πες ρητά ότι δεν βρέθηκε στα έγγραφα. Μην χρησιμοποιείς "
    "εξωτερική γνώση. Αναφέρσου στις πηγές σου με [1], [2] κ.ο.κ."
)

SIDES = {
    "for": {"label": "Εισηγητής Υπέρ", "emoji": "📢"},
    "against": {"label": "Εισηγητής Κατά", "emoji": "🛑"},
}


def _opening_system_prompt(side: str) -> str:
    if side == "for":
        return (
            f"Είσαι ο '{SIDES['for']['label']}' σε μια δομημένη αντιπαράθεση (debate). {_GROUNDING_RULES} "
            "Ο ρόλος σου: υποστήριξε την πιο ευνοϊκή, νόμιμη ερμηνεία υπέρ του χρήστη που τεκμηριώνεται "
            "από τα αποσπάσματα. Παρουσίασε το ισχυρότερο δυνατό επιχείρημά σου."
        )
    return (
        f"Είσαι ο '{SIDES['against']['label']}' σε μια δομημένη αντιπαράθεση (debate). {_GROUNDING_RULES} "
        "Ο ρόλος σου: υποστήριξε την πιο συντηρητική, προσεκτική ερμηνεία που τεκμηριώνεται από τα "
        "αποσπάσματα, επισημαίνοντας κινδύνους ή αδυναμίες στην πιο ευνοϊκή ερμηνεία. Παρουσίασε το "
        "ισχυρότερο δυνατό επιχείρημά σου."
    )


def _rebuttal_system_prompt(side: str, opponent_argument: str) -> str:
    base = _opening_system_prompt(side)
    return (
        f'{base}\n\nΟ αντίπαλός σου μόλις υποστήριξε:\n"""\n{opponent_argument}\n"""\n\n'
        "Απάντησε ΑΠΕΥΘΕΙΑΣ σε αυτό το επιχείρημα — δείξε πού είναι αδύναμο ή ελλιπές βάσει των "
        "αποσπασμάτων, και ενίσχυσε τη δική σου θέση. Μην επαναλαμβάνεις απλά το πρώτο σου επιχείρημα."
    )


JUDGE_INSTRUCTIONS = (
    "Είσαι ο Judge μιας δομημένης αντιπαράθεσης (debate) δύο πλευρών πάνω σε ένα φορολογικό ερώτημα. "
    "Σου δίνεται η πλήρης ανταλλαγή επιχειρημάτων και των δύο πλευρών, γύρο-γύρο. Έκδωσε μια τελική "
    "κρίση: ποια πλευρά τεκμηριώνεται καλύτερα από τα έγγραφα, πού η αντίθετη πλευρά έχει βάσιμα σημεία, "
    "και μια τελική ισορροπημένη σύσταση για τον χρήστη. Μην εφευρίσκεις νέα γεγονότα πέρα από όσα ήδη "
    "αναφέρθηκαν στην αντιπαράθεση."
)


def run_debate_stream(
    question: str,
    document_filter: str | None = None,
    session_id: str = DEFAULT_SESSION_ID,
):
    """
    Generator over the Debate's full trace. Yields:
      ("citations", [...])                                    — once, right after the shared retrieval
      ("argument", {"side","round","label","emoji","text"})   — once per side per round, in COMPLETION
                                                                  order within each round (both sides run
                                                                  concurrently — not a fixed left/right order)
      ("verdict", {"summary": str})                            — exactly once, last
    """
    chunks = hybrid_search(question, document_filter=document_filter, session_id=session_id)
    citations = [
        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
        for c in chunks
    ]
    yield ("citations", citations)

    if not chunks:
        yield ("verdict", {
            "summary": "Δεν βρέθηκαν σχετικά αποσπάσματα στα έγγραφα για αυτή την αντιπαράθεση.",
        })
        return

    transcript: dict[str, list[str]] = {"for": [], "against": []}

    for round_num in range(1, MAX_ROUNDS + 1):
        if round_num == 1:
            prompts = {side: _opening_system_prompt(side) for side in SIDES}
        else:
            prompts = {
                side: _rebuttal_system_prompt(side, transcript["against" if side == "for" else "for"][-1])
                for side in SIDES
            }

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_side = {
                submit_with_context(executor, generate_with_system, question, chunks, prompts[side]): side
                for side in SIDES
            }
            for future in as_completed(future_to_side):
                side = future_to_side[future]
                try:
                    text = future.result()
                except Exception as exc:
                    text = f"(Ο σύμβουλος απέτυχε: {exc})"
                transcript[side].append(text)
                yield ("argument", {
                    "side": side,
                    "round": round_num,
                    "label": SIDES[side]["label"],
                    "emoji": SIDES[side]["emoji"],
                    "text": text,
                })

    debate_text = "\n\n".join(
        f"[Γύρος {r + 1}] {SIDES['for']['label']}: {transcript['for'][r]}\n"
        f"[Γύρος {r + 1}] {SIDES['against']['label']}: {transcript['against'][r]}"
        for r in range(MAX_ROUNDS)
    )
    judge_prompt = f"{JUDGE_INSTRUCTIONS}\n\nΕρώτηση: {question}\n\nΗ αντιπαράθεση:\n{debate_text}"
    verdict = complete(judge_prompt, max_tokens=700)

    yield ("verdict", {"summary": verdict})
