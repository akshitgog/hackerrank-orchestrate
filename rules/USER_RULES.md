# 🛑 USER_RULES.md — Strict User-Defined Operational Rules
**Status:** Mandatory for all agents, sub-agents, and AI tools in this repository.  

---

## Rule 1: Zero Git Commit or Push Without Explicit User Instruction

### 1.1 Statement of Rule
* **Never** execute `git commit`, `git push`, `git merge`, `git rebase`, or any git command that mutates commit history or remote repository state unless the user **explicitly and unambiguously instructs you to do so** in their prompt.
* Creating, editing, and deleting files in the local filesystem during development is allowed, but staging (`git add`) and committing (`git commit`) must be gated behind explicit user command.

### 1.2 Enforcement
* If a task is complete, notify the user and ask if they would like to review the changes or commit them. **Do not run `git commit` automatically.**
