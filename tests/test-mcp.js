#!/usr/bin/env node
/*
 * Test du serveur MCP computer use : poignée de main, catalogue d'outils,
 * et exécution réelle des outils si un serveur X est disponible.
 * Sans X, on vérifie que les erreurs remontent proprement (isError) au lieu
 * de faire tomber le transport — c'est ce qui compte pour l'agent.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SERVER = path.join(__dirname, '..', 'mcp-computer-use', 'server.js');
let pass = 0, fail = 0;
const check = (label, ok, detail) => {
  console.log(`  ${ok ? 'OK ' : 'KO '} ${label}${detail ? ' — ' + detail : ''}`);
  ok ? pass++ : fail++;
};

(async () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'ghostboard-workspace-'));
  const stopFile = path.join(workspace, '.agent-stop');
  fs.writeFileSync(path.join(workspace, 'README.txt'), 'workspace ready\n');
  const srv = spawn('node', [SERVER], { stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, GHOSTBOARD_WORKSPACE: workspace, GHOSTBOARD_STOP_FILE: stopFile } });
  srv.stderr.on('data', d => process.stderr.write('    [srv] ' + d));

  const pending = new Map();
  let buf = '';
  srv.stdout.on('data', (d) => {
    buf += d;
    let nl;
    while ((nl = buf.indexOf('\n')) !== -1) {
      const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
      if (!line) continue;
      const msg = JSON.parse(line);
      const r = pending.get(msg.id);
      if (r) { pending.delete(msg.id); r(msg); }
    }
  });

  let seq = 0;
  const call = (method, params) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, resolve);
    srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    setTimeout(() => reject(new Error(`délai dépassé : ${method}`)), 20000);
  });

  console.log('MCP computer use — protocole');
  const init = await call('initialize', {
    protocolVersion: '2025-06-18', capabilities: {},
    clientInfo: { name: 'test', version: '0' },
  });
  check('initialize répond', !!init.result);
  check('version de protocole négociée', init.result.protocolVersion === '2025-06-18',
        init.result.protocolVersion);
  check('capability tools annoncée', !!(init.result.capabilities || {}).tools);
  check('serverInfo présent', init.result.serverInfo.name === 'ghostboard-computer-use');

  srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  check('notification sans réponse (pas de blocage)', true);

  const list = await call('tools/list', {});
  const names = list.result.tools.map(t => t.name).sort();
  console.log('\nMCP computer use — catalogue');
  for (const required of ['screenshot', 'click', 'type', 'key', 'workspace_read', 'workspace_write', 'workspace_exec']) {
    check(`outil « ${required} » exposé`, names.includes(required));
  }
  check('schémas d\'entrée complets',
        list.result.tools.every(t => t.inputSchema && t.inputSchema.type === 'object'));
  check('descriptions non vides',
        list.result.tools.every(t => t.description && t.description.length > 30));
  console.log('    outils : ' + names.join(', '));

  console.log('\nMCP computer use — robustesse');
  const bad = await call('tools/call', { name: 'nexistepas', arguments: {} });
  check('outil inconnu -> erreur JSON-RPC', !!bad.error, bad.error && bad.error.message);

  const badKey = await call('tools/call', { name: 'key', arguments: { keys: 'rm -rf /' } });
  check('combinaison de touches invalide rejetée',
        badKey.result && badKey.result.isError === true);

  const noArgs = await call('tools/call', { name: 'click', arguments: { x: 'abc', y: 2 } });
  check('coordonnées non numériques rejetées',
        noArgs.result && noArgs.result.isError === true);

  console.log('\nMCP computer use — hôte développeur');
  const read = await call('tools/call', { name: 'workspace_read', arguments: { path: 'README.txt' } });
  check('lecture du dépôt distant', read.result.content[0].text === 'workspace ready\n');
  const write = await call('tools/call', { name: 'workspace_write', arguments: { path: 'runtime/generated.txt', content: 'written remotely\n' } });
  check('écriture atomique dans le dépôt', !write.result.isError && fs.readFileSync(path.join(workspace, 'runtime/generated.txt'), 'utf8') === 'written remotely\n');
  const overwrite = await call('tools/call', { name: 'workspace_write', arguments: { path: 'runtime/generated.txt', content: 'updated remotely\n' } });
  check('remplacement atomique dans le dépôt', !overwrite.result.isError && fs.readFileSync(path.join(workspace, 'runtime/generated.txt'), 'utf8') === 'updated remotely\n');
  const escape = await call('tools/call', { name: 'workspace_read', arguments: { path: '../outside' } });
  check('sortie du dépôt refusée', escape.result.isError === true);
  const directGit = await call('tools/call', { name: 'workspace_read', arguments: { path: '.git/config' } });
  check('accès direct à .git refusé', directGit.result.isError === true);
  const exec = await call('tools/call', { name: 'workspace_exec', arguments: { command: 'node', args: ['-e', 'process.stdout.write(process.cwd())'] } });
  check('commande de développement exécutée dans le dépôt', !exec.result.isError && path.resolve(exec.result.content[0].text) === path.resolve(workspace));
  const deniedCommand = await call('tools/call', { name: 'workspace_exec', arguments: { command: 'powershell', args: [] } });
  check('commande hors liste refusée', deniedCommand.result.isError === true);
  fs.writeFileSync(stopFile, 'stop');
  const stoppedWrite = await call('tools/call', { name: 'workspace_write', arguments: { path: 'blocked.txt', content: 'bad' } });
  check('STOP bloque aussi les modifications distantes', stoppedWrite.result.isError === true && !fs.existsSync(path.join(workspace, 'blocked.txt')));
  fs.unlinkSync(stopFile);

  const hasX = !!process.env.DISPLAY;
  console.log(`\nMCP computer use — outils réels (DISPLAY=${process.env.DISPLAY || 'aucun'})`);
  const info = await call('tools/call', { name: 'screen_info', arguments: {} });
  if (hasX) {
    check('screen_info renvoie une géométrie', !info.result.isError,
          info.result.content[0].text.replace(/\s+/g, ' ').slice(0, 90));
  } else {
    check('sans X : erreur remontée proprement, transport intact',
          info.result.isError === true);
  }

  const shot = await call('tools/call', { name: 'screenshot', arguments: {} });
  if (hasX) {
    const img = shot.result.content.find(c => c.type === 'image');
    check('screenshot renvoie une image PNG', !!img && img.mimeType === 'image/png',
          img ? Math.round(img.data.length * 3 / 4 / 1024) + ' Ko' : '');
    check('PNG valide (signature)', !!img &&
          Buffer.from(img.data.slice(0, 12), 'base64').slice(0, 8)
            .equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])));
  } else {
    check('sans X : screenshot échoue sans casser le serveur', shot.result.isError === true);
  }

  if (hasX) {
    const clk = await call('tools/call', { name: 'click', arguments: { x: 5, y: 5 } });
    check('click exécuté', !clk.result.isError, clk.result.content[0].text);
    const oob = await call('tools/call', { name: 'click', arguments: { x: 99999, y: 5 } });
    check('clic hors écran refusé', oob.result.isError === true);
    const typ = await call('tools/call', { name: 'type', arguments: { text: 'ghostboard' } });
    check('type exécuté', !typ.result.isError, typ.result.content[0].text);
    const key = await call('tools/call', { name: 'key', arguments: { keys: ['ctrl+a', 'Escape'] } });
    check('key exécuté', !key.result.isError, key.result.content[0].text);
  }

  const ping = await call('ping', {});
  check('ping après erreurs -> serveur toujours vivant', !!ping.result);

  srv.stdin.end();
  fs.rmSync(workspace, { recursive: true, force: true });
  console.log(`\n${fail ? 'ÉCHEC' : 'SUCCÈS'} : ${pass} test(s) réussi(s), ${fail} échec(s)`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('ERREUR :', e.message); process.exit(1); });
