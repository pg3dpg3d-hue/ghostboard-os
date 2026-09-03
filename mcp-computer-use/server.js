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
 *    GHOSTBOARD_MCP_MAX_WIDTH réduction au-delà de cette largeur (défaut 0 = off)
 * ============================================================================
 */
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const DISPLAY = process.env.GHOSTBOARD_MCP_DISPLAY || ':0';
const MAX_WIDTH = parseInt(process.env.GHOSTBOARD_MCP_MAX_WIDTH || '0', 10);
const EXEC_TIMEOUT = 15000;

const SERVER_INFO = { name: 'ghostboard-computer-use', version: '1.0.0' };
const SUPPORTED_PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05'];

// stdout est réservé au protocole. Tout le reste part sur stderr.
const log = (...a) => process.stderr.write('[ghostboard-mcp] ' + a.join(' ') + '\n');

// ---------------------------------------------------------------------------
//  Exécution
// ---------------------------------------------------------------------------
function run(cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, {
    env: { ...process.env, DISPLAY },
    timeout: EXEC_TIMEOUT,
    maxBuffer: 64 * 1024 * 1024,
    ...opts,
  });
  if (res.error) {
    if (res.error.code === 'ENOENT') throw new Error(`${cmd} n'est pas installé`);
    throw res.error;
  }
  if (res.status !== 0) {
    const err = (res.stderr || '').toString().trim();
    throw new Error(`${cmd} a échoué (code ${res.status})${err ? ' : ' + err : ''}`);
  }
  return res;
}

const has = (cmd) =>
  spawnSync('sh', ['-c', `command -v ${cmd}`], { timeout: 4000 }).status === 0;

// ---------------------------------------------------------------------------
//  Écran
// ---------------------------------------------------------------------------
let screenCache = null;
function screenSize() {
  if (screenCache) return screenCache;
  // xdotool est déjà requis pour agir : autant l'utiliser pour mesurer.
  const out = run('xdotool', ['getdisplaygeometry']).stdout.toString().trim();
  const [w, h] = out.split(/\s+/).map(Number);
  if (!w || !h) throw new Error(`géométrie illisible : "${out}"`);
  screenCache = { width: w, height: h };
  return screenCache;
}

/**
 * Capture d'écran -> PNG.
 * Chaîne de repli : scrot (installé par défaut, ~1 Mo de dépendances) puis
 * maim, import (ImageMagick) et ffmpeg si l'un d'eux traîne déjà sur la machine.
 */
function capture(region) {
  const tmp = path.join(os.tmpdir(), `gb-shot-${process.pid}-${Date.now()}.png`);
  const cleanup = () => { try { fs.unlinkSync(tmp); } catch (_) {} };

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
    throw new Error("aucun outil de capture trouvé — installer scrot (`apt install scrot`)");
  }

  let lastErr;
  for (const [cmd, args] of attempts) {
    try {
      run(cmd, args);
      if (fs.existsSync(tmp) && fs.statSync(tmp).size > 0) {
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
    handler(args) {
      const png = capture(args.region);
      const { width, height } = screenSize();
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
    handler(args) {
      const { width, height } = screenSize();
      const x = Math.round(args.x), y = Math.round(args.y);
      // Un clic hors écran ne déclenche rien et laisse l'agent croire qu'il a
      // agi : mieux vaut une erreur explicite.
      if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('coordonnées invalides');
      if (x < 0 || y < 0 || x >= width || y >= height) {
        throw new Error(`(${x},${y}) est hors de l'écran ${width}x${height}`);
      }
      const button = BUTTONS[args.button || 'left'];
      if (!button) throw new Error(`bouton inconnu : ${args.button}`);
      const count = Math.max(1, Math.min(3, args.count || 1));
      run('xdotool', ['mousemove', '--sync', String(x), String(y),
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
    handler(args) {
      if (typeof args.text !== 'string') throw new Error('`text` doit être une chaîne');
      if (args.text.length === 0) return { content: [{ type: 'text', text: 'Rien à taper.' }] };
      if (args.text.length > 8192) throw new Error('texte trop long (max 8192 caractères)');
      const delay = Math.max(0, Math.min(500, args.delay_ms ?? 12));
      // `--` sépare les options du texte : sans lui, un texte commençant par
      // un tiret serait interprété comme une option de xdotool.
      run('xdotool', ['type', '--clearmodifiers', '--delay', String(delay), '--', args.text]);
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
    handler(args) {
      const list = Array.isArray(args.keys) ? args.keys : [args.keys];
      if (list.length === 0) throw new Error('aucune touche fournie');
      if (list.length > 32) throw new Error('trop de combinaisons en un appel (max 32)');
      for (const k of list) {
        if (typeof k !== 'string' || !/^[A-Za-z0-9_+]+$/.test(k)) {
          throw new Error(`combinaison invalide : ${JSON.stringify(k)}`);
        }
      }
      run('xdotool', ['key', '--clearmodifiers', ...list]);
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
    handler(args) {
      const wheel = { up: '4', down: '5', left: '6', right: '7' };
      const b = wheel[args.direction || 'down'];
      if (!b) throw new Error(`direction inconnue : ${args.direction}`);
      const n = Math.max(1, Math.min(25, args.amount || 3));
      run('xdotool', ['mousemove', '--sync', String(Math.round(args.x)), String(Math.round(args.y)),
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
    handler() {
      const { width, height } = screenSize();
      let pointer = 'inconnue';
      try {
        const out = run('xdotool', ['getmouselocation', '--shell']).stdout.toString();
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

// ---------------------------------------------------------------------------
//  JSON-RPC 2.0 sur stdio
// ---------------------------------------------------------------------------
function send(msg) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

function handle(req) {
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
          + "Les coordonnées sont en pixels écran, origine en haut à gauche.",
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
      const tool = TOOLS[name];
      if (!tool) return fail(-32602, `outil inconnu : ${name}`);
      try {
        return reply(tool.handler(params.arguments || {}));
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

let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buffer += chunk;
  let nl;
  while ((nl = buffer.indexOf('\n')) !== -1) {
    const line = buffer.slice(0, nl).trim();
    buffer = buffer.slice(nl + 1);
    if (!line) continue;
    let req;
    try {
      req = JSON.parse(line);
    } catch (e) {
      send({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'JSON invalide' } });
      continue;
    }
    try {
      handle(req);
    } catch (err) {
      log('erreur interne :', err.message);
      if (req && req.id !== undefined) {
        send({ jsonrpc: '2.0', id: req.id, error: { code: -32603, message: err.message } });
      }
    }
  }
});
process.stdin.on('end', () => process.exit(0));
log(`prêt — écran ${DISPLAY}` + (MAX_WIDTH ? `, largeur max ${MAX_WIDTH}` : ''));
