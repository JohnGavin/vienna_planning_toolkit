/* Shared page behaviour of the electrical editor (vienna_planning_toolkit): page tabs, sortable + filterable tables, hover
   popups, Documentation links (#doc-...), and the drawing viewer (zoom, pan, layer toggles, print view). Inline on purpose:
   nothing is loaded from the network. editor.js (after this) builds the storey stages and calls window.vptInitViewer on each. */
(function () {
  'use strict';
  function cfgJSON() { try { var el = document.getElementById('el-config'); return el ? JSON.parse(el.textContent) : {}; } catch (err) { return {}; } }
  var CFG0 = cfgJSON(), PCFG = CFG0.print || null;
  function escH(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function store(k, v) { try { if (v === undefined) return window.localStorage.getItem(k); window.localStorage.setItem(k, v); } catch (err) { return null; } return null; }

  // ---- page tabs (Editor / Documentation) ----
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.vpt-tabs [role="tab"]'));
  function showTab(id) {
    tabs.forEach(function (t) { var on = t.getAttribute('aria-controls') === id; t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1;
      var p = document.getElementById(t.getAttribute('aria-controls')); if (p) p.hidden = !on; });
    if (window.vptOnTab) window.vptOnTab(id);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { showTab(t.getAttribute('aria-controls')); });
    t.addEventListener('keydown', function (e) { if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return; e.preventDefault();
      var n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; n.focus(); showTab(n.getAttribute('aria-controls')); });
  });
  window.vptShowTab = showTab;

  // ---- tables ----
  function key(t) { var s = t.trim(); var n = s.replace(/\s*(m2|%)$/, '').replace(/\./g, '').replace(',', '.');
    return /^-?\d+(\.\d+)?$/.test(n) ? [0, parseFloat(n)] : [1, s.toLowerCase()]; }
  document.querySelectorAll('table.sf').forEach(function (tbl) {
    var heads = tbl.querySelectorAll('thead tr.names th'), body = tbl.tBodies[0];
    var inputs = tbl.querySelectorAll('thead tr.filters input'), counter = tbl.closest('.tblwrap') ? tbl.closest('.tblwrap').querySelector('.count') : null;
    function filter() {
      var shown = 0;
      Array.prototype.forEach.call(body.rows, function (r) { var ok = true;
        inputs.forEach(function (inp, c) { var q = inp.value.trim().toLowerCase(); if (q && r.cells[c].textContent.toLowerCase().indexOf(q) < 0) ok = false; });
        r.hidden = !ok; if (ok) shown++; });
      if (counter) counter.textContent = shown + ' of ' + body.rows.length + ' rows';
    }
    inputs.forEach(function (inp) { inp.addEventListener('input', filter); });
    heads.forEach(function (th, c) {
      th.tabIndex = 0;
      function sort() {
        var asc = th.getAttribute('aria-sort') !== 'ascending';
        heads.forEach(function (h) { h.removeAttribute('aria-sort'); }); th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) { var x = key(a.cells[c].textContent), y = key(b.cells[c].textContent);
          var r = x[0] - y[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0); return asc ? r : -r; });
        rows.forEach(function (r) { body.appendChild(r); });
      }
      th.addEventListener('click', sort);
      th.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); } });
    });
    filter();
  });

  // ---- hover popups (data-tip): hover, focus and tap; Escape or a tap elsewhere closes; delegated, so elements created later work ----
  var box = document.createElement('div'); box.id = 'tipbox'; box.hidden = true; box.setAttribute('role', 'tooltip');
  document.body.appendChild(box); var current = null, timer = null;
  function tipOf(t) { return t && t.closest ? t.closest('.tip') : null; }
  function open(el) { clearTimeout(timer); current = el; box.innerHTML = el.getAttribute('data-tip'); box.hidden = false;
    var r = el.getBoundingClientRect(), vw = document.documentElement.clientWidth;
    box.style.left = Math.max(8, Math.min(window.scrollX + r.left, window.scrollX + vw - box.offsetWidth - 8)) + 'px';
    box.style.top = (window.scrollY + r.bottom + 6) + 'px'; }
  function close() { clearTimeout(timer); box.hidden = true; current = null; }
  function later() { clearTimeout(timer); timer = setTimeout(function () { if (!box.matches(':hover') && !(current && current.matches(':hover'))) close(); }, 350); }
  function tipify(root) { (root || document).querySelectorAll('.tip').forEach(function (el) {
    if (!/^(BUTTON|INPUT|SUMMARY|A|SELECT)$/.test(el.tagName) && !(el instanceof SVGElement)) el.tabIndex = 0; el.setAttribute('aria-describedby', 'tipbox'); }); }
  tipify(document);
  window.vptTipify = tipify; window.vptCloseTip = close;
  document.addEventListener('mouseover', function (e) { var el = tipOf(e.target); if (el && el !== current && !box.contains(el)) open(el); });
  document.addEventListener('mouseout', function (e) { var el = tipOf(e.target); if (el && el === current && !el.contains(e.relatedTarget)) later(); });
  box.addEventListener('mouseleave', later);
  document.addEventListener('focusin', function (e) { var el = tipOf(e.target); if (el) open(el); });
  document.addEventListener('focusout', function (e) { if (current && e.target === current && !box.contains(e.relatedTarget)) later(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  document.addEventListener('click', function (e) { var el = tipOf(e.target);
    if (el && el.tagName !== 'BUTTON' && !(el instanceof SVGElement) && el !== current && !box.contains(el)) { open(el); return; }
    if (current && !current.contains(e.target) && !box.contains(e.target)) close(); });

  // ---- Documentation links: show the tab that holds the anchor, scroll to it, mark it briefly ----
  function showDoc(id) {
    var t = document.getElementById(id); if (!t) return false;
    if (document.body.classList.contains('dwg-printing')) { var x = document.querySelector('#dwg-printsheet [data-act="exit-print"]'); if (x) x.click(); }
    var pane = t.closest('.vpt-pane'); if (pane && pane.hidden) showTab(pane.id);
    setTimeout(function () { t.scrollIntoView({ block: 'start' }); t.classList.add('doc-flash'); setTimeout(function () { t.classList.remove('doc-flash'); }, 1800); }, 60);
    return true;
  }
  window.vptShowDoc = showDoc;
  document.addEventListener('click', function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#doc-"]') : null; if (!a) return;
    if (showDoc(a.getAttribute('href').slice(1))) { e.preventDefault(); close(); } });
  if (location.hash.indexOf('#doc-') === 0) setTimeout(function () { showDoc(location.hash.slice(1)); }, 50);

  // ---- the drawing viewer: one per storey stage (div.el-view) ----
  function printSheet() {
    var s = document.getElementById('dwg-printsheet'); if (s) return s;
    s = document.createElement('div'); s.id = 'dwg-printsheet'; s.hidden = true;
    s.innerHTML = '<div class="ps-bar"></div><div class="ps-sheet"><div class="ps-title"></div><div class="ps-draw"></div><div class="ps-legend"></div></div>';
    document.body.appendChild(s); return s;
  }
  function initViewer(v) {
    var svg = v.querySelector('svg'); if (!svg) return;
    var groups = {};
    svg.querySelectorAll('g[data-layer]').forEach(function (g) { groups[g.getAttribute('data-layer')] = g; });
    var lb = Array.prototype.slice.call(v.querySelectorAll('input[data-toggle-layer]'));
    var drawingLb = lb.filter(function (i) { return i.hasAttribute('data-status'); });
    function show(g, on) { if (!g) return; if (on) g.removeAttribute('display'); else g.setAttribute('display', 'none'); }
    function members(attr, val) { return lb.filter(function (i) { return i.getAttribute(attr) === val; }); }
    function summarise(sel, attr) {
      v.querySelectorAll(sel).forEach(function (b) {
        var m = members(attr, b.getAttribute(sel.slice(6, -1))), n = m.filter(function (i) { return i.checked; }).length;
        b.checked = n > 0; b.indeterminate = n > 0 && n < m.length; });
    }
    function sync() {
      lb.forEach(function (i) { show(groups[i.getAttribute('data-toggle-layer')], i.checked); });
      summarise('input[data-toggle-base]', 'data-base'); summarise('input[data-toggle-status]', 'data-status');
      if (v.onLayers) v.onLayers();
    }
    lb.forEach(function (i) { i.addEventListener('change', sync); });
    [['input[data-toggle-base]', 'data-base'], ['input[data-toggle-status]', 'data-status']].forEach(function (p) {
      v.querySelectorAll(p[0]).forEach(function (b) { b.addEventListener('change', function () {
        members(p[1], b.getAttribute(p[0].slice(6, -1))).forEach(function (i) { i.checked = b.checked; }); sync(); }); });
    });
    var page = svg.getAttribute('viewBox').split(/[ ,]+/).map(parseFloat), vb0 = page.slice(), vb = vb0.slice(), printing = null;
    // the view stays on the page: never zoomed out beyond ZOOM_OUT pages, never in beyond ZOOM_IN, its centre never leaves the page
    var ZOOM_OUT = 4, ZOOM_IN = 400;
    function clampVB() {
      var f = vb[2] / page[2], g = Math.min(Math.max(f, 1 / ZOOM_IN), ZOOM_OUT);
      if (!(isFinite(vb[0]) && isFinite(vb[1]) && f > 0 && isFinite(f))) { vb = vb0.slice(); return; }
      if (g !== f) { var cx0 = vb[0] + vb[2] / 2, cy0 = vb[1] + vb[3] / 2, k = g / f; vb = [cx0 - vb[2] * k / 2, cy0 - vb[3] * k / 2, vb[2] * k, vb[3] * k]; }
      var cx = Math.min(Math.max(vb[0] + vb[2] / 2, page[0]), page[0] + page[2]), cy = Math.min(Math.max(vb[1] + vb[3] / 2, page[1]), page[1] + page[3]);
      vb[0] = cx - vb[2] / 2; vb[1] = cy - vb[3] / 2;
    }
    function setVB() { clampVB(); svg.setAttribute('viewBox', vb.map(function (x) { return Math.round(x * 100) / 100; }).join(' ')); if (printing) fillTitle(); }
    function perPx() { var w = svg.clientWidth || 1, h = svg.clientHeight || 1; return Math.max(vb[2] / w, vb[3] / h); }
    function toUser(ev) { var r = svg.getBoundingClientRect(), k = perPx();
      return [vb[0] + vb[2] / 2 + (ev.clientX - r.left - r.width / 2) * k, vb[1] + vb[3] / 2 + (ev.clientY - r.top - r.height / 2) * k]; }
    function zoom(f, c) { c = c || [vb[0] + vb[2] / 2, vb[1] + vb[3] / 2];
      vb = [c[0] - (c[0] - vb[0]) * f, c[1] - (c[1] - vb[1]) * f, vb[2] * f, vb[3] * f]; setVB(); }
    // the plain wheel scrolls the PAGE; zoom = pinch (a wheel event with ctrlKey) or Ctrl/Cmd + wheel, proportional to the scroll
    svg.addEventListener('wheel', function (e) {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      var dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
      zoom(Math.min(2, Math.max(0.5, Math.pow(1.0025, dy))), toUser(e)); }, { passive: false });
    var drag = null;
    svg.addEventListener('pointerdown', function (e) { if (e.button !== 0 || (v.panBlock && v.panBlock(e))) return; drag = [e.clientX, e.clientY, vb.slice(), perPx()];
      svg.classList.add('dragging'); });
    window.addEventListener('pointermove', function (e) { if (!drag) return;
      vb = [drag[2][0] - (e.clientX - drag[0]) * drag[3], drag[2][1] - (e.clientY - drag[1]) * drag[3], drag[2][2], drag[2][3]]; setVB(); });
    window.addEventListener('pointerup', function () { drag = null; svg.classList.remove('dragging'); });
    v.querySelectorAll('.dwg-tools button').forEach(function (b) { b.addEventListener('click', function () {
      var a = b.getAttribute('data-act');
      if (a === 'in') zoom(0.8); else if (a === 'out') zoom(1.25); else if (a === 'reset') { vb = vb0.slice(); setVB(); }
      else if (a === 'all-on' || a === 'all-off') { drawingLb.forEach(function (i) { i.checked = a === 'all-on'; }); sync(); }
      else if (a === 'print') enterPrint(); }); });
    var flt = v.querySelector('.dwg-filter');
    if (flt) flt.addEventListener('input', function () { var q = flt.value.trim().toLowerCase();
      v.querySelectorAll('details.base').forEach(function (d) { var any = false, baseHit = d.getAttribute('data-name').indexOf(q) >= 0;
        d.querySelectorAll('.lyr').forEach(function (l) { var hit = !q || baseHit || l.getAttribute('data-name').indexOf(q) >= 0; l.hidden = !hit; if (hit) any = true; });
        d.hidden = !any; if (q) d.open = any; }); });
    var panel = v.querySelector('details.dwg-panel'), pkey = 'vpt-panel:' + (v.getAttribute('data-view-id') || '');
    if (panel) {
      var saved = store(pkey); if (saved === 'closed') panel.open = false; else if (saved === 'open') panel.open = true;
      panel.addEventListener('toggle', function () { store(pkey, panel.open ? 'open' : 'closed'); });
    }
    // print view (Pages version): the SVG moves into one A3 page (#dwg-printsheet) with a title row, scale note and legend
    function scaleNote() {
      var sc = parseFloat(v.getAttribute('data-scale')), pm = (v.getAttribute('data-page-mm') || '').split(' ').map(parseFloat);
      if (!(sc > 0) || !(pm[0] > 0) || !PCFG) return 'Not to scale';
      var paperPerUnit = pm[0] / page[2], printedPerUnit = Math.min(PCFG.draw_mm[0] / vb[2], PCFG.draw_mm[1] / vb[3]);
      return 'Scale about 1:' + Math.round(sc * paperPerUnit / printedPerUnit) + ' on ' + PCFG.paper + ' (plan page 1:' + sc + ')';
    }
    function fillTitle() {
      var s = printSheet(), shown = drawingLb.filter(function (i) { return i.checked; }).length;
      s.querySelector('.ps-title').innerHTML = '<span class="ps-l">' + escH(v.getAttribute('data-print-title') || '') + '</span><span>' + escH(v.getAttribute('data-print-date') || '') +
        '</span><span class="ps-scale">' + escH(scaleNote()) + '</span><span>' + (printing.mode === 'fit' ? 'whole storey' : 'current view') + ', ' + shown + ' of ' + drawingLb.length + ' drawing layers</span>';
    }
    function setMode(m) { printing.mode = m; vb = (m === 'fit' ? page : printing.cur).slice(); setVB(); }
    function enterPrint() {
      if (printing || document.body.classList.contains('dwg-printing')) return;
      var s = printSheet(), tips = (PCFG && PCFG.tips) || {};
      printing = { cur: vb.slice(), ph: document.createComment('dwg-svg'), mode: 'fit' };
      svg.parentNode.insertBefore(printing.ph, svg); s.querySelector('.ps-draw').appendChild(svg);
      var t = function (k) { return tips[k] ? ' class="tip" data-tip="' + escH(tips[k]) + '"' : ''; };
      s.querySelector('.ps-bar').innerHTML = '<button type="button" data-act="exit-print"' + t('exit-print') + '>Exit print view</button>' +
        '<span' + t('fit') + '><label><input type="radio" name="ps-mode" value="fit" checked> Fit storey</label> ' +
        '<label><input type="radio" name="ps-mode" value="current"> Current view</label></span>' +
        '<button type="button" data-act="do-print"' + t('print') + '>Print / Save as PDF</button>' +
        '<span class="ps-hint">' + escH(PCFG ? PCFG.paper + ' ' + PCFG.orientation : '') + ' · Destination: Save as PDF · Margins: none · Background graphics: on</span>';
      s.querySelector('[data-act="exit-print"]').onclick = exitPrint;
      // @pages-only-start
      s.querySelector('[data-act="do-print"]').onclick = function () { window.print(); };
      // @pages-only-end
      s.querySelectorAll('input[name="ps-mode"]').forEach(function (r) { r.onchange = function () { if (r.checked) setMode(r.value); }; });
      document.body.classList.add('dwg-printing'); s.hidden = false; close();
      if (v.printLegend) s.querySelector('.ps-legend').innerHTML = v.printLegend();
      setMode('fit'); window.scrollTo(0, 0);
    }
    function exitPrint() {
      if (!printing) return; var s = printSheet();
      printing.ph.parentNode.insertBefore(svg, printing.ph); printing.ph.parentNode.removeChild(printing.ph);
      vb = printing.cur.slice(); printing = null; setVB();
      document.body.classList.remove('dwg-printing'); s.hidden = true; close();
      v.scrollIntoView({ block: 'start' });
    }
    v.dwgApi = { vb: function () { return vb.slice(); }, page: page.slice(), sync: sync, printing: function () { return !!printing; },
                 exitPrint: exitPrint, enterPrint: enterPrint, reset: function () { vb = vb0.slice(); setVB(); } };
    sync();
  }
  window.vptInitViewer = initViewer;
})();
