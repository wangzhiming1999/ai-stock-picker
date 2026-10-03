const MAX_CANDIDATES = 30;

export function normalizeCandidateCodes(codes: Iterable<string>): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();

  for (const value of codes) {
    const code = value.trim();
    if (!/^\d{6}$/.test(code) || seen.has(code)) continue;
    seen.add(code);
    normalized.push(code);
    if (normalized.length === MAX_CANDIDATES) break;
  }

  return normalized;
}

export function mergeCandidateCodes(current: Iterable<string>, incoming: Iterable<string>): string[] {
  return normalizeCandidateCodes([...incoming, ...current]);
}

export function parseCandidateCodes(raw: string): string[] {
  return normalizeCandidateCodes(raw.split(/[\s,，；;]+/));
}
