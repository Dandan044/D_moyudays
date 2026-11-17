const KIND = {
  code:     { label: "代码", color: "#5DCAA5" },
  doc:      { label: "文档", color: "#EF9F27" },
  data:     { label: "数据", color: "#85B7EB" },
  ops:      { label: "配置", color: "#F0997B" },
  research: { label: "调研", color: "#97C459" },
  design:   { label: "讨论", color: "#AFA9EC" }
};

const COL = {
  weekend: "rgba(230,226,213,0.032)",
  quiet: "rgba(230,226,213,0.06)",
  grid: "#23231b",
  week: "#7a3a24",
  head: "#6f6b58",
  base: "#3a3a2e"
};

const state = { project: "all", harness: "", days: 14, payload: null, expanded: new Set(), open: new Set(), suppressClick: false, mode: "bars" };

/* 热力色阶：白 → 玫红 → 正红 → 品红 → 亮紫
   末端往紫走而不是往暗红走，否则在深色底上会糊成一团 */
const HEAT_BUCKETS = [
  { max: 1, color: "#F6EDEF" },
  { max: 3, color: "#F2A7B8" },
  { max: 8, color: "#E2504E" },
  { max: 20, color: "#C63FA8" },
  { max: Infinity, color: "#A07BF5" }
];

function heatColor(files) {
  if (!files) return "#FBEAEA";
  for (const b of HEAT_BUCKETS) if (files <= b.max) return b.color;
  return HEAT_BUCKETS[HEAT_BUCKETS.length - 1].color;
}

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (d) => { const [, m, dd] = d.split("-"); return `${Number(m)}/${Number(dd)}`; };
const nf = (n) => Number(n || 0).toLocaleString("en-US");
const fmtH = (v) => {
  const h = Math.floor(v);
  const m = Math.round((v - h) * 60);
  return `${String(h).padStart(2, "0")}:${String(m === 60 ? 0 : m).padStart(2, "0")}`;
};
const clip = (t, n) => (String(t || "").length > n ? String(t).slice(0, n - 1) + "…" : String(t || ""));

// 按像素宽度截断：中文约 12.5px，ASCII 约 7px，避免中英混排被误截
function clipPx(text, maxPx, size = 12.5) {
  const t = String(text || "");
  let w = 0;
  let out = "";
  for (const ch of t) {
    const cw = /[\x00-\xff]/.test(ch) ? size * 0.56 : size;
    if (w + cw > maxPx) return out.slice(0, -1) + "…";
    out += ch;
    w += cw;
  }
  return out;
}

/* ---------------- 结论 ---------------- */
function renderHeadline(p) {
  const s = p.summary;
  const stat = (v, unit, label, glow) =>
    `<div class="stat${glow ? " glow" : ""}"><b>${v}<i>${unit || ""}</i></b><span>${label}</span></div>`;

  const kindText = Object.entries(s.kinds)
    .sort((x, y) => y[1] - x[1])
    .map(([k, v]) => `${(KIND[k] || { label: k }).label} ${v}`)
    .join(" · ");

  $("stats").innerHTML = [
    stat(s.hours ? s.hours.toFixed(1) : "0", "h", "累计在岗", true),
    stat(nf(s.lines), "", "累计改动行", true),
    stat(s.unit_count, "", "工作单元"),
    stat(s.output_count, "", "有产出"),
    stat(`${s.active_days}/${s.total_days}`, "", "活跃天数"),
  ].join("");

  const when = (s.last_scan || "").replace("T", " ").slice(5, 16);
  $("hlSub").innerHTML =
    `<span class="dash">${fmt(s.from)} – ${fmt(s.to)}</span>` +
    (kindText ? `<span>${kindText}</span>` : "") +
    (when ? `<span class="upd">最后更新 ${when}</span>` : "");
}

function renderLegend(p) {
  if (state.mode === "heat") {
    const swatches = ["1", "2-3", "4-8", "9-20", "21+"]
      .map(
        (label, i) =>
          `<span class="k"><span class="dot" style="background:${HEAT_BUCKETS[i].color}"></span>${label}</span>`
      )
      .join("");
    $("legend").innerHTML =
      `<span class="k" style="color:#8f8a76">变更文件数</span>` +
      swatches +
      `<span class="k" style="color:#6f6b58">白＝少　紫＝多　空心条＝无文件产出</span>`;
    return;
  }
  const present = [...new Set(p.units.map((u) => u.kind))];
  $("legend").innerHTML = present
    .map((k) => {
      const m = KIND[k] || { label: k, color: "#888" };
      const cls = k === "design" ? "dot hollow" : "dot";
      const style = k === "design" ? "" : `background:${m.color}`;
      return `<span class="k"><span class="${cls}" style="${style}"></span>${m.label}</span>`;
    })
    .join("");
}

/* ---------------- 行结构 ---------------- */
function buildRows(p) {
  const rows = [];
  const grouped = new Set();
  // 统一按「最近一次有动静」（end_day）倒序，同 end_day 再比 start_day
  const byRecent = (a, b) => {
    if (a.end_day !== b.end_day) return a.end_day > b.end_day ? -1 : 1;
    if (a.start_day !== b.start_day) return a.start_day > b.start_day ? -1 : 1;
    return 0;
  };
  const gs = [...p.groups].sort(byRecent);

  gs.forEach((g, gi) => {
    g.units.forEach((u) => grouped.add(u.id));
    rows.push({ type: "group", g, key: g.end_day, sub: 0, seq: gi * 100 });
    if (state.expanded.has(g.id)) {
      const members = [...g.units].sort(byRecent);
      members.forEach((u, ui) =>
        rows.push({ type: "unit", u, g, key: g.end_day, sub: 1, seq: gi * 100 + ui + 1 })
      );
    }
  });

  p.units
    .filter((u) => !grouped.has(u.id))
    .forEach((u, i) => rows.push({ type: "unit", u, g: null, key: u.end_day, sub: 0, seq: 9000 + i }));

  rows.sort((a, b) => (a.key > b.key ? -1 : a.key < b.key ? 1 : a.seq - b.seq));

  // 长跨度下分组可能上百个，整页拉成几千像素反而没法看；默认只留最近的一段
  const LIMIT = 60;
  const showAll = new URLSearchParams(location.search).get("all") === "1";
  state.truncated = 0;
  if (!showAll && rows.length > LIMIT) {
    state.truncated = rows.length - LIMIT;
    return rows.slice(0, LIMIT);
  }
  return rows;
}

/* 把「中间只隔着折叠周末」的相邻段并成一条，避免窄列把泳道切断 */
function bridgeQuietSegs(segs, quietSet) {
  if (!segs.length) return segs;
  const nextDay = (d) => {
    const t = new Date(d + "T00:00:00Z");
    t.setUTCDate(t.getUTCDate() + 1);
    return t.toISOString().slice(0, 10);
  };
  const out = [[...segs[0]]];
  for (let i = 1; i < segs.length; i++) {
    const prev = out[out.length - 1];
    const cur = segs[i];
    let d = nextDay(prev[1]);
    let onlyQuiet = true;
    while (d < cur[0]) {
      if (!quietSet.has(d)) { onlyQuiet = false; break; }
      d = nextDay(d);
    }
    if (onlyQuiet) out[out.length - 1] = [prev[0], cur[1]];
    else out.push([...cur]);
  }
  return out;
}


/* ---------------- 悬停概览浮层 ---------------- */
const TIP_PAD = 14;
let tipOn = false;

function kindBadge(kind) {
  const m = KIND[kind] || { label: kind, color: "#888" };
  const style = kind === "design"
    ? `border:1px dashed ${m.color};color:${m.color}`
    : `background:${m.color}22;color:${m.color}`;
  return `<span class="tag" style="${style}">${m.label}</span>`;
}

function tipHtml(el) {
  const p = state.payload;
  if (!p) return "";
  const id = el.dataset.id;
  const isGroup = el.dataset.kind === "group";

  if (isGroup) {
    const g = p.groups.find((x) => x.id === id);
    if (!g) return "";
    const members = (g.units || [])
      .slice(0, 4)
      .map((u) => `<li>${esc(clip(u.title, 26))}<span>${fmt(u.start_day)}</span></li>`)
      .join("");
    return `<div class="tip-head">${kindBadge(g.kind)}<b>${esc(g.title)}</b></div>
      <div class="tip-meta">${fmt(g.start_day)} – ${fmt(g.end_day)} · ${g.unit_count} 项 · 文件 ${g.file_count} · +${nf(g.additions)} / −${nf(g.deletions)}</div>
      ${members ? `<ul class="tip-list">${members}</ul>` : ""}
      <div class="tip-hint">点击展开 / 收起这一组</div>`;
  }

  const u = p.units.find((x) => x.id === id);
  if (!u) return "";
  const head = (u.detail && u.detail.headline) || u.summary || autoSummary(u);
  const grp = groupOf(p, u.id);
  const projTag = p.project.id === "all" && u.project ? `${esc(u.project)} · ` : "";
  return `<div class="tip-head">${kindBadge(u.kind)}<b>${esc(u.title)}</b></div>
    <div class="tip-meta">${projTag}${fmt(u.start_day)} – ${fmt(u.end_day)} · 活跃 ${u.active.length} 天 · 文件 ${u.file_count} · +${nf(u.additions)} / −${nf(u.deletions)}</div>
    <div class="tip-body">${esc(head)}</div>
    ${grp && grp.title !== u.title ? `<div class="tip-grp">分组 · ${esc(grp.title)}</div>` : ""}
    <div class="tip-hint">点击跳到详情卡片</div>`;
}

const tipSize = { w: 340, h: 160 };
let tipRect = null;
let tipTimer = 0;
let tipRaf = 0;
let tipLastEv = null;

function showTip(el, ev) {
  const html = tipHtml(el);
  if (html) showTipHtml(html, ev);
}

function showTipHtml(html, ev) {
  const fo = document.getElementById("tipFo");
  const inner = document.getElementById("tipInner");
  if (!fo || !inner) return;

  inner.innerHTML = html;
  // 内容变了才量一次，量完缓存，mousemove 不再读布局
  tipSize.w = Math.ceil(inner.offsetWidth) || 340;
  tipSize.h = Math.ceil(inner.offsetHeight) || 160;
  const svg = document.querySelector(".gantt svg");
  tipRect = svg ? svg.getBoundingClientRect() : null;
  fo.setAttribute("opacity", "1");
  placeTip(ev);
  tipOn = true;
}

function placeTip(ev) {
  const inner = document.getElementById("tipInner");
  const svg = document.querySelector(".gantt svg");
  if (!inner || !svg) return;
  const r = tipRect || svg.getBoundingClientRect();
  const svgW = svg.width.baseVal.value;
  const svgH = svg.height.baseVal.value;

  let x = ev.clientX - r.left + 18;
  let y = ev.clientY - r.top + 20;
  if (x + tipSize.w > svgW - 6) x = ev.clientX - r.left - tipSize.w - 18;
  if (y + tipSize.h > svgH - 6) y = ev.clientY - r.top - tipSize.h - 16;

  // transform 不改变布局盒，不会撑大 ganttwrap 的 scrollWidth（用 x/y 属性会）
  inner.style.transform = `translate3d(${Math.max(4, x)}px, ${Math.max(4, y)}px, 0)`;
}

function hideTip() {
  const fo = document.getElementById("tipFo");
  if (fo) fo.setAttribute("opacity", "0");
  tipOn = false;
}

function scheduleTip(ev) {
  tipLastEv = ev;
  if (tipRaf) return;
  tipRaf = requestAnimationFrame(() => {
    tipRaf = 0;
    if (tipOn && tipLastEv) placeTip(tipLastEv);
  });
}

function bindTip(box) {
  box.querySelectorAll("g.row").forEach((g) => {
    // 悬停 70ms 才弹：鼠标快速扫过时不触发测量，避免长跨度视图下频繁重排
    g.addEventListener("mouseenter", (e) => {
      clearTimeout(tipTimer);
      tipTimer = setTimeout(() => showTip(g, e), 70);
    });
    g.addEventListener("mousemove", (e) => {
      if (tipOn) scheduleTip(e);
    });
    g.addEventListener("mouseleave", () => {
      clearTimeout(tipTimer);
      hideTip();
    });
  });
}

function dayAchHtml(day) {
  const p = state.payload;
  if (!p) return "";
  const list = (p.achievements || {})[day] || [];
  const d = (p.daily || {})[day] || {};
  const stat = d.n
    ? `改动 ${d.n} 处 · ${fmtH(d.first)}–${fmtH(d.last)}（${d.span.toFixed(1)}h）· ${d.projects || 0} 个项目`
    : "这天没有文件改动记录";
  const rows = list
    .map((b) => `<li><span class="ic">${b.icon}</span><b>${esc(b.label)}</b><i>${esc(b.detail)}</i></li>`)
    .join("");
  return `<div class="tip-head"><b>${fmt(day)} 的成就</b></div>
    <div class="tip-meta">${stat}</div>
    ${rows ? `<ul class="ach-list">${rows}</ul>` : `<div class="tip-body">这天还没拿到成就，继续加油</div>`}`;
}

/* ---------------- 甘特（新日期在左，空闲周末折叠） ---------------- */
function renderGantt(p) {
  const box = $("gantt");
  const avail = $("ganttwrap").clientWidth - 4;
  const labelW = 300;
  const quietW = 6;

  const activeDates = new Set();
  p.units.forEach((u) => u.active.forEach((d) => activeDates.add(d)));

  const cols = [...p.days]
    .reverse()
    .map((d) => ({ ...d, quiet: d.weekend && !activeDates.has(d.date) }));

  const activeCount = cols.filter((c) => !c.quiet).length || 1;
  const quietCount = cols.length - activeCount;
  const quietSet = new Set(cols.filter((c) => c.quiet).map((c) => c.date));
  const dayW = Math.max(15, Math.floor((avail - labelW - quietW * quietCount - 6) / activeCount));

  const pos = {};
  let cursor = labelW;
  cols.forEach((c) => {
    const w = c.quiet ? quietW : dayW;
    pos[c.date] = { x: cursor, w };
    cursor += w;
  });
  const svgW = cursor + 6;

  const headerH = 76;          // 日期行 + 成就行
  const achTop = 50;
  const chartH = 74;           // 底部日柱状图
  const rows = buildRows(p);
  const heights = rows.map((r) => (r.type === "group" ? 38 : 28));
  const rowsH = heights.reduce((a, b) => a + b, 0);
  const H = headerH + rowsH + chartH + 12;

  let s = `<svg width="${svgW}" height="${H}" viewBox="0 0 ${svgW} ${H}" xmlns="http://www.w3.org/2000/svg">`;

  cols.forEach((c) => {
    const { x, w } = pos[c.date];
    if (c.quiet) {
      s += `<rect x="${x}" y="0" width="${w}" height="${H}" fill="${COL.quiet}"></rect>`;
      s += `<circle cx="${x + w / 2}" cy="30" r="1.8" fill="#5d5947"/>`;
      return;
    }
    if (c.weekend) s += `<rect x="${x}" y="0" width="${w}" height="${H}" fill="${COL.weekend}"/>`;
    s += `<text x="${x + w / 2}" y="19" text-anchor="middle" font-size="11.5" fill="${COL.head}">${c.weekday}</text>`;
    // 列太窄时不标日期，只在周一起头标一次，避免日期叠在一起
    if (dayW >= 26 || c.is_monday) {
      s += `<text x="${x + w / 2}" y="38" text-anchor="middle" font-size="11" fill="${c.weekend ? "#57543f" : "#6a6653"}">${c.md}</text>`;
    }
    s += `<line x1="${x}" y1="${achTop}" x2="${x}" y2="${H}" stroke="${COL.grid}" stroke-width="0.5"/>`;
  });

  // 周分隔：相邻列跨周处画一条线
  const weekKey = (d) => {
    const t = new Date(d + "T00:00:00Z");
    const off = (t.getUTCDay() + 6) % 7;
    t.setUTCDate(t.getUTCDate() - off);
    return t.toISOString().slice(0, 10);
  };
  cols.forEach((c, i) => {
    if (i === 0 || weekKey(cols[i - 1].date) !== weekKey(c.date)) {
      s += `<line x1="${pos[c.date].x}" y1="${achTop}" x2="${pos[c.date].x}" y2="${H}" stroke="${COL.week}" stroke-width="1"/>`;
    }
  });
  s += `<line x1="${svgW - 2}" y1="${achTop}" x2="${svgW - 2}" y2="${H}" stroke="${COL.week}" stroke-width="1"/>`;

  s += `<line x1="${labelW}" y1="${headerH}" x2="${svgW}" y2="${headerH}" stroke="${COL.base}" stroke-width="0.5"/>`;
  s += `<text x="0" y="30" font-size="11.5" fill="${COL.head}">工作分组</text>`;
  s += `<text x="0" y="${achTop + 17}" font-size="10" fill="#4d4a3c">成就</text>`;
  s += `<text x="${labelW - 60}" y="30" font-size="10" fill="#4d4a3c" text-anchor="end">← 新 · 旧 →</text>`;
  s += `<line x1="${labelW - 52}" y1="0" x2="${labelW - 52}" y2="${H}" stroke="${COL.grid}" stroke-width="0.5"/>`;

  if (!rows.length) {
    s += `<text x="${labelW + 12}" y="${headerH + 26}" font-size="12" fill="${COL.head}">这段时间没有记录</text>`;
  
    return;
  }

  let y = headerH;
  rows.forEach((row) => {
    const h = row.type === "group" ? 38 : 28;
    const mid = y + h / 2;
    const isGroup = row.type === "group";
    const item = isGroup ? row.g : row.u;
    const m = KIND[item.kind] || { label: item.kind, color: "#888" };
    const open = isGroup && state.expanded.has(row.g.id);
    const indent = row.sub ? 8 : 0;
    const labX = isGroup ? 18 : 26;
    const maxPx = isGroup ? labelW - 108 - labX : labelW - 26 - labX;
    const segs = bridgeQuietSegs(isGroup ? row.g.segs : row.u.segs, quietSet);

    s += `<g class="row" data-kind="${isGroup ? "group" : "unit"}" data-id="${item.id}">`;
    s += `<rect class="rowbg" x="0" y="${y}" width="${svgW}" height="${h}"/>`;
    s += `<rect class="rowline" x="0" y="${y}" width="${svgW}" height="1"/>`;
    s += `<rect class="accent" x="0" y="${y + 3}" width="3" height="${h - 6}" rx="1.5" fill="${m.color}" opacity="0"/>`;

    if (isGroup) {
      s += open
        ? `<polygon class="caret open" points="6,${mid - 6} 16,${mid - 6} 11,${mid + 1}"/>`
        : `<polygon class="caret" points="8,${mid - 5} 8,${mid + 5} 14,${mid}"/>`;
    }

    s += `<text class="rowlab ${isGroup ? "grouplab" : ""}" x="${labX}" y="${mid + 4}">${esc(clipPx(item.title, maxPx))}</text>`;

    if (isGroup) {
      const cnt =
        row.g.unit_count === row.g.unit_count_total
          ? `${row.g.unit_count} 项`
          : `${row.g.unit_count}/${row.g.unit_count_total} 项`;
      const meta =
        state.project === "all"
          ? `${clip(row.g.project || "", 8)} · ${cnt}`
          : `${cnt} · ${row.g.file_count} 文件`;
      s += `<text class="rowmeta" x="${labelW - 32}" y="${mid + 4}" text-anchor="end">${esc(meta)}</text>`;
    }
    s += `<rect class="kinddot" x="${labelW - 22}" y="${mid - 3.5}" width="7" height="7" rx="1.5" fill="${item.design ? "none" : m.color}" stroke="${m.color}" stroke-width="${item.design ? 1 : 0}" ${item.design ? 'stroke-dasharray="2 1.5"' : ""}/>`;

    segs.forEach(([a, b]) => {
      const pa = pos[a], pb = pos[b];
      if (!pa || !pb) return;
      const left = Math.min(pa.x, pb.x);
      const right = Math.max(pa.x + pa.w, pb.x + pb.w);
      const x = left + 3;
      const w = Math.max(5, right - left - 6);
      const bh = isGroup ? 16 : 11;
      const tip = isGroup
        ? `${item.title}｜${row.g.unit_count} 项｜${row.g.start_day} ~ ${row.g.end_day}｜${m.label}｜文件 ${row.g.file_count}`
        : `${item.title}｜${item.start_day} ~ ${item.end_day}｜活跃 ${item.active.length} 天｜${m.label}｜文件 ${item.file_count}`;
      const heatVal = isGroup
        ? Math.round(item.file_count / Math.max(item.unit_count || 1, 1))
        : item.file_count;
      const barFill = state.mode === "heat" ? heatColor(heatVal) : m.color;
      if (item.design) {
        const stroke = state.mode === "heat" ? "#8f8a76" : m.color;
        s += `<rect class="bar-rect ${isGroup ? "" : "child"}" x="${x}" y="${mid - bh / 2}" width="${w}" height="${bh}" rx="3" fill="none" stroke="${stroke}" stroke-width="1" stroke-dasharray="3 2"></rect>`;
      } else {
        const edge = state.mode === "heat" ? ' stroke="rgba(255,255,255,0.14)" stroke-width="0.8"' : "";
        s += `<rect class="bar-rect ${isGroup ? "" : "child"}" x="${x}" y="${mid - bh / 2}" width="${w}" height="${bh}" rx="3" fill="${barFill}"${edge}></rect>`;
      }
    });

    s += `</g>`;
    y += h;
  });

  s += `<foreignObject id="tipFo" x="0" y="0" width="${svgW}" height="${H}" opacity="0" style="pointer-events:none">
    <div xmlns="http://www.w3.org/1999/xhtml" class="tipwrap">
      <div class="tipbox" id="tipInner"></div>
    </div>
  </foreignObject>`;
  // ---- 成就行（表头下方）：emoji + 整列热区 ----
  cols.forEach((d) => {
    const { x, w } = pos[d.date];
    const list = (p.achievements || {})[d.date] || [];
    if (list.length && w >= 12) {
      const show = list.slice(0, Math.max(1, Math.floor((w - 4) / 13)));
      const totalW = show.length * 13;
      const bx = x + Math.max(1, (w - totalW) / 2);
      show.forEach((b, i) => {
        s += `<text x="${bx + i * 13 + 6}" y="${achTop + 21}" font-size="11.5" text-anchor="middle"
          font-family="'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif">${b.icon}</text>`;
      });
    }
    // 整列热区：不用对准图标
    s += `<rect class="ach-hit" x="${x}" y="${achTop + 2}" width="${Math.max(w - 1, 5)}" height="24" fill="transparent" data-day="${d.date}"/>`;
  });
  s += `<line x1="0" y1="${achTop}" x2="${svgW}" y2="${achTop}" stroke="${COL.grid}" stroke-width="0.5"/>`;

  // ---- 底部日柱状图：高度 = 当日改动数 ----
  const chartTop = headerH + rowsH + 8;
  const chartBase = chartTop + 60;
  const dailyMap = p.daily || {};
  const maxDay = Math.max(1, ...Object.values(dailyMap).map((v) => v.n));
  s += `<line x1="${labelW}" y1="${chartBase}" x2="${svgW}" y2="${chartBase}" stroke="${COL.base}" stroke-width="0.5"/>`;
  s += `<text x="0" y="${chartTop + 14}" font-size="10.5" fill="${COL.head}">每日改动</text>`;
  s += `<text x="0" y="${chartTop + 28}" font-size="10" fill="#565442">峰值 ${maxDay}</text>`;
  cols.forEach((d) => {
    const v = dailyMap[d.date];
    const { x, w } = pos[d.date];
    if (!v) return;
    const bw = Math.max(3, Math.min(w - 6, 26));
    const h = Math.max(3, (v.n / maxDay) * 58);
    const bx = x + (w - bw) / 2;
    const tip = `${d.md}｜改动 ${v.n} 处｜${fmtH(v.first)}–${fmtH(v.last)}（${v.span.toFixed(1)}h）`;
    s += `<rect class="daybar" x="${bx}" y="${chartBase - h}" width="${bw}" height="${h}" rx="2" fill="#5DCAA5" opacity="0.72"><title>${esc(tip)}</title></rect>`;
  });

  box.innerHTML = s + "</svg>";

  box.querySelectorAll("g.row").forEach((g) => {
    g.addEventListener("click", () => {
      if (state.suppressClick) return;
      if (g.dataset.kind === "group") {
        const id = g.dataset.id;
        state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
        renderGantt(state.payload);
      } else {
        openCard(g.dataset.id);
      }
    });
  });

  bindTip(box);

  // 无鼠标环境下验收悬停效果：?demo=hover 点亮行，?demo=tip 弹出浮层
  const demo = new URLSearchParams(location.search).get("demo");
  box.querySelectorAll(".ach-hit").forEach((el) => {
    el.addEventListener("mouseenter", (e) => showTipHtml(dayAchHtml(el.dataset.day), e));
    el.addEventListener("mousemove", (e) => {
      if (tipOn) scheduleTip(e);
    });
    el.addEventListener("mouseleave", hideTip);
  });

  if (demo === "hover" || demo === "tip" || demo === "ach") {
    const rows = box.querySelectorAll("g.row");
    if (rows[1]) rows[1].classList.add("is-hover");
    if (demo === "hover" && rows[3]) rows[3].classList.add("is-hover");
    if (demo === "ach") {
      const hits = [...box.querySelectorAll(".ach-hit")].filter((el) => ((p.achievements || {})[el.dataset.day] || []).length);
      const el = hits[0];
      if (el) {
        const r = el.getBoundingClientRect();
        showTipHtml(dayAchHtml(el.dataset.day), { clientX: r.left + r.width / 2, clientY: r.bottom });
      }
    }
    if (demo === "tip" && rows[1]) {
      const bar = rows[1].querySelector("rect.bar-rect");
      const r = bar ? bar.getBoundingClientRect() : null;
      showTip(rows[1], { clientX: r ? r.left + r.width / 2 : 420, clientY: r ? r.top : 260 });
    }
  }
}

/* ---------------- 密度日历 ---------------- */
function renderHeatmap(p) {
  const box = $("heatmap");
  const cells = p.heatmap || [];
  if (!cells.length) { box.innerHTML = ""; return; }

  const cell = 13, gap = 3, pitch = cell + gap;
  const leftPad = 26, topPad = 16;
  const weeks = Math.ceil(cells.length / 7);
  const W = leftPad + weeks * pitch;
  const H = topPad + 7 * pitch;

  const shade = (n) => (n === 0 ? "#232319" : n <= 3 ? "#1a4d3f" : n <= 9 ? "#1d9e75" : n <= 24 ? "#5dcaa5" : "#9fe1cb");
  const WK = ["一", "二", "三", "四", "五", "六", "日"];

  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  [0, 2, 4].forEach((r) => {
    s += `<text x="0" y="${topPad + r * pitch + cell - 2}" font-size="10" fill="${COL.head}">${WK[r]}</text>`;
  });

  let lastMonth = "";
  let lastLabelCol = -99;
  cells.forEach((c, i) => {
    const wk = Math.floor(i / 7);
    const row = i % 7;
    const x = leftPad + wk * pitch;
    const yy = topPad + row * pitch;
    s += `<rect class="hm-cell" x="${x}" y="${yy}" width="${cell}" height="${cell}" rx="2" fill="${shade(c.n)}" stroke="#3d3929" stroke-width="0.9"><title>${c.date}｜${c.n} 次文件变更</title></rect>`;
    if (row === 0) {
      const mo = c.date.slice(5, 7);
      if (mo !== lastMonth && wk - lastLabelCol >= 2) {
        s += `<text x="${x}" y="11" font-size="10" fill="${COL.head}">${Number(mo)}月</text>`;
        lastMonth = mo;
        lastLabelCol = wk;
      } else if (mo !== lastMonth) {
        lastMonth = mo;
      }
    }
  });
  box.innerHTML = s + "</svg>";
}

/* ---------------- 工作时段分布 ---------------- */
function renderHours(p) {
  const box = $("hours");
  const data = p.hours || [];
  if (!data.some((v) => v > 0)) {
    box.innerHTML = '<div class="empty">这段时间没有记录</div>';
    return;
  }
  const max = Math.max(1, ...data);
  const bw = 9, pitch = 11, H0 = 66, topPad = 15;
  const W = 24 * pitch;
  const H = topPad + H0 + 16;

  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  s += `<line x1="0" y1="${topPad + H0}" x2="${W}" y2="${topPad + H0}" stroke="${COL.base}" stroke-width="0.5"/>`;
  s += `<text x="0" y="${topPad - 4}" font-size="10" fill="${COL.head}">峰值 ${max} 次/小时</text>`;

  data.forEach((v, hh) => {
    const x = hh * pitch;
    const h = v ? Math.max(2, (v / max) * H0) : 0;
    const alpha = 0.28 + 0.72 * (v / max);
    if (v) {
      s += `<rect class="hourbar" x="${x}" y="${topPad + H0 - h}" width="${bw}" height="${h}" rx="1.5" fill="#5DCAA5" opacity="${alpha.toFixed(2)}"><title>${String(hh).padStart(2, "0")}:00–${String(hh).padStart(2, "0")}:59｜${v} 次改动</title></rect>`;
    } else {
      s += `<rect x="${x}" y="${topPad + H0 - 1}" width="${bw}" height="1" fill="#2a2a21"/>`;
    }
    if (hh % 6 === 0) {
      s += `<text x="${x + bw / 2}" y="${H - 4}" text-anchor="middle" font-size="10" fill="${COL.head}">${hh}</text>`;
    }
  });
  box.innerHTML = s + "</svg>";

  const peak = data.indexOf(max);
  const span = data.slice(9, 19).reduce((a, b) => a + b, 0);
  const total = data.reduce((a, b) => a + b, 0);
  const cap = $("hoursCap");
  if (cap) {
    cap.textContent = `最高峰 ${String(peak).padStart(2, "0")}:00 · 9–19 点占 ${total ? Math.round((span / total) * 100) : 0}%`;
  }
}

/* ---------------- 周 × 类型堆叠 ---------------- */
function renderWeekly(p) {
  const box = $("weekly");
  const weeks = p.weekly || [];
  if (!weeks.length) { box.innerHTML = ""; return; }

  const order = ["design", "research", "doc", "data", "code", "ops"];
  const totals = weeks.map((w) => order.reduce((a, k) => a + (w.kinds[k] || 0), 0));
  const max = Math.max(1, ...totals);
  const barW = 22, pitchX = 34, leftPad = 4, topPad = 12;
  const H0 = 96;
  const W = leftPad + weeks.length * pitchX;
  const H = topPad + H0 + 18;

  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  s += `<line x1="0" y1="${topPad + H0}" x2="${W}" y2="${topPad + H0}" stroke="${COL.base}" stroke-width="0.5"/>`;
  s += `<text x="0" y="${topPad - 3}" font-size="10" fill="${COL.head}">${max} 个/周</text>`;

  weeks.forEach((w, i) => {
    const x = leftPad + i * pitchX;
    let acc = 0;
    s += `<g class="wk">`;
    s += `<rect class="wkbg" x="${x - 4}" y="${topPad - 2}" width="${pitchX}" height="${H0 + 6}" rx="4" fill="#ffffff" opacity="0"/>`;
    order.forEach((k) => {
      const v = w.kinds[k] || 0;
      if (!v) return;
      const hh = (v / max) * H0;
      const yy = topPad + H0 - acc - hh;
      s += `<rect class="wbar" x="${x}" y="${yy}" width="${barW}" height="${hh}" fill="${(KIND[k] || {}).color || "#888"}"><title>${w.week} 起当周｜${(KIND[k] || { label: k }).label} ${v} 项</title></rect>`;
      acc += hh;
    });
    if (!acc) s += `<rect x="${x}" y="${topPad + H0 - 2}" width="${barW}" height="2" fill="#2a2a21"/>`;
    s += `<text x="${x + barW / 2}" y="${H - 5}" text-anchor="middle" font-size="10" fill="${COL.head}">${w.md}</text>`;
    s += `</g>`;
  });
  box.innerHTML = s + "</svg>";
}

/* ---------------- 卡片 ---------------- */
function groupOf(p, id) {
  return p.groups.find((x) => x.units.some((u) => u.id === id));
}

function autoSummary(u) {
  if (u.design) return "只有讨论，没有落文件。";
  const top = (u.dirs || [])[0];
  const span = u.active.length;
  const parts = [`改了 ${u.file_count} 个文件，跨 ${span} 天`];
  if (top) parts.push(`最集中在 ${top.dir === "." ? "项目根目录" : top.dir}（${top.files} 个文件）`);
  parts.push(`+${nf(u.additions)} / −${nf(u.deletions)} 行`);
  return parts.join("，") + "。";
}

function cardHtml(p, u) {
  const m = KIND[u.kind] || { label: u.kind, color: "#888" };
  const g = groupOf(p, u.id);
  const span = u.start_day === u.end_day ? fmt(u.start_day) : `${fmt(u.start_day)} – ${fmt(u.end_day)}`;
  const tagStyle = u.design ? `border:1px dashed ${m.color};color:${m.color}` : `background:${m.color}22;color:${m.color}`;
  const open = state.open.has(u.id);
  const det = u.detail || null;

  const dirs = (u.dirs || [])
    .map(
      (d) =>
        `<span class="dchip">${esc(d.dir === "." ? "根目录" : d.dir)}<b>${d.files}</b><i>+${nf(d.add)}</i></span>`
    )
    .join("");

  const files = (u.files || [])
    .map(
      (f) =>
        `<tr><td class="fname">${esc(f.name)}</td><td class="fdir">${esc(f.path === "." ? "" : f.path)}</td><td class="fnum"><span class="add">+${nf(f.add)}</span> <span class="del">−${nf(f.del)}</span></td></tr>`
    )
    .join("");

  const sections =
    det && (det.sections || []).length
      ? det.sections
          .map(
            (sec) =>
              `<div class="sec"><div class="sech">${esc(sec.title)}</div><ul class="pts">${(sec.items || [])
                .map((i) => `<li>${esc(i)}</li>`)
                .join("")}</ul></div>`
          )
          .join("")
      : "";

  const head = det && det.headline
    ? esc(det.headline)
    : esc(u.summary || autoSummary(u)) + (u.summary ? "" : '<span class="auto">（自动生成）</span>');

  return `<article class="card ${open ? "open" : ""}" id="card-${u.id}">
    <header class="card-head">
      <span class="kbar" style="background:${m.color}"></span>
      <div class="chead-main">
        <div class="ctitle">${esc(u.title)}</div>
        <div class="cmeta">${span} · 活跃 ${u.active.length} 天 · 最长连续 ${u.max_streak} 天 · 文件 ${u.file_count} · +${nf(u.additions)} / −${nf(u.deletions)}</div>
      </div>
      <div class="chead-side">
        ${state.project === "all" && u.project ? `<span class="gtag pt">${esc(u.project)}</span>` : ""}
        ${g ? `<span class="gtag">${esc(clip(g.title, 14))}</span>` : ""}
        <span class="tag" style="${tagStyle}">${m.label}</span>
        <span class="chev">›</span>
      </div>
    </header>
    <div class="card-body">
      <p class="csum">${head}</p>
      ${sections}
      ${dirs ? `<div class="sec"><div class="sech">涉及目录</div><div class="dirs">${dirs}</div></div>` : ""}
      ${files ? `<div class="sec"><div class="sech">主要改动文件</div><table class="files"><tbody>${files}</tbody></table></div>` : ""}
      <div class="sec"><div class="sech">活跃日</div><div class="days">${u.active.map((d) => `<span>${fmt(d)}</span>`).join("")}</div></div>
    </div>
  </article>`;
}

function renderCards(p) {
  const wrap = $("list");
  if (!p.units.length) {
    wrap.innerHTML = '<div class="empty">这段时间没有记录</div>';
    return;
  }
  const ordered = [...p.units].sort((a, b) => (a.start_day > b.start_day ? -1 : 1));
  wrap.innerHTML = ordered.map((u) => cardHtml(p, u)).join("");

  const op = new URLSearchParams(location.search).get("open");
  if (op !== null) {
    const n = Number(op);
    if (!Number.isNaN(n) && ordered[n]) {
      setTimeout(() => openCard(ordered[n].id), 80);
    }
  }

  wrap.querySelectorAll(".card-head").forEach((head) => {
    head.addEventListener("click", () => {
      const card = head.parentElement;
      card.classList.toggle("open");
      const id = card.id.replace("card-", "");
      card.classList.contains("open") ? state.open.add(id) : state.open.delete(id);
      updateBackBtn();
    });
  });
}

function updateBackBtn() {
  const anyOpen = !!document.querySelector(".card.open");
  const r = $("ganttwrap").getBoundingClientRect();
  const mid = (r.top + r.bottom) / 2;
  const ganttVisible = mid > 0 && mid < window.innerHeight;
  $("backToGantt").hidden = !(anyOpen && !ganttVisible);
}

function openCard(id) {
  const card = document.getElementById("card-" + id);
  if (!card) return;
  if (!card.classList.contains("open")) {
    card.classList.add("open");
    state.open.add(id);
  }
  card.scrollIntoView({ behavior: "auto", block: "center" });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 1400);
  updateBackBtn();
}

$("backToGantt").addEventListener("click", () => {
  $("ganttwrap").scrollIntoView({ behavior: "auto", block: "center" });
  $("backToGantt").hidden = true;
});

window.addEventListener("scroll", updateBackBtn, { passive: true });

/* ---------------- 主流程 ---------------- */
function render(p) {
  state.payload = p;
  if (p.error) { $("hlMain").textContent = p.error; return; }
  if (new URLSearchParams(location.search).get("expand") === "1") {
    p.groups.forEach((g) => state.expanded.add(g.id));
  }
  const md = new URLSearchParams(location.search).get("mode");
  if (md === "heat" || md === "bars") {
    state.mode = md;
    document.querySelectorAll("#modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === md));
  }
  document.title = `worklog · ${p.project.name}`;
  renderHeadline(p);
  renderLegend(p);
  renderGantt(p);
  renderHeatmap(p);
  renderHours(p);
  renderWeekly(p);
  renderCards(p);
  const cut = state.truncated
    ? `　·　仅显示最近 ${60} 组，另有 ${state.truncated} 组未显示（URL 加 ?all=1 看全部）`
    : "";
  $("foot").textContent =
    `${p.project.name} · 数据源：workbuddy / claude-code 等 harness 的本地记录（只读）` +
    ` · 分组与摘要由 LLM 通过 MCP 写入${cut}`;
}

async function loadHarnesses() {
  try {
    const res = await fetch("/api/harnesses");
    const data = await res.json();
    const sel = $("harnSel");
    const total = data.harnesses.reduce((a, h) => a + h.units, 0);
    sel.innerHTML =
      `<option value="">全部来源（${total}）</option>` +
      data.harnesses
        .map((h) => `<option value="${esc(h.harness)}">${esc(h.harness)}（${h.units}）</option>`)
        .join("");
    sel.value = state.harness || "";
  } catch (e) {
    /* 忽略 */
  }
}

async function loadProjects() {
  try {
    const res = await fetch("/api/projects");
    const data = await res.json();
    const sel = $("projSel");
    sel.innerHTML = data.projects
      .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}（${p.units}）</option>`)
      .join("");
    if ([...sel.options].some((o) => o.value === state.project)) sel.value = state.project;
    else if (sel.options.length) state.project = sel.value;
  } catch (e) {
    /* 忽略，主视图还能用 */
  }
}

async function load() {
  try {
    const res = await fetch(`/api/project?project=${encodeURIComponent(state.project)}&days=${state.days}`);
    render(await res.json());
  } catch (e) {
    $("hlMain").textContent = "读取失败：" + e.message;
  }
}

$("harnSel").addEventListener("change", (e) => {
  state.harness = e.target.value;
  state.expanded.clear();
  state.open.clear();
  load();
});

$("projSel").addEventListener("change", (e) => {
  state.project = e.target.value;
  state.expanded.clear();
  state.open.clear();
  load();
});

$("modes").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn || btn.dataset.mode === state.mode) return;
  state.mode = btn.dataset.mode;
  document.querySelectorAll("#modes button").forEach((b) => b.classList.toggle("on", b === btn));
  if (state.payload) {
    renderLegend(state.payload);
    renderGantt(state.payload);
  }
});

$("ranges").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.days = Number(btn.dataset.days);
  document.querySelectorAll("#ranges button").forEach((b) => b.classList.toggle("on", b === btn));
  load();
});

/* 拖动平移 */
(function enablePan() {
  const wrap = $("ganttwrap");
  let down = false, startX = 0, startLeft = 0, moved = 0;

  wrap.addEventListener("mousedown", (e) => {
    down = true; moved = 0;
    startX = e.pageX;
    startLeft = wrap.scrollLeft;
  });

  window.addEventListener("mousemove", (e) => {
    if (!down) return;
    const dx = e.pageX - startX;
    moved = Math.max(moved, Math.abs(dx));
    if (moved > 4) {
      wrap.classList.add("dragging");
      wrap.scrollLeft = startLeft - dx;
    }
  });

  window.addEventListener("mouseup", () => {
    if (!down) return;
    down = false;
    wrap.classList.remove("dragging");
    state.suppressClick = moved > 4;
    setTimeout(() => (state.suppressClick = false), 0);
  });
})();

let rt;
window.addEventListener("resize", () => {
  clearTimeout(rt);
  rt = setTimeout(() => state.payload && renderGantt(state.payload), 150);
});

const pq = new URLSearchParams(location.search).get("project");
if (pq) state.project = pq;

const dq = Number(new URLSearchParams(location.search).get("days"));
if (dq) {
  state.days = dq;
  document.querySelectorAll("#ranges button").forEach((b) => b.classList.toggle("on", Number(b.dataset.days) === dq));
}

Promise.all([loadHarnesses(), loadProjects()]).then(load);
