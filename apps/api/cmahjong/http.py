"""登录、对局、存档。浏览器只提交动作，规则全在服务端。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from cmahjong.ai.heuristic import VERSION
from cmahjong.db import Game, GameEvent, Save, SessionLocal, SessionRow, User, health_db, init_db
from cmahjong.orchestrate import drive
from cmahjong.rules.engine import RuleError, State, new_match, reduce
from cmahjong.rules.tiles import INITIAL_POINTS
from cmahjong.rules.view import to_player_view

COOKIE = "cmahjong_session"
HEADER = "x-requested-with"
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
DUMMY = ph.hash("dummy-password")
ALLOW_REGISTER = os.environ.get("ALLOW_REGISTER", "true").lower() == "true"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="四川麻将训练", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in os.environ.get("WEB_ORIGIN", "http://localhost:5173").split(",") if item.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SQLAlchemyError)
async def database_error(_request: Request, _exc: SQLAlchemyError):
    return _error(503, "db_error", "数据库没有连上。请在服务器执行 docker compose -f deploy/docker-compose.yml logs api")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None, None
    db = SessionLocal()
    row = db.query(SessionRow).filter(SessionRow.token_hash == _token_hash(token)).one_or_none()
    if row is None:
        db.close()
        return None, None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now():
        db.close()
        return None, None
    user = db.get(User, row.user_id)
    return db, user


def _require(request: Request):
    db, user = _user(request)
    if user is None:
        if db:
            db.close()
        return None, None, _error(401, "unauthorized", "请先登录")
    return db, user, None


def _csrf(request: Request) -> JSONResponse | None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.headers.get(HEADER) != "cmahjong":
        return _error(403, "csrf", "缺少请求头")
    return None


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/", max_age=30 * 24 * 3600)


def _public_event(event: dict, viewer: int = 0) -> dict:
    kind = event["type"]
    payload = dict(event.get("payload") or {})
    if kind == "deal":
        payload = {"dealer": payload.get("dealer"), "hand_counts": [len(h) for h in payload.get("hands", [])]}
    elif kind == "draw" and payload.get("seat") != viewer:
        payload.pop("tile", None)
    elif kind == "exchange_submit" and payload.get("seat") != viewer:
        payload = {"seat": payload.get("seat")}
    elif kind == "dingque_submit" and payload.get("seat") != viewer:
        payload = {"seat": payload.get("seat")}
    return {"type": kind, "actor": event.get("actor"), "payload": payload, "delay_ms": 380}


def _append_events(db, game: Game, events: list[dict]) -> list[dict]:
    public = []
    for event in events:
        game.event_seq += 1
        shown = _public_event(event)
        db.add(
            GameEvent(
                game_id=game.id,
                seq=game.event_seq,
                hand_index=int(json.loads(game.state_json).get("hand_index", 0)),
                event_type=event["type"],
                payload_json=json.dumps(event, ensure_ascii=False),
                public_json=json.dumps(shown, ensure_ascii=False),
            )
        )
        public.append(shown)
    return public


def _store_state(game: Game, state: State) -> None:
    game.state_json = json.dumps(state.to_dict(), ensure_ascii=False)
    game.phase = state.phase
    game.hand_index = state.hand_index
    game.scores_json = json.dumps(state.scores_game)
    game.status = "completed" if state.phase == "completed" else "active"
    game.ruleset_version = state.ruleset_version
    game.updated_at = _now()


def _load_state(game: Game) -> State:
    return State.from_dict(json.loads(game.state_json))


def _view(game: Game, state: State) -> dict:
    return to_player_view(state, 0, game.id, game.event_seq)


@app.get("/healthz")
def healthz():
    if not health_db():
        return JSONResponse(status_code=503, content={"db": "down"})
    return {"db": "ok"}


@app.post("/api/auth/register")
async def register(request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    if not ALLOW_REGISTER:
        return _error(403, "register_closed", "注册已关闭")
    body = await request.json()
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    if not username or len(username) < 3 or len(username) > 32 or not username.replace("_", "").replace("-", "").isalnum():
        return _error(422, "invalid", "用户名用 3–32 位字母、数字、下划线或短横线")
    if len(password) < 8 or len(password) > 128:
        return _error(422, "invalid", "密码至少 8 位")
    db = SessionLocal()
    if db.query(User).filter(User.username == username.lower()).one_or_none():
        db.close()
        return _error(409, "taken", "这个用户名已经有人用了")
    user = User(id=secrets.token_hex(16), username=username.lower(), password_hash=ph.hash(password), created_at=_now())
    db.add(user)
    token = secrets.token_urlsafe(32)
    db.add(SessionRow(id=secrets.token_hex(16), user_id=user.id, token_hash=_token_hash(token), created_at=_now(), expires_at=_now() + timedelta(days=30)))
    db.commit()
    response = JSONResponse(status_code=201, content={"id": user.id, "username": user.username})
    _set_cookie(response, token)
    db.close()
    return response


@app.post("/api/auth/login")
async def login(request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    body = await request.json()
    username = str(body.get("username") or "").lower()
    password = str(body.get("password") or "")
    db = SessionLocal()
    user = db.query(User).filter(User.username == username).one_or_none()
    try:
        ph.verify(user.password_hash if user else DUMMY, password)
        ok = user is not None
    except VerifyMismatchError:
        ok = False
    if not ok or user is None:
        db.close()
        return _error(401, "unauthorized", "用户名或密码不对")
    db.query(SessionRow).filter(SessionRow.user_id == user.id).delete()
    token = secrets.token_urlsafe(32)
    db.add(SessionRow(id=secrets.token_hex(16), user_id=user.id, token_hash=_token_hash(token), created_at=_now(), expires_at=_now() + timedelta(days=30)))
    db.commit()
    response = JSONResponse({"id": user.id, "username": user.username})
    _set_cookie(response, token)
    db.close()
    return response


@app.post("/api/auth/logout")
def logout(request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    db, user, err = _require(request)
    if err:
        return err
    token = request.cookies.get(COOKIE, "")
    db.query(SessionRow).filter(SessionRow.token_hash == _token_hash(token)).delete()
    db.commit()
    db.close()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


@app.get("/api/me")
def me(request: Request):
    db, user, err = _require(request)
    if err:
        return err
    payload = {"id": user.id, "username": user.username, "created_at": user.created_at.isoformat()}
    db.close()
    return payload


@app.post("/api/games")
async def create_game(request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    db, user, err = _require(request)
    if err:
        return err
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
    try:
        base = int(body.get("base_score") or 1)
    except (TypeError, ValueError):
        db.close()
        return _error(422, "invalid", "底分要在 1 到 10000 之间")
    if not 1 <= base <= 10000:
        db.close()
        return _error(422, "invalid", "底分要在 1 到 10000 之间")
    rules = {
        "base_score": base,
        "fan_cap": 5,
        "enable_exchange": bool(body.get("enable_exchange", True)),
        "enable_jingoudiao": bool(body.get("enable_jingoudiao", False)),
        "show_ting_hint": False,
    }
    seed = secrets.token_bytes(32)
    state, events = new_match(rules, seed)
    state, more = drive(state)
    events.extend(more)
    game = Game(
        id=secrets.token_hex(16),
        user_id=user.id,
        name=(str(body.get("name"))[:40] if body.get("name") else None),
        ruleset_version="chengdu-xz-1",
        rules_json=json.dumps(rules, ensure_ascii=False),
        status="active",
        phase=state.phase,
        hand_index=0,
        seed=seed,
        state_json="{}",
        scores_json=json.dumps([INITIAL_POINTS] * 4),
        event_seq=0,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(game)
    db.flush()
    _store_state(game, state)
    public = _append_events(db, game, events)
    db.commit()
    view = _view(game, state)
    view["policy_version"] = VERSION
    db.close()
    return JSONResponse(status_code=201, content={"view": view, "public_events": public})


@app.get("/api/games")
def list_games(request: Request):
    db, user, err = _require(request)
    if err:
        return err
    rows = db.query(Game).filter(Game.user_id == user.id).order_by(Game.updated_at.desc()).limit(50).all()
    payload = [
        {
            "id": row.id,
            "name": row.name,
            "phase": row.phase,
            "status": row.status,
            "hand_index": row.hand_index,
            "ruleset_version": row.ruleset_version,
            "scores_game": json.loads(row.scores_json),
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]
    db.close()
    return payload


@app.get("/api/games/{game_id}")
def get_game(game_id: str, request: Request):
    db, user, err = _require(request)
    if err:
        return err
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).one_or_none()
    if game is None:
        db.close()
        return _error(404, "not_found", "没有这局")
    view = _view(game, _load_state(game))
    db.close()
    return view


@app.post("/api/games/{game_id}/actions")
async def act(game_id: str, request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    db, user, err = _require(request)
    if err:
        return err
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).one_or_none()
    if game is None:
        db.close()
        return _error(404, "not_found", "没有这局")
    body = await request.json()
    if int(body.get("expected_seq", -1)) != game.event_seq:
        db.close()
        return _error(409, "seq_conflict", "这手已经变了，请刷新后再走")
    action = body.get("action") or {}
    state = _load_state(game)
    try:
        if action.get("type") == "continue":
            state, events = drive(state)
        else:
            state, events = reduce(state, 0, action)
            state, more = drive(state)
            events.extend(more)
    except RuleError as exc:
        db.close()
        return _error(422, exc.code, exc.message, clause_id=exc.clause_id, legal_actions=to_player_view(state, 0)["legal_actions"])
    _store_state(game, state)
    public = _append_events(db, game, events)
    db.commit()
    view = _view(game, state)
    db.close()
    return {"view": view, "public_events": public}


@app.post("/api/games/{game_id}/save")
async def save_game(game_id: str, request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    db, user, err = _require(request)
    if err:
        return err
    game = db.query(Game).filter(Game.id == game_id, Game.user_id == user.id).one_or_none()
    if game is None:
        db.close()
        return _error(404, "not_found", "没有这局")
    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 40:
        db.close()
        return _error(422, "invalid", "存档名用 1–40 个字")
    events = (
        db.query(GameEvent)
        .filter(GameEvent.game_id == game.id, GameEvent.seq <= game.event_seq)
        .order_by(GameEvent.seq)
        .all()
    )
    row = Save(
        id=secrets.token_hex(16),
        user_id=user.id,
        source_game_id=game.id,
        name=name,
        phase=game.phase,
        hand_index=game.hand_index,
        seq=game.event_seq,
        seed=game.seed,
        state_json=game.state_json,
        events_json=json.dumps([{"seq": e.seq, "type": e.event_type, "payload": json.loads(e.payload_json)} for e in events], ensure_ascii=False),
        scores_json=game.scores_json,
        rules_json=game.rules_json,
        ruleset_version=game.ruleset_version,
        created_at=_now(),
    )
    game.name = name
    db.add(row)
    db.commit()
    payload = {"save_id": row.id, "name": name, "phase": game.phase, "seq": game.event_seq, "created_at": row.created_at.isoformat()}
    db.close()
    return payload


@app.get("/api/saves")
def list_saves(request: Request):
    db, user, err = _require(request)
    if err:
        return err
    rows = db.query(Save).filter(Save.user_id == user.id).order_by(Save.created_at.desc()).limit(50).all()
    payload = [
        {
            "id": row.id,
            "name": row.name,
            "source_game_id": row.source_game_id,
            "phase": row.phase,
            "ruleset_version": row.ruleset_version,
            "scores_game": json.loads(row.scores_json),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    db.close()
    return payload


@app.post("/api/saves/{save_id}/load")
def load_save(save_id: str, request: Request):
    blocked = _csrf(request)
    if blocked:
        return blocked
    db, user, err = _require(request)
    if err:
        return err
    row = db.query(Save).filter(Save.id == save_id, Save.user_id == user.id).one_or_none()
    if row is None:
        db.close()
        return _error(404, "not_found", "没有这个存档")
    state = State.from_dict(json.loads(row.state_json))
    game = Game(
        id=secrets.token_hex(16),
        user_id=user.id,
        name=row.name,
        ruleset_version=row.ruleset_version,
        rules_json=row.rules_json,
        status="completed" if state.phase == "completed" else "active",
        phase=state.phase,
        hand_index=state.hand_index,
        seed=row.seed,
        state_json=row.state_json,
        scores_json=row.scores_json,
        event_seq=0,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(game)
    db.flush()
    for event in json.loads(row.events_json):
        game.event_seq += 1
        shown = _public_event({"type": event["type"], "payload": event["payload"].get("payload", event["payload"])})
        db.add(
            GameEvent(
                game_id=game.id,
                seq=game.event_seq,
                hand_index=state.hand_index,
                event_type=event["type"],
                payload_json=json.dumps(event["payload"], ensure_ascii=False),
                public_json=json.dumps(shown, ensure_ascii=False),
            )
        )
    db.commit()
    view = _view(game, state)
    db.close()
    return JSONResponse(status_code=201, content={"game_id": game.id, "view": view})


@app.get("/api/clauses")
def clauses():
    from cmahjong.rules.clauses import CLAUSES

    return CLAUSES
