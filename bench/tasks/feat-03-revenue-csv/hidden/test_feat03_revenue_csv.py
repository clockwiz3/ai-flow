from fastapi.testclient import TestClient

# Periods are chosen so that they contain no cancelled reservations.


def _csv(client: TestClient, start: str, end: str):
    return client.get("/reports/revenue.csv", params={"start": start, "end": end})


def _lines(text: str) -> list[str]:
    return text.splitlines()


def test_csv_export_matches_seed(client: TestClient) -> None:
    response = _csv(client, "2025-05-01", "2025-05-20")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert _lines(response.text) == [
        "category,reservations,revenue",
        "camping,1,102.00",
        "tools,1,36.00",
        "TOTAL,2,138.00",
    ]


def test_csv_with_new_reservations(client: TestClient, reserve) -> None:
    reserve(3, 1, "2025-06-02", "2025-06-04")  # tools, 2 x 25.00
    reserve(7, 4, "2025-06-03", "2025-06-05")  # camping, 2 x 8.00
    response = _csv(client, "2025-06-01", "2025-06-05")
    assert response.status_code == 200
    assert _lines(response.text) == [
        "category,reservations,revenue",
        "camping,1,16.00",
        "tools,2,104.00",
        "TOTAL,3,120.00",
    ]


def test_csv_matches_json_report(client: TestClient, reserve) -> None:
    reserve(9, 1, "2025-06-02", "2025-06-04")
    for start, end in [("2025-05-01", "2025-05-20"), ("2025-06-01", "2025-06-05")]:
        report = client.get("/reports/revenue", params={"start": start, "end": end}).json()
        lines = _lines(_csv(client, start, end).text)
        expected = [f"{r['category']},{r['reservations']},{r['revenue']}" for r in report["rows"]]
        assert lines[1:-1] == expected
        count = sum(r["reservations"] for r in report["rows"])
        assert lines[-1] == f"TOTAL,{count},{report['total']}"


def test_csv_empty_period(client: TestClient) -> None:
    response = _csv(client, "2025-01-01", "2025-02-01")
    assert response.status_code == 200
    assert _lines(response.text) == ["category,reservations,revenue", "TOTAL,0,0.00"]


def test_csv_invalid_range(client: TestClient) -> None:
    response = _csv(client, "2025-06-01", "2025-06-01")
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert client.get("/reports/revenue.csv", params={"start": "2025-06-01"}).status_code == 422
    bad = client.get("/reports/revenue.csv", params={"start": "x", "end": "2025-06-01"})
    assert bad.status_code == 422


def test_json_report_unchanged(client: TestClient) -> None:
    params = {"start": "2025-05-01", "end": "2025-05-20"}
    body = client.get("/reports/revenue", params=params).json()
    assert body["total"] == "138.00"
    assert [r["category"] for r in body["rows"]] == ["camping", "tools"]
