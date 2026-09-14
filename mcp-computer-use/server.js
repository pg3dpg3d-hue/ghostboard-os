#!/usr/bin/env node
/*
 * ============================================================================
 *  GHOSTBOARD OS — serveur MCP « computer use » (sur la machine)
 * ============================================================================
 *  Expose l'écran graphique à Claude Code : capture -> analyse -> clic/frappe.
 *  Le raisonnement est dans le cloud, le contrôle est ici.
 *
 *  Outils : screenshot, click, type, key  (le contrat demandé)
 *           + screen_info et scroll, sans lesquels un agent est aveugle et
 *             coincé dès qu'une liste dépasse 480 px de haut.
 *
 *  ZÉRO dépendance npm. C'est délibéré :
 *    - `npm install` ne tourne jamais sur le deck,
 *    - le serveur démarre en ~25 ms au lieu de ~250 ms,
 *    - rien à mettre à jour, rien à auditer.
 *  Le protocole MCP en JSON-RPC 2.0 sur stdio tient en 80 lignes.
 *
 *  Capture optimisée pour la dalle : 800x480 natif, AUCUN redimensionnement
 *  par défaut. C'est déjà ~512 tokens d'image — inutile de suréchantillonner
 *  puis de réduire.
 *
 *  Variables d'environnement :
 *    GHOSTBOARD_MCP_DISPLAY   écran X à piloter (défaut :0)
 *                             -> c'est le point de bascule vers une session
 *                                graphique dédiée à l'agent (voir docs)
 *    GHOSTBOARD_STOP_FILE     fichier d'arrêt partagé avec le centre de contrôle
 * ============================================================================
 */
'use strict';

const { spawnSync, spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const DISPLAY = process.env.GHOSTBOARD_MCP_DISPLAY || process.env.DISPLAY || ':0';
const STOP_FILE = process.env.GHOSTBOARD_STOP_FILE || path.join(os.homedir(), '.local/state/ghostboard/agent.stop');
const HAND_STATE_FILE = process.env.GHOSTBOARD_HAND_STATE || path.join(os.homedir(), '.local/state/ghostboard/hand-control.json');
const WORKSPACE = path.resolve(process.env.GHOSTBOARD_WORKSPACE || path.join(os.homedir(), 'Ghostboard'));
let activeController = null;
let activeId = null;
let shuttingDown = false;
const EXEC_TIMEOUT = 15000;

const SERVER_INFO = { name: 'ghostboard-computer-use', version: '1.2.0' };
const SUPPORTED_PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05'];

// stdout est réservé au protocole. Tout le reste part sur stderr.
const log = (...a) => process.stderr.write('[ghostboard-mcp] ' + a.join(' ') + '\n');

// ---------------------------------------------------------------------------
//  Exécution
// ---------------------------------------------------------------------------
function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    if (!opts.releaseOnly && (activeController?.signal.aborted || fs.existsSync(STOP_FILE))) {
      return reject(new Error('Agent stopped. Resume explicitly with ghost-system resume.'));
    }
    const child = spawn(cmd, args, { env: { ...process.env, DISPLAY }, cwd: opts.cwd, stdio: ['pipe', 'pipe', 'pipe'] });
    const out = [], err = []; let bytes = 0, cause = null;
    const kill = (reason) => { cause = reason; child.kill('SIGKILL'); };
    const timeout = setTimeout(() => kill('command timed out'), opts.timeout || EXEC_TIMEOUT);
    const poll = setInterval(() => {
      if (!opts.releaseOnly && (activeController?.signal.aborted || fs.existsSync(STOP_FILE))) kill('Agent stopped');
    }, 100);
    const cleanup = () => { clearTimeout(timeout); clearInterval(poll); };
    child.stdout.on('data', d => { bytes += d.length; if (bytes > 32 * 1024 * 1024) kill('output too large'); else out.push(d); });
    child.stderr.on('data', d => { if (err.reduce((n, x) => n + x.length, 0) < 65536) err.push(d); });
    child.on('error', e => { cleanup(); reject(e); });
    child.on('close', code => {
      cleanup();
      if (cause || (code !== 0 && !opts.allowNonzero)) reject(new Error(cause || `${cmd}: ${Buffer.concat(err).toString().trim() || code}`));
      else resolve({ stdout: Buffer.concat(out), stderr: Buffer.concat(err), code });
    });
    child.stdin.on('error', () => {});
    child.stdin.end(opts.input || '');
  });
}

function integer(value, name, min, max) {
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${name}: integer required in [${min}, ${max}]`);
  return value;
}
async function point(args) {
  const size = await screenSize();
  integer(args.x, 'x', 0, size.width - 1);
  integer(args.y, 'y', 0, size.height - 1);
  return size;
}

const has = (cmd) =>
  spawnSync('sh', ['-c', `command -v ${cmd}`], { timeout: 4000 }).status === 0;

function ensureRunning() {
  if (activeController?.signal.aborted || fs.existsSync(STOP_FILE)) {
    throw new Error('Agent stopped. Resume explicitly with ghost-system resume.');
  }
}

function workspacePath(relative = '.', forWrite = false) {
  if (typeof relative !== 'string' || relative.length > 4096 || relative.includes('\0')) throw new Error('Invalid workspace path.');
  const parts = relative.replaceAll('\\', '/').split('/');
  if (parts.includes('.git')) throw new Error('Direct access to .git is refused; use the git command.');
  const candidate = path.resolve(WORKSPACE, relative);
  if (candidate !== WORKSPACE && !candidate.startsWith(WORKSPACE + path.sep)) throw new Error('Path escapes the workspace.');
  const existing = forWrite && !fs.existsSync(candidate) ? path.dirname(candidate) : candidate;
  if (fs.existsSync(existing)) {
    const real = fs.realpathSync(existing);
    if (real !== WORKSPACE && !real.startsWith(WORKSPACE + path.sep)) throw new Error('Symbolic link escapes the workspace.');
  }
  return candidate;
}

// ---------------------------------------------------------------------------
//  Écran
// ---------------------------------------------------------------------------
async function screenSize() {
  // xdotool est déjà requis pour agir : autant l'utiliser pour mesurer.
  const out = (await run('xdotool', ['getdisplaygeometry'])).stdout.toString().trim();
  const [w, h] = out.split(/\s+/).map(Number);
  if (!Number.isInteger(w) || !Number.isInteger(h) || w < 1 || h < 1 || w > 32768 || h > 32768) throw new Error(`géométrie illisible : "${out}"`);
  return { width: w, height: h };
}

/**
 * Capture d'écran -> PNG.
 * Chaîne de repli : scrot (installé par défaut, ~1 Mo de dépendances) puis
 * maim, import (ImageMagick) et ffmpeg si l'un d'eux traîne déjà sur la machine.
 */
async function capture(region) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gb-shot-'));
  fs.chmodSync(dir, 0o700);
  const tmp = path.join(dir, 'screen.png');
  const cleanup = () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) {} };

  const attempts = [];
  if (has('scrot')) {
    attempts.push(region
      ? ['scrot', ['-o', '-a', `${region.x},${region.y},${region.width},${region.height}`, tmp]]
      : ['scrot', ['-o', '-F', tmp]]);
  }
  if (has('maim')) {
    attempts.push(region
      ? ['maim', ['-g', `${region.width}x${region.height}+${region.x}+${region.y}`, tmp]]
      : ['maim', [tmp]]);
  }
  if (has('import')) {
    attempts.push(region
      ? ['import', ['-window', 'root', '-crop',
          `${region.width}x${region.height}+${region.x}+${region.y}`, '+repage', tmp]]
      : ['import', ['-window', 'root', tmp]]);
  }
  if (has('ffmpeg')) {
    const size = region ? `${region.width}x${region.height}` : null;
    const input = region ? `${DISPLAY}+${region.x},${region.y}` : DISPLAY;
    attempts.push(['ffmpeg', ['-loglevel', 'error', '-f', 'x11grab',
      ...(size ? ['-video_size', size] : []), '-i', input, '-frames:v', '1', '-y', tmp]]);
  }

  if (attempts.length === 0) {
    cleanup();
    throw new Error("aucun outil de capture trouvé — installer scrot (`apt install scrot`)");
  }

  let lastErr;
  for (const [cmd, args] of attempts) {
    try {
      await run(cmd, args);
      if (fs.existsSync(tmp) && fs.statSync(tmp).size > 0) {
        if (fs.statSync(tmp).size > 32 * 1024 * 1024) throw new Error('Screenshot exceeds 32 MiB; capture a smaller region.');
        const buf = fs.readFileSync(tmp);
        cleanup();
        return buf;
      }
    } catch (e) {
      lastErr = e;
    }
  }
  cleanup();
  throw new Error(`capture impossible : ${lastErr ? lastErr.message : 'aucune sortie'}`);
}

// ---------------------------------------------------------------------------
//  Outils
// ---------------------------------------------------------------------------
const BUTTONS = { left: 1, middle: 2, right: 3 };

const TOOLS = {
  screenshot: {
    description:
      "Capture l'écran du deck (800x480 natif) et renvoie une image PNG. "
      + "Appelle-le avant chaque action pour voir l'état réel de l'interface, "
      + "et après une action pour vérifier son effet. Les coordonnées de `click` "
      + "sont celles de cette image, origine en haut à gauche.",
    inputSchema: {
      type: 'object',
      properties: {
        region: {
          type: 'object',
          description: "Zone à capturer. Sur une dalle de 800x480 l'écran entier "
            + "coûte déjà peu ; ne cadrer que pour lire un détail précis.",
          properties: {
            x: { type: 'integer' }, y: { type: 'integer' },
            width: { type: 'integer' }, height: { type: 'integer' },
          },
          required: ['x', 'y', 'width', 'height'],
        },
      },
    },
    async handler(args) {
      if (args.region) {
        const size = await point(args.region);
        integer(args.region.width, 'width', 1, size.width - args.region.x);
        integer(args.region.height, 'height', 1, size.height - args.region.y);
      }
      const png = await capture(args.region);
      const { width, height } = await screenSize();
      const dims = args.region
        ? `${args.region.width}x${args.region.height} @ ${args.region.x},${args.region.y}`
        : `${width}x${height}`;
      return {
        content: [
          { type: 'image', data: png.toString('base64'), mimeType: 'image/png' },
          { type: 'text', text: `Capture ${dims} sur ${DISPLAY} (${Math.round(png.length / 1024)} Ko).` },
        ],
      };
    },
  },

  click: {
    description:
      "Clique à une position absolue de l'écran. Les coordonnées viennent de la "
      + "dernière capture. Vérifie toujours par une nouvelle capture après coup.",
    inputSchema: {
      type: 'object',
      properties: {
        x: { type: 'integer', description: 'Abscisse en pixels, 0 = bord gauche' },
        y: { type: 'integer', description: 'Ordonnée en pixels, 0 = bord haut' },
        button: { type: 'string', enum: ['left', 'middle', 'right'], default: 'left' },
        count: { type: 'integer', description: '2 pour un double-clic', default: 1 },
      },
      required: ['x', 'y'],
    },
    async handler(args) {
      const { width, height } = await screenSize();
      await point(args);
      const x = args.x, y = args.y;
      // Un clic hors écran ne déclenche rien et laisse l'agent croire qu'il a
      // agi : mieux vaut une erreur explicite.
      if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('coordonnées invalides');
      if (x < 0 || y < 0 || x >= width || y >= height) {
        throw new Error(`(${x},${y}) est hors de l'écran ${width}x${height}`);
      }
      const button = BUTTONS[args.button || 'left'];
      if (!button) throw new Error(`bouton inconnu : ${args.button}`);
      const count = integer(args.count ?? 1, 'count', 1, 3);
      await run('xdotool', ['mousemove', '--sync', String(x), String(y),
        'click', '--repeat', String(count), String(button)]);
      return { content: [{ type: 'text',
        text: `Clic ${args.button || 'left'}${count > 1 ? ` x${count}` : ''} en (${x},${y}).` }] };
    },
  },

  type: {
    description:
      "Tape du texte dans la fenêtre active, caractère par caractère. "
      + "Pour les touches de contrôle (Entrée, Tab, Ctrl+…), utiliser `key`.",
    inputSchema: {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'Texte littéral à saisir' },
        delay_ms: { type: 'integer',
          description: 'Délai entre frappes. 12 ms par défaut : assez lent pour '
            + 'les champs qui filtrent à la volée, assez rapide pour ne pas traîner.',
          default: 12 },
      },
      required: ['text'],
    },
    async handler(args) {
      if (typeof args.text !== 'string') throw new Error('`text` doit être une chaîne');
      if (args.text.length === 0) return { content: [{ type: 'text', text: 'Rien à taper.' }] };
      if (args.text.length > 8192) throw new Error('texte trop long (max 8192 caractères)');
      const delay = integer(args.delay_ms ?? 12, 'delay_ms', 0, 500);
      const timeout = Array.from(args.text).length * delay + 5000;
      if (timeout > 120000) throw new Error('Typing would exceed 120 seconds; reduce text or delay.');
      // stdin évite de placer le texte (éventuellement secret) dans argv.
      await run('xdotool', ['type', '--clearmodifiers', '--delay', String(delay), '--file', '-'], { input: args.text, timeout: Math.max(EXEC_TIMEOUT, timeout) });
      return { content: [{ type: 'text', text: `${args.text.length} caractère(s) saisi(s).` }] };
    },
  },

  key: {
    description:
      "Envoie une combinaison de touches, syntaxe X11/xdotool : `Return`, `Tab`, "
      + "`Escape`, `ctrl+c`, `alt+F4`, `super` (ouvre le menu démarrer), "
      + "`ctrl+shift+v`. Plusieurs combinaisons peuvent être enchaînées.",
    inputSchema: {
      type: 'object',
      properties: {
        keys: {
          oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }],
          description: 'Une combinaison, ou une liste jouée dans l\'ordre',
        },
      },
      required: ['keys'],
    },
    async handler(args) {
      const list = Array.isArray(args.keys) ? args.keys : [args.keys];
      if (list.length === 0) throw new Error('aucune touche fournie');
      if (list.length > 32) throw new Error('trop de combinaisons en un appel (max 32)');
      for (const k of list) {
        if (typeof k !== 'string' || !/^[A-Za-z0-9_+]+$/.test(k)) {
          throw new Error(`combinaison invalide : ${JSON.stringify(k)}`);
        }
      }
      await run('xdotool', ['key', '--clearmodifiers', ...list]);
      return { content: [{ type: 'text', text: `Touches envoyées : ${list.join(' ')}.` }] };
    },
  },

  scroll: {
    description:
      "Fait défiler à une position donnée. Indispensable sur cette dalle : "
      + "480 px de haut, la plupart des listes dépassent l'écran.",
    inputSchema: {
      type: 'object',
      properties: {
        x: { type: 'integer' }, y: { type: 'integer' },
        direction: { type: 'string', enum: ['up', 'down', 'left', 'right'], default: 'down' },
        amount: { type: 'integer', description: 'Nombre de crans (défaut 3)', default: 3 },
      },
      required: ['x', 'y'],
    },
    async handler(args) {
      const wheel = { up: '4', down: '5', left: '6', right: '7' };
      const b = wheel[args.direction || 'down'];
      if (!b) throw new Error(`direction inconnue : ${args.direction}`);
      await point(args);
      const n = integer(args.amount ?? 3, 'amount', 1, 25);
      await run('xdotool', ['mousemove', '--sync', String(Math.round(args.x)), String(Math.round(args.y)),
        'click', '--repeat', String(n), b]);
      return { content: [{ type: 'text',
        text: `Défilement ${args.direction || 'down'} x${n} en (${args.x},${args.y}).` }] };
    },
  },

  screen_info: {
    description:
      "Renvoie la géométrie de l'écran et la position du pointeur, sans image. "
      + "À utiliser pour se repérer sans payer le coût d'une capture.",
    inputSchema: { type: 'object', properties: {} },
    async handler() {
      const { width, height } = await screenSize();
      let pointer = 'inconnue';
      try {
        const out = (await run('xdotool', ['getmouselocation', '--shell'])).stdout.toString();
        const x = /X=(\d+)/.exec(out), y = /Y=(\d+)/.exec(out);
        if (x && y) pointer = `${x[1]},${y[1]}`;
      } catch (_) { /* non bloquant */ }
      return { content: [{ type: 'text', text: JSON.stringify({
        display: DISPLAY, width, height, pointer,
        note: 'Résolution native de la dalle GHOSTBOARD. Aucune mise à l\'échelle.',
      }, null, 2) }] };
    },
  },
};

TOOLS.windows = {
  description: 'List X11 windows with their hexadecimal IDs, desktops and titles. Use focus_window with an observed ID.',
  inputSchema: { type: 'object', properties: {} },
  async handler() {
    const out = (await run('wmctrl', ['-l'])).stdout.toString();
    return { content: [{ type: 'text', text: out || 'No windows.' }] };
  },
};
TOOLS.focus_window = {
  description: 'Activate a window by hexadecimal ID from windows. Observe the screen after focusing before typing.',
  inputSchema: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] },
  async handler(args) {
    if (typeof args.id !== 'string' || !/^0x[0-9a-fA-F]{1,16}$/.test(args.id)) throw new Error('Invalid window ID');
    await run('wmctrl', ['-ia', args.id]);
    return { content: [{ type: 'text', text: 'Window activated: ' + args.id }] };
  },
};
TOOLS.drag = {
  description: 'Drag with the left mouse button from (x,y) to (to_x,to_y), in absolute screen coordinates. Verify with a screenshot.',
  inputSchema: { type: 'object', properties: { x: { type: 'integer' }, y: { type: 'integer' }, to_x: { type: 'integer' }, to_y: { type: 'integer' } }, required: ['x', 'y', 'to_x', 'to_y'] },
  async handler(args) {
    await point(args);
    await point({ x: args.to_x, y: args.to_y });
    try {
      await run('xdotool', ['mousemove', '--sync', String(args.x), String(args.y), 'mousedown', '1', 'sleep', '0.15', 'mousemove', '--sync', String(args.to_x), String(args.to_y), 'sleep', '0.15', 'mouseup', '1']);
    } finally {
      // Relâcher même si l'arrêt est arrivé au milieu du glisser-déposer.
      await run('xdotool', ['mouseup', '1'], { releaseOnly: true, timeout: 2000 }).catch(() => {});
    }
    return { content: [{ type: 'text', text: 'Drag completed. Capture the screen to verify.' }] };
  },
};

TOOLS.workspace_status = {
  description: 'Inspect the writable Ghostboard Git checkout and host health before editing or diagnosing the Pi.',
  inputSchema: { type: 'object', properties: {} },
  async handler() {
    ensureRunning();
    if (!fs.existsSync(path.join(WORKSPACE, '.git'))) throw new Error('Workspace missing. Run ghost-workspace init on the Pi.');
    const git = await run('git', ['status', '--short', '--branch'], { cwd: WORKSPACE });
    const doctor = await run('ghost-system', ['doctor', '--json'], { cwd: WORKSPACE, allowNonzero: true }).catch(e => ({ stdout: Buffer.from(e.message) }));
    return { content: [{ type: 'text', text: `Workspace: ${WORKSPACE}\n${git.stdout.toString()}\nDiagnostics:\n${doctor.stdout.toString()}` }] };
  },
};

TOOLS.workspace_list = {
  description: 'List files and directories inside the writable Ghostboard checkout without following symlinks.',
  inputSchema: { type: 'object', properties: { path: { type: 'string', default: '.' }, depth: { type: 'integer', default: 2 } } },
  async handler(args) {
    ensureRunning();
    const start = workspacePath(args.path || '.');
    const depth = integer(args.depth ?? 2, 'depth', 0, 6);
    const found = [];
    function walk(current, level) {
      if (found.length >= 1000) return;
      for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
        if (entry.name === '.git') continue;
        const full = path.join(current, entry.name);
        const rel = path.relative(WORKSPACE, full) || '.';
        found.push(rel + (entry.isDirectory() ? '/' : entry.isSymbolicLink() ? ' -> [symlink]' : ''));
        if (entry.isDirectory() && !entry.isSymbolicLink() && level < depth) walk(full, level + 1);
        if (found.length >= 1000) break;
      }
    }
    const stat = fs.lstatSync(start);
    if (stat.isSymbolicLink()) throw new Error('Refusing to list through a symbolic link.');
    if (stat.isDirectory()) walk(start, 0); else found.push(path.relative(WORKSPACE, start));
    return { content: [{ type: 'text', text: found.join('\n') + (found.length >= 1000 ? '\n[truncated]' : '') }] };
  },
};

TOOLS.workspace_read = {
  description: 'Read a UTF-8 source or configuration file inside the writable Ghostboard checkout (maximum 1 MiB).',
  inputSchema: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] },
  async handler(args) {
    ensureRunning();
    const target = workspacePath(args.path);
    const stat = fs.statSync(target);
    if (!stat.isFile() || stat.size > 1024 * 1024) throw new Error('File must be regular and at most 1 MiB.');
    const data = fs.readFileSync(target);
    if (data.includes(0)) throw new Error('Binary files are not returned.');
    return { content: [{ type: 'text', text: data.toString('utf8') }] };
  },
};

TOOLS.workspace_write = {
  description: 'Atomically write one UTF-8 file inside the writable Ghostboard checkout. Review the diff afterwards.',
  inputSchema: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path', 'content'] },
  async handler(args) {
    ensureRunning();
    if (typeof args.content !== 'string' || Buffer.byteLength(args.content) > 1024 * 1024) throw new Error('Content must be UTF-8 and at most 1 MiB.');
    const target = workspacePath(args.path, true);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    workspacePath(path.relative(WORKSPACE, target), true);
    if (fs.existsSync(target) && fs.lstatSync(target).isSymbolicLink()) throw new Error('Refusing to replace a symbolic link.');
    const temp = path.join(path.dirname(target), `.ghostboard-write-${process.pid}-${Date.now()}`);
    try {
      fs.writeFileSync(temp, args.content, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
      if (fs.existsSync(target)) fs.chmodSync(temp, fs.statSync(target).mode & 0o777);
      fs.renameSync(temp, target);
    } finally { try { fs.unlinkSync(temp); } catch (_) {} }
    return { content: [{ type: 'text', text: `Wrote ${Buffer.byteLength(args.content)} bytes to ${path.relative(WORKSPACE, target)}.` }] };
  },
};

TOOLS.workspace_patch = {
  description: 'Apply a unified Git patch to the writable checkout after git apply validates it.',
  inputSchema: { type: 'object', properties: { patch: { type: 'string' } }, required: ['patch'] },
  async handler(args) {
    ensureRunning();
    if (typeof args.patch !== 'string' || Buffer.byteLength(args.patch) > 2 * 1024 * 1024) throw new Error('Patch must be text and at most 2 MiB.');
    await run('git', ['apply', '--check', '--whitespace=error-all', '-'], { cwd: WORKSPACE, input: args.patch });
    await run('git', ['apply', '--whitespace=error-all', '-'], { cwd: WORKSPACE, input: args.patch });
    return { content: [{ type: 'text', text: 'Patch applied. Run git diff --check and the relevant tests.' }] };
  },
};

TOOLS.workspace_exec = {
  description: 'Run a development or diagnostic command directly on the Pi, in the writable checkout, without a shell. Commands run as the paired desktop user.',
  inputSchema: {
    type: 'object',
    properties: {
      command: { type: 'string' },
      args: { type: 'array', items: { type: 'string' }, default: [] },
      cwd: { type: 'string', default: '.' },
      timeout_seconds: { type: 'integer', default: 30 },
    },
    required: ['command'],
  },
  async handler(args) {
    ensureRunning();
    const allowed = new Set(['git', 'python3', 'node', 'npm', 'bash', 'sh', 'rg', 'cmake', 'make', 'ninja', 'pytest', 'ghost-system', 'ghost-hardware', 'ghost-model', 'systemctl', 'journalctl']);
    if (!allowed.has(args.command)) throw new Error('Command is not in the developer allowlist.');
    const argv = args.args || [];
    if (!Array.isArray(argv) || argv.length > 128 || argv.some(x => typeof x !== 'string' || x.length > 8192 || x.includes('\0'))) throw new Error('Invalid command arguments.');
    const cwd = workspacePath(args.cwd || '.');
    if (!fs.statSync(cwd).isDirectory()) throw new Error('Working directory is not a directory.');
    const timeout = integer(args.timeout_seconds ?? 30, 'timeout_seconds', 1, 120) * 1000;
    const result = await run(args.command, argv, { cwd, timeout });
    const output = Buffer.concat([result.stdout, result.stderr]).toString('utf8');
    return { content: [{ type: 'text', text: output || '(command completed without output)' }] };
  },
};

TOOLS.hand_status = {
  description: 'Read-only status of GHOSTBOARD Hand Control (gesture tracking): state, mode, camera, FPS, confidence and the last recognized Point & Command event. This tool cannot enable the camera or gesture control; a person must activate hand control locally.',
  inputSchema: { type: 'object', properties: {} },
  async handler() {
    if (!fs.existsSync(HAND_STATE_FILE)) {
      return { content: [{ type: 'text', text: JSON.stringify({ state: 'DISABLED', running: false, note: 'Hand control is not running. A person can start it locally with ghost-hand start or the control center.' }, null, 2) }] };
    }
    let data;
    try {
      data = JSON.parse(fs.readFileSync(HAND_STATE_FILE, 'utf8'));
    } catch (_) {
      return { content: [{ type: 'text', text: JSON.stringify({ state: 'unknown', running: false }, null, 2) }] };
    }
    // « running » = état écrit récemment par le moteur (moins de 5 s).
    let running = false;
    try { running = (Date.now() - fs.statSync(HAND_STATE_FILE).mtimeMs) < 5000; } catch (_) {}
    data.running = running;
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
};

// ---------------------------------------------------------------------------
//  JSON-RPC 2.0 sur stdio
// ---------------------------------------------------------------------------
function send(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

async function handle(req) {
  const { id, method, params } = req;
  const reply = (result) => send({ jsonrpc: '2.0', id, result });
  const fail = (code, message) => send({ jsonrpc: '2.0', id, error: { code, message } });

  switch (method) {
    case 'initialize': {
      const asked = params && params.protocolVersion;
      const version = SUPPORTED_PROTOCOLS.includes(asked) ? asked : SUPPORTED_PROTOCOLS[0];
      return reply({
        protocolVersion: version,
        capabilities: { tools: { listChanged: false } },
        serverInfo: SERVER_INFO,
        instructions:
          "Contrôle de l'écran du cyberdeck GHOSTBOARD (800x480). "
          + "Prends une capture avant d'agir et une autre après pour vérifier. "
          + "Les coordonnées sont en pixels écran, origine en haut à gauche. "
          + `Le dépôt de développement distant est limité à ${WORKSPACE}.`,
      });
    }
    case 'notifications/initialized':
    case 'notifications/cancelled':
      return; // notification : pas de réponse
    case 'ping':
      return reply({});
    case 'tools/list':
      return reply({
        tools: Object.entries(TOOLS).map(([name, t]) => ({
          name, description: t.description, inputSchema: t.inputSchema,
        })),
      });
    case 'tools/call': {
      const name = params && params.name;
      const tool = Object.hasOwn(TOOLS, name) ? TOOLS[name] : null;
      if (!tool) return fail(-32602, `outil inconnu : ${name}`);
      try {
        if (params.arguments !== undefined && (!params.arguments || typeof params.arguments !== 'object' || Array.isArray(params.arguments))) throw new Error('arguments must be an object');
        return reply(await tool.handler(params.arguments || {}));
      } catch (err) {
        // Une erreur d'outil est un résultat, pas une panne de transport :
        // l'agent doit pouvoir la lire et se corriger.
        return reply({
          content: [{ type: 'text', text: `Erreur : ${err.message}` }],
          isError: true,
        });
      }
    }
    default:
      if (typeof method === 'string' && method.startsWith('notifications/')) return;
      return fail(-32601, `méthode non gérée : ${method}`);
  }
}

let buffer = '', queue = Promise.resolve(), queued = 0;
const sendFailure = (id, code, message) => send({ jsonrpc: '2.0', id, error: { code, message } });
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  buffer += chunk;
  if (Buffer.byteLength(buffer) > 1024 * 1024) { buffer = ''; sendFailure(null, -32600, 'Request too large'); return; }
  let nl;
  while ((nl = buffer.indexOf('\n')) !== -1) {
    const line = buffer.slice(0, nl).trim(); buffer = buffer.slice(nl + 1);
    if (!line) continue;
    let req;
    try { req = JSON.parse(line); } catch (_) { sendFailure(null, -32700, 'JSON invalide'); continue; }
    if (!req || Array.isArray(req) || req.jsonrpc !== '2.0' || typeof req.method !== 'string') {
      sendFailure(req?.id ?? null, -32600, 'Invalid request'); continue;
    }
    if (req.method === 'notifications/cancelled') {
      if (req.params?.requestId === activeId) activeController?.abort();
      continue;
    }
    if (req.method.startsWith('notifications/')) continue;
    if (req.id === undefined || !(typeof req.id === 'string' || Number.isFinite(req.id))) {
      sendFailure(null, -32600, 'Request id required'); continue;
    }
    if (queued >= 32) { sendFailure(req.id, -32000, 'Queue full'); continue; }
    queued++;
    queue = queue.then(async () => {
      if (shuttingDown) { queued--; return; }
      activeId = req.id; activeController = new AbortController();
      try { await handle(req); } catch (err) { sendFailure(req.id, -32603, err.message); }
      finally { activeId = null; activeController = null; queued--; }
    });
  }
});
process.stdin.on('end', () => { shuttingDown = true; activeController?.abort(); queue.finally(() => process.exit(0)); });
for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => { shuttingDown = true; activeController?.abort(); process.stdin.pause(); queue.finally(() => process.exit(0)); });
}
log(`ready — X11 display ${DISPLAY}`);
