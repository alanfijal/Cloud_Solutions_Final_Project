bucket = "REPLACE_WITH_APPROVED_BACKEND_BUCKET"
# Shared state key intentionally enforces one environment at a time.
key = "coldchain/application.tfstate"
region = "eu-north-1"
encrypt = true
use_lockfile = true
allowed_account_ids = ["028718095604"]
