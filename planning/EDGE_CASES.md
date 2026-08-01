# EDGE_CASES.md — Signal Framework, Cross-Table Interactions & Threat Analysis

---

## 1. Explicit Requirements (auto-fail if missed)

| ID | Requirement | Failure Mode |
| :--- | :--- | :--- |
| E-01 | One output row per input `message_id` (110 rows) | Missing/extra rows → automatic failure |
| E-02 | Exact 6-column order in `output.csv` | Column misordering breaks grading |
| E-03 | `action` must be one of: `notify`, `digest`, `mute` | Out-of-vocabulary → failure |
| E-04 | `message_type` must be one of 11 allowed values | Out-of-vocabulary → failure |
| E-05 | `confidence` must be number 0 to 1 | Out-of-range → parsing failure |
| E-06 | `evidence_message_ids` = semicolon-separated IDs or literal `none` | Wrong format → parsing failure |

---

## 2. Implicit Requirements (not stated, will break you)

| ID | Requirement | Why |
| :--- | :--- | :--- |
| I-01 | CSV quoting for `reason` (contains commas, quotes) | Unescaped commas corrupt row |
| I-02 | Evidence default = `none` (lowercase), not `""`, `null`, `N/A` | Format mismatch |
| I-03 | Pipeline must not crash on bad media files | One bad file kills entire batch |
| I-04 | `message_text` is untrusted — may contain prompt injection | LLM could obey injected instructions |
| I-05 | `payment` type absent from samples but in allowed values | Must handle all 11 types |

---

## 3. The Personalization Principle & Signal Framework

### 3.0 Core Principle — Every Decision Is Personalized

The spec is explicit about this:

> *"The routing decision must be personalized to the receiving user."*
> *"A sale poster may be useful for one user and unwanted noise for another."*
> *"A muted family group can still contain an urgent direct mention."*
> *"The final decision should balance usefulness, urgency, repetition, and risk."*

**This means:** There is no isolated rule like "forwarded = mute" or "DND = digest". Every routing decision is the result of evaluating **all available signals together** for the specific user receiving that specific message. The same message content can route to `notify` for one user and `mute` for another.

### 3.1 The Six Signal Dimensions

Every incoming message must be evaluated across these six interconnected dimensions simultaneously. No dimension alone determines the action — they interact:

```
┌─────────────────────────────────────────────────────────┐
│              ROUTING DECISION (action + message_type)    │
│                                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                │
│  │ MESSAGE │  │ SENDER  │  │  USER   │                │
│  │ CONTENT │←→│ CONTEXT │←→│ PROFILE │                │
│  └────┬────┘  └────┬────┘  └────┬────┘                │
│       │            │            │                       │
│  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐                │
│  │  MEDIA  │  │ HISTORY │  │  LOAD   │                │
│  │ CONTENT │←→│ PATTERN │←→│ FATIGUE │                │
│  └─────────┘  └─────────┘  └─────────┘                │
└─────────────────────────────────────────────────────────┘
```

| Dimension | Source Tables | What It Provides |
| :--- | :--- | :--- |
| **Message Content** | `messages.message_text`, `messages.forwarded_count` | Semantic intent, urgency, topic, scam indicators, prompt injection |
| **Media Content** | `images.csv`, `voice_notes.csv` + actual files | Visual/audio content when text is absent or supplementary |
| **Sender Context** | `groups.csv`, `group_members.csv`, `business_accounts.csv` | Who is sending: admin vs member, verified vs unverified, group type, domain trust |
| **User Profile** | `users.csv`, `user_business_history.csv`, `group_members.csv` | Recipient's preferences: DND window, promo consent, mute state, report tolerance |
| **History Pattern** | `message_history.csv`, `message_events.csv` | Past behavior: did user engage with similar messages, or dismiss/report/mute them? |
| **Load & Fatigue** | `daily_notification_summary.csv`, `users.notifications_dismissed_30d` | Is user overwhelmed? High dismissal = lean conservative |

### 3.2 How Dimensions Interact (Not Isolated)

The key insight is that these dimensions don't operate independently. Every message sits at an intersection of multiple dimensions, and the routing decision comes from their **combined** weight.

**Example of interconnected evaluation:**

Consider a message that is:
- A forwarded operational directive (`forwarded_count=2`, text about a deadline change)
- Sent by a member (not admin) in a `coworker` group
- To a user who muted the group (`group_muted_by_user=1`)
- Arriving during user's DND window (`23:00-07:00`, message at `06:30`)
- User has high `notifications_dismissed_30d` (45)
- User previously opened and replied to similar messages from this sender

No single dimension answers this. The system must weigh:
- Content says operationally important (leans `notify`)
- Sender is not admin (slightly weakens authority)
- User muted group (leans `mute`)
- DND window (leans `digest`)
- High dismissal (leans `digest`)
- History says user engages with this sender (leans `notify`)

The typed seam must be designed to **receive all six dimensions as structured input** and produce a holistic decision — not to evaluate them one by one in an if-else chain.

---

## 4. Cross-Table Edge Cases & Scenarios

These are specific scenarios where the interaction between tables and attributes creates routing complexity. They are NOT isolated rules — they're examples of how the six dimensions combine.

### 4.1 Scenarios Involving Sender Authority × User Preference

| Scenario | Dimensions In Tension | Notes |
| :--- | :--- | :--- |
| Admin in `society` group posts urgent notice + user muted group | Sender authority vs. user mute preference | Both are valid signals — content urgency and group type tip the balance |
| Admin in `friends` group posts casual chat | Admin role present but group type is social | Admin authority carries less weight in social contexts |
| Non-admin member forwards directive from higher authority in `coworker` group | Formal role is low, but content carries authority | Content and context can outweigh formal role |
| Admin sends "good morning" greeting | Admin role present but content is low-value | Content type should dominate over sender role for casual messages |

### 4.2 Scenarios Involving Business Trust × User Relationship

| Scenario | Dimensions In Tension | Notes |
| :--- | :--- | :--- |
| `verified=0` + domain mismatch + asks for OTP | Scam signals converge | Multiple fraud indicators — likely `mute`/`scam` regardless of user history |
| `verified=0` + domains match + low reports + user has active relationship | Could be new legitimate business | User relationship + content lean toward legitimate |
| Verified business sends promotion + user opted out | Trust vs. consent | Consent boundary: user explicitly said no |
| Verified business sends transactional update + user opted out of promos | Transaction vs. promotion opt-out | Opt-out applies to promotions, not transactional updates |
| No `user_business_history` record exists for this business | Unknown relationship | Lean on business verification + content to decide |
| User has high dismissed count for this business but never opted out | Behavioral signal vs. explicit consent | Behavioral fatigue is a signal but weaker than explicit opt-out |

### 4.3 Scenarios Involving Temporal Context × Message Priority

| Scenario | Dimensions In Tension | Notes |
| :--- | :--- | :--- |
| Urgent message arrives during DND | Time preference vs. urgency | Genuine urgency may override quiet hours |
| Low-value message arrives during DND | Both signals agree | Lean `digest` or `mute` |
| User has very high daily notification volume + new message | Load fatigue | System should be more conservative for overloaded users |
| User has low notification volume + promotional message | Low fatigue but low-value content | Fatigue alone doesn't elevate promotions |

### 4.4 Scenarios Involving Content × Media × History

| Scenario | Dimensions In Tension | Notes |
| :--- | :--- | :--- |
| Image message with no text — image is a school circular | Media content carries all signal | OCR/VLM must extract text from image |
| Voice note with no text — voice contains urgent request | Audio carries all signal | ASR must transcribe |
| Voice note corrupted/unreadable + sender is trusted admin | Media fails but context is strong | Fallback to sender/group context |
| Text says "attached poster" but image is a scam phishing page | Text and media content conflict | Both must be evaluated — scam in either channel is still scam |
| User previously opened similar media messages from this sender | History supports engagement | Evidence for `notify` or `digest` |
| User previously reported similar media messages from this sender | History supports rejection | Evidence for `mute` |

### 4.5 Scenarios Involving Forwarded Content × Authority × Content

| Scenario | Dimensions In Tension | Notes |
| :--- | :--- | :--- |
| High `forwarded_count` + generic blessing text | Content and forward signal agree | Low-value forwarded content |
| High `forwarded_count` + operational directive from manager | Forward count vs. content importance | Content and sender authority outweigh forward count |
| `forwarded_count=0` + scam content | No forwarding signal but content is dangerous | Scams don't need forwarding to be harmful |
| `forwarded_count=0` + generic greeting from casual user | No forwarding but still low-value | Forward count isn't the only low-value signal |

---

## 5. Threat Scenarios

| Threat | Source | Impact | Detection Signals |
| :--- | :--- | :--- | :--- |
| **Prompt injection** | `message_text` contains instructions to override routing | LLM obeys injected instructions, routes scam as `notify` | Deterministic regex/pattern check for control-override language |
| **Domain impersonation** | `business_accounts`: `official_domain ≠ domain_used_by_sender` | User trusts fake brand, opens scam link | Compare domains + check `verified` + `domain_used_by_sender_age_days` |
| **Hallucinated evidence** | LLM fabricates `evidence_message_ids` that don't exist | Grading penalty on evidence quality | Validate all proposed IDs against `message_history.csv` |
| **OTP/credential phishing** | `message_text` asks for OTP, PIN, login code | User gives up credentials | Content pattern detection — OTP/PIN language + external links |
| **Urgency pressure** | Text creates artificial deadline ("account blocked in 2 hours") | User panics and complies | Urgency language + unverified sender = scam signal |

---

## 6. Unambiguous vs. Ambiguous Summary

### Unambiguous (clear-cut regardless of user)
- Prompt injection text → `mute`/`scam`
- OTP request from unverified domain-mismatched sender → `mute`/`scam`
- User explicitly opted out of promos + promotional message → `mute`
- Output format: missing evidence = `none`, not empty string

### Ambiguous (depends on holistic evaluation of all six dimensions)
- Every other case. The spec says personalization is the core requirement. The system must evaluate all signals together, not apply isolated rules.
