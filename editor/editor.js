/* The electrical editor (vienna_planning_toolkit). vpt/editor_page.py builds the page and puts this script last; core.js (before
   it) provides the viewer, popups, tables and tabs.

   The plan (script#vpt-plan: the synthetic flat by default; Open plan or paste replaces it) gives one stage per storey: its
   drawing (SVG with one group per DXF layer, recoloured light-on-black for the screen and dark-on-white for print), its layers,
   the model -> drawing affine, rooms, doors, the placement suggestions of every rule set and, for one storey, the generated
   examples. Placed symbols live in one <g class="el-layer"> per electrical layer, drawn from the symbol library
   (script#el-symbols). Positions are MODEL coordinates (the inverse of the storey's affine), so zoom and pan never move a symbol.
   Layout files: schema script#el-schema (version 2), validated with the same keyword subset as vpt/el_layout.py; opening checks
   the drawing checksum and the storey (match / different / could-not-tell; only match opens). Draft autosave in localStorage
   (when the browser allows it). Texts: script#el-config messages (presets/editor_docs.json).

   Connect mode links a switch to the lights it works (only codes in the switch's connectable_to list); light groups, the
   proposed switch type and Apply; the layout checks H1-H9 (mirror vpt/el_checks.py); the suggestions of the chosen rule set (computed by vpt/el_rules.py
   into the plan file: shown here as faint rings, and snapped to). Groups, proposals, link rules and hints mirror vpt/el_links.py.

   Variants (CFG.variant): pages = Save layout / Save to file / Save parameters / Print view exist; artifact = they do not
   (downloads, file pickers, print and dialogs are inert there): Copy layout / Copy parameters instead. Both: in-page
   confirmation (never the browser's own dialogs), files read with FileReader, paste of a plan, layout or parameter file. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  function J(id) { var el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; }
  var LIB = J('el-symbols'), SCHEMA = J('el-schema'), PLAN_SCHEMA = J('el-plan-schema'), CFG = J('el-config'), RULES = J('el-rules'), PARAMS = J('el-params');
  var M = CFG.messages, V = CFG.variant || {};
  var SWC = RULES.switching, LINKL = RULES.links.layer, MATCH = 'match', DIFF = 'different', UNK = 'could-not-tell';
  function fmt(s, o) { return String(s).replace(/\{(\w+)\}/g, function (_, k) { return o && k in o ? o[k] : '{' + k + '}'; }); }
  function escH(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function store(k, v) { try { if (v === undefined) return window.localStorage.getItem(k); if (v === null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v); } catch (err) { return null; } return null; }
  function setById(id) { return LIB.sets.filter(function (s) { return s.id === id; })[0] || null; }
  function ruleSet(id) { return RULES.rule_sets.filter(function (s) { return s.id === id; })[0] || null; }
  function r6(v) { return Math.round(v * 1e6) / 1e6; }
  function num(id) { var n = parseInt(String(id).slice(1), 10); return isFinite(n) ? n : 0; }
  function more(a) { return '<p class="more"><a class="doclink" href="#' + escH(a) + '">More &rarr;</a></p>'; }
  function tipList(title, items, anchor) { return '<p class="tip-h"><b>' + escH(title) + '</b></p><ul class="tipl">' +
    items.map(function (x) { return '<li>' + escH(x).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>') + '</li>'; }).join('') + '</ul>' + (anchor ? more(anchor) : ''); }

  // ---- in-page confirmation (never the browser's dialog: it is inert in the shareable demo) and the copy box ----
  var ASK = document.querySelector('.vpt-ask'), askCb = null;
  function ask(msg, onYes, onNo) {
    if (askCb && askCb.no) askCb.no();
    askCb = { yes: onYes, no: onNo || null };
    ASK.querySelector('#vpt-ask-msg').textContent = msg; ASK.hidden = false;
    var y = ASK.querySelector('[data-ask="yes"]'); if (y) y.focus();
  }
  ASK.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button[data-ask]') : null; if (!b || !askCb) return;
    var cb = askCb; askCb = null; ASK.hidden = true;
    if (b.getAttribute('data-ask') === 'yes') cb.yes(); else if (cb.no) cb.no();
  });
  var COPY = document.querySelector('.vpt-copybox');
  COPY.querySelector('[data-copybox="close"]').addEventListener('click', function () { COPY.hidden = true; });
  function copyFallback(text) {
    COPY.querySelector('.vpt-copymsg').textContent = M.copy_fallback;
    var ta = COPY.querySelector('textarea'); ta.value = text; COPY.hidden = false; ta.focus(); ta.select();
  }
  // navigator.clipboard.writeText inside the click handler; a refusal (or no clipboard API) shows the text, selected
  function copyText(text, onOk) {
    var done = false;
    function fb() { if (done) return; done = true; copyFallback(text); }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { done = true; COPY.hidden = true; onOk(); }, fb);
      else fb();
    } catch (err) { fb(); }
  }
  function readFile(f, cb) {
    var r = new FileReader();
    r.onload = function () { cb(String(r.result), f.name); };
    r.onerror = function () { cb(null, f.name, r.error); };
    r.readAsText(f);
  }
  // @pages-only-start (tools/build_editor.py leaves these regions out of the shareable demo, where they would be inert)
  function download(text, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' })); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }
  // @pages-only-end
  var GSTAT = document.querySelector('.vpt-status');
  function gstatus(msg, kind) { GSTAT.textContent = msg; GSTAT.title = msg; GSTAT.className = 'vpt-status el-status' + (kind ? ' el-' + kind : ''); }

  // ---- the JSON Schema subset: the same keywords as vpt/el_layout.py validate() ----
  function isType(x, t) {
    if (t === 'number') return typeof x === 'number' && isFinite(x);
    if (t === 'integer') return typeof x === 'number' && isFinite(x) && Math.floor(x) === x;
    if (t === 'string') return typeof x === 'string';
    if (t === 'boolean') return typeof x === 'boolean';
    if (t === 'null') return x === null;
    if (t === 'array') return Array.isArray(x);
    if (t === 'object') return x !== null && typeof x === 'object' && !Array.isArray(x);
    return false;
  }
  function validate(doc, schema) {
    var out = [], same = function (a, b) { return JSON.stringify(a) === JSON.stringify(b); };
    function go(x, s, path) {
      if (s.$ref) s = schema.$defs[s.$ref.replace('#/$defs/', '')];
      if (s.type) { var ts = Array.isArray(s.type) ? s.type : [s.type];
        if (!ts.some(function (t) { return isType(x, t); })) { out.push(path + ': type, want ' + ts.join('/')); return; } }
      if ('const' in s && !same(x, s.const)) out.push(path + ': const ' + JSON.stringify(s.const) + ' wanted');
      if (s.enum && !s.enum.some(function (e) { return same(e, x); })) out.push(path + ': enum');
      if (typeof x === 'string') { if ('minLength' in s && x.length < s.minLength) out.push(path + ': minLength');
        if (s.pattern && !new RegExp(s.pattern).test(x)) out.push(path + ': pattern'); }
      if (typeof x === 'number') { if ('minimum' in s && x < s.minimum) out.push(path + ': minimum');
        if ('exclusiveMinimum' in s && !(x > s.exclusiveMinimum)) out.push(path + ': exclusiveMinimum'); }
      if (isType(x, 'object')) {
        (s.required || []).forEach(function (k) { if (!(k in x)) out.push(path + ': required property ' + k + ' missing'); });
        Object.keys(x).forEach(function (k) { if (s.properties && k in s.properties) go(x[k], s.properties[k], path + '.' + k);
          else if (s.additionalProperties === false) out.push(path + ': additional property ' + k + ' not allowed');
          else if (s.additionalProperties && typeof s.additionalProperties === 'object') go(x[k], s.additionalProperties, path + '.' + k); });
      }
      if (Array.isArray(x)) { if ('minItems' in s && x.length < s.minItems) out.push(path + ': minItems');
        if ('maxItems' in s && x.length > s.maxItems) out.push(path + ': maxItems');
        if (s.items) x.forEach(function (v, i) { go(v, s.items, path + '[' + i + ']'); }); }
    }
    go(doc, schema, '$'); return out;
  }
  // vpt/el_layout.py migrate(): version 1 -> 2 (no links, the default rule set)
  function migrate(o) {
    if (o.schema_version === 2) { o.rule_set = o.rule_set || RULES.default_rule_set; return ''; }
    if (o.schema_version === 1) { if (o.links.length) return 'a version-1 file with links (version 1 had none)';
      if ('rule_set' in o) return 'a version-1 file with a rule set (version 1 had none)';
      o.schema_version = 2; o.links = []; o.rule_set = RULES.default_rule_set; return ''; }
    return 'unknown schema_version ' + o.schema_version;
  }

  // ---- links, groups, proposal, hints: mirror vpt/el_links.py ----
  function defIn(set, code) { return set.symbols.filter(function (s) { return s.code === code; })[0] || null; }
  function isSwitch(set, code) { var d = defIn(set, code); return !!d && d.category === SWC.switch_category; }
  function isLight(set, code) { var d = defIn(set, code); return !!d && d.category === SWC.light_category; }
  function canLink(set, a, b) {
    var d = defIn(set, a);
    if (!d || !isSwitch(set, a)) return [false, a + ' is not a switch or push-button: a link starts at a switch'];
    if (d.connectable_to.indexOf(b) < 0) return [false, b + ' cannot be connected to ' + a + ' (allowed: ' + (d.connectable_to.join(', ') || 'none') + ')'];
    return [true, ''];
  }
  function linkProblems(symbols, links, set) {
    var by = {}, out = [], ids = {}, pairs = {};
    symbols.forEach(function (s) { by[s.id] = s; });
    links.forEach(function (l) {
      if (ids[l.id]) out.push('duplicate link id ' + l.id); ids[l.id] = 1;
      var a = by[l.from], b = by[l.to];
      if (!a || !b) { out.push('link ' + l.id + ': unknown symbol ' + (a ? l.to : l.from)); return; }
      if (a.id === b.id) { out.push('link ' + l.id + ': a symbol linked to itself'); return; }
      var c = canLink(set, a.code, b.code); if (!c[0]) out.push('link ' + l.id + ': ' + c[1]);
      if (pairs[a.id + '>' + b.id]) out.push('link ' + l.id + ': ' + a.id + ' -> ' + b.id + ' linked twice'); pairs[a.id + '>' + b.id] = 1;
    });
    return out;
  }
  function groups(symbols, links) {
    var parent = {}, known = {}, froms = {}, comp = {}, order = [];
    symbols.forEach(function (s) { known[s.id] = 1; });
    function find(x) { if (!(x in parent)) parent[x] = x; while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; }
    links.forEach(function (l) { if (known[l.from] && known[l.to]) parent[find(l.from)] = find(l.to); froms[l.from] = 1; });
    links.forEach(function (l) { [l.from, l.to].forEach(function (x) { if (!known[x]) return; var r = find(x);
      if (!comp[r]) { comp[r] = { switches: {}, lights: {} }; order.push(r); } comp[r][froms[x] ? 'switches' : 'lights'][x] = 1; }); });
    var srt = function (o) { return Object.keys(o).sort(function (a, b) { return num(a) - num(b); }); };
    return order.map(function (r) { return { switches: srt(comp[r].switches), lights: srt(comp[r].lights) }; })
      .sort(function (a, b) { return num((a.lights[0] || a.switches[0])) - num((b.lights[0] || b.switches[0])); });
  }
  function proposal(sw) {      // sw: [[id, code]]
    sw = sw.slice().sort(function (a, b) { return num(a[0]) - num(b[0]); });
    var codes = {}, i;
    if (sw.some(function (t) { return t[1] === SWC.push_button; })) { sw.forEach(function (t) { codes[t[0]] = t[1]; });
      return { type: 'push', name: SWC.names.push, name_en: SWC.names_en.push, codes: codes, matches: true }; }
    var n = sw.length, typ = n === 1 ? '1' : n === 2 ? '2' : '3', want = n === 1 ? [SWC.one_way] : [SWC.two_way, SWC.two_way];
    for (i = 2; i < n; i++) want.push(SWC.intermediate);
    var pool = want.slice(), rest = [];
    sw.forEach(function (t) { var j = pool.indexOf(t[1]); if (j >= 0) { codes[t[0]] = t[1]; pool.splice(j, 1); } else rest.push(t[0]); });
    rest.forEach(function (id) { codes[id] = pool.shift(); });
    return { type: typ, name: SWC.names[typ], name_en: SWC.names_en[typ], codes: codes, matches: sw.every(function (t) { return codes[t[0]] === t[1]; }) };
  }
  function segDist(p, a, b) { var dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
    var t = L2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2));
    return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy)); }
  function doorSegs(d) { if (!d.hinge || !d.ends) return [];
    if (d.closed_end === 'a' || d.closed_end === 'b') return [[d.hinge, d.ends[d.closed_end]]];
    return [[d.hinge, d.ends.a], [d.hinge, d.ends.b]]; }
  function stat(items, nothing) { if (nothing) return UNK; if (items.some(function (i) { return i.status === DIFF; })) return DIFF;
    if (items.some(function (i) { return i.status === UNK; })) return UNK; return MATCH; }
  function hints(symbols, links, doors, k, setId, set, roomsKnown) {
    var lights = symbols.filter(function (s) { return isLight(set, s.code); }), switches = symbols.filter(function (s) { return isSwitch(set, s.code); });
    var to = {}, fr = {}; links.forEach(function (l) { to[l.to] = 1; fr[l.from] = 1; });
    var i1 = lights.filter(function (s) { return !to[s.id]; }).map(function (s) { return { symbol: s.id, status: DIFF, why: 'no switch works this light' }; });
    var i2 = switches.filter(function (s) { return !fr[s.id]; }).map(function (s) { return { symbol: s.id, status: DIFF, why: 'this switch works no light' }; });
    var h1 = { id: 'H1', items: i1, status: stat(i1, !lights.length), detail: lights.length ? i1.length + ' of ' + lights.length + ' light(s) without a switch' : 'no light placed: nothing to check' };
    var h2 = { id: 'H2', items: i2, status: stat(i2, !switches.length), detail: switches.length ? i2.length + ' of ' + switches.length + ' switch(es) without a light' : 'no switch placed: nothing to check' };
    var v = (RULES.values[setId] || {}).hint_switch_near_door_m, near = v ? v.value : null, h3;
    if (!lights.length) h3 = { id: 'H3', items: [], status: UNK, detail: 'no light placed: nothing to check' };
    else if (near === null || near === undefined) h3 = { id: 'H3', items: [], status: UNK, detail: 'no value yet: hint_switch_near_door_m (rule set ' + setId + ')' };
    else if (!roomsKnown || !k) h3 = { id: 'H3', items: [], status: UNK, detail: 'the plan has no rooms and doors: could not tell' };
    else {
      var items = [], rooms = {};
      lights.forEach(function (s) { if (!s.room) items.push({ symbol: s.id, status: UNK, why: "the light's room could not be told" }); else rooms[s.room] = 1; });
      Object.keys(rooms).sort(function (a, b) { return a.length - b.length || (a < b ? -1 : a > b ? 1 : 0); }).forEach(function (rid) {
        var ds = doors.filter(function (d) { return (d.rooms || []).indexOf(rid) >= 0; });
        if (!ds.length) { items.push({ room: rid, status: UNK, why: 'no door of this room known (plan file)' }); return; }
        ds.forEach(function (d) { var segs = doorSegs(d);
          if (!segs.length) { items.push({ room: rid, door: d.id, status: UNK, why: "the door's position is not known" }); return; }
          var best = Infinity; switches.forEach(function (s) { segs.forEach(function (g) { best = Math.min(best, segDist([s.x, s.y], g[0], g[1])); }); });
          var ok = best <= near * k;
          items.push({ room: rid, door: d.id, status: ok ? MATCH : DIFF, why: ok ? 'a switch at the door' : 'no switch within ' + near + ' m of the door' }); });
      });
      var bad = items.filter(function (i) { return i.status === DIFF; }).length;
      h3 = { id: 'H3', items: items, status: stat(items, !items.length), detail: bad + ' door(s) of rooms with a light have no switch within ' + near + ' m' };
    }
    return [h1, h2, h3];
  }
  // ---- layout checks H1-H9: mirror vpt/el_checks.py (same ids, details and items) ----
  var CK = RULES.checks, SOCKET_TYPES = ['living', 'bedroom', 'kitchen', 'wet', 'hall'];
  function rval(setId, key) { var v = (RULES.values[setId] || {})[key]; return v ? (v.value === undefined ? null : v.value) : null; }
  function missing(setId, keys) { var gone = keys.filter(function (k) { return rval(setId, k) === null; });
    return gone.length ? { items: [], status: UNK, detail: 'no value yet: ' + gone.join(', ') + ' (rule set ' + setId + ')' } : null; }
  function typeKeys() { return ['kitchen_keywords'].concat(CK.room_types.filter(function (t) { return t !== 'kitchen' && t !== 'wet'; }).map(function (t) { return 'room_words_' + t; })); }
  function roomType(r, setId) {
    var name = String(r.name || '').toLowerCase(), has = function (ws) { return (ws || []).some(function (w) { return name.indexOf(String(w).toLowerCase()) >= 0; }); };
    for (var i = 0; i < CK.room_types.length; i++) { var t = CK.room_types[i];
      if (t === 'kitchen') { if (has(rval(setId, 'kitchen_keywords'))) return t; }
      else if (t === 'wet') { if (r.wet) return t; }
      else if (has(rval(setId, 'room_words_' + t))) return t; }
    return null;
  }
  function catOf(set, code) { var d = defIn(set, code); return d ? d.category : null; }
  function layoutChecks(symbols, links, rooms, doors, k, setId, set, roomsKnown) {
    var out = {}; hints(symbols, links, doors, k, setId, set, roomsKnown).forEach(function (h) { out[h.id] = h; });
    var inRoom = {}; symbols.forEach(function (s) { if (s.room) (inRoom[s.room] = inRoom[s.room] || []).push(s); });
    var mine = function (id) { return inRoom[id] || []; };
    var noRooms = (!roomsKnown || !rooms.length) ? { items: [], status: UNK, detail: 'the plan has no rooms: could not tell' } : null;
    var types = {}; rooms.forEach(function (r) { types[r.id] = roomType(r, setId); });
    var unkType = function (r) { return { room: r.id, status: UNK, why: "the room's type could not be told from its label" }; };
    var nBad = function (items) { return items.filter(function (i) { return i.status === DIFF; }).length; };
    // H4
    var h = noRooms || missing(setId, typeKeys().concat(['check_light_room_types'])), items, want;
    if (!h) { var need = rval(setId, 'check_light_room_types'); items = [];
      rooms.forEach(function (r) { var t = types[r.id]; if (t === null) { items.push(unkType(r)); return; } if (need.indexOf(t) < 0) return;
        var n = mine(r.id).filter(function (s) { return isLight(set, s.code); }).length;
        items.push({ room: r.id, status: n ? MATCH : DIFF, why: n ? n + ' light(s)' : 'no light' }); });
      h = { items: items, status: stat(items, !items.length), detail: items.length ? nBad(items) + ' of ' + items.filter(function (i) { return i.status !== UNK; }).length +
        ' room(s) that need a light have none' : 'no room of the types that need a light: nothing to check' }; }
    out.H4 = { id: 'H4', items: h.items, status: h.status, detail: h.detail };
    // H5
    h = noRooms || missing(setId, typeKeys().concat(SOCKET_TYPES.map(function (t) { return 'check_min_sockets_' + t; })));
    if (!h) { var per = CK.outlets_per_symbol || {}; items = [];
      rooms.forEach(function (r) { var t = types[r.id]; if (t === null) { items.push(unkType(r)); return; } if (SOCKET_TYPES.indexOf(t) < 0) return;
        var w = rval(setId, 'check_min_sockets_' + t), n = 0;
        mine(r.id).forEach(function (s) { if (catOf(set, s.code) === CK.socket_category) n += (s.code in per ? per[s.code] : 1); });
        items.push({ room: r.id, status: n >= w ? MATCH : DIFF, why: n + ' of at least ' + w + ' socket outlet(s) (' + t + ')' }); });
      h = { items: items, status: stat(items, !items.length), detail: items.length ? nBad(items) + ' room(s) with fewer socket outlets than our starting minimum' :
        'no room of a type with a minimum: nothing to check' }; }
    out.H5 = { id: 'H5', items: h.items, status: h.status, detail: h.detail };
    // H6
    h = noRooms || missing(setId, typeKeys().concat(['check_min_appliance_outlets_kitchen']));
    if (!h) { want = rval(setId, 'check_min_appliance_outlets_kitchen'); items = [];
      rooms.forEach(function (r) { if (types[r.id] !== 'kitchen') return;
        var cooker = mine(r.id).some(function (s) { return CK.cooker_codes.indexOf(s.code) >= 0; });
        var n = mine(r.id).filter(function (s) { return catOf(set, s.code) === CK.appliance_category; }).length;
        items.push({ room: r.id, status: cooker && n >= want ? MATCH : DIFF, why: (cooker ? 'a' : 'no') + ' cooker outlet, ' + n + ' of at least ' + want + ' appliance outlet(s)' }); });
      h = { items: items, status: stat(items, !items.length), detail: items.length ? nBad(items) + ' of ' + items.length +
        ' kitchen(s) without a cooker outlet or with too few appliance outlets' : 'no kitchen in the plan: nothing to check' }; }
    out.H6 = { id: 'H6', items: h.items, status: h.status, detail: h.detail };
    // H7
    h = noRooms || missing(setId, typeKeys().concat(['check_smoke_room_types']));
    if (!h) { var sneed = rval(setId, 'check_smoke_room_types'); items = [];
      rooms.forEach(function (r) { var t = types[r.id]; if (t === null) { items.push(unkType(r)); return; } if (sneed.indexOf(t) < 0) return;
        var ok = mine(r.id).some(function (s) { return CK.smoke_codes.indexOf(s.code) >= 0; });
        items.push({ room: r.id, status: ok ? MATCH : DIFF, why: ok ? 'a smoke alarm' : 'no smoke alarm' }); });
      h = { items: items, status: stat(items, !items.length), detail: items.length ? nBad(items) + ' room(s) without a smoke alarm (our starting rule; Austrian rules not checked)' :
        'no room of the types that need a smoke alarm: nothing to check' }; }
    out.H7 = { id: 'H7', items: h.items, status: h.status, detail: h.detail };
    // H8
    var wet = {}; rooms.forEach(function (r) { if (r.wet) wet[r.id] = 1; });
    var ws = symbols.filter(function (s) { return s.room && wet[s.room] && catOf(set, s.code) === CK.socket_category; });
    out.H8 = { id: 'H8', status: UNK, items: ws.map(function (s) { return { symbol: s.id, status: UNK, why: 'zones unknown' }; }),
      detail: 'no shower or bath zones are known in the plan: could not tell (' + ws.length + ' socket(s) in wet rooms)' };
    // H9
    var lost = symbols.filter(function (s) { return !s.room; }).map(function (s) { return { symbol: s.id, status: UNK, why: 'outside every room' }; });
    out.H9 = { id: 'H9', items: lost, status: lost.length || !symbols.length ? UNK : MATCH,
      detail: symbols.length ? lost.length + ' of ' + symbols.length + ' symbol(s) outside every room' : 'no symbol placed: nothing to check' };
    return ['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'H7', 'H8', 'H9'].map(function (i) { return out[i]; });
  }
  function kindOf(code) { var out = null; Object.keys(RULES.suggest).forEach(function (k) { if (RULES.suggest[k].codes.indexOf(code) >= 0) out = k; }); return out; }

  // ---- model <-> view: X = a*x + c*y + e, Y = b*x + d*y + f (vpt/dxf_svg.py affine) and its inverse ----
  function toView(A, x, y) { return [A[0] * x + A[2] * y + A[4], A[1] * x + A[3] * y + A[5]]; }
  function toModel(A, X, Y) { var det = A[0] * A[3] - A[1] * A[2]; X -= A[4]; Y -= A[5];
    return [(A[3] * X - A[2] * Y) / det, (-A[1] * X + A[0] * Y) / det]; }
  function inside(p, poly) { var c = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) { var a = poly[i], b = poly[j];
      if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) c = !c; }
    return c; }
  function preview(set, def, cls) {
    var b = def.box, m = Math.max(b[2], b[3]), col = colourOf(set, def);
    return '<svg class="' + cls + '" viewBox="' + (b[0] + b[2] / 2 - m / 2) + ' ' + (b[1] + b[3] / 2 - m / 2) + ' ' + m + ' ' + m + '" aria-hidden="true">' +
      '<g class="el-symg el-c-' + def.category + '" fill="none" stroke="' + col + '" color="' + col + '" stroke-width="' + set.stroke_mm + '" stroke-linecap="round">' + def.svg + '</g></svg>';
  }
  function colourOf(set, def) { return PV('colours_print', def.category); }      // the attribute (print) colour; the screen colour is CSS

  // ---- colours and line widths (presets/el_parameters.json): one generated style for the whole page ----
  function PV(sec, key) { var s = PARAMS.sections[sec]; return s && s.values[key] ? s.values[key].value : null; }
  function hexRgb(h) { h = String(h).trim();
    var m = h.match(/^#([0-9a-f]{3})$/i); if (m) h = '#' + m[1].split('').map(function (c) { return c + c; }).join('');
    m = h.match(/^#([0-9a-f]{6})$/i); if (m) return [0, 2, 4].map(function (i) { return parseInt(m[1].slice(i, i + 2), 16); });
    m = h.match(/^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)/i); if (m) return [+m[1], +m[2], +m[3]];
    var named = { black: [0, 0, 0], white: [255, 255, 255] }; return named[h.toLowerCase()] || null; }
  function toHsl(c) { var r = c[0] / 255, g = c[1] / 255, b = c[2] / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, h = 0, s = 0, d = mx - mn;
    if (d) { s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn); h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h /= 6; }
    return [h, s, l]; }
  function hslHex(h, s, l) { function f(n) { var k = (n + h * 12) % 12, a = s * Math.min(l, 1 - l);
      return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))); }
    return '#' + [f(0), f(8), f(4)].map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join(''); }
  // a CAD colour -> its screen (light on black: lightness turned round) or print (dark, muted: lightness kept in order) colour
  function recolour(col, kind, sec) {
    var c = hexRgb(col); if (!c) return null; var hsl = toHsl(c), lo = PV(sec, kind + '_lightness_min'), hi = PV(sec, kind + '_lightness_max');
    var l = sec === 'drawing_screen' ? hi - hsl[2] * (hi - lo) : lo + hsl[2] * (hi - lo);
    return hslHex(hsl[0], hsl[1] * PV(sec, 'saturation'), Math.max(0, Math.min(1, l))); }
  var SCR = '@media screen { ', PRN = '@media print { ';
  function bgRules(css) {                    // the drawing <style>'s class rules, recoloured for screen and print
    var scr = [], prn = [], re = /\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}/g, m;
    while ((m = re.exec(css))) { var dec = m[2], out = { s: [], p: [] }, isText = /--vpt-text/.test(dec);   // a text's fill is a line colour
      [['stroke', 'stroke'], ['fill', isText ? 'stroke' : 'fill']].forEach(function (pr) { var mm = dec.match(new RegExp('(?:^|;)\\s*' + pr[0] + '\\s*:\\s*([^;]+)'));
        if (!mm || /none|url/.test(mm[1])) return; var a = recolour(mm[1], pr[1], 'drawing_screen'), b = recolour(mm[1], pr[1], 'drawing_print');
        if (a) out.s.push(pr[0] + ':' + a); if (b) out.p.push(pr[0] + ':' + b); });
      if (out.s.length) scr.push('svg.el-svg g.el-bg .' + m[1] + '{' + out.s.join(';') + '}');
      if (out.p.length) prn.push('svg.el-svg g.el-bg .' + m[1] + '{' + out.p.join(';') + '}'); }
    return SCR + scr.map(function (r) { return 'body:not(.dwg-printing) ' + r; }).join(' ') + ' } ' +
      prn.map(function (r) { return 'body.dwg-printing ' + r; }).join(' ') + ' ' + PRN + prn.join(' ') + ' }';
  }
  function pageStyle() {
    var cats = LIB.sets.reduce(function (a, s) { s.categories.forEach(function (c) { if (a.indexOf(c.key) < 0) a.push(c.key); }); return a; }, []);
    function pal(sec) { var o = []; cats.forEach(function (c) { var v = PV(sec, c); if (v) o.push('.el-c-' + c + '{stroke:' + v + ';color:' + v + '}'); });
      cats.forEach(function (c) { var v = PV(sec, c); if (v) o.push('.el-svg .el-ghost-m.el-c-' + c + ' circle{stroke:' + v + '}'); });
      return o; }
    var w = function (k) { return PV('screen_lines', k); }, sb = PV('colours_screen', 'background'), pb = PV('colours_print', 'background'), dash = w('link_dash_px');
    var scr = pal('colours_screen').concat([
      '.el-view .dwg-paper,.el-chip{background:' + sb + '}', '.el-svg rect.paper{fill:' + sb + '}',
      '.el-svg .el-symg>*{vector-effect:non-scaling-stroke}', '.el-svg .el-symg{stroke-width:' + w('symbol_stroke_px') + 'px}',
      '.el-svg .el-link-line{stroke:' + PV('colours_screen', 'link') + ';stroke-width:' + w('link_stroke_px') + 'px;stroke-dasharray:' + dash.join(' ') + ';vector-effect:non-scaling-stroke}',
      '.el-svg .el-link-on .el-link-line{stroke-width:' + (2 * w('link_stroke_px')) + 'px}',
      '.el-svg .el-link-hit{stroke-width:12px;vector-effect:non-scaling-stroke}',
      '.el-svg .el-ghost-m circle{stroke:' + PV('colours_screen', 'marker') + ';stroke-width:' + w('marker_stroke_px') + 'px;vector-effect:non-scaling-stroke;fill:rgba(255,255,255,0.08);opacity:' + w('marker_opacity') + '}',
      '.el-svg .el-ghost-m.el-ghost-cur circle{opacity:1}',
      '.el-svg .el-ghost-m.el-ghost-hit circle{stroke:' + PV('colours_screen', 'marker_hit') + ';stroke-width:' + (1.5 * w('marker_stroke_px')) + 'px;opacity:1}',
      '.el-svg .el-sel{stroke:' + PV('colours_screen', 'selection') + ';stroke-width:' + w('selection_stroke_px') + 'px;vector-effect:non-scaling-stroke}',
      '.el-svg .el-sym.el-can .el-hit{stroke:' + PV('colours_screen', 'connect_allowed') + ';stroke-width:2.5px;vector-effect:non-scaling-stroke}',
      '.el-svg .el-sym.el-src .el-hit{stroke:' + PV('colours_screen', 'connect_source') + ';stroke-width:3px;vector-effect:non-scaling-stroke}',
      '.el-svg .el-sym.el-dim{opacity:' + w('dim_opacity') + '}']);
    var prn = pal('colours_print').concat(['.el-view .dwg-paper,.el-chip{background:' + pb + '}', '.el-svg rect.paper{fill:' + pb + '}',
      '.el-svg .el-link-line{stroke:' + PV('colours_print', 'link') + '}', '.el-svg .el-sym.el-dim{opacity:1}', '.el-svg .el-sym .el-hit{stroke:none}']);
    return SCR + scr.map(function (r) { return 'body:not(.dwg-printing) ' + r; }).join(' ') + ' } ' +
      prn.map(function (r) { return 'body.dwg-printing ' + r; }).join(' ') + ' ' + PRN + prn.join(' ') + ' }';
  }
  var pages = [];
  function applyStyle() {
    var st = document.getElementById('el-style'); if (!st) { st = document.createElement('style'); st.id = 'el-style'; (document.head || document.body).appendChild(st); }
    st.textContent = pageStyle();
    pages.forEach(function (pg) { if (pg.elRestyle) pg.elRestyle(); });
  }

  // ---- the Parameters panel: presets/el_parameters.json shown, edited, copied, saved, loaded (one home for the values) ----
  var PMETA = J('el-params-meta') || {}, PSCHEMA = J('el-params-schema'), PARAMS0 = JSON.parse(JSON.stringify(PARAMS));
  var PEDITED = false, PSHA = PMETA.sha256 || '', PKEY = 'el-params:' + (PMETA.sha256 || 'x'), LIVE_RULES = PMETA.live_rules || [];
  // SHA-256 (FIPS 180-4) of a string's UTF-8 bytes, synchronous (the layout file records the parameters it was made with)
  function sha256(str) {
    var b = unescape(encodeURIComponent(str)), K2 = [], H = [], i, j, isP = function (n) { for (var f = 2; f * f <= n; f++) if (n % f === 0) return false; return true; };
    var frac = function (x) { return ((x - Math.floor(x)) * 4294967296) | 0; };
    for (i = 2, j = 0; j < 64; i++) if (isP(i)) { if (j < 8) H[j] = frac(Math.pow(i, 1 / 2)); K2[j++] = frac(Math.pow(i, 1 / 3)); }
    var w = [], l = b.length * 8; b += '\x80'; while (b.length % 64 - 56) b += '\x00';
    for (i = 0; i < b.length; i++) w[i >> 2] |= b.charCodeAt(i) << ((3 - i % 4) * 8);
    w[w.length] = (l / 4294967296) | 0; w[w.length] = l | 0;
    var r = function (x, n) { return (x >>> n) | (x << (32 - n)); };
    for (j = 0; j < w.length; j += 16) { var a = H.slice(0), W = w.slice(j, j + 16);
      for (i = 0; i < 64; i++) { if (i >= 16) { var x = W[i - 15], y = W[i - 2];
          W[i] = (W[i - 16] + (r(x, 7) ^ r(x, 18) ^ (x >>> 3)) + W[i - 7] + (r(y, 17) ^ r(y, 19) ^ (y >>> 10))) | 0; }
        var t1 = (a[7] + (r(a[4], 6) ^ r(a[4], 11) ^ r(a[4], 25)) + ((a[4] & a[5]) ^ (~a[4] & a[6])) + K2[i] + W[i]) | 0;
        var t2 = ((r(a[0], 2) ^ r(a[0], 13) ^ r(a[0], 22)) + ((a[0] & a[1]) ^ (a[0] & a[2]) ^ (a[1] & a[2]))) | 0;
        a = [(t1 + t2) | 0].concat(a.slice(0, 7)); a[4] = (a[4] + t1) | 0; }
      for (i = 0; i < 8; i++) H[i] = (H[i] + a[i]) | 0; }
    return H.map(function (v) { return ('00000000' + (v >>> 0).toString(16)).slice(-8); }).join('');
  }
  function dumpParams() { return JSON.stringify(PARAMS, null, 2) + '\n'; }
  function lumHex(h) { var c = hexRgb(h); if (!c) return null; return c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); })
    .reduce(function (s, v, i) { return s + v * [0.2126, 0.7152, 0.0722][i]; }, 0); }
  function contrastHex(a, b) { var x = lumHex(a), y = lumHex(b); return x === null || y === null ? 0 : (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function paramProblems(q) {          // the page's share of vpt/el_params.py validate(): colours, contrast, positive sizes
    var out = [], lim = q.contrast_min || 3, keys = (PMETA.colour_keys || []);
    ['colours_screen', 'colours_print'].forEach(function (n) { var s = q.sections[n]; if (!s) { out.push(n + ' missing'); return; } var bgc = s.values.background.value;
      keys.forEach(function (k) { var v = s.values[k]; if (!v || !/^#[0-9a-fA-F]{6}$/.test(v.value)) { out.push(n + '.' + k + ': not a #rrggbb colour'); return; }
        var shown = v.value; if (k === 'marker') { var o = q.sections.screen_lines.values.marker_opacity.value, c1 = hexRgb(v.value), c2 = hexRgb(bgc);
          shown = '#' + c1.map(function (c, i) { return ('0' + Math.round(c * o + c2[i] * (1 - o)).toString(16)).slice(-2); }).join(''); }
        var r = contrastHex(shown, bgc); if (r < lim) out.push(n + '.' + k + ' ' + v.value + ' on ' + bgc + ': ' + r.toFixed(2) + ' < ' + lim); }); });
    ['snap', 'page', 'screen_lines'].forEach(function (n) { var s = q.sections[n]; if (!s) return; Object.keys(s.values).forEach(function (k) {
      var v = s.values[k].value, vs = Array.isArray(v) ? v : [v]; if (!vs.every(function (x) { return typeof x === 'number' && x > 0; })) out.push(n + '.' + k + ': must be positive'); }); });
    return out;
  }
  function checkParams(text) {         // mirrors vpt/el_params.py check_file(): match / different / could-not-tell
    var o; try { o = JSON.parse(text); } catch (err) { return ['could-not-tell', 'not JSON (' + err.message + ')']; }
    if (!isType(o, 'object')) return ['could-not-tell', 'not a JSON object'];
    var sp = validate(o, PSCHEMA); if (sp.length) return ['could-not-tell', 'not a valid parameter file (' + sp.length + ' problem(s), first: ' + sp[0] + ')'];
    if (o.id !== PARAMS0.id) return ['different', 'parameters of another page (' + o.id + '), not ' + PARAMS0.id];
    var shape = function (q) { return JSON.stringify([Object.keys(q.sections).sort().map(function (s) { return [s, Object.keys(q.sections[s].values).sort()]; }),
      Object.keys(q.rules.definitions).sort(), q.rules.rule_sets.map(function (r) { return r.id; }).sort()]); };
    if (shape(o) !== shape(PARAMS0)) return ['different', 'other sections, values or rules than this page knows'];
    var vp = paramProblems(o); if (vp.length) return ['could-not-tell', 'values break the rules (' + vp.length + ' problem(s), first: ' + vp[0] + ')'];
    return ['match', 'valid; same id and parameters', o];
  }
  function syncParams() {              // the merged views the page uses (vpt/el_rules.py load(), vpt/el_layout.py load_page())
    RULES.values = PARAMS.rules.values; RULES.rule_sets = PARAMS.rules.rule_sets; RULES.rules = PARAMS.rules.definitions;
    RULES.default_rule_set = PARAMS.rules.default_rule_set; RULES.settings.snap_radius_m = PV('snap', 'snap_radius_m');
    CFG.symbol_scale = PV('page', 'symbol_scale'); CFG.room_label_max_m = PV('page', 'room_label_max_m');
    applyStyle(); pages.forEach(function (pg) { if (pg.elParams) pg.elParams(); });
  }
  var PP = document.querySelector('.el-params'), PSTAT = PP && PP.querySelector('.el-params-status');
  function pstatus(msg, kind) { if (!PSTAT) return; PSTAT.textContent = msg; PSTAT.className = 'el-params-status el-status' + (kind ? ' el-' + kind : ''); }
  function markEdited(on) { var v = on ? '1' : '0'; if (PP) PP.setAttribute('data-edited', v); var tb = document.getElementById('vpt-tab-params'); if (tb) tb.setAttribute('data-edited', v); }
  function setEdited(on) { PEDITED = on; PSHA = on ? sha256(dumpParams()) : (PMETA.sha256 || ''); markEdited(on);
    store(PKEY, on ? dumpParams() : null); pages.forEach(function (pg) { if (pg.elChanged) pg.elChanged(); }); }
  function fmtVal(v) { return v === null ? '' : Array.isArray(v) ? v.join(', ') : String(v); }
  function parseVal(text, old, nullable) {
    var s = String(text).trim(); if (s === '') return nullable ? [true, null] : [false, 'a value is needed'];
    var isNum = function (x) { return /^-?\d+(\.\d+)?$/.test(x); };
    if (Array.isArray(old) || (old === null && s.indexOf(',') >= 0)) { var parts = s.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
      return [true, parts.every(isNum) ? parts.map(Number) : parts]; }
    if (typeof old === 'number' || (old === null && isNum(s))) return isNum(s) ? [true, Number(s)] : [false, 'a number is needed'];
    return [true, s];
  }
  // one tab per group (CFG.params_panel.tabs), one full-width table per tab: Parameter | Value | Unit | Source. Live values change the
  // page now; the rest is computed when the plan is exported (tools/export_plan.py): its tab carries a "Needs re-export" pill and,
  // in the shareable demo (which cannot export), its inputs are read-only. Explained once, in the dropdown beside the buttons.
  var PPC = CFG.params_panel || { tabs: [], columns: ['Parameter', 'Value', 'Unit', 'Source'], live: 'Live', export: 'Needs re-export' };
  var EXPORT_RO = V.id === 'artifact';
  function short(t, n) { var w = String(t || '').split(/\s+/).filter(Boolean); return w.slice(0, n).join(' ') + (w.length > n ? ' …' : ''); }
  function ptip(label, mark, source, live) {
    return '<p class="tip-h"><b>' + escH(label) + '</b></p><ul class="tipl"><li><b>' + escH(short(mark || 'no mark', 8)) + '</b></li>' +
      (source ? '<li><b>Source</b>: ' + escH(short(source, 10)) + '</li>' : '') +
      '<li><b>' + escH(live ? PPC.live : PPC.export) + '</b></li></ul>' + more(PMETA.anchor || 'doc-el-params');
  }
  function markPill(mark) { var m = String(mark || ''); if (!m) return '';
    var confirm = /confirm/i.test(m), none = /no value/i.test(m);
    return '<span class="pill pill--' + (none ? 'watch' : confirm ? 'check' : 'good') + '" title="' + escH(m) + '">' + escH(none ? 'no value yet' : confirm ? 'to confirm' : short(m, 3)) + '</span>'; }
  function row(path, label, v, unit, mark, source, live, nullable) {
    var colour = typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v), ro = !live && EXPORT_RO;
    return '<tr class="el-prow" data-path="' + escH(path) + '" data-live="' + (live ? '1' : '0') + '"><td class="el-plabel"><span class="tip" data-tip="' + escH(ptip(label, mark, source, live)) + '">' +
      escH(label) + '</span></td><td class="el-pval">' +
      (colour ? '<input type="color" value="' + escH(v) + '" aria-label="' + escH(label) + '"' + (ro ? ' disabled' : '') + '> <code>' + escH(v) + '</code>'
              : '<input type="text" value="' + escH(fmtVal(v)) + '" placeholder="' + (nullable ? 'no value yet' : '') + '" aria-label="' + escH(label) + '"' + (ro ? ' readonly' : '') + '>') +
      '</td><td class="el-punit">' + escH(unit || '') + '</td><td class="el-psrc">' + markPill(mark) + '</td></tr>';
  }
  function groupRow(text) { return '<tr class="el-pgroup"><th colspan="4" scope="colgroup">' + escH(text) + '</th></tr>'; }
  function buildPanel() {
    if (!PP) return; var body = PP.querySelector('.el-params-body'), live = PMETA.live_sections || [], nav = '', panels = '';
    var openTab = (body.querySelector('.tab[aria-selected="true"]') || {}).dataset;
    PPC.tabs.forEach(function (t, i) {
      var rows = [], exp = false;
      (t.sections || []).forEach(function (sk) { var s = PARAMS.sections[sk]; if (!s) return; var lv = live.indexOf(sk) >= 0; if (!lv) exp = true;
        if (t.sections.length > 1) rows.push(groupRow(s.label));
        Object.keys(s.values).forEach(function (k) { var v = s.values[k];
          rows.push(row('sections.' + sk + '.values.' + k + '.value', v.label, v.value, v.unit, v.mark || s.mark, v.source || s.source || v.note, lv, false)); }); });
      if (t.rules) PARAMS.rules.rule_sets.forEach(function (rs) { var vals = PARAMS.rules.values[rs.id], part = [];
        Object.keys(PARAMS.rules.definitions).forEach(function (k) { var lv = LIVE_RULES.indexOf(k) >= 0; if (lv !== (t.rules === 'live')) return; if (!lv) exp = true;
          var d = PARAMS.rules.definitions[k], v = vals[k] || { value: null };
          part.push(row('rules.values.' + rs.id + '.' + k + '.value', d.label, v.value, d.unit, v.mark || rs.status, v.source, lv, true)); });
        if (part.length) rows = rows.concat([groupRow(PPC.rule_set_column + ': ' + rs.name)], part); });
      var id = 'el-pp-' + i, sel = openTab ? openTab.tab === id : i === 0;
      nav += '<button type="button" class="tab" role="tab" id="tab-' + id + '" data-tab="' + id + '" aria-controls="' + id + '" aria-selected="' + (sel ? 'true' : 'false') + '"' + (sel ? '' : ' tabindex="-1"') + '>' +
        escH(t.label) + (exp ? ' <span class="pill pill--watch">' + escH(PPC.export) + '</span>' : '') + '</button>';
      panels += '<div class="tabpanel' + (sel ? ' active' : '') + '" role="tabpanel" id="' + id + '" data-panel="' + id + '" aria-labelledby="tab-' + id + '"><div class="tbl-scroll"><table class="el-ptable">' +
        '<thead><tr>' + PPC.columns.map(function (c) { return '<th scope="col">' + escH(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div></div>';
    });
    body.innerHTML = '<div class="tabset el-ptabs"><div class="tabset-nav" role="tablist" aria-label="Parameter groups">' + nav + '</div>' + panels + '</div>';
    markEdited(PEDITED); if (window.vptTabsets) window.vptTabsets(body); if (window.vptTipify) window.vptTipify(body);
  }
  function setPath(o, path, v) { var ks = path.split('.'), x = o; for (var i = 0; i < ks.length - 1; i++) x = x[ks[i]]; x[ks[ks.length - 1]] = v; }
  function getPath(o, path) { return path.split('.').reduce(function (x, k) { return x == null ? x : x[k]; }, o); }
  function loadParamsText(text, name) {
    var res = checkParams(text); if (PP) { PP.setAttribute('data-load', res[0]); PP.elLastLoad = res.slice(0, 2); }
    if (res[0] !== 'match') { pstatus(fmt(res[0] === 'different' ? M.params_refused_different : M.params_refused_unknown, { msg: res[1] }), 'err'); return res[0]; }
    PARAMS = res[2]; delete PARAMS.saved; delete PARAMS.saved_from; setEdited(JSON.stringify(PARAMS) !== JSON.stringify(PARAMS0)); syncParams(); buildPanel();
    pstatus(fmt(M.params_loaded, { file: name }), 'ok'); return 'match';
  }
  function paramsSaveText() { var o = JSON.parse(JSON.stringify(PARAMS)); o.saved = new Date().toISOString(); o.saved_from = CFG.app; return JSON.stringify(o, null, 2) + '\n'; }
  if (PP) {
    PP.addEventListener('change', function (e) { var tr = e.target.closest ? e.target.closest('[data-path]') : null; if (!tr) return;
      var path = tr.getAttribute('data-path'), old = getPath(PARAMS, path), nullable = path.indexOf('rules.') === 0, inp = e.target;
      var res = inp.type === 'color' ? [true, inp.value.toLowerCase()] : parseVal(inp.value, old, nullable);
      if (!res[0]) { inp.value = fmtVal(old); pstatus(fmt(M.params_bad, { msg: res[1] }), 'err'); return; }
      var trial = JSON.parse(JSON.stringify(PARAMS)); setPath(trial, path, res[1]); var probs = paramProblems(trial);
      setPath(PARAMS, path, res[1]); if (inp.type === 'color') { var c = tr.querySelector('code'); if (c) c.textContent = res[1]; }
      setEdited(true); syncParams();
      pstatus(probs.length ? fmt(M.params_warn, { n: probs.length, msg: probs[0] }) : tr.getAttribute('data-live') === '0' ? M.params_changed_export : M.params_changed, probs.length ? 'warn' : 'ok'); });
    var pfile = PP.querySelector('input.el-params-file'), phandle = null;
    var PB = function (a) { return PP.querySelector('[data-pact="' + a + '"]'); };
    PB('copy').addEventListener('click', function () { copyText(paramsSaveText(), function () { pstatus(M.copied_params, 'ok'); }); });
    // @pages-only-start
    if (PB('save')) PB('save').addEventListener('click', function () { var n = PMETA.file_name || 'el_parameters.json'; download(paramsSaveText(), n); pstatus(fmt(M.params_saved, { file: n }), 'ok'); });
    var sip = PB('save-in-place');
    if (sip) { sip.hidden = !(V.fs && 'showSaveFilePicker' in window);
      sip.addEventListener('click', async function () { try {
          if (!phandle) phandle = await window.showSaveFilePicker({ suggestedName: PMETA.file_name || 'el_parameters.json', types: [{ description: 'Parameters', accept: { 'application/json': ['.json'] } }] });
          var wr = await phandle.createWritable(); await wr.write(paramsSaveText()); await wr.close(); pstatus(fmt(M.params_saved, { file: phandle.name }), 'ok');
        } catch (err) { if (err && err.name === 'AbortError') return; pstatus(fmt(M.save_failed, { msg: err && err.message || err }), 'err'); } }); }
    // @pages-only-end
    PB('load').addEventListener('click', function () { pfile.click(); });
    pfile.addEventListener('change', function () { var f = pfile.files && pfile.files[0]; if (!f) return;
      readFile(f, function (tx, name, err) { pfile.value = ''; if (tx === null) { pstatus(fmt(M.params_refused_unknown, { msg: 'the file could not be read (' + err + ')' }), 'err'); return; } loadParamsText(tx, name); }); });
    PB('reset').addEventListener('click', function () { PARAMS = JSON.parse(JSON.stringify(PARAMS0)); setEdited(false); syncParams(); buildPanel(); pstatus(M.params_reset, 'ok'); });
    window.elParams = { load: loadParamsText, check: checkParams, get: function () { return JSON.parse(JSON.stringify(PARAMS)); }, sha: function () { return PSHA; },
      edited: function () { return PEDITED; }, dump: dumpParams, saveText: paramsSaveText, sha256: sha256 };
    var pd = store(PKEY);                // edits kept in this browser (when it allows it) until reset
    if (pd) { var rd = checkParams(pd); if (rd[0] === 'match') { PARAMS = rd[2]; PEDITED = true; PSHA = sha256(dumpParams()); syncParams(); pstatus(M.params_draft, 'warn'); } }
    buildPanel();
  }

  // ---- the plan: three outcomes (mirrors vpt/plan.py check()) ----
  function parseSvg(text) {
    try { var d = new DOMParser().parseFromString(text, 'image/svg+xml'), r = d.documentElement;
      if (!r || r.nodeName !== 'svg' || d.getElementsByTagName('parsererror').length) return null;
      if (r.querySelector('image, foreignObject, script') || /data:image\//.test(text)) return null;
      return r; } catch (err) { return null; }
  }
  function checkPlan(text) {
    var o; try { o = JSON.parse(text); } catch (err) { return ['could-not-tell', 'not JSON (' + err.message + ')']; }
    return checkPlanObj(o);
  }
  function checkPlanObj(o) {
    if (!isType(o, 'object')) return ['could-not-tell', 'not a JSON object'];
    var kind = o.schema || o.name;
    if (kind !== 'vpt_plan') {
      var what = kind === 'el_layout' ? 'a layout file (use Open layout)' : kind === 'el_parameters' ? 'a parameter file (use Load parameters)' : kind ? 'a file of kind ' + kind : 'a JSON file of unknown kind';
      return ['different', 'this is ' + what + ', not a plan file'];
    }
    var p = validate(o, PLAN_SCHEMA); if (p.length) return ['could-not-tell', 'not a valid plan file (' + p.length + ' problem(s), first: ' + p[0] + ')'];
    for (var i = 0; i < o.storeys.length; i++) { var st = o.storeys[i];
      if ((o.schema_version >= 2) !== ('windows' in st)) return ['could-not-tell', 'storey ' + st.key + ': a version-' + o.schema_version + ' plan file ' +
        (o.schema_version >= 2 ? 'must list its windows' : 'has no windows (they came with version 2)')];
      if (!parseSvg(st.svg)) return ['could-not-tell', 'storey ' + st.key + ': the drawing does not parse'];
      var a = st.affine; if (Math.abs(a[0] * a[3] - a[1] * a[2]) < 1e-12) return ['could-not-tell', 'storey ' + st.key + ": the drawing's affine cannot be inverted"]; }
    var nr = 0, nd = 0, nw = 0; o.storeys.forEach(function (s) { nr += s.rooms.length; nd += s.doors.length; nw += (s.windows || []).length; });
    return ['match', o.storeys.length + ' storey(s), ' + nr + ' rooms, ' + nd + ' doors, ' + (o.schema_version >= 2 ? nw + ' windows' : 'windows unknown (version-1 file)'), o];
  }

  window.elPages = {};
  var ghost = document.createElement('div'); ghost.className = 'el-ghost'; ghost.hidden = true; document.body.appendChild(ghost);
  var TPL = document.getElementById('el-page-tpl'), STOREYS = document.querySelector('.el-storeys'), STABS = document.querySelector('.el-storey-tabs');
  var PLAN = null, activeKey = null;

  function statusWord(s) { return s || 'Bestand'; }
  // the drawing layers of a storey in the layer panel: per status, per base name, per layer (the viewer wires the toggles)
  function buildLayerPanel(pg, st) {
    var by = {}, statuses = {}, n = 0;
    st.layers.forEach(function (x) { (by[x.base] = by[x.base] || []).push(x); var w = statusWord(x.status); statuses[w] = (statuses[w] || 0) + 1; n += x.paths; });
    var stEl = pg.querySelector('.dwg-status');
    stEl.innerHTML = Object.keys(statuses).sort().map(function (w) { var on = st.layers.some(function (x) { return statusWord(x.status) === w && x.default_on; });
      return '<label><input type="checkbox" data-toggle-status="' + escH(w) + '"' + (on ? ' checked' : '') + '> ' + escH(w) + ' (' + statuses[w] + ')</label>'; }).join('');
    pg.querySelector('.dwg-count').textContent = st.layers.length + ' layers in ' + Object.keys(by).length + ' base names, ' + n + ' paths';
    var lt = (CFG.tips || {}).layer || [];
    pg.querySelector('.dwg-bases').innerHTML = Object.keys(by).sort().map(function (b) {
      var g = by[b], on = g.some(function (x) { return x.default_on; }), paths = g.reduce(function (s, x) { return s + x.paths; }, 0);
      return '<details class="base" data-name="' + escH(b.toLowerCase()) + '"><summary><label><input type="checkbox" data-toggle-base="' + escH(b) + '"' + (on ? ' checked' : '') + '> ' +
        escH(b) + '</label> <span class="dwg-count">' + g.length + ' · ' + paths + '</span></summary>' + g.map(function (x) {
          return '<div class="lyr" data-name="' + escH(x.layer.toLowerCase()) + '"><label><input type="checkbox" data-toggle-layer="' + escH(x.layer) + '" data-base="' + escH(b) +
            '" data-status="' + escH(statusWord(x.status)) + '"' + (x.default_on ? ' checked' : '') + '> ' + escH(x.layer) + '</label> <span class="tip dwg-count" data-tip="' +
            escH(tipList('Layer ' + x.layer, ['**' + statusWord(x.status) + '** · **' + x.paths + '** paths'].concat(lt), CFG.anchors.layers)) + '">' + escH(statusWord(x.status)) + ' · ' + x.paths + '</span></div>'; }).join('') + '</details>'; }).join('');
  }
  function buildSvg(st, pg, lib) {
    var src = parseSvg(st.svg), svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'el-svg'); svg.setAttribute('viewBox', st.view_box.join(' ')); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Electrical plan, storey ' + st.key); svg.setAttribute('data-el-storey', st.key);
    var paper = document.createElementNS(NS, 'rect'); paper.setAttribute('class', 'paper');
    ['x', 'y', 'width', 'height'].forEach(function (a, i) { paper.setAttribute(a, String(st.view_box[i])); }); paper.setAttribute('fill', '#000000');
    svg.appendChild(paper);
    var bg = document.createElementNS(NS, 'g'); bg.setAttribute('class', 'el-bg'); svg.appendChild(bg);
    var css = '';
    if (src) { var s0 = src.querySelector('style'); if (s0) { css = s0.textContent; bg.appendChild(document.importNode(s0, true)); }
      var dwg = src.querySelector('g.dwg') || src.querySelector('g'); if (dwg) bg.appendChild(document.importNode(dwg, true)); }
    var links = document.createElementNS(NS, 'g'); links.setAttribute('class', 'el-layer el-links'); links.setAttribute('data-layer', LINKL); links.setAttribute('data-paths', '0'); svg.appendChild(links);
    var sdef = setById(LIB.default_set), seen = {};
    sdef.categories.forEach(function (c) { sdef.symbols.forEach(function (x) { if (x.category !== c.key || seen[x.layer]) return; seen[x.layer] = 1;
      var g = document.createElementNS(NS, 'g'); g.setAttribute('class', 'el-layer'); g.setAttribute('data-layer', x.layer); g.setAttribute('data-paths', '0'); svg.appendChild(g); }); });
    var gh = document.createElementNS(NS, 'g'); gh.setAttribute('class', 'el-ghosts'); gh.setAttribute('aria-hidden', 'true'); svg.appendChild(gh);
    pg.querySelector('.dwg-paper').appendChild(svg);
    return { svg: svg, css: css };
  }
  function stem(name) { return String(name).replace(/\.[^.]*$/, ''); }
  function showStorey(key) {
    activeKey = key;
    STABS.querySelectorAll('[role="tab"]').forEach(function (t) { var on = t.getAttribute('data-storey') === key; t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
    pages.forEach(function (pg) { pg.hidden = pg.getAttribute('data-storey') !== key; if (!pg.hidden && pg.elRestyle) pg.elRestyle(); });
  }
  function loadPlan(plan, name) {
    pages.forEach(function (pg) { if (pg.elDestroy) pg.elDestroy(); });
    pages = []; window.elPages = {}; STOREYS.innerHTML = ''; STABS.innerHTML = '';
    PLAN = plan;
    var synth = document.querySelector('[data-banner="synthetic"]'), own = document.querySelector('[data-banner="own"]');
    if (synth) synth.hidden = !plan.synthetic;
    var synthMore = document.querySelector('[data-banner-more="synthetic"]'); if (synthMore) { synthMore.hidden = !plan.synthetic; synthMore.open = false; }
    if (own) { own.hidden = !!plan.synthetic; own.textContent = plan.synthetic ? '' : fmt(CFG.banners.own_plan, { file: plan.drawing.file }); }
    plan.storeys.forEach(function (st, i) {
      var tab = document.createElement('button'); tab.type = 'button'; tab.setAttribute('role', 'tab'); tab.setAttribute('data-storey', st.key);
      tab.id = 'el-tab-' + i; tab.textContent = st.key + (st.label && st.label !== st.key ? ' ' + st.label : '');
      tab.addEventListener('click', function () { showStorey(st.key); }); STABS.appendChild(tab);
      var pg = setupPage(st, plan, i); pg.setAttribute('aria-labelledby', tab.id);
    });
    applyStyle();
    if (!plan.storeys.length) { gstatus(M.no_storey, 'warn'); return; }
    var ex = plan.storeys.filter(function (s) { return s.examples; })[0];
    showStorey((ex || plan.storeys[0]).key);
  }

  function setupPage(st, plan, idx) {
    var frag = TPL.content.cloneNode(true), pg = frag.querySelector('.el-page');
    pg.setAttribute('data-storey', st.key); pg.id = 'el-page-' + idx;
    STOREYS.appendChild(frag);
    pg = STOREYS.lastElementChild;
    pages.push(pg);
    var k = plan.drawing.units_per_m, mm = plan.drawing.mm_per_unit;
    var D = { storey: st.key, label: st.label, drawing_file: plan.drawing.file, sha256: plan.drawing.sha256,
      file_name: stem(plan.drawing.file) + '__' + st.key + CFG.file_suffix, view_box: st.view_box, affine: st.affine, page_mm: st.page_mm,
      scale_1_to: st.scale_1_to, vb_per_mm: st.view_box[2] / st.page_mm[0], mm_per_unit: mm, rooms_known: true,
      rooms: st.rooms.map(function (r) { return { id: r.id, outline: r.outline, anchor: r.anchor, name: r.name, wet: !!r.wet }; }),
      windows: Array.isArray(st.windows) ? st.windows : null,
      room_label_max_units: mm ? CFG.room_label_max_m * 1000 / mm : null, units_per_m: k,
      snap_units: k ? RULES.settings.snap_radius_m * k : null, doors: st.doors, suggest: st.suggest, examples: st.examples, synthetic: plan.synthetic };
    var key = D.storey, view = pg.querySelector('.el-view');
    view.setAttribute('data-view-id', 'el-' + key); view.setAttribute('data-print-title', 'Elektro – ' + key + (st.label ? ' ' + st.label : ''));
    view.setAttribute('data-print-date', plan.drawing.file + (plan.synthetic ? ' (synthetic sample)' : '')); view.setAttribute('data-scale', String(st.scale_1_to));
    view.setAttribute('data-page-mm', st.page_mm.join(' '));
    buildLayerPanel(pg, st);
    var built = buildSvg(st, pg), svg = built.svg, bg = svg.querySelector('g.el-bg'), bgCss = built.css;
    var linkG = svg.querySelector('g.el-links'), ghostG = svg.querySelector('g.el-ghosts');
    var statusEl = pg.querySelector('.el-status'), infoEl = pg.querySelector('.el-info'), fileIn = pg.querySelector('input.el-file');
    var setSel = pg.querySelector('select.el-set'), rulesSel = pg.querySelector('select.el-rules'), snapBox = pg.querySelector('input.el-snap'), sugAllBox = pg.querySelector('input.el-sugall');
    var B = function (a) { return pg.querySelector('[data-el="' + a + '"]'); };
    var A = D.affine, det = A[0] * A[3] - A[1] * A[2], base = Math.atan2(A[1], A[0]) * 180 / Math.PI, K = D.vb_per_mm * PV('page', 'symbol_scale');
    var S = { set: LIB.default_set, symbols: [], links: [], next: 1, nextLink: 1, rules: RULES.default_rule_set, example: null }, undo = [], redo = [], sel = null, armed = null, handle = null;
    var connect = false, src = null, selLink = null, ghostCode = null, exSel = pg.querySelector('select.el-example'), exBanner = pg.querySelector('.el-example-banner');
    var DKEY = 'el-draft:' + (D.sha256 || 'nosha') + ':' + key, layerG = {};
    svg.querySelectorAll('g.el-layer').forEach(function (g) { layerG[g.getAttribute('data-layer')] = g; });
    if (D.examples) pg.querySelector('.el-example-ctl').hidden = false;
    function SET() { return setById(S.set); }
    function def(code) { return SET().symbols.filter(function (s) { return s.code === code; })[0]; }
    function byId(id) { return S.symbols.filter(function (s) { return s.id === id; })[0]; }
    function linkById(id) { return S.links.filter(function (l) { return l.id === id; })[0]; }
    function status(msg, kind) { statusEl.textContent = msg; statusEl.title = msg; statusEl.className = 'el-status' + (kind ? ' el-' + kind : ''); }

    // ---- the drawing layers: which are shown (saved with the layout as background.layers) ----
    function drawingInputs() { return Array.prototype.slice.call(pg.querySelectorAll('input[data-toggle-layer][data-status]')); }
    function shownLayers() { return drawingInputs().filter(function (i) { return i.checked; }).map(function (i) { return i.getAttribute('data-toggle-layer'); }); }
    function applyLayers(list) {         // list empty: the plan's defaults
      var want = {}, have = {}, missing = 0;
      list.forEach(function (x) { want[x] = 1; });
      drawingInputs().forEach(function (i) { var n = i.getAttribute('data-toggle-layer'); have[n] = 1;
        i.checked = list.length ? !!want[n] : st.layers.some(function (x) { return x.layer === n && x.default_on; }); });
      list.forEach(function (x) { if (!have[x]) missing++; });
      if (view.dwgApi) view.dwgApi.sync();
      return missing;
    }
    function restyleBg() {
      var s = bg.querySelector('style.el-bg-style'); if (!bgCss) { if (s) s.remove(); return; }
      if (!s) { s = document.createElementNS(NS, 'style'); s.setAttribute('class', 'el-bg-style'); bg.insertBefore(s, bg.firstChild); }
      s.textContent = bgRules(bgCss);
    }

    // ---- placement suggestions: shown, never computed here ----
    function sugList(kind) { var s = (D.suggest || {})[S.rules]; return s && kind ? (s[kind] || []) : []; }
    function sugTip(kind, g) {
      var t = (RULES.tips[S.rules] || {})[kind]; if (!t) return '';
      var v0 = t.values[0] || null, marked = t.values.filter(function (v) { return v.mark; }).length;
      return '<p class="tip-h"><b>' + escH(t.name) + '</b></p><ul class="tipl">' +
        '<li><b>Rule set</b>: ' + escH(t.rule_set) + '</li>' +
        '<li><b>Room</b> ' + escH(g.room) + (g.door ? ', <b>door</b> ' + escH(g.door) + ' (' + (g.side === 'into' ? 'swing side' : 'other side') + ')' : '') + '</li>' +
        (v0 ? '<li><b>' + escH(v0.label) + '</b>: ' + escH(v0.value) + (v0.unit && v0.value !== 'no value yet' ? ' ' + escH(v0.unit.split(' (')[0]) : '') + '</li>' : '') +
        '<li><b>' + t.values.length + ' value(s)</b>' + (marked ? ', ' + marked + ' to confirm' : '') + '</li></ul>' + more(CFG.anchors.suggestions);
    }
    function unitsPerPx() { var m = svg.getScreenCTM(); var s = m ? Math.hypot(m.a, m.b) : 0; return s > 0 ? 1 / s : K; }
    function ghostR() { return PV('screen_lines', 'marker_radius_px') * unitsPerPx(); }
    function sizeGhosts() { var r = ghostR(); ghostG.querySelectorAll('circle').forEach(function (c) { c.setAttribute('r', String(r)); }); }
    function catOfKind(kind) { var d = def(RULES.suggest[kind].codes.filter(function (c) { return def(c); })[0]); return d ? d.category : ''; }
    function addGhosts(kind, all) {
      var list = sugList(kind), r = ghostR(), cat = all ? ' el-c-' + catOfKind(kind) : '';
      list.forEach(function (g, i) { var p = toView(A, g.x, g.y), e = document.createElementNS(NS, 'g');
        e.setAttribute('class', 'tip el-ghost-m' + cat); e.setAttribute('data-i', String(i)); e.setAttribute('data-room', g.room || ''); e.setAttribute('data-kind', kind);
        e.setAttribute('transform', 'translate(' + p[0] + ' ' + p[1] + ')'); e.setAttribute('data-tip', sugTip(kind, g));
        var c = document.createElementNS(NS, 'circle'); c.setAttribute('cx', '0'); c.setAttribute('cy', '0'); c.setAttribute('r', String(r));
        c.setAttribute('stroke-dasharray', '4 3'); c.setAttribute('pointer-events', 'all'); e.appendChild(c);
        ghostG.appendChild(e); });
      return list.length;
    }
    function showAll() { if (!sugAllBox || !sugAllBox.checked || ghostCode) return 0; clearGhosts(); var n = 0;
      Object.keys(RULES.suggest).forEach(function (k2) { n += addGhosts(k2, true); }); return n; }
    function showGhosts(code) {
      clearGhosts(); var kind = kindOf(code), d = def(code); ghostCode = code;
      if (!kind) { status(fmt(M.no_rule, { name: d ? d.name_de : code }), ''); return 0; }
      var list = sugList(kind), rs = ruleSet(S.rules), name = RULES.suggest[kind].name;
      addGhosts(kind, false);
      var notes = ((D.suggest || {})[S.rules] || { notes: {} }).notes[kind] || [];
      if (list.length) status(fmt(M.ghosts, { n: list.length, kind: name, set: rs.name }) + (notes.length ? ' ' + notes.length + ' could not tell (see Documentation).' : ''), '');
      else status(fmt(M.ghosts_none, { kind: name, set: rs.name, why: notes[0] || 'no room or door on this storey' }), 'warn');
      return list.length;
    }
    function clearGhosts() { while (ghostG.firstChild) ghostG.removeChild(ghostG.firstChild); }
    function hideGhosts() { ghostCode = null; clearGhosts(); showAll(); }
    var mo = new MutationObserver(sizeGhosts); mo.observe(svg, { attributes: true, attributeFilter: ['viewBox'] });
    window.addEventListener('resize', sizeGhosts);
    function nearest(code, m) {
      var kind = kindOf(code); if (!kind || !D.snap_units) return null;
      var best = null, bd = Infinity;
      sugList(kind).forEach(function (g, i) { var d = Math.hypot(g.x - m[0], g.y - m[1]); if (d < bd) { bd = d; best = { g: g, i: i, d: d }; } });
      return best && bd <= D.snap_units ? best : null;
    }
    function hover(cx, cy, code) {     // brighter rings in the room under the pointer, yellow the one it would snap to
      if (!ghostG.firstChild) return; var p = clientToView(cx, cy); if (!p) return;
      var m = toModel(A, p[0], p[1]), rm = roomOf(m[0], m[1])[0], n = snapOn() ? nearest(code, m) : null;
      ghostG.querySelectorAll('.el-ghost-m').forEach(function (e) {
        e.classList.toggle('el-ghost-cur', !!rm && e.getAttribute('data-room') === rm);
        e.classList.toggle('el-ghost-hit', !!n && e.getAttribute('data-i') === String(n.i)); });
    }
    function snapOn() { return !!snapBox && snapBox.checked; }

    // ---- symbols ----
    function roomOf(x, y) {
      if (!D.rooms_known) return [null, 'could-not-tell'];
      for (var i = 0; i < D.rooms.length; i++) if (D.rooms[i].outline && inside([x, y], D.rooms[i].outline)) return [D.rooms[i].id, 'outline'];
      var best = null, bd = Infinity;
      D.rooms.forEach(function (r) { if (r.outline || !r.anchor) return; var d = Math.hypot(r.anchor[0] - x, r.anchor[1] - y); if (d < bd) { bd = d; best = r; } });
      if (best && D.room_label_max_units != null && bd <= D.room_label_max_units) return [best.id, 'nearest label'];
      return [null, 'could-not-tell'];
    }
    function roomName(id) { var r = D.rooms.filter(function (x) { return x.id === id; })[0]; return r && r.name ? id + ' ' + r.name : id; }
    function clientToView(cx, cy) { var m = svg.getScreenCTM(); if (!m) return null; var p = svg.createSVGPoint(); p.x = cx; p.y = cy;
      var q = p.matrixTransform(m.inverse()); return [q.x, q.y]; }
    function overStage(cx, cy) { var r = svg.getBoundingClientRect(); return r.width > 0 && cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom && !document.body.classList.contains('dwg-printing'); }
    function snap() { return JSON.stringify({ symbols: S.symbols, links: S.links, next: S.next, nextLink: S.nextLink }); }
    function restore(t) { var o = JSON.parse(t); S.symbols = o.symbols; S.links = o.links || []; S.next = o.next; S.nextLink = o.nextLink || 1;
      if (sel && !byId(sel)) sel = null; if (selLink && !linkById(selLink)) selLink = null; if (src && !byId(src)) src = null; }
    function pushUndo(t) { undo.push(t || snap()); if (undo.length > CFG.undo_limit) undo.shift(); redo = []; }
    function place(code, cx, cy, free) {
      if (!overStage(cx, cy)) { hideGhosts(); status(M.outside, 'warn'); return null; }
      var p = clientToView(cx, cy), m = toModel(A, p[0], p[1]), x = r6(m[0]), y = r6(m[1]), rot = 0, d = def(code);
      var n = !free && snapOn() ? nearest(code, m) : null;
      if (n) { x = n.g.x; y = n.g.y; rot = n.g.rot || 0; }
      var rm = roomOf(x, y);
      pushUndo();
      var s = { id: 's' + S.next++, code: code, x: x, y: y, rotation: rot, room: rm[0], room_method: rm[1] };
      S.symbols.push(s); sel = s.id; selLink = null; disarm(); hideGhosts(); changed();
      status(n ? fmt(M.snapped, { name: d.name_de, code: code, kind: RULES.suggest[n.g.kind].name, set: ruleSet(S.rules).name }) : fmt(M.placed, { name: d.name_de, code: code }), 'ok');
      return s.id;
    }
    function symEl(s) {
      var d = def(s.code), set = SET(), col = colourOf(set, d), p = toView(A, s.x, s.y), b = d.box;
      var ang = base + (det < 0 ? -s.rotation : s.rotation);
      var g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'el-sym' + (sel === s.id ? ' el-selected' : '') + connectClass(s)); g.setAttribute('data-id', s.id); g.setAttribute('data-code', s.code);
      g.setAttribute('transform', 'translate(' + p[0] + ' ' + p[1] + ') rotate(' + ang + ') scale(' + K + ')');
      g.innerHTML = '<rect class="el-hit" x="' + b[0] + '" y="' + b[1] + '" width="' + b[2] + '" height="' + b[3] + '" fill="transparent" stroke="none"></rect>' +
        '<g class="el-symg el-c-' + d.category + '" fill="none" stroke="' + col + '" color="' + col + '" stroke-width="' + set.stroke_mm + '" stroke-linecap="round">' + d.svg + '</g>' +
        (sel === s.id ? '<rect class="el-sel" x="' + (b[0] - 0.6) + '" y="' + (b[1] - 0.6) + '" width="' + (b[2] + 1.2) + '" height="' + (b[3] + 1.2) +
          '" fill="none" stroke="' + PV('colours_print', 'selection') + '" stroke-width="0.3" stroke-dasharray="1 0.6"></rect>' : '') +
        '<circle class="el-anchor" cx="0" cy="0" r="0.05" fill="none" stroke="none"></circle>';
      g.querySelectorAll('.el-symg text').forEach(function (t) { t.setAttribute('transform', 'rotate(' + (-ang) + ' ' + t.getAttribute('x') + ' ' + t.getAttribute('y') + ')'); });  // letters stay upright
      return g;
    }
    function linkEls(l) {
      var a = byId(l.from), b = byId(l.to); if (!a || !b) return null;
      var p = toView(A, a.x, a.y), q = toView(A, b.x, b.y), g = document.createElementNS(NS, 'g'), on = selLink === l.id;
      var sw = PV('print_lines', 'link_stroke_mm'), dash = PV('print_lines', 'link_dash_mm');     // print widths (mm); screen: CSS px
      g.setAttribute('class', 'el-link' + (on ? ' el-link-on' : '')); g.setAttribute('data-link', l.id);
      var xy = 'x1="' + p[0] + '" y1="' + p[1] + '" x2="' + q[0] + '" y2="' + q[1] + '"';
      g.innerHTML = '<line class="el-link-line" ' + xy + ' stroke="' + PV('colours_print', 'link') + '" stroke-width="' + (sw * K * (on ? 2.2 : 1)) +
        '" stroke-dasharray="' + (dash[0] * K) + ' ' + (dash[1] * K) + '" fill="none"></line>' +
        '<line class="el-link-hit" data-link="' + escH(l.id) + '" ' + xy + ' stroke="transparent" stroke-width="' + (2.5 * K) + '" fill="none"></line>';
      return g;
    }
    // Connect mode: no switch picked -> the switches are marked, the rest dimmed; a switch picked -> what it may control is marked
    function connectClass(s) {
      if (!connect) return '';
      if (!src) return isSwitch(SET(), s.code) ? ' el-can' : ' el-dim';
      if (s.id === src) return ' el-src';
      var a = byId(src), d = a && def(a.code);
      return d && d.connectable_to.indexOf(s.code) >= 0 ? ' el-can' : ' el-dim';
    }
    function allowedText(code) { var d = def(code);
      return (d ? d.connectable_to : []).map(function (c) { var x = def(c); return (x ? x.name_de + ' ' : '') + c; }).join(', ') || 'nothing'; }
    pg.elRestyle = function () { restyleBg(); sizeGhosts(); };
    pg.elParams = function () {        // a parameter changed in the panel: symbol size, snap radius, room distance, hints
      K = D.vb_per_mm * PV('page', 'symbol_scale');
      if (D.units_per_m) D.snap_units = PV('snap', 'snap_radius_m') * D.units_per_m;
      if (D.mm_per_unit) D.room_label_max_units = PV('page', 'room_label_max_m') * 1000 / D.mm_per_unit;
      render();
    };
    pg.elChanged = function () { if (S.symbols.length && !S.example) store(DKEY, JSON.stringify(layout())); };
    pg.elDestroy = function () { mo.disconnect(); window.removeEventListener('resize', sizeGhosts); };
    function currentGroups() { return groups(S.symbols, S.links); }
    function currentHints() { return layoutChecks(S.symbols, S.links, D.rooms, D.doors || [], D.units_per_m, S.rules, SET(), D.rooms_known); }
    function renderGroups() {
      var box = pg.querySelector('.el-groups-body'); if (!box) return;
      var gs = currentGroups();
      if (!gs.length) { box.innerHTML = '<p class="el-hint-items">' + escH(M.no_links) + '</p>'; return; }
      box.innerHTML = '<ul>' + gs.map(function (g, i) {
        var p = proposal(g.switches.map(function (id) { return [id, byId(id).code]; }));
        var cur = g.switches.map(function (id) { return id + ' ' + byId(id).code; }).join(', ');
        var want = g.switches.map(function (id) { return p.codes[id]; }).join(', ');
        return '<li class="el-grp" data-group="' + i + '" data-type="' + p.type + '">' +
          escH(fmt(M.group_line, { n: i + 1, ns: g.switches.length, sw: '(' + cur + ')', nl: g.lights.length, li: '(' + g.lights.join(', ') + ')' })) +
          ' → <span class="tip el-prop" data-tip="' + escH('<p class="tip-h"><b>' + escH(p.name) + '</b></p><ul class="tipl"><li><b>' + g.switches.length +
            ' switch(es)</b> → ' + escH(p.name_en) + '</li><li><b>Apply</b> puts the proposed switches in.</li></ul>' + more(CFG.anchors.groups)) + '">' +
          escH(p.name) + '</span>' + (p.type === 'push' ? ' <span class="unk">(no proposal)</span>' :
          p.matches ? ' <span class="pass">✓ placed as proposed</span>' :
          ' (' + escH(want) + ') <button type="button" class="tip el-grp-apply" data-group="' + i + '" data-tip="' +
            escH('<p class="tip-h"><b>Apply</b></p><ul class="tipl"><li><b>Swaps</b> this group to ' + escH(want) + '.</li><li><b>One Undo</b> step.</li></ul>' + more(CFG.anchors.apply)) + '">Apply</button>') + '</li>';
      }).join('') + '</ul>';
    }
    function renderHints() {
      var hs = currentHints(), lab = { match: 'ok', different: 'to look at', 'could-not-tell': 'could not tell' }, cls = { match: 'pass', different: 'fail', 'could-not-tell': 'unk' };
      hs.forEach(function (h) { var li = pg.querySelector('.el-hint[data-hint="' + h.id + '"]'); if (!li) return;
        li.setAttribute('data-status', h.status);
        var st2 = li.querySelector('.el-hint-st'); st2.className = 'el-hint-st ' + cls[h.status]; st2.textContent = lab[h.status];
        var bad = h.items.filter(function (i) { return i.status !== MATCH; }).map(function (i) {
          return (i.symbol || (roomName(i.room) + (i.door ? ' ' + i.door : ''))) + (i.status === UNK ? ' (could not tell: ' + i.why + ')' : ''); });
        li.querySelector('.el-hint-items').textContent = h.detail + (bad.length ? ': ' + bad.slice(0, 12).join(', ') + (bad.length > 12 ? ', …' : '') : ''); });
      var n = function (s) { return hs.filter(function (h) { return h.status === s; }).length; }, cc = pg.querySelector('.el-check-counts');
      if (cc) cc.textContent = '(' + fmt(M.checks_counts, { ok: n(MATCH), look: n(DIFF), unk: n(UNK) }) + ')';
      var wl = pg.querySelector('.el-windows');
      if (wl) { wl.textContent = D.windows ? fmt(M.windows_known, { n: D.windows.length }) : M.windows_unknown; wl.setAttribute('data-windows', D.windows ? String(D.windows.length) : 'unknown'); }
    }
    function render() {
      Object.keys(layerG).forEach(function (k2) { var g = layerG[k2]; while (g.firstChild) g.removeChild(g.firstChild); });
      var counts = {};
      S.symbols.forEach(function (s) { var L = def(s.code).layer; (layerG[L] || bg).appendChild(symEl(s)); counts[L] = (counts[L] || 0) + 1; });
      S.links.forEach(function (l) { var e = linkEls(l); if (e) { linkG.appendChild(e); counts[LINKL] = (counts[LINKL] || 0) + 1; } });
      Object.keys(layerG).forEach(function (k2) { layerG[k2].setAttribute('data-paths', String(counts[k2] || 0));
        var c = pg.querySelector('[data-el-count="' + CSS.escape(k2) + '"]'); if (c) c.textContent = String(counts[k2] || 0); });
      var s = sel && byId(sel);
      infoEl.textContent = s ? fmt(M.selected, { name: def(s.code).name_de, code: s.code, rot: s.rotation,
        room: s.room ? 'room ' + roomName(s.room) + ' (' + s.room_method + ')' : M.room_none }) : '';
      B('undo').disabled = !undo.length; B('redo').disabled = !redo.length; B('rotate').disabled = !s; B('delete').disabled = !s && !selLink;
      B('discard').hidden = !S.symbols.length || !!S.example;
      B('connect').setAttribute('aria-pressed', connect ? 'true' : 'false'); view.classList.toggle('el-connecting', connect);
      setSel.disabled = S.symbols.length > 0; if (rulesSel) rulesSel.value = S.rules;
      renderGroups(); renderHints();
    }
    function layout() {
      var set = SET(), shown = shownLayers();
      var out = { schema: 'el_layout', schema_version: 2,
        drawing: { file: D.drawing_file, sha256: D.sha256 || '', storey: key, storey_label: D.label },
        model_units_mm: D.mm_per_unit == null ? null : D.mm_per_unit,
        symbol_set: { id: set.id, version: set.version, verified: !!set.verified },
        background: { layers: shown, hidden_layers: drawingInputs().length - shown.length, copied: new Date().toISOString() },
        symbols: S.symbols.map(function (s) { return { id: s.id, code: s.code, x: s.x, y: s.y, rotation: s.rotation, room: s.room, room_method: s.room_method }; }),
        links: S.links.map(function (l) { return { id: l.id, from: l.from, to: l.to }; }), rule_set: S.rules,
        parameters: { id: PARAMS.id, version: PARAMS.version, sha256: PSHA || sha256(dumpParams()), edited: PEDITED },
        saved: new Date().toISOString(), app: CFG.app };
      if (S.example && D.examples && D.examples[S.example]) out.example = JSON.parse(JSON.stringify(D.examples[S.example].example));
      return out;
    }
    // any change made by the user turns a shown example into the user's own layout (then kept as a draft like any other)
    function changed() { if (S.example) { S.example = null; exampleUi(); } render(); if (S.symbols.length) store(DKEY, JSON.stringify(layout())); else store(DKEY, null); }
    view.onLayers = function () { if (S.symbols.length && !S.example) store(DKEY, JSON.stringify(layout())); };

    // ---- examples: generated by vpt/el_examples.py into the plan; shown only when the user has no layout of this storey,
    // labelled EXAMPLE, never stored as a draft; switching never overwrites the user's own work without asking ----
    function exampleUi() { if (exSel) exSel.value = S.example || 'none'; if (exBanner) { exBanner.hidden = !S.example;
        exBanner.querySelector('.el-example-text').textContent = D.synthetic ? M.example_banner_synthetic : M.example_banner;
        exBanner.querySelector('.el-example-which').textContent = S.example && D.examples[S.example] ? D.examples[S.example].example.label : ''; }
      pg.setAttribute('data-example', S.example || ''); }
    function clearAll() { S.symbols = []; S.links = []; S.next = 1; S.nextLink = 1; sel = null; selLink = null; src = null; }
    function doShowExample(id, quiet) {
      var o = D.examples[id];
      S.set = o.symbol_set.id; S.rules = o.rule_set;
      applyLayers(o.background.layers);
      S.symbols = o.symbols.map(function (s) { return { id: s.id, code: s.code, x: s.x, y: s.y, rotation: s.rotation, room: s.room, room_method: s.room_method }; });
      S.links = o.links.map(function (l) { return { id: l.id, from: l.from, to: l.to }; });
      S.next = S.symbols.length + 1; S.nextLink = S.links.length + 1; sel = null; selLink = null; src = null;
      S.example = id; exampleUi(); render();
      if (!quiet) status(fmt(M.example_shown, { label: o.example.label, n: S.symbols.length, l: S.links.length }), 'ok');
      return id;
    }
    function showExample(id, quiet) {
      if (!D.examples) return 'none';
      if (id === 'none' || !D.examples[id]) {
        if (!S.example) { if (exSel) exSel.value = 'none'; return 'none'; }
        clearAll(); applyLayers([]); S.example = null; exampleUi(); render(); status(M.example_cleared, 'ok'); return 'none'; }
      if (S.symbols.length && !S.example) {
        ask(fmt(M.example_replace_confirm, { n: S.symbols.length }), function () { pushUndo(); doShowExample(id, quiet); }, function () { exampleUi(); });
        return 'asked'; }
      return doShowExample(id, quiet);
    }
    if (exSel) exSel.addEventListener('change', function () { showExample(exSel.value, false); });
    if (B('example-clear')) B('example-clear').addEventListener('click', function () { showExample('none', false); });
    function rotate() { var s = sel && byId(sel); if (!s) return; pushUndo(); s.rotation = (s.rotation + 90) % 360; changed(); }
    function del() {
      if (selLink) { pushUndo(); S.links = S.links.filter(function (l) { return l.id !== selLink; }); selLink = null; changed(); status(M.link_deleted, 'ok'); return; }
      var s = sel && byId(sel); if (!s) return; pushUndo();
      S.symbols = S.symbols.filter(function (x) { return x !== s; }); S.links = S.links.filter(function (l) { return l.from !== s.id && l.to !== s.id; });
      if (src === s.id) src = null; sel = null; changed(); }
    function doUndo() { if (!undo.length) return; redo.push(snap()); restore(undo.pop()); changed(); }
    function doRedo() { if (!redo.length) return; undo.push(snap()); restore(redo.pop()); changed(); }

    // ---- Connect mode ----
    function setConnect(on) { connect = on; src = null; selLink = null; disarm(); hideGhosts(); render(); status(on ? M.connect_on : M.connect_off, ''); }
    function connectClick(id) {
      var s = byId(id), set = SET(); if (!s) return;
      if (!src || isSwitch(set, s.code) && id !== src) {
        if (!isSwitch(set, s.code)) { status(fmt(M.connect_not_switch, { code: s.code }), 'warn'); return; }
        src = id; sel = null; render(); status(fmt(M.connect_from, { name: def(s.code).name_de, code: s.code, id: id, allowed: allowedText(s.code) }), ''); return; }
      if (id === src) { src = null; render(); status(M.connect_on, ''); return; }
      var a = byId(src), c = canLink(set, a.code, s.code);
      if (!c[0]) { status(fmt(M.link_not_allowed, { name: def(s.code).name_de, code: s.code, sw: a.code, allowed: allowedText(a.code) }), 'err'); return; }
      if (S.links.some(function (l) { return l.from === src && l.to === id; })) { status(fmt(M.link_exists, { from: src, to: id }), 'warn'); return; }
      pushUndo(); S.links.push({ id: 'l' + S.nextLink++, from: src, to: id }); changed();
      status(fmt(M.linked, { from: src, to: id, code: s.code }), 'ok');
    }
    function applyGroup(i) {
      var g = currentGroups()[i]; if (!g) return;
      var p = proposal(g.switches.map(function (id) { return [id, byId(id).code]; })); if (p.type === 'push' || p.matches) return;
      pushUndo(); g.switches.forEach(function (id) { byId(id).code = p.codes[id]; }); changed();
      status(fmt(M.applied, { n: i + 1, name: p.name, codes: g.switches.map(function (id) { return p.codes[id]; }).join(', ') }), 'ok');
    }
    pg.querySelector('.el-groups-body').addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('button.el-grp-apply') : null; if (b) applyGroup(+b.getAttribute('data-group')); });

    // ---- open / save / copy ----
    function check(text) {
      var o; try { o = JSON.parse(text); } catch (err) { return ['could-not-tell', 'not JSON (' + err.message + ')']; }
      var p = validate(o, SCHEMA);
      if (p.length) return ['could-not-tell', 'not a valid layout file (' + p.length + ' problem(s), first: ' + p[0] + ')'];
      var why = migrate(o); if (why) return ['could-not-tell', 'not a valid layout file: ' + why];
      if (!D.sha256) return ['could-not-tell', "the plan does not know its drawing's checksum, so it cannot tell whether the file belongs to it"];
      if (o.drawing.sha256 !== D.sha256) return ['different', 'the file belongs to another drawing (' + o.drawing.file + ', checksum ' + o.drawing.sha256.slice(0, 12) + '…), not to this one (' + D.sha256.slice(0, 12) + '…)'];
      if (o.drawing.storey !== key) return ['different', 'the file belongs to storey ' + o.drawing.storey + ', not to storey ' + key];
      var set = setById(o.symbol_set.id);
      if (!set) return ['could-not-tell', 'the file uses symbol set ' + o.symbol_set.id + ', which this page does not offer'];
      var codes = {}; set.symbols.forEach(function (s) { codes[s.code] = 1; });
      var unknown = o.symbols.filter(function (s) { return !codes[s.code]; }).map(function (s) { return s.code; });
      if (unknown.length) return ['could-not-tell', 'symbol code(s) ' + unknown.join(', ') + ' are not in set ' + set.id];
      if (!ruleSet(o.rule_set)) return ['could-not-tell', 'the file uses rule set ' + o.rule_set + ', which this page does not offer'];
      var lp = linkProblems(o.symbols, o.links, set);
      if (lp.length) return ['could-not-tell', lp.length + ' link problem(s), first: ' + lp[0]];
      return ['match', o.symbols.length + ' symbol(s), ' + o.links.length + ' link(s), drawing and storey match', o];
    }
    function doOpen(o, msgText, name, h, quiet) {
      if (!quiet) pushUndo();
      S.set = o.symbol_set.id; setSel.value = S.set; showSet(); S.rules = o.rule_set;
      var missing = applyLayers(o.background.layers);
      S.symbols = o.symbols.map(function (s) { return { id: s.id, code: s.code, x: s.x, y: s.y, rotation: s.rotation, room: s.room, room_method: s.room_method }; });
      S.links = o.links.map(function (l) { return { id: l.id, from: l.from, to: l.to }; });
      S.next = S.symbols.reduce(function (m, s) { return Math.max(m, num(s.id) + 1); }, 1);
      S.nextLink = S.links.reduce(function (m, l) { return Math.max(m, num(l.id) + 1); }, 1);
      sel = null; selLink = null; src = null; handle = h || null; inPlaceLabel(); S.example = null; exampleUi(); changed();
      var msg = quiet ? fmt(M.draft_restored, { n: S.symbols.length }) : fmt(M.opened, { file: name, msg: msgText });
      if (missing) msg += ' ' + fmt(M.missing_layers, { n: missing });
      status(msg, missing ? 'warn' : 'ok');
    }
    function openText(text, name, h, quiet) {
      var res = check(text);
      pg.setAttribute('data-el-open', res[0]); pg.elLastOpen = res.slice(0, 2);
      if (res[0] !== 'match') { if (!quiet) status(fmt(res[0] === 'different' ? M.refused_different : M.refused_unknown, { msg: res[1] }), 'err'); return res[0]; }
      if (!quiet && S.symbols.length && !S.example) {
        ask(fmt(M.replace_confirm, { n: S.symbols.length }), function () { doOpen(res[2], res[1], name, h, false); });
        return 'asked'; }
      doOpen(res[2], res[1], name, h, quiet);
      return 'match';
    }
    function layoutText() { return JSON.stringify(layout(), null, 1); }
    function inPlaceLabel() { var b = B('save-in-place'); if (!b) return; b.hidden = !(V.fs && 'showSaveFilePicker' in window);
      b.textContent = handle ? 'Save (in place: ' + handle.name + ')' : 'Save to file…'; }
    // @pages-only-start
    async function saveInPlace() {
      try {
        if (!handle) handle = await window.showSaveFilePicker({ suggestedName: D.file_name, types: [{ description: 'Electrical layout', accept: { 'application/json': ['.json'] } }] });
        var w = await handle.createWritable(); await w.write(layoutText()); await w.close();
        inPlaceLabel(); status(fmt(M.saved_in_place, { file: handle.name }), 'ok');
      } catch (err) { if (err && err.name === 'AbortError') return; status(fmt(M.save_failed, { msg: err && err.message || err }), 'err'); }
    }
    async function openPickerFs() {
      try { var hs = await window.showOpenFilePicker({ types: [{ description: 'Electrical layout', accept: { 'application/json': ['.json'] } }] });
        var f = await hs[0].getFile(); readFile(f, function (t, n) { if (t !== null) openText(t, n, hs[0], false); }); }
      catch (err) { if (err && err.name === 'AbortError') return; fileIn.click(); }
    }
    // @pages-only-end
    function openPicker() { if (typeof openPickerFs === 'function' && V.fs && 'showOpenFilePicker' in window) openPickerFs(); else fileIn.click(); }
    fileIn.addEventListener('change', function () { var f = fileIn.files && fileIn.files[0]; if (!f) return;
      readFile(f, function (t, n, err) { fileIn.value = ''; if (t === null) { status(fmt(M.refused_unknown, { msg: 'the file could not be read (' + err + ')' }), 'err'); return; } openText(t, n, null, false); }); });
    function showSet() { pg.querySelectorAll('.el-pal-set').forEach(function (d) { d.hidden = d.getAttribute('data-set') !== S.set; }); }
    setSel.addEventListener('change', function () { if (S.symbols.length) { setSel.value = S.set; return; } S.set = setSel.value; disarm(); showSet(); changed(); });
    if (sugAllBox) sugAllBox.addEventListener('change', function () { if (ghostCode) return; hideGhosts();
      if (sugAllBox.checked) status(fmt(M.sug_all, { n: ghostG.querySelectorAll('.el-ghost-m').length, set: ruleSet(S.rules).name }), ''); });
    if (rulesSel) rulesSel.addEventListener('change', function () { S.rules = rulesSel.value; var c = ghostCode; hideGhosts(); if (c) showGhosts(c); changed();
      status(fmt(M.rules_changed, { set: ruleSet(S.rules).name }), ''); });

    // ---- palette: drag onto the drawing (mouse, pen or finger), or click to select then click the drawing ----
    // picked, not placed: say so after the rings are drawn (the rings' own status line would hide it, and rings look like symbols)
    function arm(code, btn) { disarm(); if (connect) setConnect(false); armed = code; btn.setAttribute('aria-pressed', 'true'); view.classList.add('el-armed');
      var n = showGhosts(code); status(fmt(n ? M.armed_rings : M.armed, { name: def(code).name_de, n: n }), 'warn'); }
    function disarm() { armed = null; view.classList.remove('el-armed'); if (!pd && !mv) hideGhosts();
      pg.querySelectorAll('.el-sym-btn[aria-pressed="true"]').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); }); }
    var pd = null, justDragged = false, mv = null, pend = null, cpend = null;
    pg.querySelectorAll('.el-sym-btn').forEach(function (btn) {
      btn.addEventListener('pointerdown', function (e) { if (e.button !== 0) return; e.preventDefault(); btn.focus(); justDragged = false;
        pd = { id: e.pointerId, x: e.clientX, y: e.clientY, code: btn.getAttribute('data-code'), moved: false };
        try { btn.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events cannot be captured */ } });
      btn.addEventListener('pointermove', function (e) { if (!pd || e.pointerId !== pd.id) return;
        if (!pd.moved && Math.hypot(e.clientX - pd.x, e.clientY - pd.y) < CFG.drag_threshold_px) return;
        if (!pd.moved) { pd.moved = true; if (connect) setConnect(false); ghost.innerHTML = '<span class="el-chip">' + preview(SET(), def(pd.code), 'el-prev') + '</span>'; ghost.hidden = false; showGhosts(pd.code); }
        ghost.style.left = (e.clientX + 6) + 'px'; ghost.style.top = (e.clientY + 6) + 'px'; hover(e.clientX, e.clientY, pd.code); });
      btn.addEventListener('pointerup', function (e) { if (!pd || e.pointerId !== pd.id) return; var p = pd; pd = null; ghost.hidden = true;
        try { btn.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
        if (p.moved) { justDragged = true; setTimeout(function () { justDragged = false; }, 0); place(p.code, e.clientX, e.clientY, e.altKey); } });
      btn.addEventListener('pointercancel', function () { pd = null; ghost.hidden = true; hideGhosts(); });
      btn.addEventListener('click', function () { if (justDragged) { justDragged = false; return; }
        var code = btn.getAttribute('data-code'); if (armed === code) { disarm(); hideGhosts(); status('', ''); } else arm(code, btn); });
    });

    // ---- the stage: select, move, place an armed symbol, connect, select a link (the viewer pans only when none applies) ----
    view.panBlock = function (e) { return !!armed || !!(e.target.closest && (e.target.closest('.el-sym') || e.target.closest('.el-link-hit'))); };
    svg.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      var lk = e.target.closest ? e.target.closest('.el-link-hit') : null;
      if (lk && !armed) { var l = linkById(lk.getAttribute('data-link')); selLink = l ? l.id : null; sel = null; e.preventDefault(); render();
        if (l) status(fmt(M.link_selected, { id: l.id, from: l.from, to: l.to }), ''); return; }
      var t = e.target.closest ? e.target.closest('.el-sym') : null;
      if (t && connect) { cpend = { id: t.getAttribute('data-id'), pid: e.pointerId, x: e.clientX, y: e.clientY }; e.preventDefault(); return; }
      if (t && !armed) { var s = byId(t.getAttribute('data-id')), p = clientToView(e.clientX, e.clientY), m = toModel(A, p[0], p[1]);
        sel = s.id; selLink = null; mv = { id: s.id, pid: e.pointerId, x: e.clientX, y: e.clientY, dx: s.x - m[0], dy: s.y - m[1], moved: false, snap: snap(), rot: s.rotation };
        try { svg.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events cannot be captured */ } e.preventDefault(); render(); return; }
      if (armed) { pend = { pid: e.pointerId, x: e.clientX, y: e.clientY, moved: false }; e.preventDefault(); return; }
      if (sel || selLink) { sel = null; selLink = null; render(); }
    });
    svg.addEventListener('pointermove', function (e) {
      if (armed) hover(e.clientX, e.clientY, armed);
      if (pend && e.pointerId === pend.pid && Math.hypot(e.clientX - pend.x, e.clientY - pend.y) >= CFG.drag_threshold_px) pend.moved = true;
      if (!mv || e.pointerId !== mv.pid) return;
      if (!mv.moved && Math.hypot(e.clientX - mv.x, e.clientY - mv.y) < CFG.drag_threshold_px) return;
      var s = byId(mv.id);
      if (!mv.moved) { mv.moved = true; showGhosts(s.code); }
      var p = clientToView(e.clientX, e.clientY), m = toModel(A, p[0], p[1]);
      s.x = r6(m[0] + mv.dx); s.y = r6(m[1] + mv.dy); render(); hover(e.clientX, e.clientY, s.code);
    });
    svg.addEventListener('pointerup', function (e) {
      if (cpend && e.pointerId === cpend.pid) { var c = cpend; cpend = null; if (Math.hypot(e.clientX - c.x, e.clientY - c.y) < CFG.drag_threshold_px) connectClick(c.id); return; }
      if (mv && e.pointerId === mv.pid) { var q = mv; mv = null; try { svg.releasePointerCapture(e.pointerId); } catch (err) { /* released */ }
        if (q.moved) { var s = byId(q.id), n = !e.altKey && snapOn() ? nearest(s.code, [s.x, s.y]) : null;
          if (n) { s.x = n.g.x; s.y = n.g.y; s.rotation = n.g.rot || 0; }
          var rm = roomOf(s.x, s.y); s.room = rm[0]; s.room_method = rm[1]; hideGhosts(); pushUndo(q.snap); changed();
          if (n) status(fmt(M.snapped, { name: def(s.code).name_de, code: s.code, kind: RULES.suggest[n.g.kind].name, set: ruleSet(S.rules).name }), 'ok'); }
        else render();
        return; }
      if (pend && e.pointerId === pend.pid) { var pp = pend; pend = null; if (!pp.moved && armed) place(armed, e.clientX, e.clientY, e.altKey); }
    });
    view.addEventListener('keydown', function (e) {
      if (e.target !== view || !armed || (e.key !== 'Enter' && e.key !== ' ')) return;
      e.preventDefault(); var r = svg.getBoundingClientRect(); place(armed, r.left + r.width / 2, r.top + r.height / 2, false);
    });
    pg.elKey = function (e) {
      var k2 = e.key, mod = e.ctrlKey || e.metaKey;
      if (k2 === 'Escape') { if (connect) { if (src) { src = null; render(); status(M.connect_on, ''); } else setConnect(false); return true; }
        disarm(); hideGhosts(); if (sel || selLink) { sel = null; selLink = null; render(); } return true; }
      if (mod && (k2 === 'z' || k2 === 'Z')) { if (e.shiftKey) doRedo(); else doUndo(); return true; }
      if (mod && (k2 === 'y' || k2 === 'Y')) { doRedo(); return true; }
      if (mod) return false;
      if (k2 === 'Delete' || k2 === 'Backspace') { if (!sel && !selLink) return false; del(); return true; }
      if (k2 === 'r' || k2 === 'R') { if (!sel) return false; rotate(); return true; }
      return false;
    };

    // ---- the bar ----
    B('open').addEventListener('click', openPicker);
    // @pages-only-start
    if (B('save')) B('save').addEventListener('click', function () { download(layoutText(), D.file_name); status(fmt(M.saved_download, { file: D.file_name }), 'ok'); });
    if (B('save-in-place')) B('save-in-place').addEventListener('click', saveInPlace);
    // @pages-only-end
    B('copy').addEventListener('click', function () { var o = layout(); copyText(JSON.stringify(o, null, 1), function () {
      status(fmt(M.copied_layout, { n: o.symbols.length, l: o.links.length }), 'ok'); }); });
    B('undo').addEventListener('click', doUndo); B('redo').addEventListener('click', doRedo);
    B('rotate').addEventListener('click', rotate); B('delete').addEventListener('click', del);
    B('connect').addEventListener('click', function () { setConnect(!connect); });
    B('discard').addEventListener('click', function () {
      ask(M.discard_confirm, function () {
        clearAll(); undo = []; redo = []; applyLayers([]); disarm(); store(DKEY, null); render(); status(M.draft_discarded, 'ok'); });
    });

    // ---- print legend: the symbols actually placed on layers that are on; links and the switching type per group ----
    view.printLegend = function () {
      var on = {}, set = SET(), items = [];
      view.querySelectorAll('input[data-toggle-layer]').forEach(function (i) { on[i.getAttribute('data-toggle-layer')] = i.checked; });
      items.push('<span class="ps-item">' + escH(fmt(M.legend_layers, { n: shownLayers().length })) + '</span>');
      set.symbols.forEach(function (d) { if (!on[d.layer]) return; var n = S.symbols.filter(function (s) { return s.code === d.code; }).length; if (!n) return;
        items.push('<span class="ps-item el-leg" data-code="' + escH(d.code) + '">' + preview(set, d, 'el-leg-svg') + escH(d.name_de) + ' (' + escH(d.code) + ') × ' + n + '</span>'); });
      if (on[LINKL] && S.links.length) {
        items.push('<span class="ps-item el-leg-link">' + escH(fmt(M.legend_links, { n: S.links.length })) + '</span>');
        currentGroups().forEach(function (g, i) { var codes = g.switches.map(function (id) { return byId(id).code; });
          var p = proposal(g.switches.map(function (id, j) { return [id, codes[j]]; }));
          items.push('<span class="ps-item el-leg-grp" data-type="' + p.type + '">' + escH(fmt(M.legend_group, { n: i + 1, name: p.name, ns: g.switches.length, nl: g.lights.length })) +
            (p.matches ? '' : ' – ' + escH(codes.join(', ')) + ' placed') + '</span>'); });
      }
      if (S.example) items.push('<span class="ps-item el-leg-unv el-leg-ex">' + escH(D.synthetic ? M.example_banner_synthetic : M.example_banner) + '</span>');
      items.push('<span class="ps-item el-leg-unv">' + escH(M.legend_note) + '</span>');
      return items.join('');
    };

    // ---- print view notes (core.js shows them above the sheet): only placed symbols on layers that are on will print ----
    view.printNotice = function () {
      var on = {}, out = [];
      view.querySelectorAll('input[data-toggle-layer]').forEach(function (i) { on[i.getAttribute('data-toggle-layer')] = i.checked; });
      var shown = S.symbols.filter(function (s) { return on[def(s.code).layer]; }).length, hidden = S.symbols.length - shown;
      if (armed) out.push(['warn', fmt(M.print_armed, { name: def(armed).name_de })]);
      out.push(shown ? ['ok', fmt(M.print_ok, { n: shown })] : ['warn', M.print_none]);
      if (hidden) out.push(['warn', fmt(M.print_hidden, { n: hidden })]);
      return out;
    };
    view.onPrint = function () { disarm(); hideGhosts(); };

    if (window.vptInitViewer) window.vptInitViewer(view);
    if (window.vptTipify) window.vptTipify(pg);
    inPlaceLabel(); exampleUi();
    var draft = store(DKEY);
    if (draft && check(draft)[0] === 'match') openText(draft, 'draft', null, true);
    else if (D.examples && D.examples.simple) { showExample('simple', true); status(fmt(M.example_default, { label: D.examples.simple.example.label }), 'ok'); }
    else status(M.empty_storey, '');
    render();
    window.elPages[key] = { page: pg, D: D, state: function () { return JSON.parse(JSON.stringify(S)); }, layout: layout, layoutText: layoutText,
      check: check, open: function (t, n) { return openText(t, n || 'file', null, false); }, select: function (id) { sel = id; render(); },
      anchor: function (id) { var a = svg.querySelector('.el-sym[data-id="' + CSS.escape(id) + '"] .el-anchor'); if (!a) return null;
        var r = a.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; },
      groups: currentGroups, hints: currentHints, checksOf: function (symbols, links, setId) {
        return layoutChecks(symbols, links, D.rooms, D.doors || [], D.units_per_m, setId, SET(), D.rooms_known); }, proposal: function (i) { var g = currentGroups()[i];
        return g ? proposal(g.switches.map(function (id) { return [id, byId(id).code]; })) : null; },
      suggestions: function (kind) { return sugList(kind); }, ghosts: function () { return ghostG.querySelectorAll('.el-ghost-m').length; },
      example: function (id) { return showExample(id, false); }, exampleShown: function () { return S.example; }, shownLayers: shownLayers,
      toView: function (x, y) { return toView(A, x, y); }, draftKey: DKEY };
    return pg;
  }

  // ---- Open plan (file or paste) ----
  function openPlanText(text, name) {
    var res = checkPlan(text);
    document.getElementById('vpt').setAttribute('data-plan-open', res[0]);
    if (res[0] !== 'match') { gstatus(fmt(res[0] === 'different' ? M.plan_refused_different : M.plan_refused_unknown, { msg: res[1] }), 'err'); return res[0]; }
    loadPlan(res[2], name); gstatus(fmt(M.plan_opened, { file: name, msg: res[1] }), 'ok');
    return 'match';
  }
  var planIn = document.querySelector('input.vpt-plan-file');
  document.querySelector('[data-vpt="open-plan"]').addEventListener('click', function () { planIn.click(); });
  planIn.addEventListener('change', function () { var f = planIn.files && planIn.files[0]; if (!f) return;
    readFile(f, function (t, n, err) { planIn.value = ''; if (t === null) { gstatus(fmt(M.plan_refused_unknown, { msg: 'the file could not be read (' + err + ')' }), 'err'); return; } openPlanText(t, n); }); });
  function activePage() { return pages.filter(function (p) { return !p.hidden; })[0] || null; }
  // paste a plan, layout or parameter file anywhere outside an input box
  document.addEventListener('paste', function (e) {
    var t = e.target; if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
    var text = (e.clipboardData || window.clipboardData).getData('text'); if (!text) return;
    e.preventDefault();
    var o; try { o = JSON.parse(text); } catch (err) { gstatus(fmt(M.paste_unknown, { msg: 'not JSON (' + err.message + ')' }), 'err'); return; }
    var kind = o && typeof o === 'object' ? (o.schema || o.name) : null;
    if (kind === 'vpt_plan') { openPlanText(text, 'pasted text'); return; }
    if (kind === 'el_layout') { var pg = activePage(); if (pg) window.elPages[pg.getAttribute('data-storey')].open(text, 'pasted text'); gstatus('', ''); return; }
    if (kind === 'el_parameters' && window.elParams) { if (window.vptShowTab) window.vptShowTab('vpt-pane-params'); window.elParams.load(text, 'pasted text'); return; }
    gstatus(fmt(M.paste_unknown, { msg: kind ? 'a file of kind ' + kind : 'not a plan, layout or parameter file' }), 'err');
  });
  document.addEventListener('keydown', function (e) {
    var t = e.target; if (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName)) return;
    if (document.body.classList.contains('dwg-printing')) return;
    if (!ASK.hidden && e.key === 'Escape') { ASK.querySelector('[data-ask="no"]').click(); e.preventDefault(); return; }
    var pane = document.getElementById('vpt-pane-editor'); if (pane && pane.hidden) return;
    var pg = activePage();
    if (pg && pg.elKey(e)) e.preventDefault();
  });
  window.vptOnTab = function () { pages.forEach(function (pg) { if (!pg.hidden && pg.elRestyle) pg.elRestyle(); }); };

  applyStyle();
  loadPlan(J('vpt-plan'), 'sample');
  window.elApplyStyle = applyStyle;
  window.vptApi = { openPlanText: openPlanText, checkPlan: checkPlan, plan: function () { return PLAN; }, activeKey: function () { return activeKey; },
    showStorey: showStorey, askYes: function () { var b = ASK.querySelector('[data-ask="yes"]'); if (!ASK.hidden) b.click(); }, asking: function () { return !ASK.hidden; } };
})();
