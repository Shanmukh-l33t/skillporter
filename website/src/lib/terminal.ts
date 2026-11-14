/**
 * Loads the recorded CLI transcripts in src/data/recordings and turns them
 * into lightly highlighted HTML. The text is never altered: highlighting only
 * wraps existing characters in spans. Recordings are produced by
 * website/scripts/record_cli_output.py from the real CLI.
 */

const files = import.meta.glob<string>('../data/recordings/*.txt', {
  query: '?raw',
  import: 'default',
  eager: true,
});

export interface Recording {
  name: string;
  /** Exit code of each command in the transcript, in order. */
  exitCodes: number[];
  /** Transcript lines, including `$ skillporter ...` prompt lines. */
  lines: string[];
  /** The commands that were run, without the `$ ` prefix. */
  commands: string[];
}

const recordings = new Map<string, Recording>();

for (const [path, raw] of Object.entries(files)) {
  const name = path.split('/').pop()!.replace(/\.txt$/, '');
  const allLines = raw.replace(/\n+$/, '').split('\n');
  const header = allLines[0] ?? '';
  const match = /^# exit: ([\d,]+)$/.exec(header);
  const lines = match ? allLines.slice(1) : allLines;
  recordings.set(name, {
    name,
    exitCodes: match ? match[1]!.split(',').map(Number) : [],
    lines,
    commands: lines.filter((line) => line.startsWith('$ ')).map((line) => line.slice(2)),
  });
}

export function getRecording(name: string): Recording {
  const rec = recordings.get(name);
  if (!rec) throw new Error(`Unknown CLI recording: ${name}`);
  return rec;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

interface Rule {
  re: RegExp;
  cls: string;
}

// Ordered: the first rule that matches at a position wins.
const RULES: Rule[] = [
  { re: /\[(?:CRITICAL|HIGH)\]|\b(?:BLOCKED|REJECT|FAILED|DRIFT|MISSING|BROKEN SYMLINK|CRITICAL_DETECTED_RISK)\b|^error:/, cls: 't-warn' },
  { re: /\[(?:MEDIUM|LOW|INFO)\]/, cls: 't-dim' },
  { re: /\bsec-[a-z0-9-]+\b/, cls: 't-code' },
  { re: /\b(?:RUNTIME_VERIFIED|INTEGRATION_TESTED|FIXTURE_TESTED|PINNED_COMMIT|NO_DETECTED_FINDINGS)\b/, cls: 't-code' },
  { re: /\b(?:SUCCESS|PASSED|APPROVE|HEALTHY|verified)\b|\byes\b/, cls: 't-ok' },
  { re: /(?:~\/|\.)[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.<>-]+)+/, cls: 't-path' },
];

function highlightOutput(line: string): string {
  let out = '';
  let rest = line;
  let atStart = true;
  while (rest.length > 0) {
    let best: { index: number; length: number; cls: string } | null = null;
    for (const rule of RULES) {
      const m = rule.re.exec(rest);
      if (!m) continue;
      // `error:` only counts as a marker at the very start of a line.
      if (m[0].startsWith('error:') && !atStart) continue;
      if (best === null || m.index < best.index) {
        best = { index: m.index, length: m[0].length, cls: rule.cls };
      }
    }
    if (!best || best.length === 0) {
      out += escapeHtml(rest);
      break;
    }
    out += escapeHtml(rest.slice(0, best.index));
    out += `<span class="${best.cls}">${escapeHtml(rest.slice(best.index, best.index + best.length))}</span>`;
    rest = rest.slice(best.index + best.length);
    atStart = false;
  }
  return out;
}

export interface RenderOptions {
  /** Keep lines up to (not including) the first line matching this pattern. */
  cutAt?: RegExp;
  /** Text shown in place of everything after `cutAt`. */
  cutNote?: string;
  /** Keep only these line ranges (0-based, inclusive). Gaps get an ellipsis line. */
  ranges?: Array<[number, number]>;
}

export interface RenderedTranscript {
  html: string;
  abridged: boolean;
}

export function renderTranscript(name: string, options: RenderOptions = {}): RenderedTranscript {
  const rec = getRecording(name);
  let lines = rec.lines;
  let abridged = false;
  const notes = new Map<number, string>();

  if (options.cutAt) {
    const index = lines.findIndex((line) => options.cutAt!.test(line));
    if (index !== -1) {
      lines = lines.slice(0, index);
      while (lines.length && lines[lines.length - 1] === '') lines.pop();
      notes.set(lines.length, options.cutNote ?? 'remaining output omitted');
      abridged = true;
    }
  }

  let selected: Array<{ text: string; note?: boolean }> = lines.map((text) => ({ text }));
  if (options.ranges) {
    selected = [];
    let last = -1;
    for (const [from, to] of options.ranges) {
      if (from > last + 1 && selected.length) {
        selected.push({ text: 'lines omitted', note: true });
        abridged = true;
      }
      for (let i = from; i <= Math.min(to, lines.length - 1); i++) selected.push({ text: lines[i]! });
      last = to;
    }
    if (last < lines.length - 1) {
      selected.push({ text: 'remaining output omitted', note: true });
      abridged = true;
    }
  }
  for (const [, note] of notes) selected.push({ text: note, note: true });

  const html = selected
    .map(({ text, note }) => {
      if (note) return `<span class="t-note">[ ${escapeHtml(text)} ]</span>`;
      if (text.startsWith('$ ')) {
        return `<span class="t-prompt">$</span> <span class="t-cmd">${escapeHtml(text.slice(2))}</span>`;
      }
      // Diff and finding lists: removed or failing entries in amber, additions in ivory.
      if (/^\s*- /.test(text)) return `<span class="t-warn">${escapeHtml(text)}</span>`;
      if (/^\s*\+ /.test(text)) return `<span class="t-ok">${escapeHtml(text)}</span>`;
      return highlightOutput(text);
    })
    .join('\n');

  return { html, abridged };
}
