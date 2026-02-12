#!/usr/bin/env bash
# scan-zombie-repos.sh — Enumerate abandoned GitHub repos via gh CLI
# Outputs JSON array of "zombie" repos (90+ days since last push)
# Usage: bash scripts/scan-zombie-repos.sh [--days 90] [--output /path/to/output.json]

set -euo pipefail

# --- Configuration ---
ZOMBIE_THRESHOLD_DAYS="${1:-90}"
OUTPUT_DIR="${HOME}/jarvis/data/zombies/scan-history"
DATE_STAMP=$(date +%Y-%m-%d)
OUTPUT_FILE="${OUTPUT_DIR}/${DATE_STAMP}-scan.json"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --days) ZOMBIE_THRESHOLD_DAYS="$2"; shift 2 ;;
        --output) OUTPUT_FILE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# --- Preflight checks ---
if ! command -v gh &> /dev/null; then
    echo "ERROR: GitHub CLI (gh) not found. Install with: brew install gh" >&2
    exit 1
fi

if ! gh auth status &> /dev/null; then
    echo "ERROR: GitHub CLI not authenticated. Run: gh auth login" >&2
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo "ERROR: jq not found. Install with: brew install jq" >&2
    exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT_FILE")"

echo "=== Zombie Repo Scanner ===" >&2
echo "Threshold: ${ZOMBIE_THRESHOLD_DAYS} days since last push" >&2
echo "Output: ${OUTPUT_FILE}" >&2
echo "" >&2

# --- Calculate cutoff date ---
if [[ "$(uname)" == "Darwin" ]]; then
    CUTOFF_DATE=$(date -v-${ZOMBIE_THRESHOLD_DAYS}d +%Y-%m-%dT%H:%M:%SZ)
else
    CUTOFF_DATE=$(date -d "${ZOMBIE_THRESHOLD_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)
fi

echo "Cutoff date: ${CUTOFF_DATE}" >&2

# --- Fetch all repos ---
echo "Fetching repository list..." >&2

ALL_REPOS=$(gh repo list --json name,pushedAt,url,description,primaryLanguage,isArchived,isFork,stargazerCount,diskUsage --limit 500)

TOTAL_COUNT=$(echo "$ALL_REPOS" | jq 'length')
echo "Total repos found: ${TOTAL_COUNT}" >&2

# --- Filter zombies ---
# Criteria: pushed before cutoff, not archived, not a fork
ZOMBIE_REPOS=$(echo "$ALL_REPOS" | jq --arg cutoff "$CUTOFF_DATE" '[
    .[] | select(
        .pushedAt < $cutoff
        and .isArchived == false
        and .isFork == false
    ) | {
        name: .name,
        url: .url,
        description: (.description // "No description"),
        language: (.primaryLanguage.name // "Unknown"),
        lastPush: .pushedAt,
        stars: .stargazerCount,
        diskUsageKB: .diskUsage,
        daysSinceLastPush: (
            (now - (.pushedAt | fromdateiso8601)) / 86400 | floor
        )
    }
] | sort_by(-.daysSinceLastPush)')

ZOMBIE_COUNT=$(echo "$ZOMBIE_REPOS" | jq 'length')
echo "Zombie repos found: ${ZOMBIE_COUNT}" >&2

# --- Build output ---
OUTPUT=$(jq -n \
    --arg date "$DATE_STAMP" \
    --arg cutoff "$CUTOFF_DATE" \
    --argjson threshold "$ZOMBIE_THRESHOLD_DAYS" \
    --argjson total "$TOTAL_COUNT" \
    --argjson zombieCount "$ZOMBIE_COUNT" \
    --argjson zombies "$ZOMBIE_REPOS" \
    '{
        scanDate: $date,
        cutoffDate: $cutoff,
        thresholdDays: $threshold,
        totalRepos: $total,
        zombieCount: $zombieCount,
        zombies: $zombies
    }')

# --- Write output ---
echo "$OUTPUT" > "$OUTPUT_FILE"
echo "" >&2
echo "Scan complete. Results saved to: ${OUTPUT_FILE}" >&2

# Also output to stdout for piping
echo "$OUTPUT"
