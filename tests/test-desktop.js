// Test fonctionnel du bureau de démonstration produit par
// tools/build-os-preview.py : terminal, console série simulée, palette de
// commandes, bureaux virtuels, fenêtres.
//
// Ce n'est PAS un test de rendu : on vérifie que ça RÉPOND, pas que c'est joli.
//
// Il a besoin d'un navigateur. Sans playwright-core ni Chromium, il se déclare
// « sauté » et sort en 0 — un test d'interface ne doit pas faire échouer la
// suite sur une machine qui n'a pas de navigateur, comme le deck lui-même.
//
//   node tests/test-desktop.js [page.html]
//
// Variables : PLAYWRIGHT_CHROMIUM (chemin du binaire)
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

let chromium;
try {
  ({ chromium } = require('playwright-core'));
} catch (e) {
  console.log('  -- sauté : playwright-core absent (test d\'interface facultatif)');
  process.exit(0);
}

function findChromium() {
  if (process.env.PLAYWRIGHT_CHROMIUM) return process.env.PLAYWRIGHT_CHROMIUM;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
  try {
    for (const d of fs.readdirSync(root)) {
      if (!d.startsWith('chromium-')) continue;
      const p = path.join(root, d, 'chrome-linux', 'chrome');
      if (fs.existsSync(p)) return p;
    }
  } catch (e) { /* rien */ }
  return null;
}

const EXE = findChromium();
if (!EXE) {
  console.log('  -- sauté : aucun Chromium trouvé (test d\'interface facultatif)');
  process.exit(0);
}

// La page est construite à la volée : le test porte sur le GÉNÉRATEUR, pas sur
// un fichier figé qui pourrait dater.
let PAGE = process.argv[2];
if (!PAGE) {
  PAGE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'gb-desk-')), 'os.html');
  execFileSync('python3', [path.join(__dirname, '..', 'tools', 'build-os-preview.py'), PAGE],
               { stdio: 'ignore' });
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 900 } });
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('console', m => { if (m.type() === 'error' && !/ERR_CONNECTION/.test(m.text())) errs.push(m.text()); });
  await page.goto('file://' + PAGE, { waitUntil: 'load' });
  await page.waitForTimeout(500);

  let pass = 0, fail = 0;
  const ck = async (label, fn) => {
    try { const r = await fn(); if (r) { console.log('  OK  ' + label); pass++; }
          else { console.log('  KO  ' + label); fail++; } }
    catch (e) { console.log('  KO  ' + label + ' — ' + e.message); fail++; }
  };

  console.log('Bureau de démonstration — terminal');
  await ck('terminal ouvert au repos', async () =>
    (await page.locator('.win').count()) === 1);
  const input = page.locator('.term-in input').first();
  await input.click(); await input.fill('help'); await input.press('Enter');
  await page.waitForTimeout(120);
  await ck('« help » répond', async () =>
    (await page.locator('.term-line').allTextContents()).join(' ').includes('ghost-status'));
  await input.fill('ghost-perf'); await input.press('Enter');
  await page.waitForTimeout(120);
  await ck('« ghost-perf » affiche l\'audit', async () =>
    (await page.locator('.term-line').allTextContents()).join(' ').includes('audit de performance'));
  await input.fill('nawak'); await input.press('Enter');
  await page.waitForTimeout(120);
  await ck('commande inconnue -> erreur explicite', async () =>
    (await page.locator('.term-line').allTextContents()).join(' ').includes('commande introuvable'));

  console.log('\nBureau de démonstration — console série simulée');
  await input.fill('ghost-bruce console'); await input.press('Enter');
  await page.waitForTimeout(150);
  await ck('la console annonce que la carte est simulée', async () =>
    (await page.locator('.term-line').allTextContents()).join(' ').includes('SIMULÉE'));
  await ck('l\'invite passe à ⟩', async () =>
    (await page.locator('.term-in .ps').first().textContent()) === '⟩');
  await input.fill('scan'); await input.press('Enter');
  await page.waitForTimeout(120);
  await ck('« scan » répond', async () =>
    (await page.locator('.term-line').allTextContents()).join(' ').includes('networks'));
  await input.fill('exit'); await input.press('Enter');
  await page.waitForTimeout(120);
  await ck('« exit » revient au shell', async () =>
    (await page.locator('.term-in .ps').first().textContent()) === '$');

  console.log('\nBureau de démonstration — palette de commandes');
  await page.click('#palbtn');
  await page.waitForTimeout(150);
  await ck('la palette s\'ouvre', async () => await page.locator('#palette.open').isVisible());
  await page.fill('#pal-input', 'brc');
  await page.waitForTimeout(120);
  await ck('filtrage flou : « brc » trouve la carte', async () => {
    const t = await page.locator('.pal-item').allTextContents();
    return t.length > 0 && t.join(' ').toLowerCase().includes('bruce');
  });
  await page.fill('#pal-input', 'zzzz');
  await page.waitForTimeout(100);
  await ck('aucun résultat -> message clair', async () =>
    await page.locator('.pal-none').isVisible());
  await page.fill('#pal-input', 'statu');
  await page.waitForTimeout(100);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(200);
  await ck('Entrée lance l\'entrée sélectionnée', async () =>
    (await page.locator('.win').count()) >= 1 && !(await page.locator('#palette.open').isVisible()));

  console.log('\nBureau de démonstration — bureaux virtuels');
  await ck('4 pastilles de bureau', async () => (await page.locator('.pg').count()) === 4);
  const before = await page.locator('.win:visible').count();
  await page.locator('.pg').nth(2).click();
  await page.waitForTimeout(150);
  await ck('bascule sur le bureau 3', async () =>
    await page.locator('.pg').nth(2).evaluate(n => n.classList.contains('on')));
  await ck('les fenêtres du bureau 1 sont masquées', async () =>
    await page.locator('.win').first().evaluate(n => n.style.visibility === 'hidden'));
  await page.locator('.pg').nth(0).click();
  await page.waitForTimeout(150);
  await ck('retour au bureau 1 : les fenêtres reviennent', async () =>
    await page.locator('.win').first().evaluate(n => n.style.visibility !== 'hidden'));

  console.log('\nBureau de démonstration — fenêtres');
  // Les fenêtres se superposent exactement (plein écran moins la barre) :
  // viser .first() fait cliquer sur celle du DESSUS. On prend la dernière
  // ajoutée, qui est au premier plan.
  const win = page.locator('.win').last();
  const x0 = await win.evaluate(n => n.offsetLeft);
  const bar = win.locator('.win-title');
  const box = await bar.boundingBox();
  await page.mouse.move(box.x + 40, box.y + 8);
  await page.mouse.down();
  await page.mouse.move(box.x + 140, box.y + 48, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(120);
  const x1 = await win.evaluate(n => n.offsetLeft);
  await ck('la fenêtre se déplace par sa barre de titre', () => Math.abs(x1 - x0) > 30);
  await win.locator('.win-btns .min').click();
  await page.waitForTimeout(120);
  await ck('réduire cache la fenêtre', async () => await win.evaluate(n => n.style.display === 'none'));
  // Cliquer le bouton de CETTE fenêtre, pas le premier de la barre : sur le
  // premier, qui est la fenêtre active, un clic réduit au lieu de restaurer.
  const winTitle = await win.locator('.win-title span').textContent();
  await page.locator('#tasks .tb-btn', { hasText: winTitle }).first().click();
  await page.waitForTimeout(120);
  await ck('le bouton de tâche la restaure', async () => await win.evaluate(n => n.style.display !== 'none'));
  await win.locator('.win-btns .close').click();
  await page.waitForTimeout(120);
  await ck('fermer retire la fenêtre', async () => (await page.locator('.win').count()) < 3);

  console.log('\n' + (errs.length ? '  KO  erreurs JS : ' + errs.slice(0,3).join(' | ')
                                  : '  OK  aucune erreur JavaScript'));
  if (errs.length) fail++; else pass++;
  console.log('\n' + (fail ? 'ÉCHEC' : 'SUCCÈS') + ` : ${pass} réussi(s), ${fail} échec(s)`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
