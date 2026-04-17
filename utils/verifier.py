"""
String-match clause verifier.

After Agent 1 (Extractor) returns extracted clauses, this module checks whether
each quoted clause actually exists verbatim (or near-verbatim) in the raw policy
text, directly addressing the evidence grounding failure (Metric 2 / FGS) found
in the thesis.
"""

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 85  # minimum similarity score (0–100) to consider a match


def verify_clauses(
    extracted_clauses: list[dict],
    policy_text: str,
) -> tuple[list[dict], list[dict]]:
    """
    Verify each extracted clause against the raw policy text.

    Args:
        extracted_clauses: List of clause dicts from Agent 1 output, each with
                           at least a "quote" field.
        policy_text: The full raw policy text as a plain string.

    Returns:
        A tuple of (verified_clauses, flagged_clauses).
        - verified_clauses: clauses whose quote matches the policy text.
        - flagged_clauses: clauses that could not be matched (potential hallucinations).
        Each dict gains a "verified" key (True/False) and a "similarity_score" key.
    """
    verified: list[dict] = []
    flagged: list[dict] = []

    for clause in extracted_clauses:
        quote = clause.get("quote", "").strip()
        if not quote:
            clause = {**clause, "verified": False, "similarity_score": 0,
                      "verification_note": "Empty quote field."}
            flagged.append(clause)
            continue

        score = _best_match_score(quote, policy_text)
        clause = {**clause, "similarity_score": score}

        if score >= FUZZY_THRESHOLD:
            clause = {**clause, "verified": True, "verification_note": "Matched in policy text."}
            verified.append(clause)
        else:
            clause = {
                **clause,
                "verified": False,
                "verification_note": (
                    f"Could not locate quote in policy text "
                    f"(best similarity: {score:.1f}%). "
                    "Likely hallucinated or heavily paraphrased."
                ),
            }
            flagged.append(clause)

    return verified, flagged


def _best_match_score(quote: str, policy_text: str) -> float:
    """
    Compute the best fuzzy match score for a quote inside the policy text.

    Uses a sliding window roughly the length of the quote to find the best
    matching substring, then returns the similarity ratio (0–100).
    """
    quote_len = len(quote)
    text_len = len(policy_text)

    # First try: exact substring check (fastest path)
    if quote.lower() in policy_text.lower():
        return 100.0

    # Second try: rapidfuzz partial ratio (handles minor whitespace / formatting diffs)
    partial_score = fuzz.partial_ratio(quote.lower(), policy_text.lower())
    if partial_score >= FUZZY_THRESHOLD:
        return float(partial_score)

    # Third try: sliding window token_set_ratio for reordered or truncated quotes
    # Only scan if the text is not excessively large
    window_size = max(quote_len + 50, int(quote_len * 1.5))
    step = max(1, quote_len // 2)
    best = float(partial_score)

    for start in range(0, max(1, text_len - window_size), step):
        window = policy_text[start: start + window_size]
        score = fuzz.token_set_ratio(quote.lower(), window.lower())
        if score > best:
            best = score
        if best >= 100:
            break

    return best
