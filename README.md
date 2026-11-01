# HackerRank Orchestrate: my hackathon projects

HackerRank Orchestrate is a monthly 24-hour hackathon where you design, build, and ship a domain-specific AI agent under real-world constraints. Each monthly challenge lives in its own self-contained directory with its own code, dataset, and documentation.

| Month | Project | What it does | Result |
|---|---|---|---|
| October 2026 | [Ghost Data Still Exists: AI Deletion Audit Agent](hackerrank-orchestrate-october26) | Audits platform databases, replicas, backups, logs, and multimodal artifacts against deletion policies to discover ghost data and generate verified remediation plans. | Ready for Submission |
| September 2026 | [Buy or Wait? AI Financial Decision Agent](hackerrank-orchestrate-september) | Evaluates whether a user can safely afford a requested purchase by simulating a 90-day cash flow ledger across bank transactions, salary events, and bill receipts. | 203rd of 3,062 |
| August 2026 | [WhatsApp Message Notification Router](hackerrank-orchestrate-august) | Routes multimodal WhatsApp messages to notify, digest, or mute using user engagement metrics and deterministic safety gates. | 486th of 1,983 |
| June 2026 | [Multi-Modal Damage-Claim Verification](hackerrank-orchestrate-june) | Reads a claim, inspects the submitted photos, and decides whether they support the claim, contradict it, or are not enough to tell. Fills in 14 explained columns. | Not submitted |

---

## October 2026: Ghost Data Still Exists: AI Deletion Audit Agent

A deletion workflow may report "Complete" while customer personal data persists across secondary databases, replicas, backups, support attachments, logs, and analytics exports. An active sync process can even resurrect deleted data. The architecture uses a modular multi-agent pipeline: multilingual intent classification (6 languages), temporal identity backtracking, in-memory SQLite Unicode scanning, multimodal perceptual decoupling (PDFs and UI screenshots), and dependency-ordered step serialization validated by deterministic guardrails.

**[Read the October README](hackerrank-orchestrate-october26/README.md)**

---

## September 2026: Buy or Wait? AI Financial Decision Agent

Users ask whether they can safely afford an expense, such as a laptop or medical bill. The core idea is complete separation between perception and arithmetic: large language models only read receipt images or unstructured messages, while arbitrary-precision Python Decimal simulates the 90-day daily cash flow. The design choice worth stealing is testing candidate payment methods as counterfactual ledger overlays against a frozen daily baseline, ensuring essential reserve buffers can never be violated by LLM hallucination.

**[Read the September README](hackerrank-orchestrate-september/README.md)**

---

## August 2026: WhatsApp Message Notification Router

Incoming WhatsApp streams mix urgent family messages, promotional flyers, voice notes, and phishing scams. Two small LLM calls extract boolean signals and classify intent, while a 9-gate deterministic decision tree in plain Python determines whether to notify, digest, or mute. The design choice worth stealing is computing per-source user engagement ratios purely in Python and allowing personalization only to demote messages into digest, ensuring safety gates (like scam suppression and emergency overrides) can never be bypassed.

**[Read the August README](hackerrank-orchestrate-august/README.md)**

---

## June 2026: Multi-Modal Damage-Claim Verification

Damage claims for cars, laptops, and packages must be verified against photos, customer claim dialogue, and history profiles. The vision model only describes what it sees and plain Python makes the decision; contradictions override support; customer history adds caution but never flips a verdict on its own. The design choice worth stealing is multi-image aggregation with an auto-reject rule: obvious contradictions are rejected without forcing manual human review, saving reviewer time on fraudulent claims.

**[Read the June README](hackerrank-orchestrate-june/README.md)**

---

## How this repo is organized

```text
.
├── hackerrank-orchestrate-october26/   October project: Ghost Data Still Exists AI deletion auditor
├── hackerrank-orchestrate-september/   September project: Buy or Wait? financial agent
├── hackerrank-orchestrate-august/      August project: WhatsApp notification router
├── hackerrank-orchestrate-june/        June project: Multi-modal damage claim verification
├── .gitignore                          Shared gitignore for all three projects
├── LICENSE                             MIT License covering code
└── README.md                           You are here
```

---

## Good to know

- Secrets stay out of git: `.env` files are ignored across all projects, and example templates (`.env.example`) document required provider keys.
- Datasets, problem statements, and challenge specifications belong to HackerRank.
- The MIT License covers my source code only.
