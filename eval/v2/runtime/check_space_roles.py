"""Real API checks for personal/team roles; synthetic accounts only, no LLM."""
import json, secrets, uuid, time
from pathlib import Path
import httpx

report = {"synthetic_accounts_only": True, "llm_calls": 0, "checks": []}
client = httpx.Client(base_url="http://127.0.0.1:18000/api/v1", timeout=700)

def call(method, path, token, expected=200, **kw):
    r=client.request(method, path, headers={"Authorization":"Bearer "+token}, **kw)
    assert r.status_code == expected, f"{method} {path}: HTTP {r.status_code}, expected {expected}"
    return r.json() if r.content else None

def check(name):
    report["checks"].append(name)
    print("PASS "+name, flush=True)
    Path("eval/v2/runtime/space-roles-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

try:
    accounts=[]
    for i in range(4):
        email="v2-roles-"+uuid.uuid4().hex+"@example.test"
        r=client.post("/auth/register",json={"email":email,"password":secrets.token_urlsafe(24),"display_name":"Synthetic role "+str(i)})
        assert r.status_code==201
        a=r.json();accounts.append((a["tokens"]["access_token"],a["user"]["id"],email))
    owner=accounts[0][0]
    personal=call("POST","/spaces",owner,201,json={"name":"V2-personal-role-check","kind":"PERSONAL"})
    team=call("POST","/spaces",owner,201,json={"name":"V2-team-role-check","kind":"TEAM","visibility":"PUBLIC"})
    assert personal["kind"]=="PERSONAL" and team["kind"]=="TEAM"
    check("explicit_personal_and_team_creation")
    for role in ("ADMIN","EDITOR","MEMBER"):
        call("POST",f"/spaces/{personal['id']}/members",owner,403,json={"email":accounts[1][2],"role":role})
    check("personal_has_only_owner_even_for_admin_invitation")
    sid=team["id"]
    report["space_id"]=sid
    for a in accounts[1:3]:
        call("POST",f"/spaces/{sid}/members",owner,201,json={"email":a[2],"role":"ADMIN"})
    call("POST",f"/spaces/{sid}/members",owner,201,json={"email":accounts[3][2],"role":"MEMBER"})
    roles=call("GET",f"/spaces/{sid}/members",owner)
    assert sum(m["role"]=="OWNER" for m in roles)==1 and sum(m["role"]=="ADMIN" for m in roles)==2
    check("one_owner_multiple_administrators")
    for a in accounts[1:3]:
        category=call("POST",f"/spaces/{sid}/categories",a[0],201,json={"name":"admin-"+a[1][:8]})
        case=call("POST",f"/spaces/{sid}/eval-cases",a[0],201,json={"question":"管理员验收题","expected_answer":"仅合成资料"})
        call("DELETE",f"/eval-cases/{case['id']}",a[0],204)
        run=call("POST",f"/owner/spaces/{sid}/retrieval-runs",a[0],201,json={"question":"空空间权限检查","top_k":4})
        call("GET",f"/owner/retrieval-runs/{run['run_id']}",a[0])
        call("GET",f"/owner/retrieval-runs/{run['run_id']}",accounts[3][0],404)
    check("both_admins_manage_categories_evaluation_and_retrieval")
    uploaded=call("POST",f"/spaces/{sid}/documents",accounts[1][0],202,
                  files={"file":("admin-source.txt","合成资料：管理员可核对这份原文。".encode(),"text/plain")}, data={"category_id":category["id"]})
    did=uploaded["document"]["id"]
    for attempt in range(120):
        doc=call("GET",f"/documents/{did}",owner)
        if doc["status"]=="READY":break
        assert doc["status"]!="FAILED"
        time.sleep(2)
    else:raise TimeoutError("Synthetic administrator upload not ready")
    for a in accounts[1:3]:
        detail=call("GET",f"/owner/spaces/{sid}/documents/{did}",a[0])
        assert detail["chunks"] and "合成资料" in detail["chunks"][0]["content"]
    call("GET",f"/owner/spaces/{sid}/documents/{did}",accounts[3][0],404)
    check("both_admins_can_read_current_source_member_cannot")
    call("POST",f"/owner/spaces/{sid}/retrieval-runs",accounts[3][0],404,json={"question":"禁止调试"})
    call("POST",f"/spaces/{sid}/eval-cases",accounts[3][0],403,json={"question":"禁止写评测"})
    check("member_cannot_debug_or_write_evaluations")
    call("POST",f"/spaces/{sid}/members",owner,403,json={"email":accounts[1][2],"role":"OWNER"})
    call("PATCH",f"/spaces/{sid}/members/{accounts[1][1]}",accounts[1][0],403,json={"role":"OWNER"})
    call("DELETE",f"/spaces/{sid}",accounts[1][0],403)
    check("administrator_cannot_grant_ownership_or_delete_space")
    call("PATCH",f"/spaces/{sid}/members/{accounts[1][1]}",owner,json={"role":"MEMBER"})
    call("POST",f"/owner/spaces/{sid}/retrieval-runs",accounts[1][0],404,json={"question":"降级后调试"})
    call("POST",f"/spaces/{sid}/eval-cases",accounts[1][0],403,json={"question":"降级后写入"})
    call("POST",f"/owner/spaces/{personal['id']}/retrieval-runs",accounts[2][0],404,json={"question":"跨空间调试"})
    check("demotion_and_cross_space_access_rejected_immediately")
    report["status"]="PASSED"
except Exception:
    report["status"]="FAILED"
    raise
finally:
    Path("eval/v2/runtime/space-roles-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    client.close()
