# Four-document implementation

This candidate implements the four supplied proposals together: bounded code
retrieval, design quality, engineering gates and on-demand context loading.
The source is `integrations/codex/subscription-savings`; it extends the existing
context-economy application. The attached documents are design inputs, not
authority to change models, expose data, deploy or spend money.

- [Section coverage](coverage.md): every numbered section, implementation and limits.
- [Commands and contracts](commands.md): local setup, examples and extension format.
- [Project integration and activation](projects.md): HearthPulse and hs-manacost.ru.
- [Verification](verification.md): evidence, review gates and remaining operational work.
- [Real code and OpenRouter](retrieval-openrouter.md): follow-up correctness fixes and live API/cache evidence.

The local AST/BM25 implementation deliberately does not start a Zoekt service,
database server or local language model. It supplies bounded alternatives for
these purposes. Optional embeddings/reranking now use the existing server
OpenRouter by default; actual API calls and reuse were tested on public code.
No saving percentage is claimed: compare actual task usage and quality using
the existing meter, pilot and benchmark commands before drawing that conclusion.

The permanent router is a small opt-in entrypoint. The four reference documents,
this runbook and the full guard catalog must not become permanent agent context.
