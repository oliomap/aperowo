# ORG_PHILOSOPHY.md - Aperowo Project Ethics & Workflow

## Core Values
- **Highest Quality:** We prioritize robust, well-tested, and maintainable code. No shortcuts on architecture or reliability.
- **Positive & Inclusive:** Collaboration is driven by constructive feedback and a supportive environment.
- **Transparency:** We are open about our tools and processes, including the use of AI collaborators (like Alfred).

## Development Workflow
- **Branching Strategy:** 
    - `main`: Production-ready code. No direct pushes.
    - `staging`: Integration branch for tested features. All PRs must target `staging`.
    - `feature/*` or `auto/*`: Development branches.
- **PR Reviews:**
    - Every PR requires a review.
    - Alfred (AI) reviews all PRs for quality, tests, and style.
    - **Gemini Free Plan Compliance:** Alfred will batch review operations to respect rate limits (RPD/TPM) and minimize token burn.
    - Alfred may approve and merge low-stakes PRs (bug fixes, tests) directly to `staging`.
    - High-stakes PRs (architecture, core logic) require a final human sign-off from Oli.
- **Releases:**
    - Occur approximately once a week at major milestones.
    - Managed by a specialized Release Agent that generates changelogs from `staging` to `main`.
    - **Crucial:** All releases must be approved by Oli before being published.

## Branch Security
- Direct pushing to `main` is strictly prohibited.
- `staging` is the primary target for development PRs.
- Protection rules ensure that no code reaches `main` without passing through the `staging` -> `release` pipeline.
