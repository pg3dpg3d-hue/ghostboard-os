#!/usr/bin/env node
// Tests du vrai transport avec processus X11 simulés ; aucune interaction avec le bureau hôte.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gb-mcp-test-'));
const stop = path.join(root, 'stop');
const stdin = new PassThrough();
let geometry = '800 480', hang = false, typed = '', sequence = 0, passed = 0;
const commands = [], deadlines = [], pending = new Map();
let output = '';
const fakeSpawn = (cmd, args) => {
  commands.push([cmd, args]);
  const c = new EventEmitter();
  c.stdout = new PassThrough(); c.stderr = new PassThrough(); c.stdin = new PassThrough();
  let closed = false;
  c.kill = () => { if (!closed) { closed = true; c.emit('close', null); } };
  c.stdin.on('data', d => { if (args[0] === 'type') typed += d.toString(); });
  c.stdin.on('finish', () => setImmediate(() => {
    if (hang && args[0] === 'type') return;
    if (closed) return;
    if (args[0] === 'getdisplaygeometry') c.stdout.write(geometry);
    if (args[0] === 'getmouselocation') c.stdout.write('X=12\nY=14\n');
    if (cmd === 'wmctrl' && args[0] === '-l') c.stdout.write('0x1234 0 host Editor\n');
    if (cmd === 'scrot') fs.writeFileSync(args.at(-1), Buffer.from('89504e470d0a1a0a', 'hex'));
    closed = true; c.emit('close', 0);
  }));
  return c;
};
const mockProcess = {
  on() {},
  env: { GHOSTBOARD_STOP_FILE: stop, DISPLAY: ':77' }, stdin,
  stdout: { write(s) {
    output += s;
    let i;
    while ((i = output.indexOf('\n')) >= 0) {
      const msg = JSON.parse(output.slice(0, i)); output = output.slice(i + 1);
      if (pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    }
  } }, stderr: { write() {} }, exit() {},
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../mcp-computer-use/server.js'), 'utf8'), {
  require(name) { return name === 'child_process' ? { spawn: fakeSpawn, spawnSync: () => ({ status: 0 }) } : require(name); },
  process: mockProcess, Buffer, AbortController,
  setTimeout(fn, ms) { deadlines.push(ms); return setTimeout(fn, ms); },
  clearTimeout, setInterval, clearInterval,
});
function request(method, params = {}) {
  const id = ++sequence;
  const promise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Test timeout: ' + method)), 4000);
    pending.set(id, msg => { clearTimeout(timer); resolve(msg); });
  });
  stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
  return { id, promise };
}
const call = (name, args) => request('tools/call', { name, arguments: args }).promise;
const check = (name, fn) => { fn(); passed++; console.log('OK ' + name); };
(async () => {
  try {
    let r = await call('screen_info', {});
    check('Uses the actual DISPLAY', () => assert.equal(JSON.parse(r.result.content[0].text).display, ':77'));
    geometry = '1280 800';
    r = await call('click', { x: 1200, y: 700 });
    check('Resolution changes are observed', () => assert.ok(!r.result.isError));
    r = await call('click', { x: 1.1, y: 2 });
    check('Fractional clicks refused', () => assert.equal(r.result.isError, true));
    r = await call('scroll', { x: -1, y: 2 });
    check('Off-screen scrolling refused', () => assert.equal(r.result.isError, true));
    r = await call('screenshot', { region: { x: 1200, y: 700, width: 100, height: 200 } });
    check('Out-of-bounds crop refused', () => assert.equal(r.result.isError, true));
    r = await call('type', { text: '--literal secret é'.repeat(150), delay_ms: 12 });
    check('Long typing exceeds old 15-second timeout', () => { assert.ok(!r.result.isError); assert.ok(deadlines.some(d => d > 15000)); });
    check('Text travels on stdin, not command arguments', () => { assert.ok(typed.includes('--literal secret é')); assert.ok(!commands.some(c => c[1].some(a => a.includes('secret')))); });
    r = await call('type', { text: 'a'.repeat(8192), delay_ms: 500 });
    check('Excessive typing duration rejected', () => assert.equal(r.result.isError, true));
    hang = true;
    const req = request('tools/call', { name: 'type', arguments: { text: 'pending' } });
    await new Promise(resolve => setTimeout(resolve, 20));
    stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/cancelled', params: { requestId: req.id } }) + '\n');
    r = await req.promise;
    check('Cancellation interrupts an active process', () => assert.equal(r.result.isError, true));
    const next = request('tools/call', { name: 'type', arguments: { text: 'pending' } });
    await new Promise(resolve => setTimeout(resolve, 20));
    fs.writeFileSync(stop, 'stop');
    r = await next.promise;
    check('Shared STOP interrupts an active process', () => assert.equal(r.result.isError, true));
    fs.unlinkSync(stop); hang = false;
    r = await call('drag', { x: 10, y: 10, to_x: 50, to_y: 50 });
    check('Drag releases the mouse button', () => { assert.ok(!r.result.isError); assert.deepEqual(Array.from(commands.at(-1)[1]), ['mouseup', '1']); });
    r = await call('focus_window', { id: '--help' });
    check('Window ID cannot become a command option', () => assert.equal(r.result.isError, true));
    r = await call('toString', {});
    check('Prototype methods are not tools', () => assert.equal(r.error.code, -32602));
    r = await request('ping').promise;
    check('Transport survives all failures', () => assert.ok(r.result));
    console.log(passed + ' regression checks passed (simulated X11).');
  } finally {
    stdin.end();
    fs.rmSync(root, { recursive: true, force: true });
  }
})().catch(err => { console.error(err); process.exitCode = 1; });
