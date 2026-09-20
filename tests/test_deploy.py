import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_vercel_serves_the_finished_daily_page_instead_of_running_the_app():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["framework"] is None
    assert config["outputDirectory"] == "public"
    assert "https://dhrupo.github.io/denguelinkbd/" in config["buildCommand"] and "public/index.html" in config["buildCommand"]


def test_vercel_never_publishes_a_page_that_has_no_forecast():
    assert """grep -q 'id="data"' public/index.html""" in json.loads((ROOT / "vercel.json").read_text())["buildCommand"]


def test_the_daily_job_tells_vercel_only_when_a_hook_has_been_set():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    assert "VERCEL_DEPLOY_HOOK: ${{ secrets.VERCEL_DEPLOY_HOOK }}" in workflow
    assert "if: env.VERCEL_DEPLOY_HOOK != ''" in workflow
    assert workflow.index("actions/deploy-pages") < workflow.index("VERCEL_DEPLOY_HOOK != ''")


def test_a_build_with_a_missing_source_is_tried_again_and_the_best_attempt_is_kept():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    step = workflow[workflow.index("- name: Build today's page"):workflow.index("- uses: actions/configure-pages")]
    assert "for attempt in 1 2 3" in step and "sleep 120" in step
    assert "grep -c '^FAILED' attempt.log" in step
    assert "cp out/map.html best.html" in step and "cp best.html site/index.html" in step
    assert "test -f best.html" in step
