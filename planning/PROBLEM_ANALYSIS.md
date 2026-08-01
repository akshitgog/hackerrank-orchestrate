# PROBLEM_ANALYSIS.md — What the Problem Statement Demands

This document contains only what `problem_statement.md` and `README.md` explicitly require. No interpretation, no edge cases, no architectural opinions.

---

## 1. Task

Build a system that, for every incoming WhatsApp message, decides:
- `notify` — interrupt the user now
- `digest` — useful but can wait; show later
- `mute` — low-value, repetitive, unwanted, suspicious, or unsafe

Decisions must be **personalized** to the receiving user using message content, user profile, group context, business relationship, media content, and historical interaction data.

---

## 2. Input

**File:** `dataset/messages.csv` — 110 rows, each representing one incoming message.

**Columns (11):**

| Column | Description |
| :--- | :--- |
| `message_id` | Unique incoming message ID |
| `user_id` | User receiving the message |
| `conversation_type` | `personal`, `group`, or `business` |
| `group_id` | Group ID if from a group |
| `business_id` | Business ID if from a business account |
| `sender_user_id` | Sender user ID if from a user |
| `created_at` | Message timestamp |
| `message_text` | Text content; empty for voice-note messages |
| `media_type` | Empty, `image`, or `voice` |
| `media_id` | Linked image or voice-note ID, if present |
| `forwarded_count` | Forwarding signal |

---

## 3. Context Files

The spec provides 10 additional files to inform decisions:

| # | File | Spec Description |
| :--- | :--- | :--- |
| 1 | `users.csv` | User notification behavior: quiet hours, recent opens, replies, dismissals, reports |
| 2 | `groups.csv` | Group type, size, admins, recent activity |
| 3 | `group_members.csv` | User's role in group, activity, read/reply behavior, dismissals, mute state |
| 4 | `business_accounts.csv` | Brand identity, verification, domain used by sender, account age, reports |
| 5 | `user_business_history.csv` | User's relationship with a business: orders, bookings, payments, opt-ins, opt-outs |
| 6 | `message_history.csv` | Past messages received by users — for identifying patterns, ignored messages, risky content |
| 7 | `message_events.csv` | How users reacted to past messages: opened, replied, dismissed, muted, reported |
| 8 | `images.csv` | Image IDs and file paths |
| 9 | `voice_notes.csv` | Voice note IDs and file paths |
| 10 | `daily_notification_summary.csv` | Daily notification load for each user |

**Media:** `images.csv` and `voice_notes.csv` provide file paths. The spec says: *"your system should inspect the media files themselves."*

**Sample data:** `sample_messages.csv` (30 rows) provided to *"understand the expected output format and style"* only.

---

## 4. Required Output

**File:** `output.csv` — exactly one row per `message_id` in `messages.csv`.

**Columns (6), in this exact order:**

| Column | Meaning |
| :--- | :--- |
| `message_id` | Incoming message ID |
| `action` | `notify`, `digest`, or `mute` |
| `message_type` | Best-fit message category |
| `reason` | Short human-readable explanation |
| `confidence` | Number from 0 to 1 |
| `evidence_message_ids` | Semicolon-separated historical message IDs used as evidence; write `none` if no useful evidence |

---

## 5. Allowed Values

**`action` (3 values):**
`notify`, `digest`, `mute`

**`message_type` (11 values):**
`personal`, `urgent`, `event`, `payment`, `business_update`, `promotion`, `greeting`, `forward`, `spam`, `scam`, `unknown`

---

## 6. Evaluation Criteria

The spec says `output.csv` will be compared against hidden ground-truth labels. Scoring considers:

1. Correctness of `action`
2. Correctness of `message_type`
3. Usefulness and consistency of `reason`
4. Whether `evidence_message_ids` point to relevant historical messages
5. Reasonable confidence calibration

---

## 7. Constraints

From spec and README:
- Must be runnable from the terminal
- Must read files from `dataset/`
- Must produce a valid `output.csv`
- Must not use organizer-only files or hardcoded labels
- Secrets must come from environment variables, never hardcoded

---

## 8. Submission

| File | Description |
| :--- | :--- |
| `code.zip` | Full runnable solution, prompts/configs, and README |
| `output.csv` | Predictions for all rows in `messages.csv` |
| `chat_transcript` | Conversation transcript (the log.txt) |

---

## 9. Key Quotes from the Spec

> *"The routing decision must be personalized to the receiving user."*

> *"A sale poster may be useful for one user and unwanted noise for another."*

> *"A muted family group can still contain an urgent direct mention."*

> *"Clear scam or safety risk should be muted regardless of the user's usual engagement."*

> *"The final decision should balance usefulness, urgency, repetition, and risk."*

> *"Use [sample_messages.csv] only to understand the expected output format and style."*
