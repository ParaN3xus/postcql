#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$script_dir"
if git -C "$script_dir" rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git -C "$script_dir" rev-parse --show-toplevel)"
fi
output_path="${1:-$repo_root/dist/postql-submission.tar.gz}"
staging_dir="$(mktemp -d /tmp/postql-package.XXXXXX)"

cleanup() {
  rm -rf "$staging_dir"
}
trap cleanup EXIT

copy_file() {
  local src="$1"
  local dst="$staging_dir/$src"
  mkdir -p "$(dirname "$dst")"
  cp -p "$repo_root/$src" "$dst"
}

copy_dir() {
  local src="$1"
  local dst_parent="$staging_dir/$(dirname "$src")"
  mkdir -p "$dst_parent"
  cp -a "$repo_root/$src" "$dst_parent/"
}

mkdir -p "$(dirname "$output_path")"

cd "$repo_root"

# Include all tracked, non-ignored repository files.
git ls-files -z | while IFS= read -r -d '' path; do
  copy_file "$path"
done

# Preserve requested empty directories from work/.
mkdir -p \
  "$staging_dir/work/codeql-db" \
  "$staging_dir/work/source" \
  "$staging_dir/work/results"

# Include requested work artifacts.
copy_dir "work/codeql-results"
copy_dir "work/results/analyze-all"
copy_dir "work/results/analyze-all-initial"
copy_file "work/results/gt.csv"

tar -C "$staging_dir" -czf "$output_path" .

printf 'Wrote package to %s\n' "$output_path"
