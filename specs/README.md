# Specs

The design documents of the integration. They're the source of truth: the code follows them, and when a decision changes, the document changes with it.

## Layout

```
specs/
├── README.md            this index and the rules
├── panel-checks.md      register of the panel checks (V1, V2, …)
├── analysis/            dated research notes
└── NN-topic/            one folder per unit of work
    ├── spec.md          what to build
    └── plan.md          how to build it
```

## Units

| Unit | Documents | Content | Status | Release |
|---|---|---|---|---|
| 01-base | [spec](01-base/spec.md), [plan](01-base/plan.md) | Setup, connection and reconnection, power, brightness, orientation, clock, image player, diagnostics | Done | `v0.1.0` |
| 02-fixes | [plan](02-fixes/plan.md) | Rejected commands, transfer timeouts and write size, restore retry, firmware version, product id, password flag, discovery by manufacturer data | In progress | `v0.2.0` |

## Analyses

| Date | Document | Subject |
|---|---|---|
| 2026-11-11 | [Comparison with ha-ble-led-pixel-display](analysis/2026-11-11-ble-led-pixel-comparison.md) | Features and protocol knowledge of another integration for the same panels, with candidate fixes (C1–C9) and features (N1–N18) |

## Registers

| Document | Content |
|---|---|
| [panel-checks.md](panel-checks.md) | Questions that only the real panel can answer, with their outcomes (V1–V18) |

## Rules

1. **Units.** Each unit of work gets a folder named `NN-topic`: a two-digit sequence number and a short topic in kebab case, for example `01-base` or `02-fixes`. Numbers follow the order in which the work is done and are never reused.
2. **Documents of a unit.** They always have the same names:
   - `spec.md` says **what** to build: requirements, entity model, decisions. A unit has one only when it has user-visible behavior to decide;
   - `plan.md` says **how** to build it: design, tests, milestones and their outcomes.
3. **Header.** A spec or a plan starts with a table: Status, Date, Release when there is one, and Input, the documents it builds on. The status is one of:
   - **Draft**: being written or discussed;
   - **Approved**: agreed, implementation can start;
   - **In progress**: being implemented;
   - **Done**: implemented and released. From then on the document only gets outcomes and corrections of mistakes.
4. **IDs are global.** An ID is never reused or renumbered, so it means the same thing in every document, commit and code comment. A new document continues from the last ID used, and updates this table:

   | ID | Meaning | Defined in | Last used |
   |---|---|---|---|
   | F*n* | Functional requirement, with sub-requirements such as F9.4 | spec | F11 |
   | T*n* | Cross-cutting requirement | spec | T9 |
   | D*n* | Decision | spec, or the plan of a unit without one | D17 |
   | P*n* | Problem of the reference integration | 01-base spec | P10 |
   | M*n* | Milestone | plan | M8 |
   | V*n* | Panel check | panel-checks.md | V18 |

   The IDs of an analysis (for example C1 and N1 in the 2026-11-11 comparison) belong to that analysis only. A plan that takes one up cites the analysis.
5. **Analyses** go in `analysis/`, named `YYYY-MM-DD-topic.md`: research, comparisons, findings. They're snapshots that aren't updated after they're written, and they don't decide anything: a spec or a plan takes up what's useful and makes the decision.
6. **Panel checks.** A question that only the real panel can answer gets a V ID in `panel-checks.md`, with its question, its reason, its unit and, once it's run, its outcome. Specs and plans cite checks by ID.
7. **Language.** Everything is in English, like the code. Entity names and UI strings are written as they appear in HA.
8. **No personal setup.** No host names, IP addresses, paths, tokens or identifiers of the maintainer's panel and adapters (see [CLAUDE.md](../CLAUDE.md)).
