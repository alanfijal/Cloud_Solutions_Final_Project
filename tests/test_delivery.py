import hashlib
from unittest.mock import patch

import pytest

from scripts.aws_local import ACCOUNT, identity
from scripts.terraform_local import verify_saved_plan


def test_identity_rejects_wrong_account_and_root():
    for account, arn in [
        ("111111111111", "arn:aws:iam::111111111111:role/test"),
        (ACCOUNT, "arn:aws:iam::028718095604:root"),
    ]:
        with patch("scripts.aws_local.aws_json", return_value={"Account": account, "Arn": arn}):
            with pytest.raises(RuntimeError):
                identity()


def test_terraform_credentials_refresh_without_persisting_keys(tmp_path, monkeypatch):
    import os
    import shutil
    import sys
    from datetime import UTC, datetime, timedelta

    import boto3

    from scripts.aws_local import terraform_env

    source = tmp_path / "original config"
    source.write_text("# original browser-login profile\n")
    count = tmp_path / "refresh-count"
    fake_cli = tmp_path / "fake aws"
    fake_cli.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib\nfrom datetime import UTC, datetime, timedelta\n"
        f"assert os.environ['AWS_CONFIG_FILE'] == {str(source)!r}\n"
        f"p = pathlib.Path({str(count)!r})\n"
        "n = int(p.read_text()) + 1 if p.exists() else 1\np.write_text(str(n))\n"
        "print(json.dumps({'Version':1, 'AccessKeyId':'TESTKEY'+str(n), 'SecretAccessKey':'test', "
        "'SessionToken':'test', 'Expiration':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}))\n"
    )
    fake_cli.chmod(0o700)
    env_exe = shutil.which("env")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(source))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-be-removed")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-be-removed")
    config = tmp_path / "terraform config"
    with (
        patch("scripts.aws_local.identity"),
        patch("scripts.aws_local.shutil.which", side_effect=[env_exe, str(fake_cli)]),
    ):
        env = terraform_env(config)
    assert not any(key in env for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"))
    assert config.stat().st_mode & 0o777 == 0o600
    with patch.dict(os.environ, env, clear=True):
        credentials = boto3.Session().get_credentials()
        first = credentials.get_frozen_credentials().access_key
        credentials._expiry_time = datetime.now(UTC) - timedelta(seconds=1)
        second = credentials.get_frozen_credentials().access_key
    assert first != second
    assert "TESTKEY" not in config.read_text() and "SecretAccessKey" not in config.read_text()


def test_terraform_refuses_a_recursive_credential_profile(tmp_path, monkeypatch):
    from scripts.aws_local import terraform_env

    config = tmp_path / "config"
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    with patch("scripts.aws_local.identity"), pytest.raises(ValueError, match="must differ"):
        terraform_env(config)


def saved(tmp_path):
    path = tmp_path / "review.tfplan"
    path.write_bytes(b"reviewed-binary-plan")
    metadata = {
        "preview_only": False,
        "destroy": False,
        "commit": "revision",
        "clean_worktree": True,
        "source_sha256": "source",
        "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "created_at": 100,
    }
    return path, metadata


def test_exact_saved_plan_is_accepted(tmp_path):
    path, meta = saved(tmp_path)
    verify_saved_plan(meta, path, "revision", "source", ACCOUNT, False, 101, clean=True)


@pytest.mark.parametrize(
    "change",
    [
        {"preview_only": True},
        {"destroy": True},
        {"commit": "UNCOMMITTED"},
        {"source_sha256": "changed"},
        {"plan_sha256": "changed"},
        {"created_at": 0},
    ],
)
def test_unreviewed_or_stale_plan_is_refused(tmp_path, change):
    path, meta = saved(tmp_path)
    meta.update(change)
    now = 90000 if change == {"created_at": 0} else 101
    with pytest.raises(ValueError):
        verify_saved_plan(meta, path, "revision", "source", ACCOUNT, False, now, clean=True)


def test_changed_package_revision_or_account_refuses_apply(tmp_path):
    path, meta = saved(tmp_path)
    for revision, source, account in [
        ("new", "source", ACCOUNT),
        ("revision", "new", ACCOUNT),
        ("revision", "source", "111111111111"),
    ]:
        with pytest.raises(ValueError):
            verify_saved_plan(meta, path, revision, source, account, False, 101, clean=True)


def test_parameter_cleanup_refuses_untagged_resources():
    from unittest.mock import Mock

    from scripts import cleanup_parameters

    ssm = Mock()
    ssm.describe_parameters.return_value = {"Parameters": [{"Name": "/coldchain-dev/ack"}]}
    ssm.list_tags_for_resource.return_value = {"TagList": []}
    with patch.object(cleanup_parameters, "session") as session:
        session.return_value.client.return_value = ssm
        with patch(
            "sys.argv", ["cleanup", "--environment", "dev", "--confirm-account", ACCOUNT, "--confirm-data-loss"]
        ):
            with pytest.raises(RuntimeError, match="ownership"):
                cleanup_parameters.main()
    ssm.delete_parameters.assert_not_called()


def test_preview_strips_backend_from_separate_file(tmp_path):
    from scripts.terraform_local import prepare_preview

    source, target = tmp_path / "source", tmp_path / "preview"
    source.mkdir()
    target.mkdir()
    main = 'module "platform" { source = "../../modules/platform" }\n'
    (source / "main.tf").write_text(main)
    (source / "backend.tf").write_text('terraform {\n  backend "s3" {}\n}\n')
    (source / "terraform.tfstate").write_text("must never be copied")
    (source / ".terraform.lock.hcl").write_text("# pinned provider\n")
    prepare_preview(source, target)
    assert (target / "main.tf").read_text() == main
    assert 'backend "s3"' not in (target / "backend.tf").read_text()
    assert not (target / "terraform.tfstate").exists()
    assert (target / ".terraform.lock.hcl").read_text() == "# pinned provider\n"


@pytest.mark.parametrize("planned_clean,current_clean", [(False, True), (True, False)])
def test_dirty_source_before_or_after_plan_refuses_apply(tmp_path, planned_clean, current_clean):
    path, meta = saved(tmp_path)
    meta["clean_worktree"] = planned_clean
    with pytest.raises(ValueError, match="Commit source changes"):
        verify_saved_plan(meta, path, "revision", "source", ACCOUNT, False, 101, clean=current_clean)


def test_live_rehearsal_retries_network_failure_without_changing_request_id():
    from unittest.mock import Mock
    from urllib.error import URLError

    from scripts.smoke_mvp import API

    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.read.return_value = b'{"status":"running"}'
    api = API("https://dazwahczj9j0k.cloudfront.net", "local-test-only")
    body = {"request_id": "same-id"}
    with (
        patch("scripts.smoke_mvp.urlopen", side_effect=[URLError("dns"), result]) as send,
        patch("scripts.smoke_mvp.time.sleep"),
    ):
        assert api.call("sessions/start", body)["status"] == "running"
    assert send.call_args_list[0].args[0].data == send.call_args_list[1].args[0].data


def test_live_rehearsal_stops_retrying_after_three_network_failures():
    from urllib.error import URLError

    from scripts.smoke_mvp import API

    api = API("https://dazwahczj9j0k.cloudfront.net", "local-test-only")
    with patch("scripts.smoke_mvp.urlopen", side_effect=URLError("dns")) as send, patch("scripts.smoke_mvp.time.sleep"):
        with pytest.raises(RuntimeError, match="Local network"):
            api.call("state")
    assert send.call_count == 3


def test_gateway_export_contains_only_one_key_and_refuses_overwrite(tmp_path, monkeypatch):
    import json

    from scripts import export_device

    monkeypatch.chdir(tmp_path)
    folder = tmp_path / ".local"
    folder.mkdir()
    source, target = folder / "source.json", folder / "one.json"
    source.write_text(json.dumps({"unit-1": "first-test-key", "unit-2": "second-test-key"}))
    monkeypatch.setattr("sys.argv", ["export", "--unit", "unit-1", "--source", str(source), "--output", str(target)])
    export_device.main()
    assert json.loads(target.read_text()) == {"unit-1": "first-test-key"}
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        export_device.main()


def test_gateway_export_refuses_a_tracked_location(tmp_path, monkeypatch):
    from scripts import export_device

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["export", "--unit", "unit-1", "--output", str(tmp_path / "leak.json")])
    with pytest.raises(SystemExit):
        export_device.main()
    assert not (tmp_path / "leak.json").exists()
