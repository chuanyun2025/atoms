// Flat row-major boards. The caller supplies new tiles so level generation and replay can be seeded.
export type Round = { removed: number[]; board: number[] };

export function findMatches(board: number[], width: number): number[] {
  const matched = new Set<number>();
  const height = board.length / width;
  for (const [lines, cells, step, lineStep] of [[height, width, 1, width], [width, height, width, 1]]) {
    for (let line = 0; line < lines; line++) {
      const base = line * lineStep;
      for (let first = 0; first < cells;) {
        const tile = board[base + first * step];
        let end = first + 1;
        while (end < cells && board[base + end * step] === tile) end++;
        if (end - first >= 3) {
          for (let i = first; i < end; i++) matched.add(base + i * step);
        }
        first = end;
      }
    }
  }
  return [...matched].sort((a, b) => a - b);
}

function swap(board: number[], a: number, b: number): number[] {
  const next = [...board];
  [next[a], next[b]] = [next[b], next[a]];
  return next;
}

export function trySwap(board: number[], width: number, a: number, b: number): number[] | null {
  if (![a,b].every(i => Number.isInteger(i) && i >= 0 && i < board.length)) return null;
  const distance = Math.abs(a % width - b % width) + Math.abs(Math.floor(a / width) - Math.floor(b / width));
  if (distance !== 1) return null;
  const next = swap(board, a, b);
  return findMatches(next, width).some(i => i === a || i === b) ? next : null;
}

export function resolveRound(board: number[], width: number, nextTile: () => number): Round | null {
  const removed = findMatches(board, width);
  if (!removed.length) return null;
  const gaps = new Set(removed);
  const next = [...board];
  for (let column = 0; column < width; column++) {
    let destination = board.length - width + column;
    for (let source = destination; source >= 0; source -= width) {
      if (gaps.has(source)) continue;
      next[destination] = board[source];
      destination -= width;
    }
    for (; destination >= 0; destination -= width) next[destination] = nextTile();
  }
  return { removed, board: next };
}

export function hasMove(board: number[], width: number): boolean {
  return board.some((_, a) =>
    (a % width < width - 1 && trySwap(board, width, a, a + 1) !== null) ||
    trySwap(board, width, a, a + width) !== null,
  );
}
