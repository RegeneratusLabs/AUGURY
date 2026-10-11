/* AUGURY — single-file app logic.
 *
 * Two halves:
 *   1. A dependency-free port of the deterministic lookup that already ships in
 *      the Android app (SpeciesStore.kt / species_lookup.py): name search,
 *      canonical grouping, region policy. No model, no network, no randomness.
 *   2. The render layer: turns a resolved species into a soil reading whose
 *      every row carries the evidence it was read from and the source it came
 *      from.
 *
 * The core half is DOM-free on purpose, so it can be exercised under node.
 */
(function (root) {
  'use strict';

  /* ===================================================================== *
   * Careful string comparison — CPython difflib.SequenceMatcher.ratio port
   * (isjunk=None, autojunk=True), as used by species_lookup.search().
   * ===================================================================== */

  function sequenceRatio(a, b) {
    var b2j = new Map();
    for (var i = 0; i < b.length; i++) {
      var c = b[i];
      var list = b2j.get(c);
      if (!list) { list = []; b2j.set(c, list); }
      list.push(i);
    }
    if (b.length >= 200) { // autojunk
      var ntest = Math.floor(b.length / 100) + 1;
      b2j.forEach(function (v, k) { if (v.length > ntest) b2j.delete(k); });
    }

    function longestMatch(alo, ahi, blo, bhi) {
      var besti = alo, bestj = blo, bestsize = 0;
      var j2len = new Map();
      for (var i2 = alo; i2 < ahi; i2++) {
        var newj2len = new Map();
        var positions = b2j.get(a[i2]) || [];
        for (var p = 0; p < positions.length; p++) {
          var j = positions[p];
          if (j < blo) continue;
          if (j >= bhi) break;
          var k = (j2len.get(j - 1) || 0) + 1;
          newj2len.set(j, k);
          if (k > bestsize) { besti = i2 - k + 1; bestj = j - k + 1; bestsize = k; }
        }
        j2len = newj2len;
      }
      while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) {
        besti--; bestj--; bestsize++;
      }
      while (besti + bestsize < ahi && bestj + bestsize < bhi &&
             a[besti + bestsize] === b[bestj + bestsize]) bestsize++;
      return [besti, bestj, bestsize];
    }

    var queue = [[0, a.length, 0, b.length]];
    var total = 0;
    while (queue.length) {
      var q = queue.pop();
      var m = longestMatch(q[0], q[1], q[2], q[3]);
      var ii = m[0], jj = m[1], kk = m[2];
      if (kk > 0) {
        total += kk;
        if (q[0] < ii && q[2] < jj) queue.push([q[0], ii, q[2], jj]);
        if (ii + kk < q[1] && jj + kk < q[3]) queue.push([ii + kk, q[1], jj + kk, q[3]]);
      }
    }
    var totalLen = a.length + b.length;
    return totalLen === 0 ? 1 : (2 * total) / totalLen;
  }

  var GENERIC_TOKENS = {};
  ('weed weeds grass grasses thistle thistles dock docks sedge rush rushes clover ' +
   'plant plants common wild native annual perennial black red white yellow blue ' +
   'purple giant creeping spiny prickly slender small large water marsh swamp ' +
   'couch brome fescue sorrel burr bur cress').split(' ').forEach(function (t) {
    GENERIC_TOKENS[t] = 1;
  });

  function contentTokens(text) {
    var out = {};
    var words = String(text || '').toLowerCase().match(/[a-z0-9]+/g) || [];
    for (var i = 0; i < words.length; i++) {
      var w = words[i];
      if (w.length > 2 && !GENERIC_TOKENS[w]) out[w] = 1;
    }
    return out;
  }

  function tokenOverlap(a, b) {
    var ta = contentTokens(a), tb = contentTokens(b);
    var ka = Object.keys(ta), kb = Object.keys(tb);
    if (!ka.length || !kb.length) return 0;
    var hit = 0;
    for (var i = 0; i < ka.length; i++) if (tb[ka[i]]) hit++;
    return hit / Math.max(ka.length, kb.length);
  }

  function round2(x) { return Math.round(x * 100) / 100; }

  var CLAY_PSEUDO = { 'dandelion clay': 1, 'plantains clay': 1, 'goosegrass clay': 1, 'chicory clay': 1 };

  /* ===================================================================== *
   * Store — species index, name resolution, deterministic indicator lookup.
   * ===================================================================== */

  function Store(data) {
    this.data = data;
    this.species = data.species || [];
    this.byKey = new Map();
    this.sciNames = [];      // lowercased, file order
    this.sciToKey = new Map();
    this.commonIdx = new Map();
    this.canonical = new Map();
    var self = this;

    var canon = data.canonical || {};
    Object.keys(canon).forEach(function (k) { self.canonical.set(k, canon[k]); });

    this.species.forEach(function (sp) {
      self.byKey.set(sp.k, sp);
      // region rows -> insertion-ordered lookup maps
      sp._i = {}; sp._src = {}; sp._lin = {};
      (sp.r || []).forEach(function (row) {
        sp._i[row.n] = row.i || {};
        sp._src[row.n] = row.src || {};
        sp._lin[row.n] = row.l || null;
      });
      var sl = String(sp.s || sp.k).toLowerCase();
      self.sciNames.push(sl);
      if (!self.sciToKey.has(sl)) self.sciToKey.set(sl, sp.k);
      (sp.n || []).forEach(function (name) {
        var lower = String(name).toLowerCase();
        if (lower && !self.commonIdx.has(lower)) self.commonIdx.set(lower, sp.k);
      });
    });

    // Curated vernacular synonyms, applied last so they win — and only when the
    // target key actually exists, exactly like species_lookup._load_synonyms.
    var syn = data.synonyms || {};
    Object.keys(syn).forEach(function (name) {
      var key = String(syn[name]).toLowerCase();
      if (!self.byKey.has(key)) return;
      var lower = name.toLowerCase().trim();
      if (!lower || self.commonIdx.has(lower)) return;
      self.commonIdx.set(lower, key);
      var sp = self.byKey.get(key);
      if (!sp.n) sp.n = [];
      if (sp.n.indexOf(name) < 0) sp.n.push(name);
    });

    // Resolve the display name once, after every scientific name is indexed.
    //
    // The rule is stronger than "first vernacular": the name shown must also be
    // a name that resolves *back to this species*. Two database keys can claim
    // the same vernacular ("Great brome" is a common name of both anisantha
    // diandra and bromus diandrus), and the curated synonym map sends it to one
    // of them. Showing the other species' name would mean the picker and the
    // search box disagreed about what the user is reading, so a vernacular that
    // routes elsewhere is refused and the binomial is shown instead.
    this.species.forEach(function (sp) {
      var chosen = null;
      var names = sp.n || [];
      for (var i = 0; i < names.length; i++) {
        var p = self.pretty(names[i], sp.s);
        if (!p) continue;
        var t = titleFirst(p);
        if (self.resolvesTo(t, sp.k)) { chosen = t; break; }
      }
      sp._dn = { main: chosen || sp.s, sci: sp.s };
    });
  }

  /** True when `name` resolves to `key` or to a canonical sibling of it. */
  Store.prototype.resolvesTo = function (name, key) {
    var m = this.bestPlantMatch(name);
    if (!m) return false;
    if (m.key === key) return true;
    return this.canonicalGroup(key).indexOf(m.key) >= 0;
  };

  /** True when `name` is a scientific name the database knows. */
  Store.prototype.isKnownScientific = function (name) {
    return this.sciToKey.has(String(name || '').toLowerCase());
  };

  Store.prototype.pretty = function (common, sci) {
    return prettyCommon(common, sci, this.isKnownScientific.bind(this));
  };

  Store.prototype.classifySpecificity = function (key) {
    var k = String(key || '').trim();
    if (this.data.junk && this.data.junk.indexOf(k.toLowerCase()) >= 0) return 'junk';
    if (/\bspp\.?$/i.test(k)) return 'genus_bucket';
    return 'exact_species';
  };

  Store.prototype.canonicalGroup = function (key) {
    var target = this.canonical.get(key);
    var out = [], self = this;
    if (target !== undefined) {
      out.push(target);
      this.canonical.forEach(function (v, k) { if (v === target) out.push(k); });
    } else {
      out.push(key);
      this.canonical.forEach(function (v, k) { if (v === key) out.push(k); });
    }
    return out;
  };

  Store.prototype.speciesFor = function (key) {
    var k = String(key || '').trim().toLowerCase();
    if (!k) return null;
    if (this.byKey.has(k)) return this.byKey.get(k);
    if (this.sciToKey.has(k)) return this.byKey.get(this.sciToKey.get(k));
    var group = this.canonicalGroup(k);
    for (var i = 0; i < group.length; i++) if (this.byKey.has(group[i])) return this.byKey.get(group[i]);
    return null;
  };

  Store.prototype.mergeIndicators = function (spList, region) {
    var out = {};
    for (var i = 0; i < spList.length; i++) {
      var inds = spList[i]._i[region];
      if (!inds) continue;
      Object.keys(inds).forEach(function (k) {
        var v = inds[k];
        if (v === null || v === undefined || String(v).trim() === '') return;
        if (!(k in out)) out[k] = v;   // canonical-first sibling wins
      });
    }
    return out;
  };

  Store.prototype.mergedCommonNames = function (keys) {
    var out = [], seen = {};
    for (var i = 0; i < keys.length; i++) {
      var sp = this.byKey.get(keys[i]);
      if (!sp) continue;
      (sp.n || []).forEach(function (cn) {
        var lower = String(cn).toLowerCase();
        if (!seen[lower]) { seen[lower] = 1; out.push(cn); }
      });
    }
    return out;
  };

  /**
   * species_lookup.SpeciesDB.get_indicators — region policy is the requested
   * region, then Australia / UK / Europe, then any region that has rows.
   * A region fallback is always reported, never silent.
   */
  Store.prototype.getIndicators = function (name, region) {
    var raw = String(name || '').trim().toLowerCase();
    if (!raw) return null;
    var queried = this.byKey.has(raw) ? raw
      : (this.commonIdx.get(raw) || this.sciToKey.get(raw) || raw);

    var group = this.canonicalGroup(queried);
    var lead = (group.length && this.byKey.has(group[0])) ? group[0] : queried;
    var keys = [lead];
    group.filter(function (k) { return k !== lead; }).sort().forEach(function (k) {
      if (this.byKey.has(k)) keys.push(k);
    }, this);

    var infos = [];
    for (var i = 0; i < keys.length; i++) if (this.byKey.has(keys[i])) infos.push(this.byKey.get(keys[i]));
    if (!infos.length) return null;
    var key = keys[0];
    var mergedFrom = infos.map(function (s) { return s.k; });

    var identity = this.byKey.has(queried) ? queried : key;
    var idInfo = this.byKey.get(identity);

    var order = [];
    if (region) order.push(region);
    ['Australia', 'UK', 'Europe'].forEach(function (r) { if (order.indexOf(r) < 0) order.push(r); });

    var self = this, found = null;
    order.forEach(function (r) {
      if (found) return;
      if (!infos.some(function (s) { return s._i[r]; })) return;
      var inds = self.mergeIndicators(infos, r);
      if (Object.keys(inds).length) found = [r, inds];
    });
    if (!found) {
      var seen = {};
      infos.forEach(function (s) {
        Object.keys(s._i).forEach(function (r) {
          if (seen[r] || found) return;
          seen[r] = 1;
          var inds = self.mergeIndicators(infos, r);
          if (Object.keys(inds).length) found = [r, inds];
        });
      });
    }
    if (!found) return null;

    return {
      key: key,
      // Identity follows what was asked for, not the canonical lead: data
      // merges, identity does not.
      identityKey: identity,
      scientificName: idInfo.s,
      commonNames: this.mergedCommonNames(mergedFrom),
      region: found[0],
      requestedRegion: region || null,
      regionFallback: !!region && found[0] !== region,
      indicators: found[1],
      source: Object.keys(idInfo._src[found[0]] || {}).length
        ? Array.from(new Set([].concat.apply([], Object.keys(idInfo._src[found[0]])
            .map(function (k) { return idInfo._src[found[0]][k]; })))).join(', ')
        : '',
      specificity: this.classifySpecificity(queried),
      mergedFrom: mergedFrom
    };
  };

  /** species_lookup.SpeciesDB.search — six ordered steps, fuzzy last. */
  Store.prototype.search = function (query, limit) {
    limit = limit || 5;
    var q = String(query || '').trim().toLowerCase();
    if (!q) return [];
    var stem = null;
    if (/ies$/.test(q) && q.length > 4) stem = q.slice(0, -3) + 'y';
    else if (/s$/.test(q) && q.length > 3 && !/ss$/.test(q)) stem = q.slice(0, -1);
    var variants = stem ? [q, stem] : [q];

    var results = [], seen = {};
    var self = this;

    function push(sci, names, type, score, key, seenKey) {
      results.push({ scientificName: sci, commonNames: names, matchType: type, score: score, key: key });
      seen[seenKey] = 1;
    }

    // 1. exact scientific name
    if (this.byKey.has(q)) {
      var sp = this.byKey.get(q);
      push(sp.s, sp.n || [], 'exact_scientific', 1, q, q);
    }
    // 2. exact common name
    if (this.commonIdx.has(q)) {
      var k2 = this.commonIdx.get(q);
      if (!seen[k2]) { var s2 = this.byKey.get(k2); push(s2.s, s2.n || [], 'exact_common', 1, k2, k2); }
    }
    // 3. partial scientific name
    if (results.length < limit) {
      for (var v = 0; v < variants.length; v++) {
        var vv = variants[v];
        for (var n = 0; n < this.sciNames.length; n++) {
          var nameLower = this.sciNames[n];
          if (!(nameLower.indexOf(vv) >= 0 || vv.indexOf(nameLower) >= 0)) continue;
          if (seen[nameLower]) continue;
          var key3 = this.sciToKey.get(nameLower);
          if (!key3) continue;
          var s3 = this.byKey.get(key3);
          if (!s3) continue;
          var score3 = Math.min(0.9, 0.6 + (nameLower.length / Math.max(vv.length, 1)) * 0.3);
          push(s3.s, s3.n || [], 'partial_scientific', round2(score3), key3, nameLower);
          if (results.length >= limit) break;
        }
        if (results.length >= limit) break;
      }
    }
    // 4. partial common name (a generic-token-only hit is a false friend)
    if (results.length < limit) {
      var entries = Array.from(this.commonIdx.entries());
      for (var v4 = 0; v4 < variants.length; v4++) {
        var vv4 = variants[v4];
        for (var e4 = 0; e4 < entries.length; e4++) {
          var cnLower = entries[e4][0], key4 = entries[e4][1];
          if (!(cnLower.indexOf(vv4) >= 0 || vv4.indexOf(cnLower) >= 0)) continue;
          if (seen[key4]) continue;
          var qTok = contentTokens(vv4), cTok = contentTokens(cnLower);
          if (!Object.keys(qTok).some(function (t) { return cTok[t]; })) continue;
          var s4 = this.byKey.get(key4);
          if (!s4) continue;
          var score4 = Math.min(0.85, 0.55 + (cnLower.length / Math.max(vv4.length, 1)) * 0.3);
          push(s4.s, s4.n || [], 'partial_common', round2(score4), key4, key4);
          if (results.length >= limit) break;
        }
        if (results.length >= limit) break;
      }
    }
    // 5. fuzzy scientific name (long queries skipped: sentence false positives)
    if (results.length < limit && q.length <= 40) {
      var want = Math.max(limit - results.length, 3);
      var scored = [];
      for (var f = 0; f < this.sciNames.length; f++) {
        var r = sequenceRatio(this.sciNames[f], q);
        if (r >= 0.6) scored.push([r, this.sciNames[f]]);
      }
      scored.sort(function (a, b) { return b[0] - a[0] || (a[1] < b[1] ? 1 : -1); });
      for (var t = 0; t < scored.length && t < want; t++) {
        var match = scored[t][1];
        if (seen[match]) continue;
        var key5 = this.sciToKey.get(match);
        if (!key5) continue;
        var s5 = this.byKey.get(key5);
        if (!s5) continue;
        push(s5.s, s5.n || [], 'fuzzy_scientific',
          round2(0.5 * sequenceRatio(q, match) + 0.5 * tokenOverlap(q, match)), key5, match);
      }
    }
    // 6. fuzzy common name (vernacular the DB never learned)
    if (results.length < limit && q.length <= 40) {
      var qTokens = contentTokens(q);
      if (Object.keys(qTokens).length) {
        var best = [];
        this.commonIdx.forEach(function (key6, cnLower) {
          if (seen[key6]) return;
          var cnTokens = contentTokens(cnLower);
          var kn = Object.keys(cnTokens);
          if (!kn.length || !kn.some(function (t) { return qTokens[t]; })) return;
          var seq = sequenceRatio(q, cnLower);
          var inter = kn.filter(function (t) { return qTokens[t]; }).length;
          var tok = inter / Math.max(Object.keys(qTokens).length, kn.length);
          if (seq >= 0.6 || tok >= 0.5) best.push([0.5 * seq + 0.5 * tok, key6, cnLower]);
        });
        best.sort(function (a, b) {
          if (b[0] !== a[0]) return b[0] - a[0];
          if (a[1] !== b[1]) return a[1] < b[1] ? 1 : -1;
          return a[2] < b[2] ? 1 : -1;
        });
        for (var b2 = 0; b2 < best.length && results.length < limit; b2++) {
          var sp6 = this.byKey.get(best[b2][1]);
          if (!sp6) continue;
          push(sp6.s, sp6.n || [], 'fuzzy_common', round2(Math.min(best[b2][0], 0.85)), best[b2][1], best[b2][1]);
        }
      }
    }
    return results.length > limit ? results.slice(0, limit) : results;
  };

  Store.prototype.bestPlantMatch = function (query) {
    if (!String(query || '').trim()) return null;
    var q = String(query).trim().toLowerCase();
    // Fast path. `search()` emits exact scientific then exact common first, so
    // when one of those exists and is usable it is the answer, and the six-step
    // scan (O(names) per call, fuzzy included) can be skipped. This is what keeps
    // name resolution O(1) for the thousands of exact lookups the picker and the
    // self-consistency sweep perform.
    var exactKey = this.byKey.has(q) ? q : (this.commonIdx.has(q) ? this.commonIdx.get(q) : null);
    if (exactKey && !CLAY_PSEUDO[exactKey] && this.classifySpecificity(exactKey) !== 'junk') {
      var exact = this.byKey.get(exactKey);
      return {
        scientificName: exact.s,
        commonNames: exact.n || [],
        matchType: this.byKey.has(q) ? 'exact_scientific' : 'exact_common',
        score: 1,
        key: exactKey
      };
    }
    var matches = this.search(query, 5);
    if (!matches.length) return null;
    if (CLAY_PSEUDO[q]) return matches[0];
    for (var i = 0; i < matches.length; i++) {
      if (!CLAY_PSEUDO[matches[i].key] && this.classifySpecificity(matches[i].key) !== 'junk') return matches[i];
    }
    return null;
  };

  /**
   * A deterministic "did you mean" — plain edit-distance ranking over every
   * known name, used only when the ordered `search()` steps find nothing (a
   * typo). It never resolves a species on its own: the caller offers the
   * result, the user picks it. Junk keys and soil-association pseudo-species
   * are excluded so a typo cannot be answered with "dandelion clay".
   */
  Store.prototype.didYouMean = function (query, limit) {
    limit = limit || 4;
    var q = String(query || '').trim().toLowerCase();
    if (q.length < 3) return [];
    var self = this;
    var best = new Map();
    function consider(text, key) {
      var t = String(text).toLowerCase();
      if (!t) return;
      var r = sequenceRatio(q, t);
      if (r < 0.55) return;
      var prev = best.get(key);
      if (!prev || r > prev.score) best.set(key, { key: key, name: text, score: r });
    }
    for (var i = 0; i < this.sciNames.length; i++) {
      if (this.classifySpecificity(this.sciNames[i]) === 'junk') continue;
      consider(this.sciNames[i], this.sciToKey.get(this.sciNames[i]));
    }
    this.commonIdx.forEach(function (key, cn) {
      if (self.classifySpecificity(key) === 'junk' || CLAY_PSEUDO[key]) return;
      consider(cn, key);
    });
    return Array.from(best.values())
      .sort(function (a, b) { return b.score - a.score || (a.name < b.name ? -1 : 1); })
      .slice(0, limit);
  };

  Store.prototype.resolveQuery = function (query, region) {
    var whole = this.bestPlantMatch(query);
    if (!whole || whole.score < 0.5) return null;
    var match = this.bestPlantMatch(whole.scientificName);
    if (!match || match.score < 0.5) return null;
    var info = this.getIndicators(match.key, region);
    if (!info) return null;
    info.match = { query: query, matchType: match.matchType, score: match.score, key: match.key };
    return info;
  };

  /* ===================================================================== *
   * Render layer
   * ===================================================================== */

  /* Presentation order only — the keys and values are the database's own. A   * reading is easier to scan when moisture leads and salinity trails, but an
   * unknown key must still render, so anything not listed sorts last. */
  var KEY_ORDER = ['Moisture', 'Soil pH', 'Ph', 'Fertility', 'Structure', 'Organic matter',
    'Salinity', 'Soil type', 'Disturbance', 'General indicators', 'Other indicators', 'Species'];

  function keyRank(k) {
    var i = KEY_ORDER.indexOf(k);
    return i < 0 ? KEY_ORDER.length : i;
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /**
   * The name to show for a species. Database rows frequently repeat the
   * binomial inside the vernacular ("Spear thistle (Cirsium vulgare)"), and a
   * merged genus reading can carry a sibling's binomial, so the parenthetical is
   * dropped when it is the shown scientific name or any scientific name the
   * database knows. Nothing else is stripped.
   */
  function prettyCommon(common, sci, isKnownSci) {
    if (!common) return null;
    var c = String(common).trim();
    var s = String(sci || '').trim().replace(/\.$/, '').toLowerCase();
    if (!c) return null;
    if (s && c.toLowerCase() === s) return null;
    var m = c.match(/^(.*?)\s*\(([^()]+)\)\s*$/);
    if (m) {
      var inner = m[2].trim().replace(/\.$/, '').toLowerCase();
      if (inner && (inner === s || (isKnownSci && isKnownSci(inner)))) {
        var stripped = m[1].trim();
        if (stripped) return stripped;
      }
    }
    return c;
  }

  function displayName(sp) {
    if (sp && sp._dn) return sp._dn;
    return { main: (sp && sp.s) || '', sci: (sp && sp.s) || '' };
  }

  /** "serrated tussock" -> "Serrated tussock"; anything else untouched. */
  function titleFirst(s) {
    var t = String(s || '');
    if (!t || t !== t.toLowerCase()) return t;
    return t.charAt(0).toUpperCase() + t.slice(1);
  }

  /**
   * Australian rows are often a paragraph of quoted evidence rather than a short
   * reading, which turns a card into a wall of text. The row shows the first
   * sentence and the Evidence panel always carries the whole thing verbatim, so
   * nothing is hidden — only shortened on the surface.
   */
  var PREVIEW_LIMIT = 180;

  function preview(text) {
    var t = String(text).replace(/\s+/g, ' ').trim();
    if (t.length <= PREVIEW_LIMIT) return t;
    var cut = t.slice(0, PREVIEW_LIMIT);
    var m = cut.match(/^(.{40,}?[.!?])\s/);
    if (m) return m[1];
    var sp = cut.lastIndexOf(' ');
    return (sp > 40 ? cut.slice(0, sp) : cut) + '…';
  }

  function regionLabel(r) { return r || 'Europe'; }

  function App(data, doc) {
    this.doc = doc;
    this.data = data;
    this.store = new Store(data);
    this.meta = data.meta || {};
    this.sources = data.sources || {};
    this.lineage = data.lineage || {};
    this.region = '';
    this.sel = -1;
  }

  App.prototype.el = function (id) { return this.doc.getElementById(id); };

  App.prototype.closeSuggest = function () {
    var box = this.el('suggest');
    box.className = 'suggest';
    box.innerHTML = '';
    var q = this.el('q');
    if (q) q.setAttribute('aria-expanded', 'false');
  };

  /* ---- suggestions -------------------------------------------------- */

  App.prototype.suggest = function (text) {
    var box = this.el('suggest');
    var self = this;
    var input = this.el('q');
    function open() {
      box.className = 'suggest on';
      if (input) input.setAttribute('aria-expanded', 'true');
    }
    function close() {
      box.className = 'suggest';
      box.innerHTML = '';
      if (input) input.setAttribute('aria-expanded', 'false');
    }
    if (!text || text.trim().length < 2) { close(); return; }
    var matches = this.store.search(text, 6);
    if (!matches.length) {
      var dym = this.store.didYouMean(text, 4);
      if (dym.length) {
        box.innerHTML = '<div class="sg-empty">No exact match — did you mean:</div>' +
          dym.map(function (d) {
            var sp2 = self.store.byKey.get(d.key);
            var dn2 = displayName(sp2);
            return '<div class="sg" role="option" data-key="' + esc(d.key) + '">' +
              '<div class="ic">🌿</div><div class="nm"><b>' + esc(dn2.main) + '</b><i>' + esc(dn2.sci) +
              '</i></div></div>';
          }).join('');
        open();
        return;
      }
      box.innerHTML = '<div class="sg-empty">No species matches “' + esc(text) + '”. ' +
        'Try a common name or a scientific name.</div>';
      open();
      return;
    }
    var html = '';
    for (var i = 0; i < matches.length; i++) {
      var m = matches[i];
      var sp = this.store.byKey.get(m.key);
      var dn = displayName(sp);
      var au = (sp.r || []).some(function (r) { return r.n === 'Australia'; });
      html += '<div class="sg' + (i === this.sel ? ' sel' : '') + '" role="option" data-key="' + esc(m.key) + '">' +
        '<div class="ic">🌿</div><div class="nm"><b>' + esc(dn.main) + '</b><i>' + esc(dn.sci) + '</i></div>' +
        (au ? '<span class="rt au">AU</span>' : '') +
        '<span class="sc">' + esc(m.matchType.replace(/_/g, ' ')) + '</span></div>';
    }
    box.innerHTML = html;
    open();
  };

  /* ---- refs ---------------------------------------------------------- */

  /**
   * Sources attached to one indicator row, in priority order:
   *   1. the species' recorded provenance, when it names this indicator
   *   2. a source named inside the evidence text for this region
   *   3. the region's pipeline lineage (declared, not per-species)
   * Returns an array of {name, url, kind} and never an empty array: the
   * lineage entry is always available as the honest floor.
   */
  App.prototype.refsFor = function (sp, region, key) {
    var out = [], self = this, seen = {};
    function add(name, url, kind) {
      var n = String(name || '').trim();
      if (!n || seen[n.toLowerCase()]) return;
      seen[n.toLowerCase()] = 1;
      out.push({ name: n, url: url || (self.sources[n] ? self.sources[n].u : null), kind: kind });
    }
    var prov = sp.p && sp.p.s ? sp.p.s : null;
    if (prov) {
      prov.forEach(function (s) {
        if ((s.f || []).indexOf(key) >= 0) add(s.n, s.u, 'recorded');
      });
    }
    var byKey = (sp._src && sp._src[region]) || {};
    (byKey[key] || []).forEach(function (s) { add(s, null, 'inline'); });
    if (!out.length) {
      var lin = this.lineage[region];
      if (lin) add(lin.label, lin.url, 'lineage');
    }
    return out;
  };

  App.prototype.lineageNote = function (region) {
    var lin = this.lineage[region];
    if (!lin) return '';
    return '<div class="notice"><b>Where ' + esc(region) + ' data comes from.</b> ' +
      esc(lin.note) + '</div>';
  };

  /* ---- answer -------------------------------------------------------- */

  App.prototype.visibleIndicators = function (info) {
    var out = [];
    Object.keys(info.indicators).forEach(function (k) {
      var v = info.indicators[k];
      if (String(v).trim().toLowerCase() === 'not specified') return;
      out.push([k, v]);
    });
    out.sort(function (a, b) {
      var ra = keyRank(a[0]), rb = keyRank(b[0]);
      return ra !== rb ? ra - rb : (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
    });
    return out;
  };

  App.prototype.renderSpecies = function (info, index) {
    // The heading is the identity's own display name — the same string the
    // picker shows and the search box accepts — not the canonical lead's.
    var sp = this.store.speciesFor(info.identityKey || info.key) || this.store.byKey.get(info.key);
    var main = displayName(sp).main || info.scientificName;

    var html = '<div class="card hero">' +
      '<div class="kicker">' + (index ? 'Also in this reading' : 'Soil reading') + '</div>' +
      '<div class="big">' + esc(main) + '</div>' +
      '<div class="sci">' + esc(info.scientificName) + '</div>' +
      '<div class="matchline">' + (info.match
        ? 'matched “' + esc(info.match.query) + '” · ' + esc(String(info.match.matchType).replace(/_/g, ' '))
        : 'looked up by key') + '</div>' +
      '<div class="meta">' +
        '<span class="pill">' + esc(regionLabel(info.region)) + ' data</span>' +
        '<span class="pill">' + esc(info.indicators ? Object.keys(info.indicators).length : 0) + ' data points</span>' +
      '</div></div>';

    var rows = this.visibleIndicators(info);
    var body = '';
    var self = this;
    rows.forEach(function (pair) {
      var key = pair[0], val = pair[1];
      var refs = self.refsFor(sp, info.region, key);
      var chips = refs.map(function (r) {
        var label = r.name + (r.kind === 'lineage' ? ' (pipeline default)' : '');
        return r.url
          ? '<a class="refchip" href="' + esc(r.url) + '" target="_blank" rel="noopener noreferrer">' + esc(label) + '</a>'
          : '<span class="refchip plain">' + esc(label) + '</span>';
      }).join('');
      var long = String(val).length > PREVIEW_LIMIT;
      var shown = long ? preview(val) : val;
      body += '<div class="ind">' +
        '<div class="top"><div class="key">' + esc(key) + '</div>' +
        '<div class="val">' + esc(shown) +
          (long ? ' <span class="morehint">full text under Evidence</span>' : '') + '</div>' +
        '<button class="ev-btn" type="button" aria-expanded="false" data-ev="' + esc(index + ':' + key) + '">Evidence</button></div>' +
        '<div class="ev" id="ev-' + esc(index + ':' + key) + '">' +
          '<div class="ev-lbl">Evidence — verbatim from the database</div>' +
          '<div class="ev-text">' + esc(val) + '</div>' +
          (chips ? '<div class="ev-src">' + chips + '</div>' : '') +
        '</div></div>';
    });

    var reading = '<div class="card"><div class="sec-h"><h2>What it indicates</h2>' +
      '<span class="sub">each row is one database data point — open “Evidence” to see the source</span></div>' +
      (body || '<div class="notice">No indicator rows are recorded for this species in this region.</div>') + '</div>';

    var nutrients = this.renderNutrients(sp);
    var refsCard = this.renderReferences(info, sp);
    var notices = '';
    if (info.specificity === 'genus_bucket') {
      notices += '<div class="notice warn"><b>Genus-level match.</b> “' + esc(main) +
        '” is a genus, not one species. The indicators below are for the group, so treat them as indicative of the genus.</div>';
    }
    if (info.regionFallback) {
      notices += '<div class="notice warn"><b>Region fallback.</b> No ' + esc(info.requestedRegion) +
        ' data is recorded for this species — showing <b>' + esc(info.region) + '</b> data instead. ' +
        'Treat it as indicative only: it was not recorded for ' + esc(info.requestedRegion) + '.</div>';
    }
    if (info.mergedFrom && info.mergedFrom.length > 1) {
      notices += '<div class="notice">Database rows merged for this reading: ' +
        info.mergedFrom.map(function (k) { return '<b>' + esc(k) + '</b>'; }).join(', ') + '.</div>';
    }

    return html + notices + reading + nutrients + refsCard;
  };

  App.prototype.renderNutrients = function (sp) {
    var claims = sp.cl || [];
    if (!claims.length) return '';
    var byNut = {};
    claims.forEach(function (c) {
      var n = c.n || 'nutrient';
      (byNut[n] = byNut[n] || []).push(c);
    });
    var rows = '';
    Object.keys(byNut).forEach(function (n) {
      byNut[n].forEach(function (c, i) {
        var conf = (c.c || '').toLowerCase();
        var cls = conf === 'high' ? 'hi' : conf === 'medium' ? 'med' : 'lo';
        rows += '<tr><td class="n">' + (i === 0 ? esc(n) : '') + '</td><td>' + esc(c.r) +
          (c.d ? ' — ' + esc(c.d) : '') +
          (c.c ? '<span class="badge ' + cls + '">' + esc(c.c) + ' confidence</span>' : '') + '</td>' +
          '<td class="s">' + esc(c.s || '') + '</td></tr>';
      });
    });
    return '<div class="card"><div class="sec-h"><h2>Nutrient claims</h2>' +
      '<span class="sub">recorded per nutrient, each with its own source and confidence</span></div>' +
      '<table class="nut">' + rows + '</table></div>';
  };

  App.prototype.renderReferences = function (info, sp) {
    var self = this;
    var prov = (sp.p && sp.p.s) ? sp.p.s : [];
    var inlineNames = [];
    var srcByKey = (sp._src && sp._src[info.region]) || {};
    Object.keys(srcByKey).forEach(function (k) {
      (srcByKey[k] || []).forEach(function (n) { if (inlineNames.indexOf(n) < 0) inlineNames.push(n); });
    });
    var lin = this.lineage[info.region] || null;
    var seen = {};

    var items = '';
    prov.forEach(function (s) {
      seen[s.n.toLowerCase()] = 1;
      var url = s.u || (self.sources[s.n] ? self.sources[s.n].u : null);
      items += '<li><span class="sname">' + (url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(s.n) + '</a>'
        : esc(s.n)) + '</span>' +
        (url ? '<span class="surl">' + esc(url) + '</span>' : '') +
        (s.f && s.f.length ? '<div class="used">Read for: <b>' + esc(s.f.join(', ')) + '</b></div>' : '') +
        '</li>';
    });
    inlineNames.forEach(function (n) {
      if (seen[n.toLowerCase()]) return;
      seen[n.toLowerCase()] = 1;
      var url = self.sources[n] ? self.sources[n].u : null;
      items += '<li><span class="sname">' + (url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(n) + '</a>'
        : esc(n)) + '</span>' + (url ? '<span class="surl">' + esc(url) + '</span>' : '') +
        '<div class="used">Named inside the recorded evidence text.</div></li>';
    });
    var layer = (sp._lin && sp._lin[info.region]) || null;
    if (layer) {
      items += '<li><span class="sname">' + esc(layer) + '</span>' +
        '<div class="used">The database\u2019s own layer marker for this region row.</div></li>';
    }
    if (lin) {
      items += '<li><span class="sname">' + (lin.url
        ? '<a href="' + esc(lin.url) + '" target="_blank" rel="noopener noreferrer">' + esc(lin.label) + '</a>'
        : esc(lin.label)) + '</span>' +
        '<div class="used">Pipeline default for <b>' + esc(info.region) +
        '</b> — recorded at the dataset level, not per species. ' + esc(lin.note) + '</div></li>';
    }

    var claimSrcs = {};
    (sp.cl || []).forEach(function (c) { if (c.s) claimSrcs[c.s] = 1; });
    Object.keys(claimSrcs).forEach(function (n) {
      if (seen[n.toLowerCase()]) return;
      seen[n.toLowerCase()] = 1;
      var url = self.sources[n] ? self.sources[n].u : null;
      items += '<li><span class="sname">' + (url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(n) + '</a>'
        : esc(n)) + '</span><div class="used">Nutrient claim source.</div></li>';
    });

    var dbNote = '<details class="more"><summary>How to read this, and where the database itself comes from</summary>' +
      '<div class="body">' +
      '<p><b>The reading is not generated.</b> Each row is a string stored in the species database for this ' +
      'species and region. This app searches that database and prints what it finds; it contains no language ' +
      'model and makes no network request.</p>' +
      '<p><b>Two confidence levels exist here.</b> A source listed as <i>recorded</i> is attached to this ' +
      'species in the database, often with the exact indicator it was read for. A source listed as ' +
      '<i>pipeline default</i> is the dataset-level lineage for that region: the database does not record ' +
      'which line of which document produced that particular row.</p>' +
      '<p><b>Database:</b> <code>' + esc(this.meta.db_path || '') + '</code><br>' +
      'sha256 <code>' + esc(this.meta.db_sha256 || '') + '</code><br>' +
      'species <b>' + esc(this.meta.species_count || '') + '</b> · ' +
      'with indicator data <b>' + esc(this.meta.with_data || '') + '</b> · ' +
      'built <b>' + esc(this.meta.build_date || '') + '</b></p>' +
      '<p><b>Matched key:</b> <code>' + esc(info.key) + '</code> · ' +
      'match <b>' + esc(info.match ? info.match.matchType : 'direct') + '</b></p>' +
      '</div></details>';

    return '<div class="card"><div class="sec-h"><h2>Where this came from</h2>' +
      '<span class="sub">' + (prov.length ? prov.length + ' source(s) recorded for this species' : 'dataset-level lineage') +
      '</span></div>' +
      '<ul class="srclist">' + items + '</ul>' + dbNote + '</div>';
  };

  App.prototype.renderNotFound = function (query) {
    var dym = this.store.didYouMean(query, 4);
    var hints = '';
    if (dym.length) {
      hints = '<div class="examples">' + dym.map(function (d) {
        var sp = this.store.byKey.get(d.key);
        var dn = displayName(sp);
        return '<button class="ex" type="button" data-key="' + esc(d.key) + '">' + esc(dn.main) + '</button>';
      }, this).join('') + '</div>';
    } else {
      var matches = this.store.search(query, 4);
      if (matches.length) {
        hints = '<div class="examples">' + matches.map(function (m) {
          var sp = this.store.byKey.get(m.key);
          var dn = displayName(sp);
          return '<button class="ex" type="button" data-key="' + esc(m.key) + '">' + esc(dn.main) + '</button>';
        }, this).join('') + '</div>';
      }
    }
    return '<div class="card empty"><div class="big">No species found for “' + esc(query) + '”</div>' +
      '<p>AUGURY matches common and scientific names. Check the spelling, or try the other name — ' +
      'many database rows are keyed by scientific name.</p>' + hints + '</div>';
  };

  App.prototype.renderNoData = function (query) {
    return '<div class="card empty"><div class="big">“' + esc(query) + '” is in the database, ' +
      'but carries no indicator rows</div><p>Some species are recorded as present without any soil ' +
      'indicator data. This app says so rather than inventing a reading.</p></div>';
  };

  App.prototype.renderEmpty = function () {
    var examples = ['dandelion', 'serrated tussock', 'curled dock', 'capeweed', 'bathurst burr',
      'African boxthorn', 'stinging nettle', 'couch'];
    var html = '<div class="card empty"><div class="big">Name a weed, get a soil reading</div>' +
      '<p>' + esc(this.meta.species_count) + ' species in the database, each with the evidence it was read from.</p>' +
      '<div class="examples">' + examples.map(function (e) {
        return '<button class="ex" type="button" data-term="' + esc(e) + '">' + esc(e) + '</button>';
      }).join('') + '</div></div>';
    return html;
  };

  /**
   * "dandelion and thistles" is two readings, not one long name — but only when
   * every part actually resolves. A single name that merely contains a
   * separator-like word ("salt and pepper") stays whole.
   */
  App.prototype.splitNames = function (text) {
    var whole = String(text).trim();
    if (!whole) return [];
    if (/[,;+&]|\band\b/i.test(whole)) {
      var parts = whole.split(/\s*(?:,|;|\+|&|\band\b)\s*/i)
        .map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length > 1; })
        .slice(0, 4);
      var self = this;
      if (parts.length > 1 && parts.every(function (p) { return !!self.store.bestPlantMatch(p); })) return parts;
    }
    return [whole];
  };

  App.prototype.render = function (text) {
    var answer = this.el('answer');
    if (!text || !String(text).trim()) { answer.innerHTML = this.renderEmpty(); return; }
    var names = this.splitNames(text);
    var found = [], missing = [], noData = [], seen = {};
    var self = this;
    names.forEach(function (n) {
      var match = self.store.bestPlantMatch(n);
      if (!match) { missing.push(n); return; }
      var info = self.store.getIndicators(match.key, self.region);
      if (!info) { noData.push(n); return; }
      info.match = { query: n, matchType: match.matchType, score: match.score, key: match.key };
      if (seen[info.key]) return;
      seen[info.key] = 1;
      found.push(info);
    });

    var html = '';
    if (found.length) {
      for (var i = 0; i < found.length; i++) html += this.renderSpecies(found[i], i);
      if (found.length > 1) {
        html += '<div class="notice good"><b>' + found.length +
          ' species resolved.</b> Each block above is an independent reading from the database — ' +
          'AUGURY does not average them or draw a combined conclusion.</div>';
      }
    } else {
      html += this.renderNotFound(text);
    }
    if (noData.length) {
      html += '<div class="notice warn"><b>Known, but no data:</b> ' + noData.map(esc).join(', ') +
        ' — recorded in the database without indicator rows.</div>';
    }
    if (missing.length && found.length) {
      html += '<div class="notice"><b>Not matched:</b> ' + missing.map(esc).join(', ') + '.</div>';
    }
    answer.innerHTML = html;
  };

  /* ---- browse -------------------------------------------------------- */

  App.prototype.browseList = function (filter, limit) {
    var self = this;
    var q = String(filter || '').trim().toLowerCase();
    var rows = this.store.species.filter(function (sp) {
      if (!sp.r || !sp.r.length) return false;
      if (sp.y === 'junk') return false;
      if (!q) return true;
      if (String(sp.k).indexOf(q) >= 0 || String(sp.s).toLowerCase().indexOf(q) >= 0) return true;
      return (sp.n || []).some(function (n) { return String(n).toLowerCase().indexOf(q) >= 0; });
    });
    rows.sort(function (a, b) {
      var an = displayName(a).main.toLowerCase(), bn = displayName(b).main.toLowerCase();
      return an < bn ? -1 : an > bn ? 1 : 0;
    });
    var slice = rows.slice(0, limit);
    var html = '<div class="sec-h"><h2>Browse species</h2><span class="sub">' +
      rows.length + ' with indicator data' + (rows.length > limit ? ' · showing ' + slice.length : '') +
      '</span></div>' +
      '<div class="searchrow" style="height:42px"><svg viewBox="0 0 20 20" fill="none"><circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="2"/><path d="m14 14 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' +
      '<input id="bfilter" type="search" placeholder="Filter…" value="' + esc(filter || '') + '" style="flex:1;border:0;outline:0;font-size:14px;font-family:inherit;background:transparent"></div>';
    if (!slice.length) {
      html += '<div class="notice">No species match that filter.</div>';
    } else {
      html += slice.map(function (sp) {
        var dn = displayName(sp);
        var au = (sp.r || []).some(function (r) { return r.n === 'Australia'; });
        return '<div class="row" data-key="' + esc(sp.k) + '"><div class="nm">' + esc(dn.main) + '</div>' +
          '<div class="sc">' + esc(dn.sci) + '</div>' +
          '<span class="rt">' + (au ? 'AU' : (sp.r[0] ? sp.r[0].n : '')) + '</span></div>';
      }).join('');
      if (rows.length > limit) html += '<button class="morebtn" type="button" id="bmore">Show 60 more</button>';
    }
    return { html: html, total: rows.length };
  };

  App.prototype.toggleBrowse = function (on) {
    var box = this.el('browse');
    if (!on) { box.className = 'card browse hidden'; return; }
    this.browseLimit = 60;
    this.browseFilter = '';
    box.className = 'card browse';
    box.innerHTML = this.browseList('', this.browseLimit).html;
  };

  /* ---- wiring -------------------------------------------------------- */

  App.prototype.init = function () {
    var self = this, doc = this.doc;
    var q = this.el('q');

    var input = function () {
      self.sel = -1;
      self.render(q.value);
      self.suggest(q.value);
      self.el('clear').className = q.value ? 'clear on' : 'clear';
    };

    q.addEventListener('input', input);

    q.addEventListener('keydown', function (e) {
      var box = self.el('suggest');
      var items = box.className.indexOf('on') >= 0 ? box.querySelectorAll('.sg') : [];
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!items.length) return;
        e.preventDefault();
        self.sel = e.key === 'ArrowDown'
          ? Math.min(self.sel + 1, items.length - 1)
          : Math.max(self.sel - 1, 0);
        for (var i = 0; i < items.length; i++) items[i].className = 'sg' + (i === self.sel ? ' sel' : '');
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (self.sel >= 0 && items[self.sel]) {
          var sp = self.store.byKey.get(items[self.sel].getAttribute('data-key'));
          q.value = displayName(sp).main;
        }
        self.closeSuggest();
        self.render(q.value);
      } else if (e.key === 'Escape') {
        self.closeSuggest();
      }
    });

    this.el('clear').addEventListener('click', function () {
      q.value = ''; self.sel = -1; self.render(''); self.suggest('');
      self.el('clear').className = 'clear'; q.focus();
    });

    this.el('suggest').addEventListener('mousedown', function (e) {
      var row = e.target.closest ? e.target.closest('.sg') : null;
      if (!row) return;
      e.preventDefault();
      var sp = self.store.byKey.get(row.getAttribute('data-key'));
      q.value = displayName(sp).main;
      self.closeSuggest();
      self.render(q.value);
    });

    doc.addEventListener('click', function (e) {
      var t = e.target;
      var ex = t.closest ? t.closest('.ex') : null;
      if (ex) {
        var term = ex.getAttribute('data-term') ||
          displayName(self.store.byKey.get(ex.getAttribute('data-key'))).main;
        q.value = term;
        self.closeSuggest();
        self.render(term);
        return;
      }
      var brow = t.closest ? t.closest('.browse .row') : null;
      if (brow) {
        var sp2 = self.store.byKey.get(brow.getAttribute('data-key'));
        q.value = displayName(sp2).main;
        self.toggleBrowse(false);
        self.el('browseBtn').className = 'chip ghost';
        self.render(q.value);
        return;
      }
      var mrow = t.closest ? t.closest('.sg') : null;
      if (mrow && mrow.parentNode === self.el('suggest')) return;
      if (!(t.closest && t.closest('.searchbox'))) self.closeSuggest();

      var evb = t.closest ? t.closest('.ev-btn') : null;
      if (evb) {
        var id = 'ev-' + evb.getAttribute('data-ev');
        var panel = doc.getElementById(id);
        var open = panel.className.indexOf('on') >= 0;
        panel.className = open ? 'ev' : 'ev on';
        evb.setAttribute('aria-expanded', open ? 'false' : 'true');
        return;
      }
      var more = t.closest ? t.closest('#bmore') : null;
      if (more) {
        self.browseLimit += 60;
        var pos = self.el('browse').scrollTop;
        self.el('browse').innerHTML = self.browseList(self.browseFilter, self.browseLimit).html;
        self.el('browse').scrollTop = pos;
      }
    });

    this.el('browse').addEventListener('input', function (e) {
      if (e.target.id !== 'bfilter') return;
      self.browseFilter = e.target.value;
      var pos = self.el('browse').scrollTop;
      self.el('browse').innerHTML = self.browseList(self.browseFilter, self.browseLimit).html;
      self.el('browse').scrollTop = pos;
      var f = doc.getElementById('bfilter');
      if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); }
    });

    Array.prototype.forEach.call(doc.querySelectorAll('.chip[data-region]'), function (c) {
      c.addEventListener('click', function () {
        Array.prototype.forEach.call(doc.querySelectorAll('.chip[data-region]'), function (o) {
          o.className = 'chip';
        });
        c.className = 'chip on';
        self.region = c.getAttribute('data-region');
        if (q.value) self.render(q.value);
      });
    });

    this.el('browseBtn').addEventListener('click', function () {
      var on = self.el('browse').className.indexOf('hidden') >= 0;
      self.toggleBrowse(on);
      self.el('browseBtn').className = on ? 'chip on' : 'chip ghost';
    });

    var meta = this.meta;
    this.el('footmeta').innerHTML =
      meta.species_count + ' species · ' + (meta.with_data || '') + ' with indicator data · ' +
      'built ' + esc(meta.build_date || '') + ' · database sha256 <span style="font-family:var(--mono)">' +
      esc((meta.db_sha256 || '').slice(0, 16)) + '…</span><br>' +
      'Offline single file · no model · no network · ' +
      '<a href="https://github.com/RegeneratusLabs/AUGURY" target="_blank" rel="noopener noreferrer">Apache-2.0 code / CC-BY-4.0 data</a>';

    this.render('');
    q.focus();
  };

  /* ---- export -------------------------------------------------------- */

  var AUGURY = { Store: Store, App: App, sequenceRatio: sequenceRatio, version: 1 };
  if (typeof module !== 'undefined' && module.exports) module.exports = AUGURY;
  root.AUGURY = AUGURY;

  if (typeof document !== 'undefined') {
    function boot() {
      var node = document.getElementById('augury-db');
      if (!node) return;
      try {
        var data = JSON.parse(node.textContent);
        var app = new App(data, document);
        root.__auguryApp = app;
        app.init();
      } catch (err) {
        document.getElementById('answer').innerHTML =
          '<div class="card empty"><div class="big">The embedded database could not be read</div><p>' +
          String(err && err.message ? err.message : err) + '</p></div>';
      }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
