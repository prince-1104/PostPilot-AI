<#
PostPilot AI reliability verification (Windows PowerShell)
Place this file in the PostPilot-AI repository root, then run:
  .\verify_postpilot_reliability.ps1
Optional PostgreSQL integration run (ONLY after preparing a dedicated local test DB):
  .\verify_postpilot_reliability.ps1 -IncludeIntegration

This script does not call the live LinkedIn API. All selected unit tests
use in-memory SQLite and a fake provider; integration tests use a fake
or HTTPX-mocked provider with real PostgreSQL.
#>
param([switch]$IncludeIntegration)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$apiDir = Join-Path $root 'apps/api'
if (-not (Test-Path (Join-Path $apiDir 'pyproject.toml'))) {
    throw 'Place verify_postpilot_reliability.ps1 at the root of the PostPilot-AI repository.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found on PATH. Activate/install uv before running.'
}

Push-Location $apiDir
try {
    Write-Host "`n=== SAFE UNIT TESTS: retry / duplicate / cancellation / ambiguity ===" -ForegroundColor Cyan
    $unitTests = @(
        'tests/test_publishing.py::test_rate_limit_schedules_retry',
        'tests/test_publishing.py::test_retry_backoff_honors_retry_after',
        'tests/test_publishing.py::test_retry_exhaustion_marks_failed',
        'tests/test_publishing.py::test_cancel_before_claim_skips_worker',
        'tests/test_publishing.py::test_ambiguous_requires_review_no_auto_retry',
        'tests/test_publishing.py::test_recovery_after_submitting_requires_review',
        'tests/test_posts.py::test_edit_reschedule_version_and_cancel',
        'tests/test_canary.py::test_duplicate_delivery_safe_with_canary'
    )
    & uv run pytest @unitTests -v
    if ($LASTEXITCODE -ne 0) { throw "Unit reliability suite failed (exit $LASTEXITCODE)." }
    Write-Host "`nUnit reliability suite PASSED." -ForegroundColor Green

    if ($IncludeIntegration) {
        Write-Host "`n=== POSTGRESQL INTEGRATION TESTS ===" -ForegroundColor Cyan
        # These explicit overrides must point to a separate local, migrated test DB.
        $env:POSTGRES_HOST = '127.0.0.1'
        $env:POSTGRES_DB = 'postpilot_test'
        # Verify resolved settings, not just the raw .env file.
        & uv run --env-file ../../.env python -c 'from app.core.config import Settings; s=Settings(); assert s.postgres_host in ("127.0.0.1", "localhost") and s.postgres_db == "postpilot_test", "Refusing to test a non-local or non-test database"; print("Integration DB:", s.postgres_host, s.postgres_port, s.postgres_db)'
        if ($LASTEXITCODE -ne 0) { throw 'Test-database safety preflight failed.' }
        $integrationTests = @(
            'tests/integration/test_publishing_concurrency.py::test_two_workers_race_single_claim',
            'tests/integration/test_publishing_concurrency.py::test_duplicate_task_delivery_publishes_once',
            'tests/integration/test_multi_post_scheduling.py::test_cancel_one_leaves_siblings_scheduled',
            'tests/integration/test_multi_post_scheduling.py::test_genuine_retry_backoff_preserved',
            'tests/integration/test_multi_post_scheduling.py::test_three_posts_same_utc_instant_claimed_and_executed_once',
            'tests/integration/test_real_publishing_postgres.py::test_concurrent_workers_single_real_api_call'
        )
        & uv run --env-file ../../.env pytest -m integration @integrationTests -v
        if ($LASTEXITCODE -ne 0) { throw "Integration reliability suite failed (exit $LASTEXITCODE)." }
        Write-Host "`nIntegration reliability suite PASSED." -ForegroundColor Green
    }
} finally {
    Pop-Location
}
