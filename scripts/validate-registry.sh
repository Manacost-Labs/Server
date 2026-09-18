#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
registry="$repo_root/registry.yaml"
inventory="$repo_root/inventory/skills.tsv"
source_inventory="$repo_root/inventory/sources.tsv"
external_inventory="$repo_root/inventory/external-skills.tsv"

failures=0
fail() {
  printf 'ERROR: %s\n' "$1" >&2
  failures=$((failures + 1))
}

[[ -f "$registry" ]] || fail "missing registry.yaml"
[[ -f "$inventory" ]] || fail "missing inventory/skills.tsv"
[[ -f "$source_inventory" ]] || fail "missing inventory/sources.tsv"
[[ -f "$external_inventory" ]] || fail "missing inventory/external-skills.tsv"

for required in AGENTS.md README.md docs/migration.md docs/engineering-skills.md docs/agent-entrypoints.md integrations/cursor/manacost-global.mdc profiles/server.yaml profiles/openbot.yaml profiles/hearthpulse.yaml profiles/icecrow.yaml profiles/wordpress.yaml profiles/data.yaml profiles/engineering.yaml third_party/NOTICE.md scripts/check-agent-entrypoints.sh scripts/install-global-agent-entrypoints.sh; do
  [[ -f "$repo_root/$required" ]] || fail "missing $required"
done

# Host installation is separate from portable repository validation.
# Use make entrypoints explicitly on the managed server.

if [[ -f "$registry" ]]; then
  rg -q '^version: [0-9]+$' "$registry" || fail "registry has no version"
  rg -q '^canonical_root: skills$' "$registry" || fail "registry canonical_root is not skills"
  rg -q '^policy_file: AGENTS\.md$' "$registry" || fail "registry policy_file is not AGENTS.md"
fi

skill_files=$(rg --files "$repo_root/skills" -g 'SKILL.md' 2>/dev/null || true)
if [[ -z "$skill_files" ]]; then
  fail "no canonical SKILL.md files found"
else
  while IFS= read -r skill_file; do
    skill_dir=$(dirname -- "$skill_file")
    relative_skill_file=${skill_file#"$repo_root"/}
    skill_id=$(basename -- "$skill_dir")
    [[ "$skill_id" =~ ^[a-z0-9][a-z0-9-]*$ ]] || fail "invalid skill id: $skill_id"
    [[ -f "$skill_dir/skill.yaml" ]] || fail "missing metadata: $skill_dir/skill.yaml"
    rg -q '^id: ' "$skill_dir/skill.yaml" || fail "missing metadata id: $skill_dir/skill.yaml"
    rg -q '^namespace: ' "$skill_dir/skill.yaml" || fail "missing metadata namespace: $skill_dir/skill.yaml"
    metadata_id=$(sed -n 's/^id: //p' "$skill_dir/skill.yaml" | head -n 1)
    metadata_namespace=$(sed -n 's/^namespace: //p' "$skill_dir/skill.yaml" | head -n 1)
    [[ "$metadata_id" == "$metadata_namespace/$skill_id" ]] || fail "metadata id does not match path: $skill_dir/skill.yaml"
    rg -q -F $'\t'"$relative_skill_file"$'\t' "$inventory" || fail "canonical skill missing from inventory: $skill_dir"
    rg -q '^---$' "$skill_file" || fail "missing frontmatter: $skill_file"
    rg -q '^name: ' "$skill_file" || fail "missing frontmatter name: $skill_file"
    rg -q '^description: ' "$skill_file" || fail "missing frontmatter description: $skill_file"
    if rg -n -i -e 'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY' -e 'gh[pousr]_[A-Za-z0-9_]+' -e 'sk-[A-Za-z0-9]{20,}' "$skill_file" >/dev/null; then
      fail "possible secret marker in $skill_file"
    fi
  done <<< "$skill_files"
fi

if [[ -f "$inventory" ]]; then
  header=$(head -n 1 "$inventory")
  [[ "$header" == $'id\tnamespace\tcanonical_path\tsource_count\tvariant_count\tstatus' ]] || fail "invalid inventory header"
  duplicate_ids=$(tail -n +2 "$inventory" | awk -F '\t' 'NF && ++seen[$1] > 1 {print $1}' | sort -u)
  [[ -z "$duplicate_ids" ]] || fail "duplicate inventory ids: $duplicate_ids"
  while IFS=$'\t' read -r id namespace canonical_path source_count variant_count status; do
    [[ -z "$id" ]] && continue
    [[ -n "$namespace" ]] || fail "missing namespace for $id"
    [[ -f "$repo_root/$canonical_path" ]] || fail "inventory path does not exist: $canonical_path"
    [[ "$source_count" =~ ^[0-9]+$ ]] || fail "invalid source count for $id"
    [[ "$variant_count" =~ ^[0-9]+$ ]] || fail "invalid variant count for $id"
    [[ -n "$status" ]] || fail "missing status for $id"
  done < <(tail -n +2 "$inventory")
fi

if [[ -f "$source_inventory" ]]; then
  source_header=$(head -n 1 "$source_inventory")
  [[ "$source_header" == $'id\tsource_path\tsha256\tselected\tsource_class' ]] || fail "invalid source inventory header"
  while IFS=$'\t' read -r id source_path hash selected source_class; do
    [[ -z "$id" ]] && continue
    awk -F '\t' -v wanted="$id" 'NR > 1 && $1 == wanted {found=1} END {exit !found}' "$inventory" || fail "source inventory references missing id: $id"
    [[ "$source_path" == /* ]] || fail "source path is not absolute for $id"
    [[ "$hash" =~ ^[0-9a-f]{64}$ ]] || fail "invalid source hash for $id"
    [[ "$selected" == yes || "$selected" == no ]] || fail "invalid selected flag for $id"
    [[ "$source_class" == project-local || "$source_class" == user-managed ]] || fail "invalid source class for $id"
  done < <(tail -n +2 "$source_inventory")
fi

if [[ -f "$external_inventory" ]]; then
  external_header=$(head -n 1 "$external_inventory")
  [[ "$external_header" == $'id\tsource_repo\tsource_commit\tsource_path\tsource_sha256\tcanonical_sha256\tlicense\timported_variant\tstatus' ]] || fail "invalid external inventory header"
  while IFS=$'\t' read -r id source_repo source_commit source_path source_hash canonical_hash license imported_variant status; do
    [[ -z "$id" ]] && continue
    awk -F '\t' -v wanted="$id" 'NR > 1 && $1 == wanted {found=1} END {exit !found}' "$inventory" || fail "external inventory references missing id: $id"
    [[ "$source_repo" == https://github.com/* ]] || fail "invalid source repository for $id"
    [[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || fail "invalid source commit for $id"
    [[ -n "$source_path" ]] || fail "missing source path for $id"
    [[ "$source_hash" =~ ^[0-9a-f]{40,64}$ ]] || fail "invalid source hash for $id"
    [[ "$canonical_hash" =~ ^[0-9a-f]{64}$ ]] || fail "invalid canonical hash for $id"
    [[ -n "$license" && -n "$imported_variant" && -n "$status" ]] || fail "incomplete external metadata for $id"
  done < <(tail -n +2 "$external_inventory")
fi

for profile in "$repo_root"/profiles/*.yaml; do
  while IFS= read -r skill_id; do
    [[ -z "$skill_id" ]] && continue
    if ! awk -F '\t' -v id="$skill_id" 'NR > 1 && $1 == id {found=1} END {exit !found}' "$inventory"; then
      fail "profile $(basename -- "$profile") references missing canonical skill: $skill_id"
    fi
  done < <(awk '/^available:/{active=1; next} /^[^[:space:]]/{active=0} active && /^  - [^\/]+\/[^[:space:]]+$/{print $2}' "$profile")
  while IFS= read -r included_profile; do
    [[ -z "$included_profile" ]] && continue
    [[ -f "$repo_root/profiles/$included_profile.yaml" ]] || fail "profile $(basename -- "$profile") includes missing profile: $included_profile"
  done < <(awk '/^include:/{active=1; next} /^[^[:space:]]/{active=0} active && /^  - [a-z0-9][a-z0-9-]*$/{print $2}' "$profile")
done

if (( failures > 0 )); then
  printf 'Validation failed with %s error(s).\n' "$failures" >&2
  exit 1
fi

printf 'Skills registry is valid (%s canonical skill file(s)).\n' "$(printf '%s\n' "$skill_files" | sed '/^$/d' | wc -l)"
