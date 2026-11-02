/* AUGURY — single-file app logic.
 *
 * Two halves:
 *   1. A dependency-free port of the deterministic lookup that already ships in
 *      the Android app (SpeciesStore.kt / species_lookup.py): name search,
 *      canonical grouping, region policy. Deterministic throughout — no
 *      randomness, and nothing that reaches outside this file.
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

  /** Two-letter monogram for an avatar chip, from the display name. */
  function monogram(name) {
    var words = String(name || '').replace(/[^A-Za-z ]/g, ' ').split(/\s+/).filter(Boolean);
    if (!words.length) return '·';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
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

  /** Lowercase, alphanumerics only — for deciding whether two source names are
   *  the same organisation written at two lengths ("NSW WeedWise (NSW DPIRD)" is
   *  contained in "NSW WeedWise (NSW DPIRD) - African boxthorn"). */
  function srcKey(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  /** Drop a source name when a longer name in the same list already contains it. */
  function dedupeNames(names) {
    var keys = names.map(srcKey);
    return names.filter(function (n, i) {
      var k = keys[i];
      if (!k) return false;
      for (var j = 0; j < keys.length; j++) {
        if (j === i || !keys[j]) continue;
        if (keys[j] !== k && keys[j].indexOf(k) >= 0) return false;
      }
      return true;
    });
  }

  function dedupeRefs(refs) {
    var kept = dedupeNames(refs.map(function (r) { return r.name; }));
    return refs.filter(function (r) { return kept.indexOf(r.name) >= 0; });
  }

  /** True when a key is a soil-association pseudo-species or a non-species key.
   *  `bestPlantMatch` refuses these, so the picker and the browse list must not
   *  offer them either — a suggestion the app will not answer is a trap. */
  function isUnusable(store, key) {
    return !!CLAY_PSEUDO[key] || store.classifySpecificity(key) === 'junk';
  }

  /* Small inline icon set — every glyph the page needs, as data URI-free SVG. */
  var ICONS = {
    leaf: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 21V11M12 11c0-3.3 2.7-6 6-6 0 3.3-2.7 6-6 6Zm0 4.5c0-2.5-2-4.5-4.5-4.5 0 2.5 2 4.5 4.5 4.5Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    search: '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="2"/><path d="m14 14 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    quote: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 7h4v4a4 4 0 0 1-4 4V7Zm8 0h4v4a4 4 0 0 1-4 4V7Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.7"/><path d="M12 11v5.5M12 7.6v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    warn: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 4.5 21 19.5H3L12 4.5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 10v3.6M12 16.4v.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.7"/><path d="m8 12.3 2.6 2.6L16 9.5" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.4" stroke="currentColor" stroke-width="1.7"/><path d="M15 6.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    share: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 15V4M8.5 7.5 12 4l3.5 3.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 13v5.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    print: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 9V4h10v5" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><rect x="4" y="9" width="16" height="7" rx="2" stroke="currentColor" stroke-width="1.7"/><path d="M7 14h10v6H7z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    source: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10l2 2h6.5A1.5 1.5 0 0 1 20 7.5v11A1.5 1.5 0 0 1 18.5 20h-13A1.5 1.5 0 0 1 4 18.5v-13Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    flask: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 3h6M10 3v6.2L5.6 17A2 2 0 0 0 7.4 20h9.2a2 2 0 0 0 1.8-3L14 9.2V3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };

  function notice(kind, body) {
    var icon = kind === 'warn' ? ICONS.warn : kind === 'good' ? ICONS.check : ICONS.info;
    return '<div class="notice ' + kind + '"><span class="nic">' + icon + '</span>' +
      '<div class="nbody">' + body + '</div></div>';
  }

  function App(data, doc) {
    this.doc = doc;
    this.data = data;
    this.store = new Store(data);
    this.meta = data.meta || {};
    this.sources = data.sources || {};
    this.lineage = data.lineage || {};
    this.region = '';
    this.sel = -1;
    this.toastTimer = null;
    this.copies = {};
  }

  App.prototype.el = function (id) { return this.doc.getElementById(id); };

  App.prototype.closeSuggest = function () {
    var box = this.el('suggest');
    if (box) { box.className = 'suggest'; box.innerHTML = ''; }
    var q = this.el('q');
    if (q) q.setAttribute('aria-expanded', 'false');
  };

  App.prototype.toast = function (msg) {
    var el = this.el('toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast on';
    var self = this;
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(function () { el.className = 'toast'; }, 2400);
  };

  /* ---- clipboard ------------------------------------------------------ */

  App.prototype.copyText = function (text, okMessage) {
    var self = this;
    function fallback() {
      var doc = self.doc;
      try {
        var ta = doc.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        doc.body.appendChild(ta);
        ta.select();
        var done = doc.execCommand && doc.execCommand('copy');
        doc.body.removeChild(ta);
        self.toast(done === false ? 'Copy is blocked in this browser' : okMessage);
      } catch (err) {
        self.toast('Copy is blocked in this browser');
      }
    }
    var nav = typeof navigator !== 'undefined' ? navigator : null;
    if (nav && nav.clipboard && nav.clipboard.writeText) {
      nav.clipboard.writeText(text).then(function () { self.toast(okMessage); }, fallback);
      return;
    }
    fallback();
  };

  /** The reading as plain text — for the clipboard and for sharing. */
  App.prototype.readingText = function (info) {
    var sp = this.store.speciesFor(info.identityKey || info.key) || this.store.byKey.get(info.key);
    var dn = displayName(sp);
    var lines = [dn.main + (dn.sci && dn.sci !== dn.main ? ' (' + dn.sci + ')' : ''),
      'Region: ' + regionLabel(info.region)];
    var rows = this.visibleIndicators(info);
    rows.forEach(function (pair) { lines.push(pair[0] + ': ' + String(pair[1]).replace(/\s+/g, ' ').trim()); });
    var refs = this.referenceNames(sp, info.region);
    if (refs.length) lines.push('Sources: ' + refs.join('; '));
    lines.push('— AUGURY, indicators only.');
    return lines.join('\n');
  };

  App.prototype.referenceNames = function (sp, region) {
    var names = [];
    ((sp.p && sp.p.s) || []).forEach(function (s) { if (names.indexOf(s.n) < 0) names.push(s.n); });
    var byKey = (sp._src && sp._src[region]) || {};
    Object.keys(byKey).forEach(function (k) {
      (byKey[k] || []).forEach(function (n) { if (names.indexOf(n) < 0) names.push(n); });
    });
    if (!names.length && this.lineage[region]) names.push(this.lineage[region].label);
    return dedupeNames(names);
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
    var matches = this.store.search(text, 10).filter(function (m) {
      return !isUnusable(self.store, m.key);
    }).slice(0, 6);
    if (!matches.length) {
      var dym = this.store.didYouMean(text, 4);
      if (dym.length) {
        box.innerHTML = '<div class="sg-empty">Nothing exact — <b>did you mean</b></div>' +
          dym.map(function (d) {
            var sp2 = self.store.byKey.get(d.key);
            var dn2 = displayName(sp2);
            return '<div class="sg" role="option" tabindex="-1" data-key="' + esc(d.key) + '">' +
              '<div class="av">' + esc(monogram(dn2.main)) + '</div><div class="nm"><b>' + esc(dn2.main) +
              '</b><i>' + esc(dn2.sci) + '</i></div></div>';
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
      html += '<div class="sg' + (i === this.sel ? ' sel' : '') + '" role="option" tabindex="-1" data-key="' + esc(m.key) + '">' +
        '<div class="av">' + esc(monogram(dn.main)) + '</div>' +
        '<div class="nm"><b>' + esc(dn.main) + '</b><i>' + esc(dn.sci) + '</i></div>' +
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
    return dedupeRefs(out);
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
    var dn = displayName(sp);
    var main = dn.main || info.scientificName;
    var nPoints = Object.keys(info.indicators || {}).length;
    var hasRecorded = !!((sp.p && sp.p.s && sp.p.s.length));
    var safeIndex = String(index);

    var metaPills =
      '<span class="pill">' + ICONS.leaf + esc(regionLabel(info.region)) + ' data</span>' +
      '<span class="pill">' + esc(nPoints) + ' data point' + (nPoints === 1 ? '' : 's') + '</span>' +
      (info.regionFallback ? '<span class="pill warn">' + ICONS.warn + 'fallback region</span>' : '') +
      (info.specificity === 'genus_bucket' ? '<span class="pill warn">genus-level</span>' : '') +
      (hasRecorded ? '<span class="pill">' + ICONS.check + 'sources recorded</span>' : '');

    var actions =
      '<div class="acts">' +
        '<button class="act" type="button" data-act="copy" data-idx="' + safeIndex + '">' + ICONS.copy + 'Copy reading</button>' +
        '<button class="act" type="button" data-act="print" data-idx="' + safeIndex + '">' + ICONS.print + 'Print</button>' +
        '<button class="act" type="button" data-act="sources" data-idx="' + safeIndex + '">' + ICONS.source + 'Jump to sources</button>' +
      '</div>';

    var html = '<div class="card hero" data-hero="' + safeIndex + '">' +
      '<div class="flora" aria-hidden="true">' +
        '<svg viewBox="0 0 120 120" fill="none"><path d="M60 116V58M60 58c0-20 14-36 34-36 0 20-14 36-34 36Zm0 24c0-15-11-27-25-27 0 15 11 27 25 27Z" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><path d="M28 30c14 2 24 10 30 22M92 30c-14 2-24 10-30 22" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" opacity=".7"/></svg>' +
      '</div>' +
      '<div class="kicker">' + (index ? 'Also in this reading' : 'Soil reading') + '</div>' +
      '<div class="big">' + esc(main) + '</div>' +
      '<div class="sci">' + esc(info.scientificName) + '</div>' +
      '<div class="matchline">' + (info.match
        ? 'read from “' + esc(info.match.query) + '”'
        : 'read from the database key') + '</div>' +
      '<div class="meta">' + metaPills + '</div>' +
      actions +
      '</div>';

    var rows = this.visibleIndicators(info);
    var body = '';
    var self = this;
    rows.forEach(function (pair) {
      var key = pair[0], val = pair[1];
      var refs = self.refsFor(sp, info.region, key);
      var chips = refs.map(function (r) {
        var label = r.name + (r.kind === 'lineage' ? ' · pipeline default' : '');
        return r.url
          ? '<a class="refchip" href="' + esc(r.url) + '" target="_blank" rel="noopener noreferrer">' + esc(label) + '</a>'
          : '<span class="refchip plain">' + esc(label) + '</span>';
      }).join('');
      var long = String(val).length > PREVIEW_LIMIT;
      var shown = long ? preview(val) : val;
      var id = safeIndex + ':' + key;
      body += '<div class="ind" data-ind="' + esc(id) + '">' +
        '<div class="top"><div class="key">' + esc(key) + '</div>' +
        '<div class="val">' + esc(shown) +
          (long ? ' <span class="morehint">full text under Evidence</span>' : '') + '</div>' +
        '<button class="ev-btn" type="button" aria-expanded="false" aria-controls="ev-' + esc(id) + '" data-ev="' + esc(id) + '">' +
          ICONS.quote + '<span>Evidence</span>' + ICONS.chevron + '</button></div>' +
        '<div class="ev" id="ev-' + esc(id) + '"><div class="ev-in">' +
          '<div class="ev-lbl">' + ICONS.quote + 'Verbatim from the database</div>' +
          '<div class="ev-text">' + esc(val) + '</div>' +
          (chips ? '<div class="ev-src"><span class="lbl">Source</span>' + chips + '</div>' : '') +
        '</div></div></div>';
    });

    var reading = '<div class="card"><div class="sec-h"><h2>What it indicates</h2>' +
      '<span class="sub">each row is one stored data point — open “Evidence” for the source text</span>' +
      '<span class="count">' + rows.length + '</span></div>' +
      (body || notice('', 'No indicator rows are recorded for this species in this region.')) + '</div>';

    var notices = '';
    if (info.specificity === 'genus_bucket') {
      notices += notice('warn', '<b>Genus-level match.</b> “' + esc(main) +
        '” names a genus rather than one species, so the indicators below describe the group.');
    }
    if (info.regionFallback) {
      notices += notice('warn', '<b>Region fallback.</b> There is no ' + esc(info.requestedRegion) +
        ' record for this species yet, so this is the <b>' + esc(info.region) + '</b> reading. ' +
        'It is documented data for ' + esc(info.region) + ' — it was not recorded for ' +
        esc(info.requestedRegion) + ', so treat it as a guide rather than a local measurement.');
    }

    return html + notices + reading + this.renderNutrients(sp) + this.renderReferences(info, sp, safeIndex);
  };

  App.prototype.renderNutrients = function (sp) {
    var claims = sp.cl || [];
    if (!claims.length) return '';
    // Grouped by nutrient, one row per recorded claim: the claim, its confidence
    // and its own source stay legible without turning 15 claims into 15 cards.
    var order = [], byNut = {};
    claims.forEach(function (c) {
      var n = c.n || 'nutrient';
      if (!byNut[n]) { byNut[n] = []; order.push(n); }
      byNut[n].push(c);
    });
    var groups = order.map(function (n) {
      var list = byNut[n];
      var rows = list.map(function (c) {
        var conf = (c.c || '').toLowerCase();
        var cls = conf === 'high' ? 'hi' : conf === 'medium' ? 'med' : 'lo';
        return '<li class="claim">' +
          '<div class="cr">' + esc(c.r || '') +
            (c.c ? '<span class="badge ' + cls + '">' + esc(c.c) + '</span>' : '') + '</div>' +
          (c.d ? '<div class="cd">' + esc(c.d) + '</div>' : '') +
          (c.s ? '<div class="cs">' + esc(c.s) + '</div>' : '') +
          '</li>';
      }).join('');
      return '<div class="ngroup">' +
        '<div class="nhead"><span class="nn">' + esc(n) + '</span>' +
        '<span class="nc">' + list.length + ' claim' + (list.length === 1 ? '' : 's') + '</span></div>' +
        '<ul class="clist">' + rows + '</ul></div>';
    }).join('');
    return '<div class="card"><div class="sec-h"><h2>Nutrient claims</h2>' +
      '<span class="sub">recorded one nutrient at a time, each with its own source and confidence</span>' +
      '<span class="count">' + claims.length + '</span></div>' +
      '<div class="nut">' + groups + '</div></div>';
  };

  App.prototype.renderReferences = function (info, sp, index) {
    var self = this;
    var prov = (sp.p && sp.p.s) ? sp.p.s : [];
    var inlineNames = [];
    var srcByKey = (sp._src && sp._src[info.region]) || {};
    Object.keys(srcByKey).forEach(function (k) {
      (srcByKey[k] || []).forEach(function (n) { if (inlineNames.indexOf(n) < 0) inlineNames.push(n); });
    });
    var lin = this.lineage[info.region] || null;

    function link(n, url) {
      return url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(n) + '</a>'
        : esc(n);
    }

    // Every candidate source for this reading, recorded ones first. The database
    // names one organisation at several lengths and at several grades ("NSW
    // WeedWise (NSW DPIRD) - African boxthorn" is the recorded document;
    // "NSW WeedWise (NSW DPIRD)" is the same body named inside the evidence), so
    // the list is reduced to the longest form of each name, and a name already
    // covered by a recorded source is not repeated lower down as a separate one.
    var entries = [];
    prov.forEach(function (s) {
      entries.push({ kind: 'recorded', name: s.n, url: s.u || (self.sources[s.n] ? self.sources[s.n].u : null), read: s.f || [] });
    });
    var recordedKeys = prov.map(function (s) { return srcKey(s.n); });
    inlineNames.forEach(function (n) {
      entries.push({ kind: 'inline', name: n, url: self.sources[n] ? self.sources[n].u : null, read: [] });
    });
    var layer = (sp._lin && sp._lin[info.region]) || null;
    if (layer) entries.push({ kind: 'layer', name: layer, url: null, read: [] });
    if (lin) entries.push({ kind: 'lineage', name: lin.label, url: lin.url, read: [], note: lin.note });
    var claimSrcs = {};
    (sp.cl || []).forEach(function (c) { if (c.s) claimSrcs[c.s] = 1; });
    Object.keys(claimSrcs).forEach(function (n) {
      entries.push({ kind: 'claim', name: n, url: self.sources[n] ? self.sources[n].u : null, read: [] });
    });

    var keptKeys = dedupeNames(entries.map(function (e) { return e.name; })).map(srcKey);
    var seen = {};
    entries = entries.filter(function (e) {
      var k = srcKey(e.name);
      if (!k || keptKeys.indexOf(k) < 0 || seen[k]) return false;
      seen[k] = 1;
      // Only a recorded source may absorb a lower-grade mention of itself.
      if (e.kind !== 'recorded' && recordedKeys.some(function (rk) { return rk.indexOf(k) >= 0; })) return false;
      return true;
    });

    var KIND_LABEL = {
      recorded: 'recorded',
      inline: 'named in the evidence',
      layer: 'database layer',
      lineage: 'pipeline default',
      claim: 'nutrient claim'
    };
    var KIND_NOTE = {
      inline: 'Named inside the recorded evidence text.',
      layer: 'The database\u2019s own layer marker for this region row.',
      claim: 'Source for the nutrient claim above.'
    };

    var items = entries.map(function (e) {
      var note = KIND_NOTE[e.kind] || '';
      if (e.kind === 'recorded' && e.read.length) {
        note = 'Read for: <b>' + esc(e.read.join(', ')) + '</b>';
      } else if (e.kind === 'lineage') {
        note = 'The documented lineage for <b>' + esc(info.region) +
          '</b> — recorded for the dataset, not for this species. ' + esc(e.note || '');
      }
      return '<li><span class="sname">' + link(e.name, e.url) + '</span>' +
        '<span class="kind' + (e.kind === 'recorded' ? ' recorded' : '') + '">' + KIND_LABEL[e.kind] + '</span>' +
        (e.url ? '<span class="surl">' + esc(e.url) + '</span>' : '') +
        (note ? '<div class="used">' + note + '</div>' : '') +
        '</li>';
    }).join('');

    var merged = (info.mergedFrom && info.mergedFrom.length > 1)
      ? '<div class="used" style="margin-top:10px">This reading gathers ' + info.mergedFrom.length +
        ' database entries for the same plant: <b>' + esc(info.mergedFrom.join(', ')) + '</b>.</div>'
      : '';

    var dbNote = '<details class="more"><summary>' + ICONS.chevron + 'Technical details</summary>' +
      '<div class="body">' +
      '<p><b>Where the reading comes from.</b> Each row is a stored string in the species database for this ' +
      'species and region. The app looks that string up and prints it, working entirely from the copy of the ' +
      'database inside this file.</p>' +
      '<p><b>Two kinds of source.</b> A source marked <i>recorded</i> is attached to this species in the ' +
      'database, often with the exact indicator it was read for. A <i>pipeline default</i> is the documented ' +
      'lineage for the whole region: the database does not record which line of which document produced that ' +
      'particular row, and the app does not pretend otherwise.</p>' +
      '<p><b>Database</b></p>' +
      '<div class="kv">' +
        '<span class="k">File</span><span class="v"><code>' + esc(this.meta.db_path || '') + '</code></span>' +
        '<span class="k">sha256</span><span class="v"><code>' + esc(this.meta.db_sha256 || '') + '</code></span>' +
        '<span class="k">Species</span><span class="v">' + esc(this.meta.species_count || '') +
          ' · ' + esc(this.meta.with_data || '') + ' with indicator data · built ' + esc(this.meta.build_date || '') + '</span>' +
        '<span class="k">Matched key</span><span class="v"><code>' + esc(info.key) + '</code> · ' +
          esc(info.match ? String(info.match.matchType).replace(/_/g, ' ') : 'direct') + '</span>' +
      '</div>' +
      '</div></details>';

    var nRecorded = entries.filter(function (e) { return e.kind === 'recorded'; }).length;
    var sub = nRecorded
      ? nRecorded + ' source' + (nRecorded === 1 ? '' : 's') + ' recorded for this species'
      : 'the documented lineage for this region';

    return '<div class="card" id="sources-' + esc(index) + '"><div class="sec-h"><h2>Where this came from</h2>' +
      '<span class="sub">' + esc(sub) + '</span></div>' +
      '<ul class="srclist">' + items + '</ul>' + merged + dbNote + '</div>';
  };

  App.prototype.renderNotFound = function (query) {
    var dym = this.store.didYouMean(query, 4);
    var hints = '';
    var source = dym.length ? dym : this.store.search(query, 4);
    if (source.length) {
      hints = '<div class="examples">' + source.map(function (d) {
        var sp = this.store.byKey.get(d.key);
        if (!sp) return '';
        var dn = displayName(sp);
        return '<button class="ex" type="button" data-key="' + esc(d.key) + '">' + esc(dn.main) + '</button>';
      }, this).join('') + '</div>';
    }
    return '<div class="card empty">' +
      '<div class="glyph">' + ICONS.search + '</div>' +
      '<div class="big">No match for “' + esc(query) + '”</div>' +
      '<p>AUGURY looks up common and scientific names. Check the spelling, or try the other name — ' +
      'many records are keyed by their scientific name.</p>' + hints + '</div>';
  };

  App.prototype.renderNoData = function (query) {
    return '<div class="card empty"><div class="glyph">' + ICONS.leaf + '</div>' +
      '<div class="big">“' + esc(query) + '” has no indicator rows yet</div>' +
      '<p>This species is recorded in the database without soil indicator data. ' +
      'AUGURY says so rather than filling the gap with a guess.</p></div>';
  };

  App.prototype.renderEmpty = function () {
    var examples = ['dandelion', 'serrated tussock', 'curled dock', 'capeweed', 'bathurst burr',
      'African boxthorn', 'stinging nettle', 'couch'];
    return '<div class="card empty">' +
      '<div class="glyph">' + ICONS.leaf + '</div>' +
      '<div class="big">Name a weed, read the soil</div>' +
      '<p>' + esc(this.meta.species_count) + ' species are in the database, each one with the evidence it was ' +
      'read from. Start with a name you know, or browse the list.</p>' +
      '<div class="examples">' + examples.map(function (e) {
        return '<button class="ex" type="button" data-term="' + esc(e) + '">' + esc(e) + '</button>';
      }).join('') + '</div></div>';
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
      this.lastReadings = found;
      for (var i = 0; i < found.length; i++) html += this.renderSpecies(found[i], i);
      if (found.length > 1) {
        html += notice('good', '<b>' + found.length + ' independent readings.</b> Each block above stands on ' +
          'its own — AUGURY does not blend them into one answer.');
      }
    } else {
      html += this.renderNotFound(text);
    }
    if (noData.length) {
      html += notice('warn', '<b>Known, but no data:</b> ' + noData.map(esc).join(', ') +
        ' — recorded in the database without indicator rows.');
    }
    if (missing.length && found.length) {
      html += notice('', '<b>Not matched:</b> ' + missing.map(esc).join(', ') + '.');
    }
    answer.innerHTML = html;
  };

  /* ---- browse -------------------------------------------------------- */

  App.prototype.browseRows = function (filter) {
    var q = String(filter || '').trim().toLowerCase();
    return this.store.species.filter(function (sp) {
      if (!sp.r || !sp.r.length) return false;
      if (isUnusable(this.store, sp.k)) return false;
      if (!q) return true;
      if (String(sp.k).indexOf(q) >= 0 || String(sp.s).toLowerCase().indexOf(q) >= 0) return true;
      return (sp.n || []).some(function (n) { return String(n).toLowerCase().indexOf(q) >= 0; });
    }, this).sort(function (a, b) {
      var an = displayName(a).main.toLowerCase(), bn = displayName(b).main.toLowerCase();
      return an < bn ? -1 : an > bn ? 1 : 0;
    });
  };

  App.prototype.browseShell = function (filter) {
    return '<div class="bhead"><div class="sec-h"><h2>Browse species</h2>' +
      '<span class="sub" id="bcount"></span></div></div>' +
      '<div class="bfilterrow">' + ICONS.search +
      '<input id="bfilter" type="search" placeholder="Filter by any name…" value="' + esc(filter || '') + '" aria-label="Filter species"></div>' +
      '<div class="list" id="blist"></div>';
  };

  App.prototype.browseListHtml = function (filter, limit) {
    var rows = this.browseRows(filter);
    var slice = rows.slice(0, limit);
    if (!slice.length) {
      return { html: '<div class="none">No species match that filter.</div>', total: rows.length };
    }
    var html = slice.map(function (sp) {
      var dn = displayName(sp);
      var au = (sp.r || []).some(function (r) { return r.n === 'Australia'; });
      return '<div class="row" role="button" tabindex="0" data-key="' + esc(sp.k) + '">' +
        '<div class="av">' + esc(monogram(dn.main)) + '</div>' +
        '<div class="nm">' + esc(dn.main) + '</div>' +
        '<div class="sc">' + esc(dn.sci) + '</div>' +
        '<span class="rt">' + esc(au ? 'AU' : (sp.r[0] ? sp.r[0].n : '')) + '</span></div>';
    }).join('');
    if (rows.length > limit) {
      html += '<button class="morebtn" type="button" id="bmore">Show more (' +
        (rows.length - limit) + ' left)</button>';
    }
    return { html: html, total: rows.length };
  };

  App.prototype.browseRender = function (filter, limit) {
    var box = this.el('browse');
    var out = this.browseListHtml(filter, limit);
    var list = this.doc.getElementById('blist');
    if (list) list.innerHTML = out.html;
    var count = this.doc.getElementById('bcount');
    if (count) {
      count.textContent = out.total + ' with indicator data' +
        (out.total > limit ? ' · showing ' + Math.min(limit, out.total) : '');
    }
  };

  App.prototype.toggleBrowse = function (on) {
    var box = this.el('browse');
    var btn = this.el('browseBtn');
    if (!on) {
      box.className = 'card browse hidden';
      if (btn) { btn.className = 'chip ghost'; btn.setAttribute('aria-expanded', 'false'); }
      return;
    }
    this.browseLimit = 80;
    this.browseFilter = '';
    box.className = 'card browse';
    box.innerHTML = this.browseShell('');
    this.browseRender('', this.browseLimit);
    if (btn) { btn.className = 'chip on'; btn.setAttribute('aria-expanded', 'true'); }
  };

  /* ---- theme --------------------------------------------------------- */

  App.prototype.initTheme = function () {
    var self = this;
    var order = ['auto', 'light', 'dark'];
    var label = { auto: 'Colour theme: follow system', light: 'Colour theme: light', dark: 'Colour theme: dark' };
    function read() {
      try {
        var v = root.localStorage && root.localStorage.getItem('augury-theme');
        return order.indexOf(v) >= 0 ? v : 'auto';
      } catch (err) { return 'auto'; }
    }
    function apply(v) {
      var html = self.doc.documentElement;
      if (!html) return;
      html.setAttribute('data-theme', v);
      var btn = self.el('themeBtn');
      if (btn) {
        btn.setAttribute('aria-label', label[v]);
        btn.title = label[v];
      }
    }
    this.theme = read();
    apply(this.theme);
    var btn = this.el('themeBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        self.theme = order[(order.indexOf(self.theme) + 1) % order.length];
        apply(self.theme);
        try { if (root.localStorage) root.localStorage.setItem('augury-theme', self.theme); } catch (err) { /* ignore */ }
      });
    }
  };

  /* ---- wiring -------------------------------------------------------- */

  App.prototype.init = function () {
    var self = this, doc = this.doc;
    var q = this.el('q');
    if (!q) return;

    this.initTheme();

    var input = function () {
      self.sel = -1;
      self.render(q.value);
      self.suggest(q.value);
      var clear = self.el('clear');
      if (clear) clear.className = q.value ? 'on' : '';
    };

    q.addEventListener('input', input);

    q.addEventListener('keydown', function (e) {
      var box = self.el('suggest');
      var items = box && box.className.indexOf('on') >= 0 ? box.querySelectorAll('.sg') : [];
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!items.length) return;
        e.preventDefault();
        self.sel = e.key === 'ArrowDown'
          ? Math.min(self.sel + 1, items.length - 1)
          : Math.max(self.sel - 1, 0);
        for (var i = 0; i < items.length; i++) items[i].className = 'sg' + (i === self.sel ? ' sel' : '');
        if (items[self.sel] && items[self.sel].scrollIntoView) items[self.sel].scrollIntoView({ block: 'nearest' });
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

    var clear = this.el('clear');
    if (clear) {
      clear.addEventListener('click', function () {
        q.value = ''; self.sel = -1; self.render(''); self.suggest('');
        clear.className = ''; q.focus();
      });
    }

    var suggest = this.el('suggest');
    if (suggest) {
      suggest.addEventListener('mousedown', function (e) {
        var row = e.target.closest ? e.target.closest('.sg') : null;
        if (!row) return;
        e.preventDefault();
        var sp = self.store.byKey.get(row.getAttribute('data-key'));
        q.value = displayName(sp).main;
        self.closeSuggest();
        self.render(q.value);
      });
    }

    doc.addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var ex = t.closest('.ex');
      if (ex) {
        var keyAttr = ex.getAttribute('data-key');
        var term = ex.getAttribute('data-term') ||
          displayName(self.store.byKey.get(keyAttr)).main;
        q.value = term;
        self.closeSuggest();
        self.render(term);
        return;
      }
      var brow = t.closest('.browse .row');
      if (brow) {
        var sp2 = self.store.byKey.get(brow.getAttribute('data-key'));
        q.value = displayName(sp2).main;
        self.toggleBrowse(false);
        self.render(q.value);
        return;
      }
      var mrow = t.closest('.sg');
      if (mrow && mrow.parentNode === self.el('suggest')) return;
      if (!t.closest('.searchbox')) self.closeSuggest();

      var evb = t.closest('.ev-btn');
      if (evb) {
        var id = 'ev-' + evb.getAttribute('data-ev');
        var panel = doc.getElementById(id);
        if (!panel) return;
        var open = panel.className.indexOf('on') >= 0;
        panel.className = open ? 'ev' : 'ev on';
        evb.setAttribute('aria-expanded', open ? 'false' : 'true');
        var wrap = evb.closest('.ind');
        if (wrap) wrap.className = open ? 'ind' : 'ind is-open';
        return;
      }

      var act = t.closest('[data-act]');
      if (act) {
        var kind = act.getAttribute('data-act');
        var info = (self.lastReadings || [])[Number(act.getAttribute('data-idx'))];
        if (kind === 'print') { if (root.print) root.print(); return; }
        if (kind === 'sources') {
          var target = doc.getElementById('sources-' + act.getAttribute('data-idx'));
          if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          return;
        }
        if (kind === 'copy' && info) {
          self.copyText(self.readingText(info), 'Reading copied');
          return;
        }
      }

      var more = t.closest('#bmore');
      if (more) {
        self.browseLimit += 80;
        self.browseRender(self.browseFilter || '', self.browseLimit);
        return;
      }
    });

    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target && e.target.classList && e.target.classList.contains('row') &&
          e.target.closest && e.target.closest('.browse')) {
        e.target.click();
      }
    });

    var browse = this.el('browse');
    if (browse) {
      browse.addEventListener('input', function (e) {
        if (e.target.id !== 'bfilter') return;
        self.browseFilter = e.target.value;
        self.browseRender(self.browseFilter, self.browseLimit);
      });
    }

    Array.prototype.forEach.call(doc.querySelectorAll('.chip[data-region]'), function (c) {
      c.addEventListener('click', function () {
        Array.prototype.forEach.call(doc.querySelectorAll('.chip[data-region]'), function (o) {
          o.className = 'chip';
          o.setAttribute('aria-pressed', 'false');
        });
        c.className = 'chip on';
        c.setAttribute('aria-pressed', 'true');
        self.region = c.getAttribute('data-region');
        if (q.value) self.render(q.value);
      });
    });

    var browseBtn = this.el('browseBtn');
    if (browseBtn) {
      browseBtn.addEventListener('click', function () {
        var on = self.el('browse').className.indexOf('hidden') >= 0;
        self.toggleBrowse(on);
      });
    }

    var howBtn = this.el('howBtn');
    if (howBtn) {
      howBtn.addEventListener('click', function () {
        var panel = self.el('how');
        if (!panel) return;
        var opening = panel.className.indexOf('hidden') >= 0;
        panel.className = opening ? 'card how' : 'card how hidden';
        howBtn.setAttribute('aria-expanded', opening ? 'true' : 'false');
        if (opening && panel.scrollIntoView) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    }

    var home = this.el('brandHome');
    if (home) {
      home.addEventListener('click', function (e) {
        e.preventDefault();
        q.value = ''; self.sel = -1;
        self.toggleBrowse(false);
        self.render(''); self.suggest('');
        var c = self.el('clear'); if (c) c.className = '';
        if (root.scrollTo) root.scrollTo({ top: 0, behavior: 'smooth' });
        q.focus();
      });
    }

    // "/" focuses the search box, Escape leaves it — a keyboard path to the app.
    doc.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      var typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
      if (e.key === '/' && !typing) { e.preventDefault(); q.focus(); q.select(); }
    });

    var totop = this.el('totop');
    if (totop) {
      totop.addEventListener('click', function () {
        if (root.scrollTo) root.scrollTo({ top: 0, behavior: 'smooth' });
      });
      var ticking = false;
      var onScroll = function () {
        if (ticking) return;
        ticking = true;
        (root.requestAnimationFrame || function (fn) { setTimeout(fn, 60); })(function () {
          ticking = false;
          var y = root.pageYOffset || (doc.documentElement && doc.documentElement.scrollTop) || 0;
          totop.className = y > 640 ? 'on' : '';
        });
      };
      if (root.addEventListener) root.addEventListener('scroll', onScroll, { passive: true });
    }

    var meta = this.meta;
    var footmeta = this.el('footmeta');
    if (footmeta) {
      footmeta.innerHTML =
        '<b>' + esc(meta.species_count) + '</b> species' +
        '<span class="dot">·</span><b>' + esc(meta.with_data || '') + '</b> with indicator data' +
        '<span class="dot">·</span>Australia, UK and Europe' +
        '<span class="dot">·</span><a href="https://github.com/RegeneratusLabs/AUGURY" target="_blank" rel="noopener noreferrer">Apache-2.0 code / CC-BY-4.0 data</a>';
    }

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
        var answer = document.getElementById('answer');
        if (answer) {
          answer.innerHTML =
            '<div class="card empty"><div class="big">The embedded database could not be read</div><p>' +
            String(err && err.message ? err.message : err) + '</p></div>';
        }
      }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
