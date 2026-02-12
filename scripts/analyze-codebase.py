#!/usr/bin/env python3
"""analyze-codebase.py — Automated codebase analysis for acquisition due diligence.

Performs stack detection, LOC counting, dependency audit, secret detection,
and entry point identification on a target repository.

Usage:
    python3 scripts/analyze-codebase.py /path/to/repo
    python3 scripts/analyze-codebase.py https://github.com/user/repo
    python3 scripts/analyze-codebase.py /path/to/repo --output /path/to/output.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# --- Language detection by file extension ---
LANGUAGE_EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JSX", ".tsx": "TSX", ".rb": "Ruby", ".go": "Go",
    ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".swift": "Swift",
    ".c": "C", ".cpp": "C++", ".h": "C/C++ Header", ".cs": "C#",
    ".php": "PHP", ".sh": "Shell", ".bash": "Shell",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sql": "SQL", ".r": "R", ".R": "R",
    ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir",
    ".lua": "Lua", ".zig": "Zig", ".nim": "Nim",
}

# --- Framework detection patterns ---
FRAMEWORK_PATTERNS = {
    "React": [r"from ['\"]react['\"]", r"import React"],
    "Next.js": [r"from ['\"]next", r"next\.config"],
    "Vue": [r"from ['\"]vue['\"]", r"createApp"],
    "Angular": [r"@angular/core", r"@NgModule"],
    "Django": [r"django\.conf", r"DJANGO_SETTINGS_MODULE"],
    "Flask": [r"from flask", r"Flask\(__name__\)"],
    "FastAPI": [r"from fastapi", r"FastAPI\(\)"],
    "Express": [r"require\(['\"]express['\"]", r"from ['\"]express['\"]"],
    "Rails": [r"Rails\.application", r"class.*<.*ApplicationController"],
    "Spring Boot": [r"@SpringBootApplication", r"spring-boot-starter"],
    "Laravel": [r"use Illuminate", r"artisan"],
    "Gin": [r"github\.com/gin-gonic/gin"],
    "Actix": [r"actix_web", r"actix-web"],
    "Tailwind CSS": [r"tailwindcss", r"@tailwind"],
    "Bootstrap": [r"bootstrap", r"Bootstrap"],
}

# --- Database detection ---
DATABASE_PATTERNS = {
    "PostgreSQL": [r"psycopg2", r"pg_", r"postgresql", r"postgres://"],
    "MySQL": [r"mysql", r"pymysql", r"mysql://"],
    "SQLite": [r"sqlite3", r"sqlite://", r"\.sqlite"],
    "MongoDB": [r"pymongo", r"mongodb://", r"mongoose"],
    "Redis": [r"redis", r"Redis\("],
    "DynamoDB": [r"dynamodb", r"boto3.*dynamodb"],
    "Supabase": [r"supabase", r"@supabase/"],
    "Firebase": [r"firebase", r"firestore"],
}

# --- Secret patterns ---
SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"][a-zA-Z0-9_\-]{20,}['\"]", "API Key"),
    (r"(?i)(secret|password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{8,}['\"]", "Secret/Password"),
    (r"(?i)(token)\s*[=:]\s*['\"][a-zA-Z0-9_\-]{20,}['\"]", "Token"),
    (r"(?i)Bearer\s+[a-zA-Z0-9_\-\.]{20,}", "Bearer Token"),
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"(?i)aws_secret_access_key\s*[=:]\s*['\"][^'\"]+['\"]", "AWS Secret Key"),
    (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Private Key"),
]

# --- Ignore patterns ---
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "vendor", "target", ".gradle",
}

IGNORE_FILES = {
    ".DS_Store", "Thumbs.db", "package-lock.json", "yarn.lock",
    "poetry.lock", "Pipfile.lock", "Cargo.lock", "composer.lock",
}


def clone_repo(url: str) -> str:
    """Shallow clone a remote repo to a temp directory."""
    tmpdir = tempfile.mkdtemp(prefix="archaeology-")
    print(f"Cloning {url} to {tmpdir}...", file=sys.stderr)
    subprocess.run(
        ["git", "clone", "--depth", "1", url, tmpdir],
        check=True,
        capture_output=True,
        text=True,
    )
    return tmpdir


def count_lines(filepath: Path) -> int:
    """Count non-blank lines in a file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except (OSError, UnicodeDecodeError):
        return 0


def detect_languages(repo_path: Path) -> dict:
    """Count lines of code by language."""
    lang_lines = Counter()
    lang_files = Counter()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            if fname in IGNORE_FILES:
                continue
            ext = Path(fname).suffix.lower()
            lang = LANGUAGE_EXTENSIONS.get(ext)
            if lang:
                filepath = Path(root) / fname
                lines = count_lines(filepath)
                lang_lines[lang] += lines
                lang_files[lang] += 1

    total_lines = sum(lang_lines.values())
    result = {}
    for lang, lines in lang_lines.most_common():
        result[lang] = {
            "lines": lines,
            "files": lang_files[lang],
            "percentage": round(lines / total_lines * 100, 1) if total_lines else 0,
        }
    return result


def detect_frameworks(repo_path: Path) -> list:
    """Detect frameworks by scanning file contents."""
    detected = set()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in LANGUAGE_EXTENSIONS and ext not in {".json", ".toml", ".yaml", ".yml", ".cfg"}:
                continue
            filepath = Path(root) / fname
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for framework, patterns in FRAMEWORK_PATTERNS.items():
                if framework in detected:
                    continue
                for pattern in patterns:
                    if re.search(pattern, content):
                        detected.add(framework)
                        break

    return sorted(detected)


def detect_databases(repo_path: Path) -> list:
    """Detect databases by scanning file contents."""
    detected = set()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            filepath = Path(root) / fname
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for db, patterns in DATABASE_PATTERNS.items():
                if db in detected:
                    continue
                for pattern in patterns:
                    if re.search(pattern, content):
                        detected.add(db)
                        break

    return sorted(detected)


def scan_secrets(repo_path: Path) -> list:
    """Scan for potential secrets in the codebase."""
    findings = []

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            if fname in IGNORE_FILES:
                continue
            filepath = Path(root) / fname
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                for pattern, secret_type in SECRET_PATTERNS:
                    if re.search(pattern, line):
                        rel_path = str(filepath.relative_to(repo_path))
                        findings.append({
                            "type": secret_type,
                            "file": rel_path,
                            "line": line_num,
                        })

    return findings


def find_entry_points(repo_path: Path) -> list:
    """Identify likely entry points."""
    entry_points = []
    candidates = [
        "main.py", "app.py", "server.py", "index.js", "index.ts",
        "main.go", "main.rs", "Main.java", "Program.cs",
        "manage.py", "wsgi.py", "asgi.py",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "Makefile", "Procfile", "fly.toml", "vercel.json",
        "package.json", "setup.py", "pyproject.toml",
    ]

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            if fname in candidates:
                rel_path = str(Path(root).relative_to(repo_path) / fname)
                if rel_path.startswith("."):
                    rel_path = fname
                entry_points.append(rel_path)

    return sorted(set(entry_points))


def analyze_dependencies(repo_path: Path) -> dict:
    """Analyze dependency files."""
    deps = {"files": [], "totalPackages": 0, "details": []}

    dep_files = {
        "requirements.txt": "pip",
        "Pipfile": "pipenv",
        "pyproject.toml": "python",
        "setup.py": "python",
        "package.json": "npm",
        "Gemfile": "bundler",
        "go.mod": "go",
        "Cargo.toml": "cargo",
        "composer.json": "composer",
        "pom.xml": "maven",
        "build.gradle": "gradle",
    }

    for fname, manager in dep_files.items():
        found = list(repo_path.rglob(fname))
        for fp in found:
            if any(ignored in str(fp) for ignored in IGNORE_DIRS):
                continue
            rel_path = str(fp.relative_to(repo_path))
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
                if fname == "requirements.txt":
                    pkg_count = sum(1 for l in content.splitlines() if l.strip() and not l.startswith("#"))
                elif fname == "package.json":
                    data = json.loads(content)
                    pkg_count = len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))
                else:
                    pkg_count = None
            except (json.JSONDecodeError, OSError):
                pkg_count = None

            info = {"file": rel_path, "manager": manager}
            if pkg_count is not None:
                info["packageCount"] = pkg_count
                deps["totalPackages"] += pkg_count
            deps["files"].append(rel_path)
            deps["details"].append(info)

    return deps


def analyze_git_history(repo_path: Path) -> dict:
    """Analyze git history for contributor and commit metadata."""
    result = {"available": False}

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return result

    try:
        # Get contributor count
        authors = subprocess.run(
            ["git", "shortlog", "-sn", "--all"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        contributor_count = len([l for l in authors.stdout.splitlines() if l.strip()])

        # Get total commit count
        commit_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )

        # Get first and last commit dates
        first_commit = subprocess.run(
            ["git", "log", "--reverse", "--format=%aI", "--max-count=1"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        last_commit = subprocess.run(
            ["git", "log", "--format=%aI", "--max-count=1"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )

        result = {
            "available": True,
            "contributors": contributor_count,
            "totalCommits": int(commit_count.stdout.strip()) if commit_count.stdout.strip() else 0,
            "firstCommit": first_commit.stdout.strip() if first_commit.stdout.strip() else None,
            "lastCommit": last_commit.stdout.strip() if last_commit.stdout.strip() else None,
            "busFactor": min(contributor_count, 1),  # Simplified — 1 if solo dev
        }
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        pass

    return result


def check_tests(repo_path: Path) -> dict:
    """Check for test files and estimate coverage."""
    test_files = []
    test_dirs = {"tests", "test", "spec", "__tests__", "testing"}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            is_test = (
                fname.startswith("test_")
                or fname.endswith("_test.py")
                or fname.endswith(".test.js")
                or fname.endswith(".test.ts")
                or fname.endswith(".test.tsx")
                or fname.endswith(".spec.js")
                or fname.endswith(".spec.ts")
                or fname.endswith("_spec.rb")
                or Path(root).name in test_dirs
            )
            if is_test:
                rel_path = str(Path(root).relative_to(repo_path) / fname)
                test_files.append(rel_path)

    test_lines = sum(count_lines(repo_path / f) for f in test_files)

    return {
        "testFilesFound": len(test_files),
        "testLines": test_lines,
        "hasTests": len(test_files) > 0,
        "testFiles": test_files[:20],  # Cap at 20 for readability
    }


def check_documentation(repo_path: Path) -> dict:
    """Check for documentation files."""
    doc_files = []
    doc_names = {"README.md", "README.rst", "README.txt", "CONTRIBUTING.md",
                 "CHANGELOG.md", "LICENSE", "LICENSE.md", "docs", "wiki"}

    for item in repo_path.iterdir():
        if item.name in doc_names:
            doc_files.append(item.name)

    docs_dir = repo_path / "docs"
    doc_count = 0
    if docs_dir.is_dir():
        doc_count = sum(1 for _ in docs_dir.rglob("*.md")) + sum(1 for _ in docs_dir.rglob("*.rst"))

    return {
        "hasReadme": "README.md" in doc_files or "README.rst" in doc_files,
        "hasLicense": any(f.startswith("LICENSE") for f in doc_files),
        "hasChangelog": "CHANGELOG.md" in doc_files,
        "hasContributing": "CONTRIBUTING.md" in doc_files,
        "hasDocsDir": docs_dir.is_dir(),
        "docsFileCount": doc_count,
        "foundFiles": doc_files,
    }


def check_ci(repo_path: Path) -> dict:
    """Check for CI/CD configuration."""
    ci_configs = {
        ".github/workflows": "GitHub Actions",
        ".gitlab-ci.yml": "GitLab CI",
        "Jenkinsfile": "Jenkins",
        ".circleci": "CircleCI",
        ".travis.yml": "Travis CI",
        "azure-pipelines.yml": "Azure DevOps",
        "bitbucket-pipelines.yml": "Bitbucket Pipelines",
    }

    found = []
    for path, name in ci_configs.items():
        if (repo_path / path).exists():
            found.append(name)

    return {
        "hasCI": len(found) > 0,
        "providers": found,
    }


def analyze(repo_path: str, output_path: str = None):
    """Run full analysis on the given repository path."""
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        print(f"ERROR: {repo} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing: {repo}", file=sys.stderr)
    print("", file=sys.stderr)

    report = {
        "analysisDate": datetime.now(timezone.utc).isoformat(),
        "repoPath": str(repo),
        "repoName": repo.name,
    }

    print("  [1/9] Detecting languages...", file=sys.stderr)
    report["languages"] = detect_languages(repo)
    total_loc = sum(v["lines"] for v in report["languages"].values())
    report["totalLinesOfCode"] = total_loc

    print("  [2/9] Detecting frameworks...", file=sys.stderr)
    report["frameworks"] = detect_frameworks(repo)

    print("  [3/9] Detecting databases...", file=sys.stderr)
    report["databases"] = detect_databases(repo)

    print("  [4/9] Scanning for secrets...", file=sys.stderr)
    report["secrets"] = scan_secrets(repo)
    report["secretsCount"] = len(report["secrets"])

    print("  [5/9] Finding entry points...", file=sys.stderr)
    report["entryPoints"] = find_entry_points(repo)

    print("  [6/9] Analyzing dependencies...", file=sys.stderr)
    report["dependencies"] = analyze_dependencies(repo)

    print("  [7/9] Analyzing git history...", file=sys.stderr)
    report["gitHistory"] = analyze_git_history(repo)

    print("  [8/9] Checking tests...", file=sys.stderr)
    report["tests"] = check_tests(repo)

    print("  [9/9] Checking documentation & CI...", file=sys.stderr)
    report["documentation"] = check_documentation(repo)
    report["ci"] = check_ci(repo)

    # Output
    output_json = json.dumps(report, indent=2)

    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(output_json)
        print(f"\nReport saved to: {output_path}", file=sys.stderr)
    else:
        print(output_json)

    # Summary to stderr
    print(f"\n=== Analysis Summary ===", file=sys.stderr)
    print(f"Languages: {', '.join(report['languages'].keys())}", file=sys.stderr)
    print(f"Total LOC: {total_loc:,}", file=sys.stderr)
    print(f"Frameworks: {', '.join(report['frameworks']) if report['frameworks'] else 'None detected'}", file=sys.stderr)
    print(f"Databases: {', '.join(report['databases']) if report['databases'] else 'None detected'}", file=sys.stderr)
    print(f"Secrets found: {report['secretsCount']}", file=sys.stderr)
    print(f"Test files: {report['tests']['testFilesFound']}", file=sys.stderr)
    print(f"Has README: {report['documentation']['hasReadme']}", file=sys.stderr)
    print(f"Has CI: {report['ci']['hasCI']}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a codebase for acquisition due diligence"
    )
    parser.add_argument(
        "repo",
        help="Path to local repo or GitHub URL (will be shallow-cloned)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
        default=None,
    )
    args = parser.parse_args()

    repo_path = args.repo

    # If it's a URL, clone it first
    if repo_path.startswith("http://") or repo_path.startswith("https://") or repo_path.startswith("git@"):
        repo_path = clone_repo(repo_path)

    analyze(repo_path, args.output)


if __name__ == "__main__":
    main()
