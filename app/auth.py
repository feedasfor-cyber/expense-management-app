from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import Response, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import base64
import secrets

app = FastAPI()

# ======================================
# ✅ 共通の認証情報（本番では環境変数）
# ======================================
USERNAME = "admin"
PASSWORD = "secret123"

security = HTTPBasic()

# ======================================
# ✅ ミドルウェア — 全体にBasic認証を適用
# ======================================
@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Basic "):
        return Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="Access to the site"'},
        )

    encoded = auth.split(" ")[1]
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="Access to the site"'},
        )

    if username != USERNAME or password != PASSWORD:
        return Response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="Access to the site"'},
        )

    return await call_next(request)


# ======================================
# ✅ Depends用（個別エンドポイント用にも使える）
# ======================================
def basic_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ======================================
# ✅ 認証後リダイレクト用のトップページ
# ======================================
@app.get("/")
def root(request: Request, username: str = Depends(basic_auth)):
    redirect_url = request.query_params.get("redirect")
    if redirect_url:
        return RedirectResponse(url=redirect_url)
    return {"message": "認証OK"}


# ======================================
# ✅ 例：個別のAPIでもDependsを使える
# ======================================
@app.get("/secure", dependencies=[Depends(basic_auth)])
def secure_endpoint():
    return {"message": "You are authenticated!"}
