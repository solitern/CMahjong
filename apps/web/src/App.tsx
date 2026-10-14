import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { Action, DIR, SEAT, SUIT_NAME, View, api, total } from "./api";
import { Tile, tileParts } from "./tiles";

type User = { id: string; username: string };

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setReady(true));
  }, []);
  if (!ready) return <p className="page">正在打开牌桌…</p>;
  return (
    <div className="app">
      <header className="top">
        <b>四川麻将训练</b>
        <span className="badge">成都血战 · 每人 100 分</span>
        <nav>
          <Link to="/">大厅</Link>
          <Link to="/rules">规则</Link>
          {user && <button onClick={() => api.logout().then(() => setUser(null))}>退出 {user.username}</button>}
        </nav>
      </header>
      <Routes>
        <Route path="/rules" element={<Rules />} />
        <Route path="/game/:id" element={user ? <Table /> : <Auth onUser={setUser} />} />
        <Route path="*" element={user ? <Lobby user={user} /> : <Auth onUser={setUser} />} />
      </Routes>
    </div>
  );
}

function Auth({ onUser }: { onUser: (user: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const user = mode === "login" ? await api.login(username, password) : await api.register(username, password);
      onUser(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "失败");
    }
  }
  return (
    <main className="page">
      <form className="card" onSubmit={submit} style={{ maxWidth: 420 }}>
        <h1>{mode === "login" ? "登录" : "注册"}</h1>
        <p>一个人练成都血战。另外三家是人机。每人从 100 分开始，谁先到 0 分或以下，这一整局结束。再开一局恢复为各 100 分。</p>
        <label>用户名<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label>密码<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="err">{error}</p>}
        <button className="solid" type="submit">{mode === "login" ? "登录" : "注册并进入"}</button>
        <p><button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "没有账号，去注册" : "已有账号，去登录"}</button></p>
      </form>
    </main>
  );
}

function Lobby({ user }: { user: User }) {
  const navigate = useNavigate();
  const [games, setGames] = useState<any[]>([]);
  const [saves, setSaves] = useState<any[]>([]);
  const [base, setBase] = useState(1);
  const [exchange, setExchange] = useState(true);
  const [error, setError] = useState("");
  async function refresh() {
    setGames(await api.games());
    setSaves(await api.saves());
  }
  useEffect(() => { refresh().catch((err) => setError(err.message)); }, []);
  async function create() {
    setError("");
    const created = await api.createGame({ base_score: base, enable_exchange: exchange, name: `${user.username} 的练习` });
    navigate(`/game/${created.view.game_id}`);
  }
  return (
    <main className="page">
      <div className="grid">
        <section className="card">
          <h2>新的一局</h2>
          <p>四家都从 100 分起。底分只乘和牌、查叫和花猪，不乘刮风下雨。</p>
          <label>底分<input type="number" min={1} max={10000} value={base} onChange={(e) => setBase(Number(e.target.value))} /></label>
          <label><input type="checkbox" checked={exchange} onChange={(e) => setExchange(e.target.checked)} /> 换三张</label>
          {error && <p className="err">{error}</p>}
          <button className="solid" onClick={() => create().catch((err) => setError(err.message))}>开始</button>
        </section>
        <section className="card">
          <h2>进行中的对局</h2>
          <div className="list">
            {games.length === 0 && <p>还没有对局。</p>}
            {games.map((game) => (
              <button key={game.id} onClick={() => navigate(`/game/${game.id}`)}>
                {game.name || "未命名"} · {phaseName(game.phase)} · {game.scores_game.join(" / ")}
              </button>
            ))}
          </div>
          <h2>命名存档</h2>
          <div className="list">
            {saves.length === 0 && <p>还没有存档。牌桌上可以随时保存。</p>}
            {saves.map((save) => (
              <button key={save.id} onClick={() => api.load(save.id).then((loaded) => navigate(`/game/${loaded.game_id}`))}>
                {save.name} · {phaseName(save.phase)} · {save.scores_game.join(" / ")}
              </button>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function Rules() {
  return (
    <main className="page card">
      <h1>成都血战到底</h1>
      <p>108 张，只有万、条、筒。不能吃。先换三张，再定缺。手上有缺门，就只能打缺门，也不能碰、杠、胡。</p>
      <p>一家胡了不结束，直到三家胡，或者牌墙摸完。点炮只由点炮者付一份。自摸由还没胡的各家各付一份，自摸不加番。封顶 5 番，1 番 1 倍，5 番 16 倍。</p>
      <p>暗杠每家 2 分，直杠点杠者付 2 分，巴杠每家 1 分。巴杠只有这一巡刚摸到的第四张才收分。杠上炮把这一笔杠分转给胡牌的人。</p>
      <p>牌墙摸完先查花猪：手里还有三种花色，向每个不是花猪的人付极品。然后查大叫。没听牌的人退回自己收到的杠分。死叫不算听。</p>
      <p>能胡却放过，在你下一次摸牌之前不能再胡别人打出的牌。牌出现前墙里只剩不超过 4 张时，能胡必须胡。</p>
      <p>训练计分：每人开局 100 分。任意一家到 0 分或以下，这一整局结束。再开一局，四家都恢复为 100 分。</p>
    </main>
  );
}

function Table() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [clauses, setClauses] = useState<Record<string, string>>({});
  const [saveName, setSaveName] = useState("练习存档");
  useEffect(() => { api.clauses().then(setClauses).catch(() => undefined); }, []);
  useEffect(() => {
    api.game(id).then(setView).catch((err) => setError(err.message));
  }, [id]);
  async function send(action: Action) {
    if (!view) return;
    setError("");
    const result = await api.act(id, view.seq, action);
    setView(result.view);
    setPicked([]);
  }
  const scores = view ? total(view) : [];
  const que = view?.dingque[String(view.self_seat)];
  const hand = useMemo(() => {
    if (!view) return [];
    const tiles = [...view.hand];
    if (!que) return tiles.sort((a, b) => a - b);
    const missing = tiles.filter((tile) => tileParts(tile).suit === ["wan", "tiao", "tong"].indexOf(que));
    const rest = tiles.filter((tile) => !missing.includes(tile));
    return [...missing.sort((a, b) => a - b), ...rest.sort((a, b) => a - b)];
  }, [view, que]);
  if (!view) return <p className="page">{error || "正在读取对局…"}</p>;
  const sameSuit = picked.length === 0 || picked.every((tile) => tileParts(tile).suit === tileParts(picked[0]).suit);
  return (
    <main className="table-page">
      {view.phase === "exchanging" && <p className="banner">换三张，交给{DIR[view.exchange_direction || "to_next"]}。选同一花色的 3 张。</p>}
      {view.phase === "dingque" && <p className="banner">定缺。这一门必须先打完，才能碰、杠、胡。</p>}
      {view.end_reason === "bust" && <p className="banner">有人分数已经到 0 或以下，这一整局结束。新的一局会把四家都恢复为 100 分。</p>}
      <section className="felt">
        <Seat view={view} seat={2} className="west" scores={scores} />
        <Seat view={view} seat={3} className="north" scores={scores} />
        <div className="center">
          {[0, 1, 2, 3].map((seat) => (
            <div key={seat}>
              <div className="meta">{SEAT[seat]} 牌河</div>
              <div className="river">
                {view.discards[String(seat)].map((item, index) => <Tile key={index} id={item.tile} dim={item.claimed_by.length > 0} />)}
              </div>
            </div>
          ))}
        </div>
        <Seat view={view} seat={1} className="south" scores={scores} />
        <div className="east seat you">
          <h3>你 · 东 {view.dealer === 0 ? "庄" : ""} <span className="score">{scores[0]} 分</span> {que && <span className="que">缺{SUIT_NAME[que]}</span>}</h3>
          {!view.legal_actions.some((action) => action.type === "exchange") && <div className="hand">
            {hand.map((tile) => {
              const isQue = que && tileParts(tile).suit === ["wan", "tiao", "tong"].indexOf(que);
              return (
                <span key={tile} className={isQue ? "que-gap" : ""}>
                  <Tile id={tile} mark={isQue ? "缺" : undefined} dim={false} />
                </span>
              );
            })}
          </div>}
          <div className="hand" onClick={(event) => event.stopPropagation()}>
            {view.legal_actions.some((action) => action.type === "exchange") && hand.map((tile) => (
              <button key={tile} className={picked.includes(tile) ? "picked" : ""} onClick={() => setPicked((current) => current.includes(tile) ? current.filter((item) => item !== tile) : current.length >= 3 ? current : [...current, tile])}>
                <Tile id={tile} />
              </button>
            ))}
          </div>
          <div className="actions">
            {view.legal_actions.some((action) => action.type === "exchange") && <button className="solid" disabled={picked.length !== 3 || !sameSuit} onClick={() => send({ type: "exchange", tiles: picked })}>交出 3 张</button>}
            {view.legal_actions.some((action) => action.type === "dingque") && ["wan", "tiao", "tong"].map((suit) => (
              <button key={suit} onClick={() => send({ type: "dingque", suit })}>缺{SUIT_NAME[suit]}（{view.hand.filter((tile) => tileParts(tile).suit === ["wan", "tiao", "tong"].indexOf(suit)).length}）</button>
            ))}
            {view.legal_actions.filter((action) => action.type === "hu").length > 0 && <button className="hu" onClick={() => send({ type: "hu" })}>胡</button>}
            {view.legal_actions.filter((action) => action.type === "pong").map((action) => <button key="pong" onClick={() => send(action)}>碰</button>)}
            {view.legal_actions.filter((action) => action.type === "kong").map((action) => <button key={`${action.kong_kind}-${action.tile}`} onClick={() => send(action)}>{action.kong_kind === "an" ? "暗杠" : action.kong_kind === "ba" ? "巴杠" : "杠"}</button>)}
            {view.legal_actions.filter((action) => action.type === "pass").map((action) => <button key="pass" onClick={() => send(action)}>过</button>)}
            {view.legal_actions.filter((action) => action.type === "discard").slice(0, 14).map((action) => (
              <button key={action.tile} onClick={() => send(action)}>打 {tileParts(action.tile || 0).label}</button>
            ))}
            {view.legal_actions.some((action) => action.type === "next_hand") && <button className="solid" onClick={() => send({ type: "next_hand" })}>再来一盘</button>}
            {view.legal_actions.some((action) => action.type === "end_game") && <button onClick={() => send({ type: "end_game" }).then(() => navigate("/"))}>结束并回大厅</button>}
            {view.end_reason === "bust" && <button className="solid" onClick={() => navigate("/")}>回大厅，新局恢复 100 分</button>}
          </div>
          {error && <p className="err">{error}</p>}
        </div>
      </section>
      <section className="ledger">
        <div className="actions">
          <span>牌墙 {view.wall_remaining} · 第 {view.hand_index + 1} 盘 · 累计 {scores.join(" / ")}</span>
          <input value={saveName} onChange={(e) => setSaveName(e.target.value)} style={{ width: 180 }} />
          <button onClick={() => api.save(id, saveName).then(() => setError("已保存")).catch((err) => setError(err.message))}>保存对局</button>
        </div>
        <ul>
          {view.ledger.map((entry, index) => (
            <li key={index}>{SEAT[entry.from_seat]} → {SEAT[entry.to_seat]} {entry.amount} 分 · {clauses[entry.clause_id] || entry.clause_id} {entry.detail?.patterns?.join(" ")}</li>
          ))}
          {view.ledger.length === 0 && <li>这一盘还没有分数进出。</li>}
        </ul>
        {(view.phase === "between_hands" || view.phase === "completed") && view.revealed_hands && (
          <div>
            <h3>亮牌</h3>
            {[0, 1, 2, 3].map((seat) => (
              <p key={seat}>{SEAT[seat]} {view.revealed_hands?.[String(seat)].map((tile) => tileParts(tile).label).join(" ")}</p>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function Seat({ view, seat, className, scores }: { view: View; seat: number; className: string; scores: number[] }) {
  const que = view.dingque[String(seat)];
  const win = view.wins[String(seat)];
  const handCount = view.revealed_hands ? view.revealed_hands[String(seat)].length : seat === 0 ? view.hand.length : guessCount(view, seat);
  return (
    <aside className={`seat ${className}`}>
      <h3>{SEAT[seat]} {view.dealer === seat ? "庄" : ""}</h3>
      <div className="meta">
        <span className="score">{scores[seat]} 分</span>
        {que && <span className="que">缺{SUIT_NAME[que]}</span>}
        {win && <span>已胡 {win.points}</span>}
        {!win && <span>{handCount} 张牌背</span>}
      </div>
      <div className="river">
        {view.melds[String(seat)].map((meld, index) => (
          <span key={index}>{meld.tiles.map((tile) => <Tile key={tile} id={tile} />)}</span>
        ))}
      </div>
    </aside>
  );
}

function guessCount(view: View, seat: number) {
  if (view.wins[String(seat)]) return view.wins[String(seat)]!.hand.length;
  return 13;
}

function phaseName(phase: string) {
  const names: Record<string, string> = {
    exchanging: "换三张",
    dingque: "定缺",
    turn_discard: "行牌",
    await_claims: "等应牌",
    await_rob: "抢杠",
    between_hands: "本盘结束",
    completed: "整局结束",
  };
  return names[phase] || phase;
}
