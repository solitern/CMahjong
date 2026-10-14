const SUITS = ["万", "条", "筒"];
const COLORS = ["#a33b32", "#2f6f4e", "#2c4f7c"];

export function tileParts(id: number) {
  const suit = Math.floor(id / 36);
  const rank = Math.floor((id % 36) / 4) + 1;
  return { suit, rank, label: `${rank}${SUITS[suit]}`, color: COLORS[suit] };
}

export function Tile({ id, dim, mark }: { id: number; dim?: boolean; mark?: string }) {
  const { rank, suit, color } = tileParts(id);
  return (
    <span className={`tile${dim ? " dim" : ""}`} style={{ color }}>
      <svg viewBox="0 0 24 32" aria-hidden>
        {suit === 0 && <text x="12" y="21" textAnchor="middle" fontSize="14" fontFamily="serif">{rank}</text>}
        {suit === 1 && <Bamboo rank={rank} />}
        {suit === 2 && <Dots rank={rank} />}
      </svg>
      {mark && <i>{mark}</i>}
    </span>
  );
}

function Bamboo({ rank }: { rank: number }) {
  const sticks = Math.min(rank, 5);
  return (
    <>
      {Array.from({ length: sticks }, (_, index) => (
        <rect key={index} x={4 + (index % 3) * 6} y={6 + Math.floor(index / 3) * 10} width="3" height="8" rx="1" fill="#2f6f4e" />
      ))}
      <text x="20" y="30" fontSize="7" fill="#2f6f4e">{rank}</text>
    </>
  );
}

function Dots({ rank }: { rank: number }) {
  const dots = Math.min(rank, 5);
  return (
    <>
      {Array.from({ length: dots }, (_, index) => (
        <circle key={index} cx={7 + (index % 3) * 5} cy={10 + Math.floor(index / 3) * 6} r="2" fill="#2c4f7c" />
      ))}
      <text x="20" y="30" fontSize="7" fill="#2c4f7c">{rank}</text>
    </>
  );
}

export function Back({ count }: { count: number }) {
  return <span className="backs">{count} 张</span>;
}
