export type Action = {
  type: string;
  tile?: number;
  tiles?: number[];
  suit?: string;
  kong_kind?: string;
};

export type View = {
  game_id: string;
  seq: number;
  phase: string;
  hand_index: number;
  dealer: number;
  turn: number | null;
  wall_remaining: number;
  must_hu: boolean;
  self_seat: number;
  exchange_direction: string | null;
  dingque: Record<string, string | null>;
  hand: number[];
  melds: Record<string, { kind: string; tiles: number[] }[]>;
  discards: Record<string, { tile: number; claimed_by: number[] }[]>;
  wins: Record<string, { tile: number | null; hand: number[]; fan_raw: number; patterns: string[]; additives: string[]; points: number; win_kind: string } | null>;
  revealed_hands?: Record<string, number[]>;
  scores_hand: number[];
  scores_game: number[];
  hand_folded: boolean;
  initial_points: number;
  end_reason: string | null;
  ledger: { clause_id: string; from_seat: number; to_seat: number; amount: number; fan_raw: number | null; detail: { patterns?: string[] } }[];
  legal_actions: Action[];
  pending_kind: string | null;
  rules: { base_score: number; enable_exchange: boolean; enable_jingoudiao: boolean };
};

const headers = { "Content-Type": "application/json", "X-Requested-With": "cmahjong" };

async function send(path: string, options: RequestInit = {}) {
  const response = await fetch(path, { credentials: "include", ...options, headers: { ...headers, ...(options.headers || {}) } });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body?.error?.message
      || (response.status === 502 || response.status === 504
        ? "接口没有起来。请在服务器查看 docker compose logs api"
        : `请求失败（${response.status}）`);
    throw new Error(message);
  }
  return body;
}

export const api = {
  me: () => send("/api/me"),
  register: (username: string, password: string) => send("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
  login: (username: string, password: string) => send("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => send("/api/auth/logout", { method: "POST" }),
  games: () => send("/api/games"),
  createGame: (body: object) => send("/api/games", { method: "POST", body: JSON.stringify(body) }),
  game: (id: string) => send(`/api/games/${id}`),
  act: (id: string, seq: number, action: Action) => send(`/api/games/${id}/actions`, { method: "POST", body: JSON.stringify({ expected_seq: seq, action }) }),
  save: (id: string, name: string) => send(`/api/games/${id}/save`, { method: "POST", body: JSON.stringify({ name }) }),
  saves: () => send("/api/saves"),
  load: (id: string) => send(`/api/saves/${id}/load`, { method: "POST" }),
  clauses: () => send("/api/clauses"),
};

export const SUIT = ["万", "条", "筒"];
export const SEAT = ["你 · 东", "下家 · 南", "对家 · 西", "上家 · 北"];
export const SUIT_NAME: Record<string, string> = { wan: "万", tiao: "条", tong: "筒" };
export const DIR: Record<string, string> = { to_next: "下家", to_prev: "上家", to_across: "对家" };

export function total(view: View) {
  if (view.hand_folded) return view.scores_game;
  return view.scores_game.map((score, index) => score + view.scores_hand[index]);
}
