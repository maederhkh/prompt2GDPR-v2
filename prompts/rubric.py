"""
Shared GDPR Article 5(1)(b) purpose-limitation rubric.

Single source of truth imported by both the Evaluator and the Blind Labeler so
their judgments use identical wording. Changing the rubric here changes it for
every labeler at once — this is intentional (removes prompt-wording as a
confound when comparing labels across models).
"""

RUBRIC_BLOCK = """\
## Two-stage rubric

### Stage 1 — Purpose Specification
Apply to every clause. Assess whether the stated purpose is:

| Criterion | Key question | Compliant example | Non-compliant example |
|---|---|---|---|
| specific | Does the clause name a concrete processing activity? | "to generate personalised health assessments via the Ada app" | "to improve our products and services" |
| explicit | Is the purpose stated in plain language a data subject can understand? | "to send you appointment reminders by email" | "for operational purposes" |
| legitimate | Is the purpose legally permissible under EU law? | Any clearly lawful purpose | Purposes contrary to law or public policy |
| determined_at_collection | Was (or could) the purpose be known at or before data collection? | Purpose tied to the service the user signed up for | Post-hoc purpose defined after data is collected |

### Stage 2 — Compatibility Assessment
Apply only if the clause describes further or secondary use of already-collected data.
Assess whether the further use is compatible with the original purpose by checking:

| Criterion | Key question |
|---|---|
| purpose_link | Is there a meaningful connection between the original and secondary purpose? |
| context_consistent | Would a data subject reasonably expect this further use given the collection context? |
| data_nature_considered | Does the clause acknowledge the nature of the data (especially health/special category)? |
| impact_assessed | Does the clause address the potential impact on data subjects? |
| safeguards_present | Are technical/organisational safeguards stated (pseudonymisation, access controls, consent)? |

### Article 89 Exception Branch
Apply only if the clause explicitly invokes research, archiving, or statistical purposes.
Check:
- Is the Article 89 exception explicitly claimed (not merely implied)?
- Are appropriate safeguards stated (pseudonymisation, anonymisation, functional separation, access controls)?
- Is the purpose genuinely archiving/scientific/statistical (not a disguised commercial use)?

---

## Label decision rules

### Per-clause label
- **Compliant**: All applicable Stage 1 criteria are met (yes or partial-but-sufficient); \
Stage 2 criteria met if applicable; or Article 89 exception properly invoked with safeguards stated.
- **Partially Compliant**: At least one Stage 1 criterion is met but at least one is missing \
(e.g. specific but not explicit); Stage 2 partially addressed; or Article 89 invoked \
without full safeguard specification.
- **Non-Compliant**: No specific purpose stated; vague catch-all language only \
(e.g. "to improve services", "for business purposes"); further processing incompatible \
with original purpose without justification; or Article 89 invoked without any safeguards.

**IMPORTANT — no other labels are permitted.** You must use exactly one of: \
"Compliant", "Partially Compliant", or "Non-Compliant". \
Do NOT use "Not Applicable", "N/A", or any other value. \
Every clause that was extracted and verified is relevant to purpose limitation; \
if a clause contains no purpose limitation language at all, label it "Non-Compliant".

### Overall policy label (derived from clause labels)
- All clauses Compliant → **Compliant**
- Mix of Compliant + Partially Compliant (no Non-Compliant) → **Partially Compliant**
- Any Non-Compliant clause → **Non-Compliant**
  (Exception: if the Non-Compliant clause is fully covered by a proper Article 89 exception, \
  it does not force a Non-Compliant overall label.)

---

## Criterion answer values
Use exactly: "yes", "no", or "partial"
- yes = criterion is clearly met
- no = criterion is clearly not met
- partial = criterion is partly met but not fully"""
