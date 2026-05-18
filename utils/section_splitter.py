"""
Section splitter utility for two-pass extraction.

Given a full policy text and a list of section headings from the Scout,
this module locates each section's boundaries in the text and returns
the full text of each section.
"""

from rapidfuzz import fuzz


def split_sections(policy_text: str, section_names: list[str]) -> list[dict]:
    """
    Locate each section name in the policy text and return the full text
    of each section (from its heading to the start of the next section).

    Args:
        policy_text: Full raw policy text.
        section_names: Section headings returned by the Scout.

    Returns:
        List of {"name": str, "text": str} dicts, ordered by position
        in the document. Falls back to the full policy as one section
        if no sections can be located.
    """
    if not section_names:
        return [{"name": "Full Policy", "text": policy_text}]

    lines = policy_text.splitlines()

    # For each section name, find the best-matching line in the policy
    matched: list[tuple[int, str]] = []  # (line_index, section_name)
    for name in section_names:
        best_score = 0
        best_idx = None
        name_lower = name.lower().strip()
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            # partial_ratio handles cases where the heading is part of a longer line
            score = fuzz.partial_ratio(name_lower, line_stripped.lower())
            if score > best_score:
                best_score = score
                best_idx = i
        # Only accept matches above 60% similarity
        if best_idx is not None and best_score >= 60:
            matched.append((best_idx, name))

    if not matched:
        # Scout returned names that don't appear in the text — use full policy
        return [{"name": "Full Policy", "text": policy_text}]

    # Sort by position, deduplicate same-line matches (keep first)
    matched.sort(key=lambda x: x[0])
    seen: set[int] = set()
    unique: list[tuple[int, str]] = []
    for idx, name in matched:
        if idx not in seen:
            seen.add(idx)
            unique.append((idx, name))

    # Extract section text: from each section start to the next
    sections = []
    for i, (start_line, name) in enumerate(unique):
        end_line = unique[i + 1][0] if i + 1 < len(unique) else len(lines)
        section_text = "\n".join(lines[start_line:end_line]).strip()
        if section_text:
            sections.append({"name": name, "text": section_text})

    return sections if sections else [{"name": "Full Policy", "text": policy_text}]
