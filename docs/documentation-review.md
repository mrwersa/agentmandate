# Documentation review — 9 October 2026

Baseline: `f10e646c53e810b642b0676e7ef227c28d760d10`. An independent agent
read all 69 tracked Markdown files at that commit: 9 root documents, 56 under
`docs/` (including 22 evidence documents), one example, one probe, and two
fixture READMEs. No files were skipped. This is an out-of-band documentation
and code review, not a GitHub approval or acceptance of captured evidence.

The review covered writing, navigation, consistency with implementation,
duplication, historical status, and the steps a community user needs to take.
It did not reverify current external vendor claims or repeat live captures.
The new principal contract and implementation received a separate review.

## Changes made

| Reader problem | Correction |
|---|---|
| Installed-package examples lacked their files | README now starts with clone, virtual environment, installation, and repository-root commands |
| Advanced evidence flags obscured ordinary adoption | README leads with scan/review, lint/reach, diff/drift, and replay; an attachment table links to the owning guides |
| Readers had to infer which guide to open | Documentation index now routes by task and defines the different meanings of binding |
| Historical proposals looked like accepted inputs | Conditions show a supported standalone record; delegation, Cedar, and closing-review pages distinguish current formats from earlier proposals |
| Reference text contradicted implemented behavior | Corrected effect-count limits, per-binding ceilings, static inventory selection, tool-name diffs, and the continuity transition list |
| Trace grouping appeared to establish mandate identity | Documented trace grouping and call-ID deduplication assumptions, recorded ordering limits, and incomplete effect evidence |
| Diagnostics appeared safe to publish without review | Security guidance now accounts for observed identifiers and amounts in violations |
| CI and evaluation examples skipped prerequisites | Added baseline fetching, explicit review-file export and shape, and contributor installation steps |
| Manual release advice conflicted with repository policy | Release recovery now uses the automated workflow; Marketplace metadata is treated separately |
| Current status was repeated or contradicted dated records | Roadmap points to the consolidation record; documentation index supplies current readings of historical audits; landscape comparison is labelled as a survey snapshot |
| Old version literals and broken links could mislead | Removed the redundant AGENTS version, updated the production pin, corrected anchors, and checked changed local file links |

The principal implementation adds its own task-oriented contract, synthetic
example, and separate unreviewed historical projection. Its documentation
states the unresolved accounting boundary alongside the runnable commands.

## Records preserved

Captured source files, byte-pinned upstream documents, acceptance quotations,
accepted review metadata, archival profiles, and published changelog history
were preserved. Some historical audits describe an initial proposal before
recording its later outcome; the documentation index links to the closing
decision instead of rewriting those baselines. The evidence index explains
why capture-time feature claims are not a current capability list.

Contract-specific trust and failure rules remain in their owning guides. The
overview now links to them rather than repeating long command blocks. Future
edits should follow the [contributor writing guidance](../CONTRIBUTING.md#writing-documentation)
and keep example metadata clearly labelled as synthetic or illustrative.
