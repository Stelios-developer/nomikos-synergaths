"""
Advisory Panel — multiple competing advisor personas debate the SAME
retrieved evidence in parallel, followed by a Moderator that synthesizes
their agreement/disagreement into one final recommendation.

This is architecturally distinct from both other multi-agent patterns in
the app: the Supervisor (services/supervisor.py) is a sequential
tool-calling router that decides which ONE subsystem to invoke next, and
the Action Agent (services/code_agent.py) is a sequential Planner ->
Coder -> Reviewer loop. The Advisory Panel instead runs three
differently-instructed agents CONCURRENTLY over one shared retrieval,
each producing an independent, self-contained recommendation, then a
fourth agent (the Moderator) reconciles them.

Why parallel, and why it matters here: the three advisors have no
information advantage over each other — they read the exact same
chunks — so there's no reason to force them through one at a time. Real
concurrency (via ThreadPoolExecutor, since the LLM SDK calls are
synchronous/blocking) also means advisors stream back to the UI in
whatever order they actually finish, not a fixed sequence — which is the
whole visual/architectural point of a panel versus a pipeline.

Design note on grounding: every advisor persona still inherits the same
document-only constraint as the main RAG system prompt (see
services/llm.SYSTEM_PROMPT) — only the *interpretive angle* differs
(aggressive optimization vs. conservative compliance vs. risk
assessment), never the evidentiary bar. A panel that let personas
hallucinate more freely than the base system would be a worse, not
better, feature.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.retrieval import hybrid_search
from services.llm import generate_with_system, complete
from services.observability import submit_with_context
from services.session_scope import DEFAULT_SESSION_ID

_GROUNDING_RULES = (
    "Απάντα ΜΟΝΟ βάσει των παρακάτω αποσπασμάτων εγγράφων (chunks). Αν η απάντηση δεν "
    "βρίσκεται σε αυτά, πες ρητά ότι δεν βρέθηκε στα έγγραφα. Μην χρησιμοποιείς εξωτερική "
    "γνώση. Αναφέρσου στις πηγές σου με [1], [2] κ.ο.κ., αντιστοιχώντας στη σειρά των chunks "
    "όπως δίνονται."
)

ADVISORS = [
    {
        "id": "aggressive",
        "label": "Επιθετικός Φοροτεχνικός",
        "emoji": "🚀",
        "system_prompt": (
            f"Είσαι ο 'Επιθετικός Φοροτεχνικός' σε ένα advisory panel. {_GROUNDING_RULES} "
            "Ο ρόλος σου: πρότεινε την πιο επιθετική ερμηνεία που μεγιστοποιεί νόμιμα το όφελος "
            "του πελάτη, χωρίς ποτέ να ξεπερνάς όσα υποστηρίζουν ρητά τα έγγραφα. Δώσε έμφαση σε "
            "εκπτώσεις, απαλλαγές και ερμηνείες προς όφελος του πελάτη που τα αποσπάσματα επιτρέπουν."
        ),
    },
    {
        "id": "conservative",
        "label": "Συντηρητικός Υπεύθυνος Συμμόρφωσης",
        "emoji": "🛡️",
        "system_prompt": (
            f"Είσαι ο 'Συντηρητικός Υπεύθυνος Συμμόρφωσης' σε ένα advisory panel. {_GROUNDING_RULES} "
            "Ο ρόλος σου: πρότεινε την πιο ασφαλή, ξεκάθαρα συμμορφούμενη ερμηνεία και απόφυγε "
            "οτιδήποτε θα μπορούσε να θεωρηθεί επισφαλές ή αμφιλεγόμενο. Επισήμανε ρητά κάθε "
            "αβεβαιότητα ή σημείο που θα χρειαζόταν πρόσθετη τεκμηρίωση σε πραγματικό έλεγχο."
        ),
    },
    {
        "id": "risk",
        "label": "Αναλυτής Κινδύνου",
        "emoji": "⚠️",
        "system_prompt": (
            f"Είσαι ο 'Αναλυτής Κινδύνου' σε ένα advisory panel. {_GROUNDING_RULES} "
            "Ο ρόλος σου ΔΕΝ είναι να προτείνεις δράση, αλλά να εντοπίσεις και να βαθμολογήσεις "
            "(Χαμηλός / Μεσαίος / Υψηλός) τους κινδύνους, τις ασάφειες ή τα κενά τεκμηρίωσης στα "
            "αποσπάσματα σε σχέση με την ερώτηση."
        ),
    },
]

MODERATOR_INSTRUCTIONS = (
    "Είσαι ο Moderator ενός advisory panel φορολογικών συμβούλων. Σου δίνονται τρεις ανεξάρτητες "
    "γνώμες πάνω στο ίδιο ερώτημα: του Επιθετικού Φοροτεχνικού, του Συντηρητικού Υπεύθυνου "
    "Συμμόρφωσης, και του Αναλυτή Κινδύνου. Σύνθεσε μια τελική απάντηση: ανέφερε ρητά πού "
    "συμφωνούν, πού διαφωνούν, και δώσε μια ισορροπημένη τελική σύσταση για τον χρήστη. Μην "
    "εφεύρεις νέα γεγονότα πέρα από όσα ήδη αναφέρουν οι τρεις γνώμες."
)


def run_panel_stream(
    question: str,
    document_filter: str | None = None,
    session_id: str = DEFAULT_SESSION_ID,
):
    """
    Generator over the Advisory Panel's full trace. Yields:
      ("citations", [...])                                    — once, right after the shared retrieval
      ("advisor", {"id", "label", "emoji", "answer"})          — once per advisor, in COMPLETION order
                                                                   (not a fixed sequence — proves real
                                                                   parallelism)
      ("done", {"moderator_summary": str})                     — exactly once, last
    """
    chunks = hybrid_search(question, document_filter=document_filter, session_id=session_id)
    citations = [
        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
        for c in chunks
    ]
    yield ("citations", citations)

    if not chunks:
        yield ("done", {
            "moderator_summary": "Δεν βρέθηκαν σχετικά αποσπάσματα στα έγγραφα για αυτή την ερώτηση.",
        })
        return

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(ADVISORS)) as executor:
        future_to_advisor = {
            submit_with_context(executor, generate_with_system, question, chunks, advisor["system_prompt"]): advisor
            for advisor in ADVISORS
        }
        for future in as_completed(future_to_advisor):
            advisor = future_to_advisor[future]
            try:
                answer = future.result()
            except Exception as exc:
                answer = f"(Ο σύμβουλος απέτυχε: {exc})"
            results[advisor["id"]] = answer
            yield ("advisor", {
                "id": advisor["id"],
                "label": advisor["label"],
                "emoji": advisor["emoji"],
                "answer": answer,
            })

    # Reassembled in the ADVISORS' fixed order for a stable moderator
    # prompt, regardless of which advisor actually finished first.
    opinions_text = "\n\n".join(f"[{a['label']}]\n{results[a['id']]}" for a in ADVISORS)
    moderator_prompt = (
        f"{MODERATOR_INSTRUCTIONS}\n\nΕρώτηση: {question}\n\nΟι τρεις γνώμες:\n{opinions_text}"
    )
    moderator_summary = complete(moderator_prompt, max_tokens=700)

    yield ("done", {"moderator_summary": moderator_summary})
