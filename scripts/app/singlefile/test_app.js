#!/usr/bin/env node
/* AUGURY single-file app — core lookup checks, run outside a browser.
 *
 * The app's search/lookup half is deliberately DOM-free, so the same code that
 * ships inside augury.html can be exercised here against the embedded database.
 *
 *   node scripts/app/singlefile/test_app.js [path/to/augury.html]
 */
'use strict';

const fs = require('fs');
const path = require('path');

const htmlPath = process.argv[2] || path.join(__dirname, '..', '..', '..', 'augury.html');
const appPath = path.join(__dirname, 'app.js');

let pass = 0, fail = 0;
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  \u2713 ' + name); }
  else { fail++; console.log('  \u2717 ' + name + (detail ? '  \u2014 ' + detail : '')); }
}

const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script id="augury-db" type="application\/json">([\s\S]*?)<\/script>/);
if (!m) { console.error('no embedded database found in ' + htmlPath); process.exit(2); }
const data = JSON.parse(m[1].replace(/<\\\//g, '</'));

const AUGURY = require(appPath);
const store = new AUGURY.Store(data);

console.log('AUGURY core checks \u2014 ' + path.basename(htmlPath) +
  ' (' + data.species.length + ' species, built ' + data.meta.build_date + ')\n');

function key(q) { const r = store.resolveQuery(q, null); return r ? r.key : null; }
function name(q) { const sp = store.speciesFor(key(q)); return sp ? (sp.n && sp.n[0]) || sp.s : null; }

console.log('name resolution');
ok('common name "dandelion"', key('dandelion') === 'taraxacum officinale', String(key('dandelion')));
ok('scientific name "Taraxacum officinale"', key('Taraxacum officinale') === 'taraxacum officinale');
ok('scientific name, lowercase', key('taraxacum officinale') === 'taraxacum officinale');
ok('common name "serrated tussock"', key('serrated tussock') === 'nassella trichotoma', String(key('serrated tussock')));
ok('common name "capeweed"', key('capeweed') === 'arctotheca calendula', String(key('capeweed')));
ok('common name "bathurst burr"', key('bathurst burr') === 'xanthium spinosum', String(key('bathurst burr')));
ok('plural stem "docks" resolves', !!key('docks'), String(key('docks')));
ok('"thistles" resolves to a genus bucket', !!key('thistles'), String(key('thistles')));
ok('misspelling "dandilion" does NOT resolve silently (deterministic path)',
  key('dandilion') === null, String(key('dandilion')));
ok('…but "did you mean" offers the right species',
  store.didYouMean('dandilion', 4).some(d => d.key === 'taraxacum officinale'),
  JSON.stringify(store.didYouMean('dandilion', 4).map(d => d.key)));
ok('"did you mean" never offers a junk/pseudo-species',
  store.didYouMean('dandelion clay', 4).every(d => d.key !== 'dandelion clay'));
ok('nonsense "zzzqqq" resolves to nothing', key('zzzqqq') === null, String(key('zzzqqq')));

console.log('\nindicator lookup');
const dan = store.resolveQuery('dandelion', null);
ok('dandelion returns indicators', !!(dan && Object.keys(dan.indicators).length));
ok('auto region prefers Australia when present', dan.region === 'Australia', dan.region);
ok('no fallback when the requested region has data',
  store.resolveQuery('dandelion', 'Australia').regionFallback === false);
const eu = store.resolveQuery('geranium phaeum', 'Australia');
ok('Europe-only species falls back and says so', eu.regionFallback === true && eu.region === 'Europe',
  eu ? eu.region + ' fallback=' + eu.regionFallback : 'null');
const eu2 = store.resolveQuery('geranium phaeum', 'Europe');
ok('same species with Europe requested is not a fallback', eu2.regionFallback === false);

console.log('\nsource references');
function refsFor(sp, region, k) {
  const out = [], seen = {};
  (sp.p && sp.p.s || []).forEach(s => { if ((s.f || []).indexOf(k) >= 0 && !seen[s.n]) { seen[s.n] = 1; out.push(s.n); } });
  const byKey = (sp._src && sp._src[region]) || {};
  (byKey[k] || []).forEach(s => { if (!seen[s]) { seen[s] = 1; out.push(s); } });
  return out;
}
const box = store.speciesFor('lycium ferocissimum');
const boxRefs = refsFor(box, 'Australia', 'Soil type');
ok('African boxthorn carries recorded source names for "Soil type"', boxRefs.length >= 2, boxRefs.join(', '));
ok('recorded provenance has URLs',
  (box.p.s || []).some(s => /^https?:/.test(s.u || '')), JSON.stringify((box.p.s || []).map(s => s.u)));
const detected = store.speciesFor('echinochloa crus-galli');
ok('inline-detected sources survive into the payload',
  data.species.some(s => (s.r || []).some(r => Object.keys(r.src || {}).length)));
ok('inline sources are attached to the data point that names them, not the region',
  data.species.every(s => (s.r || []).every(r =>
    Object.keys(r.src || {}).every(k => Object.prototype.hasOwnProperty.call(r.i, k)))));
ok('a source registry with URLs is present',
  Object.values(data.sources).some(s => /^https?:/.test(s.u || '')));

console.log('\npayload integrity');
ok('meta.species_count matches the array', data.meta.species_count === data.species.length);
ok('every record has a key and scientific name',
  data.species.every(s => typeof s.k === 'string' && typeof s.s === 'string'));
ok('every region row has indicators', data.species.every(s => (s.r || []).every(r => Object.keys(r.i || {}).length > 0)));
ok('lineage is declared for all three regions',
  ['Australia', 'UK', 'Europe'].every(r => data.lineage[r] && data.lineage[r].note));
ok('junk keys are exported for the specificity rule', Array.isArray(data.junk) && data.junk.length > 0);

console.log('\ndisplay names');
const dnOf = k => (store.speciesFor(k) || {})._dn || {};
ok('the vernacular leads, not the binomial',
  dnOf('nassella trichotoma').main === 'Serrated tussock', dnOf('nassella trichotoma').main);
ok('a synonym-supplied name is shown', dnOf('lolium rigidum').main === 'Annual ryegrass',
  dnOf('lolium rigidum').main);
ok('"Spear thistle (Cirsium vulgare)" loses the repeated binomial',
  dnOf('cirsium vulgare').main === 'Spear thistle', dnOf('cirsium vulgare').main);
ok('a genus bucket keeps its own identity',
  dnOf('cirsium spp').main === 'Thistles' && dnOf('cirsium spp').sci === 'Cirsium spp',
  JSON.stringify(dnOf('cirsium spp')));
ok('a species with no vernacular falls back to the binomial',
  dnOf('geranium phaeum').main === 'Geranium phaeum', dnOf('geranium phaeum').main);

console.log('\nrender layer');
function fakeDoc() {
  const nodes = {};
  return {
    nodes,
    getElementById(id) {
      if (!nodes[id]) {
        const node = {
          id, innerHTML: '', className: '', value: '', attrs: {},
          addEventListener() {},
          setAttribute(k, v) { this.attrs[k] = String(v); },
          getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
        };
        nodes[id] = node;
      }
      return nodes[id];
    },
    querySelectorAll() { return []; },
    addEventListener() {}
  };
}
const doc = fakeDoc();
const app = new AUGURY.App(data, doc);
const out = () => doc.getElementById('answer').innerHTML;

app.render('dandelion');
let markup = out();
ok('renders the species name', /Dandelion/.test(markup));
ok('renders a soil-reading card', /What it indicates/.test(markup));
ok('renders an Evidence control per data point', (markup.match(/class="ev-btn"/g) || []).length >= 3);
ok('renders a "Where this came from" section', /Where this came from/.test(markup));
ok('states the database identity (sha256)', markup.indexOf(data.meta.db_sha256.slice(0, 12)) >= 0);
ok('shows the region it served', /Australia data/.test(markup));

app.region = 'Australia';
app.render('lycium ferocissimum');
markup = out();
ok('recorded provenance renders a real link', /<a class="refchip" href="https:\/\//.test(markup));
ok('provenance lists "read for" mapping', /Read for:/.test(markup));
ok('boxthorn evidence is quoted verbatim', markup.indexOf('drought tolerant') >= 0);

app.region = 'Australia';
app.render('geranium phaeum');
markup = out();
ok('Europe-only species shows a region-fallback warning', /Region fallback/.test(markup));
ok('fallback notice is explicit about provenance of the fallback', /not recorded for Australia/.test(markup));

app.region = '';
app.render('thistles');
markup = out();
ok('genus bucket is disclosed', /Genus-level match/.test(markup));

app.render('dandelion and thistles');
markup = out();
ok('multi-name query renders independent readings', (markup.match(/class="card hero"/g) || []).length >= 2);

app.render('zzzqqq');
markup = out();
ok('unknown name renders the not-found card', /No match for/.test(markup));

app.render('<img src=x onerror=alert(1)>');
markup = out();
ok('user input is HTML-escaped', markup.indexOf('<img src=x') < 0 && markup.indexOf('&lt;img') >= 0);

console.log('\nsoftened, human-first wording');
{
  const pages = [];
  const probes = [
    'dandelion', 'thistles', 'dandelion and thistles', 'lycium ferocissimum',
    'geranium phaeum', 'zzzqqq', ''
  ];
  app.region = '';
  for (const p of probes) { app.render(p); pages.push(out()); }
  app.region = 'Australia';
  app.render('geranium phaeum');
  pages.push(out());
  const fallbackPage = pages.length - 1;
  app.region = '';
  app.render('dandelion');
  pages.push(out());
  const regionPage = pages.length - 1;
  const all = pages.join('\n');
  for (const ban of ['No AI', 'no guessing', 'no model', 'no network', 'Offline single file',
                     'Database rows merged', 'not generated']) {
    ok('never says "' + ban + '"', all.toLowerCase().indexOf(ban.toLowerCase()) < 0);
  }
  ok('the empty state invites a name instead of asserting absence',
    /Name a weed, read the soil/.test(pages[probes.length - 1]));
  ok('the hero states the region as data, not as a boast', /Australia data/.test(pages[regionPage]));
  ok('the fallback notice still says the row was not recorded for the asked-for region',
    /not recorded for Australia/.test(pages[fallbackPage]));
}

console.log('\ntechnical details stay available, one level down');
{
  app.region = '';
  app.render('dandelion');
  const markup2 = out();
  ok('the database sha256 is still in the page', markup2.indexOf(data.meta.db_sha256.slice(0, 12)) >= 0);
  ok('it lives inside the collapsible Technical details panel',
    /Technical details/.test(markup2) && /<details class="more">/.test(markup2));
  ok('the reading offers copy, print and jump-to-sources controls',
    /data-act="copy"/.test(markup2) && /data-act="print"/.test(markup2) && /data-act="sources"/.test(markup2));
  app.region = '';
  app.render('lycium ferocissimum');
  const text = app.readingText(app.lastReadings[0]);
  ok('the plain-text reading carries the name, a row and a source',
    /African boxthorn/.test(text) && /Moisture:/.test(text) && /Sources: .+/.test(text), text.slice(0, 160));
  ok('the plain-text reading makes no offline/anti-AI claim',
    !/no model|no network|no ai/i.test(text));
  app.render('dandelion');
  const fallbackText = app.readingText(app.lastReadings[0]);
  ok('a species with no recorded source still names its region lineage',
    /Sources: .+/.test(fallbackText), fallbackText.slice(0, 160));
}

console.log('\nsource list deduplication');
{
  app.region = 'Australia';
  app.render('lycium ferocissimum');
  const markup3 = out();
  const names = (markup3.match(/class="sname">(?:<a[^>]*>)?([^<]+)/g) || [])
    .map(s => s.replace(/.*?>/, '').trim());
  const keys = names.map(n => n.toLowerCase().replace(/[^a-z0-9]+/g, ''));
  ok('the sources card lists each organisation once',
    keys.length === new Set(keys).size, names.join(' | '));
  ok('a lower-grade mention of a recorded source is absorbed, not repeated',
    !keys.includes('nswweedwisenswdpird') && !keys.includes('herbiguideau'),
    names.join(' | '));
  ok('the recorded document keeps its "read for" mapping', /Read for:/.test(markup3));
  ok('each evidence panel lists each source once',
    (() => {
      const rows = markup3.split('<div class="ev-src">').slice(1);
      return rows.every(r => {
        const chips = [...r.split('</div>')[0].matchAll(/class="refchip[^"]*"[^>]*>([^<]+)</g)].map(m => m[1]);
        const ck = chips.map(n => n.toLowerCase().replace(/[^a-z0-9]+/g, ''));
        return ck.length === new Set(ck).size;
      });
    })(), 'duplicate chips inside one evidence panel');
}

console.log('\npicker hygiene');
{
  // A suggestion the app refuses to answer is a trap: "dandelion clay" is a
  // soil-association pseudo-species that bestPlantMatch() rejects, so the picker
  // and the browse list must not offer it.
  const doc2 = fakeDoc();
  const app2 = new AUGURY.App(data, doc2);
  const keysFor = q => {
    app2.suggest(q);
    const html = doc2.getElementById('suggest').innerHTML;
    return [...html.matchAll(/data-key="([^"]+)"/g)].map(m => m[1]);
  };
  const dand = keysFor('dandelion');
  ok('the picker offers the real species first', dand[0] === 'taraxacum officinale', dand.join(', '));
  ok('the picker never offers a pseudo-species', dand.every(k => k !== 'dandelion clay'), dand.join(', '));
  ok('the picker never offers a junk key',
    !keysFor('dandelion clay').some(k => (data.junk || []).includes(k)));
  ok('the picker still returns suggestions', dand.length > 0);
  ok('browse never lists a pseudo-species',
    !app2.browseRows('dandelion').some(sp => sp.k === 'dandelion clay'));
}

console.log('\nbrowse list');
{
  const b = app.browseListHtml('', 40);
  ok('browse renders a bounded page of species', (b.html.match(/class="row"/g) || []).length === 40);
  ok('browse reports the full total, not just the page', b.total > 1000, String(b.total));
  ok('browse offers a "show more" affordance when truncated', /id="bmore"/.test(b.html));
  ok('a filter narrows the list', app.browseListHtml('thistle', 40).total < b.total);
  ok('a filter that matches nothing says so', /No species match/.test(app.browseListHtml('zzzqqq', 40).html));
}

console.log('\nself-consistency sweep');
{
  // The user-visible property is not "the same key" — the canonical map
  // deliberately serves a duplicate key's data through whichever name was asked
  // for — but "the same reading". So each species is looked up by its own key and
  // by the name the picker shows, and the two readings must be identical.
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  let keyHits = 0; const keyMiss = [];
  let nameHits = 0; const nameMiss = [];
  let lookupHits = 0; const lookupMiss = [];
  for (const sp of data.species) {
    if (sp.y === 'junk') continue;
    const byKey = store.bestPlantMatch(sp.k);
    if (byKey) keyHits++; else if (keyMiss.length < 5) keyMiss.push(sp.k);
    const shown = (sp._dn || {}).main || sp.s;
    const byName = store.bestPlantMatch(shown);
    if (byName) nameHits++; else if (nameMiss.length < 5) nameMiss.push(sp.k);
    if ((sp.r || []).length) {
      const viaKey = store.getIndicators(sp.k, null);
      const viaName = byName ? store.getIndicators(byName.key, null) : null;
      if (viaKey && viaName && same(viaKey.indicators, viaName.indicators)
          && viaKey.region === viaName.region) lookupHits++;
      else if (lookupMiss.length < 5) lookupMiss.push(sp.k);
    }
  }
  const real = data.species.filter(s => s.y !== 'junk').length;
  const withRows = data.species.filter(s => s.y !== 'junk' && (s.r || []).length).length;
  ok(`every species key resolves to a species (${keyHits}/${real})`, keyMiss.length === 0, keyMiss.join(', '));
  ok(`every displayed name resolves to a species (${nameHits}/${real})`, nameMiss.length === 0, nameMiss.join(', '));
  ok(`the displayed name gives the same reading as the key (${lookupHits}/${withRows})`,
    lookupMiss.length === 0, lookupMiss.join(', '));
}

console.log('\n' + (fail ? fail + ' FAILED, ' : '') + pass + ' passed');
process.exit(fail ? 1 : 0);
