"""Pattern-based knowledge base of common CI/CD failure modes.

Each :class:`Rule` maps regexes to a rich diagnosis: root cause, a deeper
explanation, ordered fix steps, and copy-paste-ready command snippets. The
heuristic analyzer scans build logs against this catalogue and ranks matches
by severity and confidence.

Adding a new failure pattern is a single entry here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import Severity

# (label, language, code) — rendered as a copy-paste block in the UI.
Cmd = tuple[str, str, str]


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    title: str
    severity: Severity
    patterns: tuple[str, ...]
    root_cause: str
    suggested_fix: str
    explanation: str = ""
    fix_steps: tuple[str, ...] = ()
    commands: tuple[Cmd, ...] = ()
    confidence: float = 0.7
    docs_url: str | None = None
    compiled: tuple[re.Pattern, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "compiled",
            tuple(re.compile(p, re.IGNORECASE) for p in self.patterns),
        )


RULES: tuple[Rule, ...] = (
    Rule(
        id="npm-eresolve",
        category="dependency",
        title="npm dependency conflict (ERESOLVE)",
        severity=Severity.high,
        patterns=(r"ERESOLVE", r"could not resolve dependency", r"peer dep"),
        root_cause="npm could not build a consistent dependency tree — a peer-dependency version clash.",
        explanation=(
            "npm v7+ installs peer dependencies automatically and refuses to proceed when two packages "
            "demand incompatible versions of the same peer (e.g. one needs React 17, another React 18). "
            "The 'Could not resolve dependency' block in the log names the exact package and version that clash."
        ),
        suggested_fix="Reconcile the conflicting versions, then reinstall and commit the lockfile.",
        fix_steps=(
            "Read the log's 'Could not resolve dependency' block to find the clashing package and required peer version.",
            "Either upgrade the outdated package, or pin the peer with an `overrides` entry in package.json.",
            "Reinstall and commit the updated package-lock.json so CI is reproducible.",
        ),
        commands=(
            ("Temporary unblock (skips peer checks)", "bash", "npm install --legacy-peer-deps"),
            ("Preferred: upgrade the conflicting package", "bash", "npm install <package>@latest\nnpm install"),
            ("Or force a version via package.json overrides", "json", '"overrides": {\n  "<peer-package>": "<version>"\n}'),
        ),
        confidence=0.85,
        docs_url="https://docs.npmjs.com/cli/v10/commands/npm-install",
    ),
    Rule(
        id="npm-generic-err",
        category="dependency",
        title="npm install failed",
        severity=Severity.high,
        patterns=(r"npm ERR!", r"npm error"),
        root_cause="`npm install` exited non-zero — a package failed to download, build, or resolve.",
        explanation=(
            "npm aborted the install. The most common causes are a registry/network hiccup, a native "
            "module failing to compile (node-gyp), or a package-lock.json that is out of sync with package.json. "
            "The first `npm ERR!` line usually names the offending package."
        ),
        suggested_fix="Check the first `npm ERR!` line, clear the cache, and reinstall from a committed lockfile.",
        fix_steps=(
            "Scroll to the FIRST `npm ERR!` line — later ones are usually noise.",
            "If it mentions node-gyp/build, ensure build tools and the right Node version are present.",
            "Clear the npm cache and reinstall deterministically with `npm ci`.",
        ),
        commands=(
            ("Clean reinstall", "bash", "npm cache clean --force\nrm -rf node_modules package-lock.json\nnpm install"),
            ("Deterministic CI install (needs committed lockfile)", "bash", "npm ci"),
        ),
        confidence=0.7,
    ),
    Rule(
        id="pip-no-version",
        category="dependency",
        title="pip cannot find a matching package version",
        severity=Severity.high,
        patterns=(
            r"Could not find a version that satisfies the requirement",
            r"No matching distribution found",
        ),
        root_cause="A pinned Python dependency version does not exist for this interpreter/platform.",
        explanation=(
            "pip searched the index but no distribution matched your version specifier for the CI's Python "
            "version or OS/architecture. This happens after a bad pin, a yanked release, or when a wheel isn't "
            "published for the runner's Python (e.g. requiring a package that only supports 3.11 on a 3.13 runner)."
        ),
        suggested_fix="Verify the package/version on PyPI and align it with the CI Python version.",
        fix_steps=(
            "Confirm the exact package name and that the version exists on PyPI.",
            "Check which Python version CI uses and whether the package supports it.",
            "Correct or relax the pin in requirements.txt.",
        ),
        commands=(
            ("List available versions", "bash", "pip index versions <package>"),
            ("Pin a version that exists", "bash", 'echo "<package>==<valid-version>" >> requirements.txt'),
        ),
        confidence=0.85,
    ),
    Rule(
        id="python-module-not-found",
        category="dependency",
        title="Python ModuleNotFoundError",
        severity=Severity.high,
        patterns=(r"ModuleNotFoundError: No module named", r"ImportError: No module named"),
        root_cause="A Python module imported at runtime is not installed in the CI environment.",
        explanation=(
            "The code imported a package that pip never installed in CI — usually because it's missing from "
            "requirements.txt, is in the wrong dependency group (dev vs prod), or the install step ran against "
            "a different environment than the tests."
        ),
        suggested_fix="Add the missing package to requirements and ensure it installs before tests run.",
        fix_steps=(
            "Note the module name from the error (`No module named 'X'`).",
            "Add the correct PyPI package to requirements.txt (the import name may differ from the package name).",
            "Confirm the install step runs in the same environment/step as the tests.",
        ),
        commands=(
            ("Add and install the dependency", "bash", "pip install <package>\npip freeze | grep -i <package> >> requirements.txt"),
        ),
        confidence=0.8,
    ),
    Rule(
        id="test-failure",
        category="tests",
        title="Test suite failed",
        severity=Severity.high,
        patterns=(
            r"FAILED\s+\S+::",
            r"AssertionError",
            r"Tests:\s+\d+ failed",
            r"\d+ failed,\s*\d+ passed",
            r"\d+ failing",
        ),
        root_cause="One or more automated tests failed, stopping the pipeline at the test stage.",
        explanation=(
            "The test runner reported failing assertions. This is the pipeline working as intended — it caught a "
            "regression. The log shows the failing test's name and the expected-vs-actual values; reproduce it "
            "locally with the same command to fix the code or update the test."
        ),
        suggested_fix="Reproduce the named failing test locally, then fix the code or the assertion.",
        fix_steps=(
            "Copy the failing test's name/path from the log.",
            "Run just that test locally to reproduce fast.",
            "Fix the underlying code (or update the test if the expectation changed) and re-run.",
        ),
        commands=(
            ("Reproduce one pytest test", "bash", "pytest path/to/test_file.py::test_name -x -vv"),
            ("Reproduce one Jest test", "bash", 'npx jest -t "test name"'),
        ),
        confidence=0.75,
    ),
    Rule(
        id="docker-build",
        category="container",
        title="Docker image build failed",
        severity=Severity.high,
        patterns=(
            r"failed to solve",
            r"returned a non-zero code",
            r"executor failed running",
            r"error building image",
        ),
        root_cause="A step in the Dockerfile exited non-zero, aborting the image build.",
        explanation=(
            "BuildKit stopped at a failing instruction. The log shows the step number and the command that "
            "failed (often a `RUN` that hit a missing package, a bad path, or a network error). Reproduce the "
            "build locally to iterate quickly instead of pushing repeatedly to CI."
        ),
        suggested_fix="Find the failing build step, reproduce with `docker build` locally, and fix that command.",
        fix_steps=(
            "Locate the `#N [step] RUN …` line that failed and the error under it.",
            "Reproduce the exact build locally.",
            "Fix the failing command (install the missing tool, correct the path), then rebuild.",
        ),
        commands=(
            ("Reproduce the build with full logs", "bash", "docker build --progress=plain -t app:debug ."),
            ("Debug interactively up to the failing layer", "bash", "docker build --target <stage> -t app:debug .\ndocker run -it app:debug sh"),
        ),
        confidence=0.8,
    ),
    Rule(
        id="oom",
        category="resources",
        title="Out of memory",
        severity=Severity.critical,
        patterns=(
            r"OOMKilled",
            r"JavaScript heap out of memory",
            r"MemoryError",
            r"Killed\s*$",
            r"signal: killed",
        ),
        root_cause="The job exceeded available memory and was killed by the runner (often exit code 137).",
        explanation=(
            "The process asked for more RAM than the runner allows, so the kernel killed it (exit 137 / SIGKILL). "
            "For Node builds this is usually the V8 heap cap; for data jobs it's loading too much at once. Either "
            "raise the memory ceiling or reduce peak usage (smaller batches, fewer parallel workers)."
        ),
        suggested_fix="Raise the memory limit (e.g. Node's heap) or reduce peak memory per step.",
        fix_steps=(
            "Confirm it's memory: exit code 137 or an explicit 'out of memory' line.",
            "For Node, raise the V8 heap via NODE_OPTIONS.",
            "If it persists, reduce parallelism/batch size or use a larger runner.",
        ),
        commands=(
            ("Raise Node's heap (GitHub Actions env)", "yaml", "env:\n  NODE_OPTIONS: --max-old-space-size=4096"),
            ("Or inline before the build step", "bash", "export NODE_OPTIONS=--max-old-space-size=4096\nnpm run build"),
        ),
        confidence=0.85,
    ),
    Rule(
        id="disk-space",
        category="resources",
        title="No space left on device",
        severity=Severity.critical,
        patterns=(r"No space left on device", r"ENOSPC"),
        root_cause="The runner ran out of disk space mid-build.",
        explanation=(
            "The build filled the runner's disk — commonly from large Docker layers, caches, or downloaded "
            "artifacts. Free space before the heavy step, or prune unused data. Hosted runners have limited disk."
        ),
        suggested_fix="Free disk space before the heavy step (prune caches/images) or use a larger runner.",
        fix_steps=(
            "Add a cleanup step before the disk-heavy step.",
            "Prune unused Docker data and large preinstalled tooling you don't need.",
            "If still tight, split the job or request more disk.",
        ),
        commands=(
            ("Reclaim disk on the runner", "bash", "docker system prune -af --volumes\nsudo rm -rf /usr/share/dotnet /opt/ghc /usr/local/lib/android\ndf -h"),
        ),
        confidence=0.9,
    ),
    Rule(
        id="missing-env",
        category="config",
        title="Missing environment variable or secret",
        severity=Severity.high,
        patterns=(
            r"environment variable .* is not set",
            r"is not defined",
            r"missing required (?:env|environment|secret)",
            r"KeyError: '[A-Z_]+'",
        ),
        root_cause="Code referenced an env var/secret that was not provided to the CI job.",
        explanation=(
            "A script read an environment variable that CI never set. Secrets aren't exposed to a job unless you "
            "map them explicitly, and forks don't receive secrets at all. Add the variable to the job's `env:` "
            "block, sourcing sensitive values from repository/organization secrets — never hard-code them."
        ),
        suggested_fix="Provide the variable via the workflow `env:` block, sourced from repository secrets.",
        fix_steps=(
            "Identify the missing variable name from the error.",
            "Add it under **Settings → Secrets and variables → Actions** if it's sensitive.",
            "Map it into the job/step's `env:` so the code can read it.",
        ),
        commands=(
            ("Expose a secret to a step (GitHub Actions)", "yaml", "env:\n  DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}"),
        ),
        confidence=0.7,
    ),
    Rule(
        id="auth-failure",
        category="auth",
        title="Authentication / authorization failure",
        severity=Severity.high,
        patterns=(
            r"\b401 Unauthorized\b",
            r"\b403 Forbidden\b",
            r"authentication failed",
            r"authentication required",
            r"invalid credentials",
            r"permission denied \(publickey\)",
            r"bad credentials",
            r"denied: requested access to the resource is denied",
            r"denied: access forbidden",
            r"unauthorized: ",
        ),
        root_cause="A request to a registry, API, or repo was rejected due to bad or missing credentials.",
        explanation=(
            "A 401/403 or 'bad credentials' means the token/key CI used is expired, wrong, or lacks the required "
            "scope — or the secret wasn't exposed to this workflow (common for PRs from forks). Rotate or re-scope "
            "the credential and confirm the job can actually see it."
        ),
        suggested_fix="Rotate/verify the token or key, confirm its scope, and ensure the secret reaches the job.",
        fix_steps=(
            "Identify which service returned 401/403 (registry, API, git).",
            "Regenerate the token with the needed scopes and store it as a secret.",
            "Reference the secret in the job and re-run.",
        ),
        commands=(
            ("Use a scoped token from secrets", "yaml", "env:\n  REGISTRY_TOKEN: ${{ secrets.REGISTRY_TOKEN }}"),
        ),
        confidence=0.75,
    ),
    Rule(
        id="permission-denied",
        category="permissions",
        title="Permission denied",
        severity=Severity.medium,
        patterns=(r"Permission denied", r"EACCES", r"Operation not permitted"),
        root_cause="A file or command could not run due to insufficient filesystem permissions.",
        explanation=(
            "Usually a script that isn't marked executable, or a write to a protected path. On CI, checked-out "
            "shell scripts often lose the +x bit; mark them executable in git so it survives checkout."
        ),
        suggested_fix="Make the script executable (and commit the bit), or avoid writing to protected paths.",
        fix_steps=(
            "Identify the file/command that was denied.",
            "Add the executable bit and commit it so CI checkouts keep it.",
            "For write errors, target a writable directory instead.",
        ),
        commands=(
            ("Make a script executable in git", "bash", "chmod +x scripts/deploy.sh\ngit update-index --chmod=+x scripts/deploy.sh\ngit commit -m 'make deploy.sh executable'"),
        ),
        confidence=0.65,
    ),
    Rule(
        id="network-timeout",
        category="network",
        title="Network timeout / connection failure",
        severity=Severity.medium,
        patterns=(
            r"ETIMEDOUT",
            r"ECONNREFUSED",
            r"Connection refused",
            r"connection timed out",
            r"Temporary failure in name resolution",
            r"Could not resolve host",
        ),
        root_cause="A network call failed — often transient, or a required service wasn't ready.",
        explanation=(
            "A download or service call couldn't connect. 'Connection refused' usually means a dependent service "
            "(DB, cache) isn't up yet; DNS/timeout errors are often transient registry issues. Add readiness waits "
            "for services and retries with backoff for flaky downloads."
        ),
        suggested_fix="Retry transient failures; wait for dependent services to be ready before using them.",
        fix_steps=(
            "Decide if it's transient (registry/DNS) or a service not ready (ECONNREFUSED).",
            "For services, add a readiness wait before the step that connects.",
            "For downloads, wrap the command in a retry with backoff.",
        ),
        commands=(
            ("Retry a flaky command", "bash", "for i in 1 2 3; do <command> && break || sleep $((i*5)); done"),
            ("Wait for a service port", "bash", "until nc -z localhost 5432; do echo waiting; sleep 2; done"),
        ),
        confidence=0.6,
    ),
    Rule(
        id="lint",
        category="quality",
        title="Lint / formatting check failed",
        severity=Severity.medium,
        patterns=(
            r"eslint",
            r"flake8",
            r"would reformat",
            r"ruff.*error",
            r"Lint(?:ing)? failed",
        ),
        root_cause="A static-analysis or formatting gate rejected the code.",
        explanation=(
            "A linter/formatter found violations and returned non-zero to block the merge. Most tools can auto-fix "
            "the majority of issues; run the same tool locally, apply fixes, and commit."
        ),
        suggested_fix="Run the linter/formatter locally with auto-fix and commit the result.",
        fix_steps=(
            "Note which tool failed (ruff, black, eslint, flake8).",
            "Run it locally with its auto-fix flag.",
            "Review and commit the changes.",
        ),
        commands=(
            ("Python (ruff + black)", "bash", "ruff check --fix .\nblack ."),
            ("JavaScript/TypeScript (eslint)", "bash", "npx eslint . --fix"),
        ),
        confidence=0.6,
    ),
    Rule(
        id="syntax-error",
        category="build",
        title="Syntax / compilation error",
        severity=Severity.high,
        patterns=(
            r"SyntaxError",
            r"Unexpected token",
            r"cannot find symbol",
            r"error TS\d+",
            r"compilation failed",
        ),
        root_cause="Source code failed to parse or compile.",
        explanation=(
            "The compiler/interpreter couldn't parse a file — a typo, missing import, or type error. The log names "
            "the file and line. Fix it locally and re-run the same build command before pushing."
        ),
        suggested_fix="Open the file/line from the error and fix the syntax or type issue.",
        fix_steps=(
            "Read the file path and line number in the error.",
            "Fix the syntax/type problem there.",
            "Re-run the build locally to confirm before pushing.",
        ),
        commands=(
            ("Type-check TypeScript locally", "bash", "npx tsc --noEmit"),
            ("Byte-compile Python to catch syntax errors", "bash", "python -m compileall ."),
        ),
        confidence=0.75,
    ),
    Rule(
        id="command-not-found",
        category="config",
        title="Command / tool not found",
        severity=Severity.medium,
        patterns=(r"command not found", r": not found", r"is not recognized as"),
        root_cause="A CLI tool the job invoked is not installed on the runner or not on PATH.",
        explanation=(
            "The runner image doesn't include the tool, or a setup step didn't run before it was called. Add an "
            "install/setup step (or the appropriate setup action) earlier in the job."
        ),
        suggested_fix="Add a setup/install step for the tool before the step that uses it.",
        fix_steps=(
            "Identify the missing command.",
            "Add a setup action or install step earlier in the job.",
            "Verify it's on PATH before the step that failed.",
        ),
        commands=(
            ("Install a tool on an Ubuntu runner", "bash", "sudo apt-get update && sudo apt-get install -y <tool>"),
            ("Provision a language toolchain (example)", "yaml", "- uses: actions/setup-node@v4\n  with:\n    node-version: '20'"),
        ),
        confidence=0.65,
    ),
    Rule(
        id="yaml-workflow",
        category="config",
        title="Workflow / YAML syntax error",
        severity=Severity.high,
        patterns=(
            r"yaml: line \d+",
            r"Invalid workflow file",
            r"mapping values are not allowed",
            r"did not find expected",
        ),
        root_cause="The workflow or a YAML config file is malformed, so it never ran correctly.",
        explanation=(
            "YAML is whitespace-sensitive: a wrong indent, a tab, or an unquoted special character breaks parsing. "
            "The error points to a line — fix the indentation/quoting and validate before pushing."
        ),
        suggested_fix="Fix the indentation/quoting at the reported line and validate the YAML.",
        fix_steps=(
            "Open the file at the reported line.",
            "Check for tabs, bad indentation, or unquoted `:` / special characters.",
            "Validate locally before pushing.",
        ),
        commands=(
            ("Validate a YAML file locally", "bash", 'python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" .github/workflows/ci.yml'),
        ),
        confidence=0.8,
    ),
    Rule(
        id="terraform",
        category="iac",
        title="Terraform error",
        severity=Severity.high,
        patterns=(
            r"Error: .*terraform",
            r"terraform (?:plan|apply) .*(?:error|failed)",
            r"Error acquiring the state lock",
            r"Error: Invalid",
            r"╷",  # Terraform's diagnostic box drawing
        ),
        root_cause="A Terraform plan/apply failed — invalid config, a provider error, or a locked state.",
        explanation=(
            "Terraform stopped applying infrastructure changes. Common causes are a syntax/validation error in "
            "HCL, a provider/credentials issue, or a leftover state lock from a previous run that crashed. The "
            "'Error:' block names the resource and problem."
        ),
        suggested_fix="Read the Error block, validate the config, and clear a stale state lock if present.",
        fix_steps=(
            "Run `terraform validate` to catch HCL/config errors early.",
            "If it says 'Error acquiring the state lock', confirm no other apply is running, then force-unlock.",
            "Re-run plan to preview before applying.",
        ),
        commands=(
            ("Validate and format", "bash", "terraform fmt -check\nterraform validate"),
            ("Release a stale state lock (use the LOCK_ID from the error)", "bash", "terraform force-unlock <LOCK_ID>"),
        ),
        confidence=0.75,
    ),
    Rule(
        id="java-build",
        category="build",
        title="Maven / Gradle build failed",
        severity=Severity.high,
        patterns=(
            r"BUILD FAILURE",
            r"BUILD FAILED",
            r"Could not resolve (?:dependencies|all files)",
            r"FAILURE: Build failed with an exception",
            r"\[ERROR\] Failed to execute goal",
        ),
        root_cause="A Java/Kotlin build (Maven or Gradle) failed to compile or resolve dependencies.",
        explanation=(
            "The build tool exited non-zero. Maven's '[ERROR] Failed to execute goal' and Gradle's 'BUILD FAILED' "
            "point to the failing plugin/task — often a missing dependency (wrong repo/version), a compile error, "
            "or a failing test bound to the build."
        ),
        suggested_fix="Reproduce the build locally with a stack trace and fix the failing goal/task.",
        fix_steps=(
            "Find the '[ERROR]' (Maven) or 'What went wrong' (Gradle) section.",
            "Reproduce locally with full output.",
            "Fix the dependency/compile error and rebuild.",
        ),
        commands=(
            ("Maven with full errors", "bash", "mvn -e -X clean install"),
            ("Gradle with stacktrace", "bash", "./gradlew build --stacktrace --info"),
        ),
        confidence=0.75,
    ),
    Rule(
        id="go-build",
        category="build",
        title="Go build/test failure",
        severity=Severity.high,
        patterns=(
            r"\.go:\d+:\d+:",           # compile error: file.go:line:col:
            r"undefined: \w+",
            r"cannot find package",
            r"go: .*(?:no required module|missing go.sum entry)",
            r"--- FAIL: ",
        ),
        root_cause="A Go build or test failed — a compile error, a missing module, or a failing test.",
        explanation=(
            "The Go toolchain reported an error. 'undefined:' and '.go:line' are compile errors; 'missing go.sum "
            "entry' means modules are out of sync; '--- FAIL:' is a failing test. Tidy modules and run vet/tests "
            "locally to reproduce."
        ),
        suggested_fix="Sync modules, fix the compile/test error, and re-run `go build ./...`.",
        fix_steps=(
            "If it's a module error, run `go mod tidy` and commit go.mod/go.sum.",
            "For compile errors, open the reported .go file and line.",
            "Reproduce with `go build ./...` and `go test ./...`.",
        ),
        commands=(
            ("Sync modules and build", "bash", "go mod tidy\ngo build ./...\ngo vet ./..."),
        ),
        confidence=0.7,
    ),
    Rule(
        id="rust-cargo",
        category="build",
        title="Rust / Cargo build failed",
        severity=Severity.high,
        patterns=(
            r"error\[E\d+\]",
            r"error: could not compile",
            r"cargo:.*error",
            r"error: failed to (?:run|resolve)",
        ),
        root_cause="A Rust build failed — a compile error (Exxxx) or a dependency resolution problem.",
        explanation=(
            "rustc/cargo stopped on an error. `error[Exxxx]` codes are compile errors with a link to an "
            "explanation; 'could not compile' names the crate. `cargo build` locally reproduces it fast, and "
            "`cargo explain` describes any error code."
        ),
        suggested_fix="Reproduce with `cargo build`, read the error code, and fix the crate.",
        fix_steps=(
            "Note the `error[Exxxx]` code and the file/line.",
            "Run `cargo build` locally to iterate.",
            "Use `rustc --explain Exxxx` to understand the error class.",
        ),
        commands=(
            ("Build and explain an error code", "bash", "cargo build\nrustc --explain E0308"),
        ),
        confidence=0.75,
    ),
    Rule(
        id="k8s-pod",
        category="deploy",
        title="Kubernetes deployment failure",
        severity=Severity.high,
        patterns=(
            r"ImagePullBackOff",
            r"ErrImagePull",
            r"CrashLoopBackOff",
            r"CreateContainerConfigError",
            r"failed to pull image",
            r"0/\d+ nodes are available",
        ),
        root_cause="A pod failed to start — bad image reference, crashing container, or unschedulable.",
        explanation=(
            "Kubernetes couldn't run the pod. ImagePullBackOff/ErrImagePull means the image name/tag is wrong or "
            "the registry needs credentials; CrashLoopBackOff means the container starts then exits (check its "
            "logs); '0/N nodes available' is a scheduling constraint (resources, taints, affinity)."
        ),
        suggested_fix="Inspect the pod events and container logs to see which of the three it is.",
        fix_steps=(
            "Describe the pod to read the Events section.",
            "For image errors, verify the image:tag and registry pull secret.",
            "For crashes, read the previous container's logs.",
        ),
        commands=(
            ("Inspect a failing pod", "bash", "kubectl describe pod <pod>\nkubectl logs <pod> --previous"),
        ),
        confidence=0.8,
    ),
    Rule(
        id="helm",
        category="deploy",
        title="Helm release failed",
        severity=Severity.high,
        patterns=(
            r"Error: UPGRADE FAILED",
            r"Error: INSTALLATION FAILED",
            r"another operation .* is in progress",
            r"helm.*error",
        ),
        root_cause="A Helm install/upgrade failed — often a bad values/template or a stuck previous release.",
        explanation=(
            "Helm couldn't reconcile the release. A common trap is 'another operation is in progress', left by a "
            "prior failed upgrade, which blocks new ones until the release is rolled back. Otherwise it's usually "
            "an invalid template or values."
        ),
        suggested_fix="Roll back the stuck release, or lint/template the chart to find the bad manifest.",
        fix_steps=(
            "Check release history for a pending/failed revision.",
            "Roll back to the last good revision to clear the lock.",
            "Lint and render the chart locally before retrying.",
        ),
        commands=(
            ("Recover a stuck release", "bash", "helm history <release>\nhelm rollback <release> <last-good-revision>"),
            ("Validate the chart locally", "bash", "helm lint ./chart\nhelm template ./chart --values values.yaml"),
        ),
        confidence=0.75,
    ),
    Rule(
        id="git-fetch",
        category="scm",
        title="Git clone / checkout failed",
        severity=Severity.medium,
        patterns=(
            r"fatal: (?:could not read|repository .* not found|Authentication failed)",
            r"fatal: reference is not a tree",
            r"error: Your local changes",
            r"could not resolve host: github",
        ),
        root_cause="A git operation failed — auth, a missing ref, or network/DNS.",
        explanation=(
            "The checkout step couldn't fetch the repo or a specific ref. 'Authentication failed' points to a "
            "token/permissions issue (submodules and private repos need credentials); 'reference is not a tree' "
            "means a commit/tag no longer exists (e.g. force-pushed)."
        ),
        suggested_fix="Fix credentials for private repos/submodules, or point at a ref that still exists.",
        fix_steps=(
            "Confirm the repo and ref still exist and are reachable.",
            "For private repos/submodules, provide a token with read access.",
            "Ensure the checkout fetches enough history if you reference older commits.",
        ),
        commands=(
            ("Full-history checkout with submodules (GitHub Actions)", "yaml", "- uses: actions/checkout@v4\n  with:\n    submodules: recursive\n    fetch-depth: 0\n    token: ${{ secrets.REPO_TOKEN }}"),
        ),
        confidence=0.65,
    ),
    Rule(
        id="flaky-test",
        category="tests",
        title="Possible flaky test (passed on retry)",
        severity=Severity.low,
        patterns=(
            r"RETRYING|attempt \d+ of \d+",
            r"flaky",
            r"passed on retry",
            r"rerun",
        ),
        root_cause="A step succeeded only after a retry, suggesting a flaky (non-deterministic) test or job.",
        explanation=(
            "Retries that eventually pass hide instability — usually timing/race conditions, shared state between "
            "tests, or reliance on external services. These erode trust in CI. Identify the intermittent test and "
            "make it deterministic rather than relying on retries."
        ),
        suggested_fix="Find the intermittent test and remove the nondeterminism (timing, order, shared state).",
        fix_steps=(
            "Identify which test needed a retry from the log.",
            "Run it in isolation and in a loop to reproduce the flake.",
            "Fix the root cause (add proper waits, isolate state, mock external calls).",
        ),
        commands=(
            ("Hammer one pytest test to expose flakiness", "bash", "pytest path::test_name --count=50 -p no:randomly"),
        ),
        confidence=0.55,
    ),
)
