from factories import add_user, make_gstin, ok


def test_invalid_gstin_is_rejected(tenant):
    good = make_gstin("29")
    wrong_check = good[:-1] + ("0" if good[-1] != "0" else "1")
    response = tenant.post("/api/org/legal-entities", json={"name": "Bad GST Pvt", "gstin": wrong_check})
    assert response.status_code == 422
    assert "GSTIN" in response.json()["detail"]


def test_state_comes_from_the_gstin(tenant):
    entity = ok(tenant.post("/api/org/legal-entities", json={"name": "Maha Pvt", "gstin": make_gstin("27")}), 201)
    assert entity["state_code"] == "27"
    assert entity["state_name"] == "Maharashtra"


def test_two_branches_can_share_one_state_registration(tenant):
    entity = ok(tenant.post("/api/org/legal-entities", json={"name": "Maha Pvt", "gstin": make_gstin("27")}), 201)
    for code, city in (("MUM", "Mumbai"), ("PUN", "Pune")):
        ok(tenant.post("/api/org/branches", json={"code": code, "name": f"{city} Hub", "city": city, "legal_entity_id": entity["id"]}), 201)
    overview = ok(tenant.get("/api/org/overview"))
    assert {branch["gstin"] for branch in overview["branches"]} == {entity["gstin"]}
    assert len(overview["branches"]) == 2


def test_branch_csv_import_is_all_or_nothing(tenant):
    gstin = make_gstin("29")
    ok(tenant.post("/api/org/legal-entities", json={"name": "K Pvt", "gstin": gstin}), 201)
    bad = f"code,name,city,gstin\nB1,One,Bengaluru,{gstin}\nB2,Two,Mysuru,{make_gstin('29')}\n"
    response = tenant.post("/api/org/branches/import", files={"file": ("branches.csv", bad, "text/csv")})
    assert response.status_code == 422
    assert ok(tenant.get("/api/org/overview"))["branches"] == []

    good = f"code,name,city,gstin\nB1,One,Bengaluru,{gstin}\nB2,Two,Mysuru,{gstin}\n"
    assert ok(tenant.post("/api/org/branches/import", files={"file": ("branches.csv", good, "text/csv")}), 201)["imported"] == 2


def test_branch_scoped_user_sees_only_their_branch(tenant):
    entity = ok(tenant.post("/api/org/legal-entities", json={"name": "K Pvt", "gstin": make_gstin("29")}), 201)
    mine = ok(tenant.post("/api/org/branches", json={"code": "MINE", "name": "Mine", "city": "Mysuru", "legal_entity_id": entity["id"]}), 201)
    ok(tenant.post("/api/org/branches", json={"code": "OTHER", "name": "Other", "city": "Hubballi", "legal_entity_id": entity["id"]}), 201)
    requester = add_user(tenant, "requester", [mine["id"]])
    assert [branch["code"] for branch in ok(requester.get("/api/org/overview"))["branches"]] == ["MINE"]


def test_branch_scoped_role_must_have_a_branch(tenant):
    from conftest import PASSWORD, unique_email

    response = tenant.post(
        "/api/auth/users", json={"name": "No branch", "email": unique_email(), "password": PASSWORD, "role": "requester"}
    )
    assert response.status_code == 422


def test_organization_data_is_invisible_to_another_tenant(two_tenants):
    ok(two_tenants.a.post("/api/org/legal-entities", json={"name": "A Pvt", "gstin": make_gstin("29")}), 201)
    assert ok(two_tenants.b.get("/api/org/overview"))["legal_entities"] == []
