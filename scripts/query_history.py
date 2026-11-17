"""One bounded Athena history query after deployment approval; no polling loop runs forever."""

import argparse
import json
import time
import uuid
from pathlib import Path

from aws_local import CONFIG, session


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--environment", choices=["dev", "demo"], default="dev")
    args = p.parse_args()
    query = (Path(__file__).resolve().parents[1] / "analytics/sql/history.sql").read_text()
    query = query.replace("coldchain_dev.events", f"coldchain_{args.environment}.events")
    athena = session().client("athena", config=CONFIG)
    qid = athena.start_query_execution(
        QueryString=query, WorkGroup="coldchain-" + args.environment, ClientRequestToken=uuid.uuid4().hex
    )["QueryExecutionId"]
    for _ in range(20):
        result = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        status = result["Status"]["State"]
        if status == "SUCCEEDED":
            print(json.dumps({"query_execution_id": qid, "bytes_scanned": result["Statistics"]["DataScannedInBytes"]}))
            print(json.dumps(athena.get_query_results(QueryExecutionId=qid, MaxResults=201)["ResultSet"]["Rows"]))
            return
        if status in ("CANCELLED", "FAILED"):
            raise RuntimeError("Query " + status + ": " + qid)
        time.sleep(1)
    athena.stop_query_execution(QueryExecutionId=qid)
    raise RuntimeError("Query exceeded local 20-poll wait; cancellation requested: " + qid)


if __name__ == "__main__":
    main()
