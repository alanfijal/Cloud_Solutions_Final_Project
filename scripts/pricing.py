"""Read current Stockholm public on-demand prices; retain a dated evidence file."""

import json
from datetime import datetime, timezone
from pathlib import Path

from aws_local import aws_json, identity

SERVICES = [
    "AWSLambda",
    "AmazonApiGateway",
    "AWSEvents",
    "AWSQueueService",
    "AmazonDynamoDB",
    "AmazonStates",
    "AWSXRay",
    "AWSSystemsManager",
    "AmazonS3",
    "AmazonSNS",
    "AmazonCloudWatch",
    "AmazonAthena",
    "AWSGlue",
    "awskms",
]


def main():
    identity()
    output = {"checked_at": datetime.now(timezone.utc).isoformat(), "location": "EU (Stockholm)", "services": {}}
    for service in SERVICES:
        result = aws_json(
            "pricing",
            "get-products",
            "--service-code",
            service,
            "--filters",
            "Type=TERM_MATCH,Field=location,Value=EU (Stockholm)",
            region="us-east-1",
        )
        rows = []
        for raw in result.get("PriceList", []):
            product = json.loads(raw)
            attributes = product["product"]["attributes"]
            for term in product["terms"].get("OnDemand", {}).values():
                for dimension in term["priceDimensions"].values():
                    rows.append(
                        {
                            "sku": product["product"]["sku"],
                            "usage": attributes.get("usagetype"),
                            "operation": attributes.get("operation"),
                            "family": product["product"].get("productFamily"),
                            "description": dimension["description"],
                            "unit": dimension["unit"],
                            "usd": dimension["pricePerUnit"].get("USD"),
                            "begin": dimension["beginRange"],
                            "end": dimension["endRange"],
                            "effective": term["effectiveDate"],
                        }
                    )
        output["services"][service] = rows
        print(service, len(rows), "price dimensions")
    path = Path(".local/pricing-stockholm.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(output, indent=2))
    path.chmod(0o600)


if __name__ == "__main__":
    main()
