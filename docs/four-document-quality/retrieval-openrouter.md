# Real code retrieval and OpenRouter verification

The user requested a correctness review with special attention to existing real
code, and explicitly chose the server's existing OpenRouter for embeddings and
reranking. This supersedes the initial unprovisioned-provider assumption. No
credential, installed release or application runtime was changed.

## Findings and corrections

1. The original semantic adapter was only an external subprocess contract.
   `quality_openrouter.py` now implements the real OpenRouter embedding and
   cross-encoder rerank endpoints, reusing `remote.api_key()` and the shared
   `remote.Ledger`. No chat completion is substituted for reranking.
2. Only the first 60 source lines originally reached semantic providers. The
   shortlist now considers definitions throughout each explicitly selected file.
   Existing ast-grep parsing supplies function names/ranges. Large functions are
   bounded exact excerpts with `complete_definition: false`; a snippet is not
   falsely described as a complete copy-paste implementation.
3. Keyword frequency could select constructor documentation or test code over
   an implementation. Function-name matches now take priority in local selection;
   external test sources are excluded unless `--include-tests` is explicit.
4. GitHub content now has an independently calculated Git blob SHA/byte-length
   check, full-file SHA256 and a commit-pinned source URL. Metadata filtering and
   AST selection do not assert that the upstream tests passed or the code is
   compatible with the target application; those fields remain explicitly false.
5. GitHub commit responses could exceed the output cap by including an unrelated
   commit's patch. Metadata/commit lookups now select only the required JSON fields,
   reuse repository metadata, and reject oversized file results explicitly.
6. Historical cached usage is now `cached_usage`; a cache hit has `usage: null`,
   `network_calls: 0`, `openrouter_calls: 0`, and `call_cost_usd: 0`. It is not
   reported as a new charge.

## Default provider and controls

| Operation | OpenRouter model | Native endpoint |
| --- | --- | --- |
| semantic-search | `qwen/qwen3-embedding-8b` | `/api/v1/embeddings` |
| rerank | `qwen/qwen3-reranker-8b` | `/api/v1/rerank` |

The embedding vector size is 1024. Model availability was checked against the
live embedding catalog and the `models?output_modalities=rerank` catalog. The
smaller Qwen 0.6B reranker had no serving endpoints; it was not silently assumed
available. Defaults are configurable, not a claim that these models are optimal
for every codebase.

No project provider file is required for these defaults. An optional
`.ai/manacost-quality.json` may override them:

```json
{
  "version": 1,
  "providers": {
    "semantic-search": {"backend": "openrouter", "model": "qwen/qwen3-embedding-8b", "dimensions": 1024},
    "rerank": {"backend": "openrouter", "model": "qwen/qwen3-reranker-8b"}
  }
}
```

The existing `OPENROUTER_API_KEY` or private
`~/.config/codex-context-economy/remote.env` is used without copying its contents.
Preview/cache-hit operations do not load credentials. Cache misses require
`--allow-remote`; no automatic fallback, retry or model promotion occurs.
Requests cannot follow redirects or environment proxies. Selected input is
limited to 30 exact chunks and 24 KB; potential credential patterns are rejected
before credential loading or transmission. This is a precaution, not a complete
secret detector: select only authorized source paths.

Defaults reserve $0.01 per call against the shared $0.10/24h retrieval budget,
with a shared 30-call ceiling. Switching project state directories or operations
does not reset the shared ledger. Failed/unknown charges keep their reservation;
reported actual costs replace it. The request also sets a nominal provider input
price filter. Effective rerank billing is not reliably described by the model
catalog's zero prompt price: actual returned `usage.cost` is authoritative.
These are conservative reservations/routing controls, not a hard billing limit
at the provider account; a configured backend ceiling does not override invoices.

Embeddings are cached by backend/model/vector configuration, revision, source
SHA, exact range and text. A different query can reuse document vectors while
requesting only its own vector. Complete query results are cached separately.
Model IDs do not prove immutable provider weights; the explicit revision and
cache TTL bound reuse, and operators must bump the revision on backend changes.

## Working commands

```sh
quality_src=/srv/projects/tools/skills/integrations/codex/subscription-savings
quality_python=python3

# Fetch real public implementations and rerank the verified snippets.
"$quality_python" "$quality_src/context_economy.py" --project /path/to/project reference-search \
  'acquire repo:redis/redis-py filename:lock.py' --limit 2 \
  --evidence-gap 'Need a reusable Redis locking implementation' --rerank-references --allow-remote

# Optional semantic comparison of explicitly chosen local source.
"$quality_python" "$quality_src/context_economy.py" --project /path/to/project semantic-search \
  'Acquire a Redis lock with a blocking timeout' --source src/locks --limit 3 \
  --evidence-gap 'Lexical matches do not distinguish implementations' --preview-remote

# Replace preview with --allow-remote only for authorized selected source.
# The same explicit source selection works with the rerank command.

# Evaluate versioned labels owned by each project; remote mode is opt-in.
"$quality_python" "$quality_src/context_economy.py" --project /srv/projects/web/HeartPulse \
  retrieval-eval --manifest config/retrieval-eval.json
"$quality_python" "$quality_src/context_economy.py" --project /srv/projects/wordpress/hs-manacost.ru \
  retrieval-eval --manifest config/retrieval-eval.json --semantic --case-id s3-image-path

# Inspect bounded UTC daily cache activity without source or query keys.
"$quality_python" "$quality_src/context_economy.py" --project /path/to/project cache-stats --days 7
```

The models return vectors or scores. All code returned to the caller comes from
the original verified source; the models cannot supply invented code or new
source IDs. Unknown, duplicated or missing response indices and invalid vectors
or scores fail validation. Source may still be unsuitable or malicious: inspect
the license, compatibility and relevant tests before incorporating a reference.

## Project retrieval check and task measurement

The original built-in `retrieval-eval` suites pin two small, labeled cases per
project in `context_economy/retrieval_eval.py`. On 2026-09-24, HearthPulse at
`09b417e16bb929ff6508cf2566520bbefb5aa039` returned the expected file at
rank 1 for both cases locally and through native OpenRouter embedding/rerank.
hs-manacost.ru at `7ca40c8ef04438d6765d111c2327309fe50dcf5b` returned
both files within the top three locally (mean reciprocal rank 0.75) and at
rank 1 after embedding/rerank (mean reciprocal rank 1.0). First remote runs
made four OpenRouter calls per project; immediate repeats made zero. A real
PHP AST edge case found during this run was fixed so empty reference fragments
are skipped. These four cases are a smoke benchmark, not a representative
measure of task success or token savings; expand the labeled set before tuning
default search behavior. The versioned project manifests now carry six positive
and one no-answer case each, so labels can move with source. On current selected
project worktrees, the local search found all twelve target files in the top
three snippets (HearthPulse MRR 1.0; hs-manacost.ru MRR 0.917) and rejected
both no-answer cases. The expanded OpenRouter run reached the shared 24-hour
call cap before completion; no full remote score is claimed. `--case-id` permits
bounded subsets and cached rechecks without bypassing the cap.

The existing `meter-start`, `meter-finish`, `pilot-record --meter-task` and
`report --end-to-end` commands measure completed attempts and matched task
outcomes. `meter-start --current-session` resolves the exact local Codex or
Claude Code session ID from its host environment without guessing from recent
files. Start an
interval before preparation, record verification evidence
and rework, and finish it after the final check. Include both baseline and
advised variants for the same task hash. Current historical project data does
not contain a completed matched pilot, so no percentage reduction is claimed.
`cache-stats` exposes hit, miss, expiry, write, eviction and retained-entry
counts by namespace plus up to 30 UTC daily buckets. Historical daily counts
cannot be backfilled. The 1000-entry global cap and existing TTL remain in
place until real churn data justify a change.

## Live smoke evidence (public source only)

Artifacts are under `/tmp/four-document-retrieval-live-20260923/`:

- `github-rerank-ast.json`: two actual `acquire` implementations in
  `redis/asyncio/lock.py` and `redis/lock.py`, both MIT metadata, verified blobs and
  pinned to redis-py commit `d32d9cda6283`. They are implementation sources, not
  test files. Native rerank returned usage of 660 tokens and $0.000132.
- `embeddings.json`: real copies of those public sources plus a CPython JSON
  decoding distractor. Both lock implementations ranked first, ahead of JSON
  decoding. 1024-dimensional embeddings, 3257 reported input tokens, $0.00003257.
- `embeddings-reuse.json`: a slightly changed query reused 20 cached source
  vectors and sent only 27 reported tokens, costing $0.00000027.
- `embeddings-cache.json`: an exact repeated query succeeded without
  `--allow-remote`, with zero network calls and zero new charge.

Four live model calls, including the first diagnostic run that exposed the test/
documentation ranking problem, reported **$0.00049824 total**. This demonstrates
these calls and cache behavior; it is not a general token-saving percentage or
a code-retrieval quality benchmark across the projects. Private application code
was not sent during this smoke test.

Offline regressions: `tests/test_quality_retrieval.py` checks provenance, source
tails, function-vs-documentation selection, test filtering, model index/vector/
score validation, credential-free previews, shared budgets and cache accounting.
Existing quality and remote-assistant regressions remain part of canonical CI.

Primary references used for the protocol:
[OpenRouter RAG guide](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag),
[Embeddings API](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings).
The existing Context7 integration was used to verify the request and response
contracts against OpenRouter's documentation source.
