"""GitHub code report, repo helpers, and create_repo with mocked HTTP."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.providers import github_infra
from app.providers.github_infra import GitHubCredentials, _CODE_MATCHERS


def _client() -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


@pytest.mark.unit
def test_path_matches_and_lang_for():
    tf = _CODE_MATCHERS["terraform"]
    assert github_infra._path_matches("infra/main.tf", tf)
    assert not github_infra._path_matches("readme.md", tf)
    wf = _CODE_MATCHERS["workflows"]
    assert github_infra._path_matches(".github/workflows/ci.yml", wf)
    assert not github_infra._path_matches("docs/ci.yml", wf)
    assert github_infra._lang_for("main.tf", "hcl") == "hcl"
    assert github_infra._lang_for("app.py", "") in {"python", ""}
    assert github_infra._filter_repos(
        [{"full_name": "a/b"}, {"full_name": "c/d"}], {"a/b"}
    ) == [{"full_name": "a/b"}]
    assert github_infra._format_rows([], 1) == "(none found)"


@pytest.mark.unit
def test_build_code_report_fetches_matching_files():
    creds = GitHubCredentials(token="gho_x", username="octo")
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    repos = [{"full_name": "octo/app", "archived": False, "default_branch": "main", "language": "Python"}]
    client = _client()
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._allowed_repos", return_value=None):
            with patch("app.providers.github_infra._client", return_value=client):
                with patch("app.providers.github_infra._get", return_value=who):
                    with patch("app.providers.github_infra._list_repos", return_value=repos):
                        with patch("app.providers.github_infra._list_branches", return_value=["main"]):
                            with patch("app.providers.github_infra._resolve_branch", return_value="main"):
                                with patch(
                                    "app.providers.github_infra._get_tree",
                                    return_value=[
                                        {"type": "blob", "path": "infra/main.tf"},
                                        {"type": "tree", "path": "infra"},
                                    ],
                                ):
                                    with patch(
                                        "app.providers.github_infra._get_raw_file",
                                        return_value='resource "null_resource" "x" {}',
                                    ):
                                        report = github_infra.build_code_report(
                                            "p1", ["terraform"]
                                        )
    assert report is not None
    assert "main.tf" in report["text"]
    assert report["meta"]["files"] == 1


@pytest.mark.unit
def test_build_code_report_unknown_kind_and_empty_tree():
    assert github_infra.build_code_report("p1", ["not-a-kind"]) is None
    creds = GitHubCredentials(token="gho_x")
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    client = _client()
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._allowed_repos", return_value=None):
            with patch("app.providers.github_infra._client", return_value=client):
                with patch("app.providers.github_infra._get", return_value=who):
                    with patch(
                        "app.providers.github_infra._list_repos",
                        return_value=[{"full_name": "octo/app", "archived": False}],
                    ):
                        with patch("app.providers.github_infra._list_branches", return_value=["main"]):
                            with patch("app.providers.github_infra._resolve_branch", return_value="main"):
                                with patch("app.providers.github_infra._get_tree", return_value=[]):
                                    report = github_infra.build_code_report("p1", ["terraform"])
    assert report["meta"]["files"] == 0
    assert "No matching files" in report["text"]


@pytest.mark.unit
def test_create_repo_validates_name_and_posts():
    with pytest.raises(ValueError, match="Invalid repository name"):
        github_infra.create_repo("p1", name="bad/name")
    creds = GitHubCredentials(token="gho_x", org="acme")
    client = _client()
    created = MagicMock(status_code=201)
    created.json.return_value = {
        "full_name": "acme/demo",
        "html_url": "https://github.com/acme/demo",
        "private": True,
        "default_branch": "main",
        "clone_url": "https://github.com/acme/demo.git",
    }
    client.post.return_value = created
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            result = github_infra.create_repo("p1", name="demo", description="test")
    assert result["full_name"] == "acme/demo"
    failed = MagicMock(status_code=422, text="exists")
    failed.json.return_value = {"message": "already exists"}
    client.post.return_value = failed
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with pytest.raises(github_infra.GitHubApiError, match="Could not create"):
                github_infra.create_repo("p1", name="demo")


@pytest.mark.unit
def test_list_repo_names_and_error_detail():
    creds = GitHubCredentials(token="gho_x")
    client = _client()
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with patch("app.providers.github_infra._get", return_value=who):
                with patch(
                    "app.providers.github_infra._list_repos",
                    return_value=[{"full_name": "octo/b"}, {"full_name": "octo/a"}],
                ):
                    names = github_infra.list_repo_names("p1")
    assert names == ["octo/a", "octo/b"]
    denied = MagicMock(status_code=403, text="nope")
    denied.json.return_value = {"message": "Bad credentials"}
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with patch("app.providers.github_infra._get", return_value=denied):
                with pytest.raises(github_infra.GitHubApiError, match="rejected"):
                    github_infra.list_repo_names("p1")
    resp = MagicMock(text="plain")
    resp.json.side_effect = ValueError("bad")
    assert github_infra._error_detail(resp) == "plain"
