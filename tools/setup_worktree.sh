#!/bin/bash
# Create a git worktree and initialize it for Dockerized evaluation:
# copy datasets, generate parser-location files, and compile the Coq
# theory inside the ccg2lambda:latest container. Fails fast on any
# missing prerequisite instead of falling back silently.
set -eu

usage() {
  cat <<'EOF'
Usage: tools/setup_worktree.sh <worktree-path> [branch] [options]

Run from the root of the main checkout.

Arguments:
  <worktree-path>   Where to create the new worktree.
  [branch]          Branch to check out there (default: basename of the path).
                    Created at HEAD if it does not exist yet.

Options:
  --coqlib FILE     Coq static library source (default: en/coqlib_sick.v)
  --tactics FILE    Coq tactics file (default: en/tactics_coq_sick.txt)
EOF
}

die() { echo "ERROR: $1" >&2; exit 1; }
info() { echo "==> $1"; }

IMAGE=ccg2lambda:latest
coqlib=en/coqlib_sick.v
tactics=en/tactics_coq_sick.txt
worktree_path=""
branch=""

while [ $# -gt 0 ]; do
  case "$1" in
    --coqlib) coqlib="$2"; shift 2 ;;
    --tactics) tactics="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) usage; die "unknown option: $1" ;;
    *)
      if [ -z "${worktree_path}" ]; then worktree_path="$1"
      elif [ -z "${branch}" ]; then branch="$1"
      else usage; die "unexpected argument: $1"
      fi
      shift ;;
  esac
done

[ -n "${worktree_path}" ] || { usage; die "worktree path is required"; }
[ -z "${branch}" ] && branch="$(basename "${worktree_path}")"

# --- Preflight checks in the main checkout -------------------------------
main_root="$(git rev-parse --show-toplevel)" || die "not inside a git repository"
[ "$(pwd)" = "${main_root}" ] || die "run this script from the repository root (${main_root})"
[ -f scripts/prove.py ] || die "this does not look like a ccg2lambda checkout"

[ -f data/raw/SICK.semeval.txt ] \
  || die "data/raw/SICK.semeval.txt not found; run en/download_dependencies.sh first"
[ -f data/interim/verbocean.json ] \
  || die "data/interim/verbocean.json not found; run en/download_dependencies.sh first"
[ -f "${coqlib}" ] || die "coqlib source not found: ${coqlib}"
[ -f "${tactics}" ] || die "tactics file not found: ${tactics}"

docker image inspect "${IMAGE}" > /dev/null 2>&1 \
  || die "Docker image ${IMAGE} not found; build it from the main checkout with: docker compose build eval"

[ ! -e "${worktree_path}" ] || die "worktree path already exists: ${worktree_path}"

# --- Create the worktree ---------------------------------------------------
if git show-ref --verify --quiet "refs/heads/${branch}"; then
  info "creating worktree at ${worktree_path} (existing branch: ${branch})"
  git worktree add "${worktree_path}" "${branch}"
else
  info "creating worktree at ${worktree_path} (new branch: ${branch} at HEAD)"
  git worktree add -b "${branch}" "${worktree_path}"
fi

# --- Copy datasets ---------------------------------------------------------
info "copying datasets into the worktree"
mkdir -p "${worktree_path}/data"
cp -R data/raw "${worktree_path}/data/"
cp -R data/interim "${worktree_path}/data/"
[ -d data/processed ] && cp -R data/processed "${worktree_path}/data/"

# --- Generate parser-location files (paths inside the Docker image) --------
info "generating parser-location files"
echo "/opt/candc-1.00" > "${worktree_path}/en/candc_location.txt"
echo "/opt/easyccg" > "${worktree_path}/en/easyccg_location.txt"
printf "candc:/opt/candc-1.00\neasyccg:/opt/easyccg\ndepccg:\n" \
  > "${worktree_path}/en/parser_location.txt"

# --- Compile the Coq theory inside the container ---------------------------
info "compiling ${coqlib} and installing ${tactics} (inside ${IMAGE})"
if ! cmp -s "${coqlib}" coqlib.v; then
  echo "WARNING: ${coqlib} differs from the tracked coqlib.v;" \
       "the worktree will show a diff on coqlib.v after setup" >&2
fi
(cd "${worktree_path}" && docker compose run --rm eval \
  bash -c "cp '${coqlib}' coqlib.v && coqc coqlib.v && cp '${tactics}' tactics_coq.txt") \
  || die "Coq theory setup failed inside the container"

# --- Verify ----------------------------------------------------------------
info "verifying the worktree"
fail=0
check() {
  if eval "$2"; then echo "  ok: $1"; else echo "  NG: $1"; fail=1; fi
}
check "SICK dataset copied" "cmp -s data/raw/SICK.semeval.txt '${worktree_path}/data/raw/SICK.semeval.txt'"
check "VerbOcean dictionary copied" "cmp -s data/interim/verbocean.json '${worktree_path}/data/interim/verbocean.json'"
check "parser_location.txt generated" "[ -s '${worktree_path}/en/parser_location.txt' ]"
check "candc_location.txt generated" "[ -s '${worktree_path}/en/candc_location.txt' ]"
check "easyccg_location.txt generated" "[ -s '${worktree_path}/en/easyccg_location.txt' ]"
check "coqlib.vo compiled" "[ -s '${worktree_path}/coqlib.vo' ]"
check "tactics_coq.txt installed" "[ -s '${worktree_path}/tactics_coq.txt' ]"
[ "${fail}" -eq 0 ] || die "verification failed; see NG items above"

if [ -n "$(git -C "${worktree_path}" status --porcelain)" ]; then
  echo "WARNING: the worktree is not clean after setup:" >&2
  git -C "${worktree_path}" status --short >&2
fi

info "done. Try it with:"
echo "  cd ${worktree_path} && docker compose run --rm eval coqtop --version"
