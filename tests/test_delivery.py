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


def saved(tmp_path):
    path = tmp_path / "review.tfplan"
    path.write_bytes(b"reviewed-binary-plan")
    metadata = {
        "preview_only": False,
        "destroy": False,
        "commit": "revision",
        "source_sha256": "source",
        "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "created_at": 100,
    }
    return path, metadata


def test_exact_saved_plan_is_accepted(tmp_path):
    path, meta = saved(tmp_path)
    verify_saved_plan(meta, path, "revision", "source", ACCOUNT, False, 101)


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
        verify_saved_plan(meta, path, "revision", "source", ACCOUNT, False, now)


def test_changed_package_revision_or_account_refuses_apply(tmp_path):
    path, meta = saved(tmp_path)
    for revision, source, account in [
        ("new", "source", ACCOUNT),
        ("revision", "new", ACCOUNT),
        ("revision", "source", "111111111111"),
    ]:
        with pytest.raises(ValueError):
            verify_saved_plan(meta, path, revision, source, account, False, 101)


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
