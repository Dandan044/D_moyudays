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
  grid: "var(--line)",
  week: "var(--line2)",
  head: "var(--ink3)",
  base: "var(--line2)"
};

const query = new URLSearchParams(location.search);
const state = {
  project: "all", harness: "", days: 7, payload: null, expanded: new Set(), open: new Set(),
  suppressClick: false, mode: query.get("mode") === "bars" ? "bars" : "heat",
  order: query.get("order") === "recent" ? "recent" : "project"
};

const HEAT_COLORS = [[255, 255, 255], [240, 65, 74], [144, 58, 213]];
// 主题均值可能小于一份文件，色阶从 0.25 份的量级开始展开。
const HEAT_REFERENCE = 0.25;

function heatMaximum(units) {
  return units.reduce((max, u) => Object.values(u.hour_files).reduce((v, n) => Math.max(v, n), max), 1);
}

function heatPosition(value, max) {
  return Math.log1p(Math.min(max, Math.max(0, value)) / HEAT_REFERENCE) / Math.log1p(max / HEAT_REFERENCE);
}

function heatColor(value, max) {
  const position = heatPosition(value, max) * 2;
  const segment = Math.min(1, Math.floor(position));
  const fraction = position - segment;
  const color = HEAT_COLORS[segment].map((start, i) =>
    Math.round(start + fraction * (HEAT_COLORS[segment + 1][i] - start)));
  return `rgb(${color.join(",")})`;
}

function workload(item) {
  return item.unit_count ? item.file_count / item.unit_count : item.file_count;
}

const $ = (id) => document.getElementById(id);
const themeSelector = $("themeSel");
const themeKey = "worklog.theme";
function setTheme(theme) {
  if (![...themeSelector.options].some(option => option.value === theme)) return false;
  document.documentElement.dataset.theme = theme;
  themeSelector.value = theme;
  return true;
}
let savedTheme;
try { savedTheme = localStorage.getItem(themeKey); } catch { /* 本地文件可禁用存储 */ }
if (!setTheme(query.get("theme"))) setTheme(savedTheme || "midnight");
themeSelector.addEventListener("change", () => {
  setTheme(themeSelector.value);
  try { localStorage.setItem(themeKey, themeSelector.value); } catch { /* 本次浏览仍可切换 */ }
  if (query.has("theme")) {
    const url = new URL(location.href);
    url.searchParams.set("theme", themeSelector.value);
    try { history.replaceState(null, "", url); } catch { /* file:// 下由浏览器决定 */ }
  }
});
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
    const max = heatMaximum(p.units);
    const tickValues = [0, 0.25, 0.5, 0.75, 1].map(position => {
      const raw = HEAT_REFERENCE * Math.expm1(position * Math.log1p(max / HEAT_REFERENCE));
      return Number(raw.toFixed(raw < 10 ? 1 : 0));
    });
    const ticks = tickValues.map(value =>
      `<span style="left:${heatPosition(value, max) * 100}%">${nf(value)}</span>`);
    const colors = HEAT_COLORS.map(rgb => `rgb(${rgb.join(",")})`).join(", ");
    $("legend").innerHTML = `<span class="scale-label">每小时变更文件数 · 指数刻度</span>
      <div class="heat-scale" aria-label="文件数按指数递增，0 到 ${max} 个文件">
        <div class="scale-ramp" style="background:linear-gradient(to right in srgb, ${colors})"></div>
        <div class="scale-axis">${ticks.join("")}</div>
      </div><span class="scale-note">主题取同小时组内均值</span>
      <span class="k">白色 · 该小时无产出</span>
      ${p.units.some(u => u.date_only.length) ? '<span class="k">斜线 · 仅知日期</span>' : ""}`;
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
function topicSections(p) {
  const topics = [...p.groups];
  const pending = new Map();
  for (const u of p.units) {
    if (u.group_id) continue;
    if (!pending.has(u.project_id)) {
      pending.set(u.project_id, { id: u.id, title: "待归组", project_id: u.project_id,
        project: u.project, updated_ms: u.updated_ms, pending: true, units: [] });
    }
    pending.get(u.project_id).units.push(u);
  }
  topics.push(...pending.values());
  topics.sort((a, b) => b.updated_ms - a.updated_ms || a.id.localeCompare(b.id));
  if (state.order === "recent") return [{ topics }];

  const projects = new Map();
  for (const topic of topics) {
    if (!projects.has(topic.project_id)) {
      projects.set(topic.project_id, { name: topic.project, topics: [] });
    }
    projects.get(topic.project_id).topics.push(topic);
  }
  return [...projects.values()];
}

function topicName(g) {
  return state.order === "recent" ? `${g.title} · ${g.project}` : g.title;
}

function buildRows(p) {
  const rows = [];
  for (const section of topicSections(p)) {
    if (section.name && p.project.id === "all") rows.push({type: "heading", label: section.name});
    for (const g of section.topics) {
      rows.push(g.pending ? {type: "heading", label: topicName(g)} : {type: "group", g});
      if (g.pending || state.expanded.has(g.id)) {
        for (const u of g.units) rows.push({type: "unit", u});
      }
    }
  }
  return rows;
}

let tipOn = false;
let tipTimer;
let tipTarget = null;

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
  const isGroup = (el.dataset.kind || el.dataset.lane) === "group";

  if (isGroup) {
    const g = p.groups.find((x) => x.id === id);
    if (!g) return "";
    const members = (g.units || [])
      .slice(0, 4)
      .map((u) => `<li>${esc(clip(u.title, 26))}<span>${fmt(u.end_day)}</span></li>`)
      .join("");
    return `<div class="tip-head">${kindBadge(g.kind)}<b>${esc(topicName(g))}</b></div>
      <div class="tip-meta">${fmt(g.start_day)} – ${fmt(g.end_day)} · ${g.unit_count} 项 · 组均 ${Number(workload(g).toFixed(1))} 个文件 · +${nf(g.additions)} / −${nf(g.deletions)}</div>
      ${members ? `<ul class="tip-list">${members}</ul>` : ""}
      <div class="tip-hint">点击展开 / 收起这一组</div>`;
  }

  const u = p.units.find((x) => x.id === id);
  if (!u) return "";
  const head = (u.detail && u.detail.headline) || u.summary || "待整理：需要回查本段会话，补充任务经过和结果。";
  const grp = groupOf(p, u.id);
  const projTag = p.project.id === "all" && u.project ? `${esc(u.project)} · ` : "";
  return `<div class="tip-head">${kindBadge(u.kind)}<b>${esc(u.title)}</b></div>
    <div class="tip-meta">${projTag}${fmt(u.start_day)} – ${fmt(u.end_day)} · 活跃 ${u.active.length} 天 · 文件 ${u.file_count} · +${nf(u.additions)} / −${nf(u.deletions)}</div>
    <div class="tip-body">${esc(head)}</div>
    ${grp && grp.title !== u.title ? `<div class="tip-grp">分组 · ${esc(grp.title)}</div>` : ""}
    <div class="tip-hint">点击跳到详情卡片</div>`;
}

function showTip(el, ev) {
  const html = tipHtml(el);
  if (html) showTipHtml(html, ev);
}

function showTipHtml(html, ev) {
  const inner = $("tipInner");
  inner.innerHTML = html;
  inner.hidden = false;
  tipOn = true;
  placeTip(ev);
}

function placeTip(ev) {
  const inner = $("tipInner");
  const x = ev.clientX + 18 + inner.offsetWidth <= window.innerWidth
    ? ev.clientX + 18 : ev.clientX - inner.offsetWidth - 12;
  const y = ev.clientY + 16 + inner.offsetHeight <= window.innerHeight
    ? ev.clientY + 16 : ev.clientY - inner.offsetHeight - 12;
  inner.style.left = Math.max(4, x) + "px";
  inner.style.top = Math.max(4, y) + "px";
}

function hideTip() {
  clearTimeout(tipTimer);
  tipTarget = null;
  tipOn = false;
  $("tipInner").hidden = true;
}

function bindGantt(box) {
  const highlightPair = (e, on) => {
    const row = e.target.closest(".row");
    if (!row || row.contains(e.relatedTarget)) return;
    const other = row.dataset.lane ? $("taskRail") : $("gantt");
    other.querySelector(`.row[data-id="${CSS.escape(row.dataset.id)}"]`)?.classList.toggle("is-hover", on);
  };
  box.addEventListener("mouseover", e => highlightPair(e, true));
  box.addEventListener("mouseout", e => highlightPair(e, false));
  box.addEventListener("click", e => {
    const row = e.target.closest(".row");
    if (!row || state.suppressClick) return;
    const id = row.dataset.id;
    if ((row.dataset.kind || row.dataset.lane) === "group") {
      state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
      renderGantt(state.payload);
    } else openCard(id);
  });
  box.addEventListener("mousemove", e => {
    if (e.buttons) { hideTip(); return; }
    const target = e.target.closest("[data-hour], [data-date-only], .ach-hit, .row");
    if (target === tipTarget) {
      if (tipOn) placeTip(e);
      return;
    }
    hideTip();
    if (!target) return;
    tipTarget = target;
    tipTimer = setTimeout(() => {
      if (target.matches(".ach-hit")) return showTipHtml(dayAchHtml(target.dataset.day), e);
      const row = target.closest(".row");
      let html = tipHtml(row);
      if (target.dataset.hour) {
        const [day, hour] = target.dataset.hour.split("T");
        const value = Number(target.dataset.value);
        const count = value ? (row.dataset.lane === "group" ? "组均 " : "") + nf(value) + " 个变更文件" : "该小时无文件产出";
        html = `<div class="tip-hour">${day} · ${hour}:00–${hour}:59　${count}</div>` + html;
      } else if (target.dataset.dateOnly) {
        html = `<div class="tip-hour">${target.dataset.dateOnly} · 有记录缺少具体小时</div>` + html;
      }
      showTipHtml(html, e);
    }, 70);
  });
  box.addEventListener("mouseleave", hideTip);
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

function dayColumns(p, available) {
  const active = new Set(p.units.flatMap(u => u.active));
  const days = [...p.days].reverse();
  const quiet = days.filter(d => d.weekend && !active.has(d.date)).length;
  const dayWidth = Math.max(15, Math.floor((available - 6 * quiet) / Math.max(1, days.length - quiet)));
  let x = 0;
  return days.map(d => {
    const compact = d.weekend && !active.has(d.date);
    const w = compact ? 6 : dayWidth;
    const col = {...d, x, w, compact};
    x += w;
    return col;
  });
}

// 连续有产出的日期共享一根条，仅裁剪首尾。列内的时间从右向左递增。
function workloadBands(item, cols) {
  const productive = new Set(Object.entries(item.hour_files).filter(([, n]) => n > 0).map(([h]) => h.slice(0, 10)));
  const runs = [];
  let run = [];
  for (const col of cols) {
    if (!productive.has(col.date)) { run = []; continue; }
    if (!run.length) runs.push(run);
    run.push(col);
  }
  return runs.map(days => {
    const newest = days[0], oldest = days[days.length - 1];
    const last = item.day_bounds[newest.date][1], first = item.day_bounds[oldest.date][0];
    const position = (col, hour) => col.x + col.w * (1 - hour / 24);
    const left = position(newest, last), right = position(oldest, first);
    const slices = [];
    for (const col of days) {
      for (let h = 23; h >= 0; h--) {
        const x = Math.max(left, position(col, h + 1));
        const end = Math.min(right, position(col, h));
        if (end <= x) continue;
        const hour = col.date + "T" + String(h).padStart(2, "0");
        slices.push({hour, value: item.hour_files[hour] || 0, x, end});
      }
    }
    // 单点和极短记录在日列中保留可见宽度，不会伸入相邻的空白日。
    if (newest === oldest && Math.floor(first) === Math.floor(last) && right - left < 2) {
      const x = Math.max(newest.x, Math.min(newest.x + newest.w - 2, (left + right) / 2 - 1));
      const hour = newest.date + "T" + String(Math.floor(first)).padStart(2, "0");
      return [{x, end: x + 2, hour, value: item.hour_files[hour]}];
    }
    return slices;
  });
}

function renderBand(slices, id, y, height, color, heat, max, group) {
  const x = slices[0].x, width = slices[slices.length - 1].end - x;
  let fill = color, defs = "", hits = "";
  if (heat) fill = heatColor(slices[0].value, max);
  if (heat && slices.some(s => s.value !== slices[0].value)) {
    const stops = [];
    const center = s => ((s.x + s.end) / 2 - x) / width;
    for (let i = 0; i < slices.length; i++) {
      const s = slices[i], prev = slices[i-1];
      if (prev?.value === s.value && slices[i+1]?.value === s.value) continue;
      const offset = center(s);
      // 相邻小时以中心的真实颜色为锚点。跨越色标中点时，保留图例中的红色。
      if (prev && prev.value !== s.value) {
        const a = heatPosition(prev.value, max), b = heatPosition(s.value, max);
        if (Math.min(a,b) < 0.5 && Math.max(a,b) > 0.5) {
          const start = center(prev);
          const red = start + (offset - start) * (0.5 - a) / (b - a);
          stops.push(`<stop offset="${red}" stop-color="rgb(${HEAT_COLORS[1].join(",")})"/>`);
        }
      }
      stops.push(`<stop offset="${offset}" stop-color="${heatColor(s.value, max)}"/>`);
    }
    defs = `<defs><linearGradient id="${id}">${stops.join("")}</linearGradient></defs>`;
    fill = `url(#${id})`;
  }
  for (const s of slices) {
    hits += `<rect x="${s.x}" y="${y}" width="${s.end-s.x}" height="${height}" fill="transparent" data-hour="${s.hour}" data-value="${s.value}"/>`;
  }
  return defs + `<rect class="bar-rect${group ? "" : " child"}" x="${x}" y="${y}" width="${width}" height="${height}" rx="3" fill="${fill}"/>` + hits;
}

function renderGantt(p) {
  hideTip();
  const box = $("gantt");
  const rail = $("taskRail");
  const labelW = rail.clientWidth;
  const days = dayColumns(p, $("timelineScroll").clientWidth);
  const width = days.reduce((w, col) => w + col.w, 0);
  const positions = new Map(days.map(col => [col.date, col]));
  const rows = buildRows(p);
  const headerH = 76;
  const rowHeight = row => row.type === "group" ? 38 : 28;
  const chartY = headerH + rows.reduce((h, row) => h + rowHeight(row), 0) + 12;
  const H = chartY + 70;
  const heat = state.mode === "heat";
  const max = heatMaximum(p.units);
  box.classList.toggle("workload-view", heat);
  const svg = w => `<svg width="${w}" height="${H}" viewBox="0 0 ${w} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  let left = svg(labelW);
  let right = svg(width);
  right += `<defs>
    <pattern id="date-hatch" patternUnits="userSpaceOnUse" width="7" height="7"><path d="M0 7L7 0" stroke="var(--ink3)" opacity=".6"/></pattern>
    </defs>`;
  left += `<text x="8" y="46" class="axis-label">← 新 · 旧 →</text>
    <text x="8" y="65" class="axis-label">成就</text>`;
  days.forEach(day => {
    const {x, w} = day, center = x + w / 2;
    if (day.weekend) right += `<rect x="${x}" width="${w}" height="${H}" fill="${day.compact ? COL.quiet : COL.weekend}"/>`;
    right += `<path d="M${x} 50V${H}" stroke="${day.weekday === "日" ? COL.week : COL.grid}"/>`;
    if (day.compact) {
      right += `<circle cx="${center}" cy="29" r="1.5" fill="var(--ink3)"/>`;
      return;
    }
    right += `<text x="${center}" y="20" text-anchor="middle" class="date-heading">${day.weekday}</text>`;
    if (w >= 26 || day.is_monday) right += `<text x="${center}" y="38" text-anchor="middle" class="date-heading">${day.md}</text>`;
    const badges = (p.achievements[day.date] || []).slice(0, Math.max(1, Math.floor(w / 17)));
    if (badges.length) {
      right += w < 20 ? `<circle cx="${center}" cy="64" r="2" fill="var(--accent)"/>`
        : `<text x="${center}" y="67" text-anchor="middle" font-size="12">${badges.map(b => b.icon).join(" ")}</text>`;
      right += `<rect class="ach-hit" x="${x}" y="50" width="${w}" height="25" fill="transparent" data-day="${day.date}"/>`;
    }
  });
  right += `<path d="M0 50H${width} M0 ${headerH}H${width}" stroke="var(--line)"/>`;
  let y = headerH;
  for (const row of rows) {
    const h = rowHeight(row), mid = y + h / 2;
    if (row.type === "heading") {
      const band = w => `<rect x="0" y="${y}" width="${w}" height="${h}" fill="var(--elevated)"/>`;
      left += band(labelW) + `<text x="8" y="${mid+4}" fill="var(--ink)" font-size="13">${esc(clipPx(row.label, labelW-15))}<title>${esc(row.label)}</title></text>`;
      right += band(width);
    } else {
      const group = row.type === "group", item = group ? row.g : row.u;
      const color = (KIND[item.kind] || {}).color || "#888";
      const attrs = `class="row" data-id="${esc(item.id)}"`;
      const bg = w => `<rect class="rowbg" y="${y}" width="${w}" height="${h}"/>`;
      left += `<g ${attrs} data-kind="${row.type}">${bg(labelW)}`;
      right += `<g ${attrs} data-lane="${row.type}">${bg(width)}`;
      const labX = group ? 18 : 26;
      const suffix = group && state.order === "recent";
      const maxPx = labelW - labX - (group ? 65 : 20);
      left += `<text class="rowlab ${group ? "grouplab" : ""}" x="${labX}" y="${mid+(suffix ? -1 : 4)}">${esc(clipPx(item.title,maxPx))}</text>`;
      if (suffix) left += `<text class="project-suffix" x="${labX}" y="${mid+13}">· ${esc(clipPx(item.project,maxPx,10))}</text>`;
      if (group) {
        const count = item.unit_count === item.unit_count_total ? item.unit_count : `${item.unit_count}/${item.unit_count_total}`;
        left += `<text class="caret" x="4" y="${mid+4}">${state.expanded.has(item.id) ? "▾" : "▸"}</text>
          <text class="rowmeta" x="${labelW-24}" y="${mid+4}" text-anchor="end">${count} 项</text>`;
      }
      left += `<rect class="kinddot" x="${labelW-16}" y="${mid-3.5}" width="7" height="7" rx="1.5" stroke="${color}" fill="${item.design ? "none" : color}"/></g>`;
      for (const date of item.date_only) {
        const col = positions.get(date);
        right += `<rect data-date-only="${date}" x="${col.x+1}" y="${y+h-7}" width="${col.w-2}" height="5" fill="url(#date-hatch)"/>`;
      }
      const bh = group ? 16 : 11;
      workloadBands(item, days).forEach((band, i) => {
        right += renderBand(band, `band-${y}-${i}`, mid-bh/2, bh, color, heat, max, group);
      });
      right += "</g>";
    }
    y += h;
  }
  const peak = Math.max(1,...Object.values(p.daily).map(v => v.n));
  left += `<text x="8" y="${chartY+14}" class="axis-label">每日改动</text>
    <text x="8" y="${chartY+30}" class="axis-label">峰值 ${peak}</text>`;
  for (const day of days) {
    const daily = p.daily[day.date];
    if (!daily) continue;
    const height = Math.max(2, daily.n / peak * 52);
    const w = Math.min(26, day.w - 2);
    right += `<rect class="daybar" x="${day.x+(day.w-w)/2}" y="${chartY+56-height}" width="${w}" height="${height}" rx="2" fill="var(--accent)" opacity=".75"><title>${day.md} · ${daily.n} 处改动</title></rect>`;
  }
  if (!rows.length) right += `<text x="8" y="${headerH+16}" class="axis-label">这段时间没有记录</text>`;
  rail.innerHTML = left + "</svg>";
  box.innerHTML = right + "</svg>";
  const demo = query.get("demo");
  const demoRow = rail.querySelectorAll(".row")[1];
  if (demoRow && demo === "hover") demoRow.classList.add("is-hover");
  if (demoRow && demo === "tip") {
    const r = demoRow.getBoundingClientRect();
    showTip(demoRow, {clientX:r.right, clientY:r.top});
  }
  const achievement = box.querySelector(".ach-hit");
  if (demo === "ach" && achievement) {
    const r = achievement.getBoundingClientRect();
    showTipHtml(dayAchHtml(achievement.dataset.day), {clientX:r.left, clientY:r.top});
  }
}
bindGantt($("ganttwrap"));
$("timelineScroll").addEventListener("scroll", hideTip, {passive: true});
window.addEventListener("scroll", hideTip, {passive: true});

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

  const shade = (n) => (n === 0 ? "var(--panel)" : n <= 3 ? "color-mix(in srgb, var(--accent) 23%, var(--panel))" : n <= 9 ? "color-mix(in srgb, var(--accent) 45%, var(--panel))" : n <= 24 ? "color-mix(in srgb, var(--accent) 72%, var(--panel))" : "var(--accent)");
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
    s += `<rect class="hm-cell" x="${x}" y="${yy}" width="${cell}" height="${cell}" rx="2" fill="${shade(c.n)}" stroke="var(--line)" stroke-width="0.9"><title>${c.date}｜${c.n} 次文件变更</title></rect>`;
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
      s += `<rect class="hourbar" x="${x}" y="${topPad + H0 - h}" width="${bw}" height="${h}" rx="1.5" fill="var(--accent)" opacity="${alpha.toFixed(2)}"><title>${String(hh).padStart(2, "0")}:00–${String(hh).padStart(2, "0")}:59｜${v} 次改动</title></rect>`;
    } else {
      s += `<rect x="${x}" y="${topPad + H0 - 1}" width="${bw}" height="1" fill="var(--line)"/>`;
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
    if (!acc) s += `<rect x="${x}" y="${topPad + H0 - 2}" width="${barW}" height="2" fill="var(--line)"/>`;
    s += `<text x="${x + barW / 2}" y="${H - 5}" text-anchor="middle" font-size="10" fill="${COL.head}">${w.md}</text>`;
    s += `</g>`;
  });
  box.innerHTML = s + "</svg>";
}

/* ---------------- 卡片 ---------------- */
function groupOf(p, id) {
  return p.groups.find((x) => x.units.some((u) => u.id === id));
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
    : esc(u.summary || "待整理：需要回查本段会话，补充任务经过和结果。");

  return `<article class="card ${open ? "open" : ""}" id="card-${esc(u.id)}">
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
      ${u.review_issues.length ? `<div class="sec">${esc(u.review_issues.join(" · "))} · ${esc(u.harness || "")} · ${esc(u.id)}</div>` : ""}
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
  const ordered = [];
  const topicCards = (label, units) => {
    ordered.push(...units);
    return `<h4 class="topic-heading">${esc(label)} · ${units.length} 项</h4>` + units.map(u => cardHtml(p, u)).join("");
  };
  wrap.innerHTML = topicSections(p).map(project => {
    const heading = project.name && p.project.id === "all" ? `<h3 class="project-heading">${esc(project.name)}</h3>` : "";
    const topics = project.topics.map(g => topicCards(topicName(g), g.units)).join("");
    return heading + topics;
  }).join("");

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
  document.title = `worklog · ${p.project.name}`;
  renderHeadline(p);
  renderLegend(p);
  renderGantt(p);
  renderHeatmap(p);
  renderHours(p);
  renderWeekly(p);
  renderCards(p);
  const pending = p.units.filter(u => !u.group_id).length;
  const incomplete = p.units.filter(u => u.review_issues.length).length;
  $("foot").textContent = `${p.project.name} · ${p.units.length} 个任务 · ${p.groups.length} 个主题 · ${pending} 项待归组 · ${incomplete} 项待补标题或详情`;
  if (pending || incomplete) $("hlSub").insertAdjacentHTML("beforeend", `<span>整理中 · 待归组 ${pending} · 待补标题或详情 ${incomplete}</span>`);

}

const embedded = document.getElementById("worklog-snapshot");
const snapshot = embedded ? JSON.parse(embedded.textContent) : null;

async function readReport(url) {
  if (snapshot) {
    const {pathname, searchParams} = new URL(url, "http://localhost");
    const source = snapshot.sources[searchParams.get("harness") || ""];
    if (pathname === "/api/harnesses") return {harnesses: snapshot.harnesses};
    if (pathname === "/api/projects") return {projects: source.projects};
    return source.views[searchParams.get("project")][searchParams.get("days")];
  }
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadHarnesses() {
  try {
    const data = await readReport("/api/harnesses");
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
    const url = "/api/projects" + (state.harness ? `?harness=${encodeURIComponent(state.harness)}` : "");
    const data = await readReport(url);
    const sel = $("projSel");
    sel.innerHTML = data.projects
      .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}（${p.units}）</option>`)
      .join("");
    // 换了来源后，原来选的项目可能没数据了 —— 回退到「全部项目」
    if ([...sel.options].some((o) => o.value === state.project)) {
      sel.value = state.project;
    } else {
      sel.value = "all";
      state.project = "all";
    }
  } catch (e) {
    /* 忽略，主视图还能用 */
  }
}

async function load() {
  try {
    const qs = `project=${encodeURIComponent(state.project)}&days=${state.days}` +
      (state.harness ? `&harness=${encodeURIComponent(state.harness)}` : "");
    render(await readReport(`/api/project?${qs}`));
  } catch (e) {
    $("hlSub").textContent = "读取失败：" + e.message;
  }
}

$("harnSel").addEventListener("change", (e) => {
  state.harness = e.target.value;
  state.expanded.clear();
  state.open.clear();
  // 项目列表要跟着来源重算，否则会列出该来源下根本没数据的项目
  loadProjects().then(load);
});

$("projSel").addEventListener("change", (e) => {
  state.project = e.target.value;
  state.expanded.clear();
  state.open.clear();
  load();
});

function markSelection(id, key, value) {
  for (const button of $(id).querySelectorAll("button")) {
    const active = button.dataset[key] === value;
    button.classList.toggle("on", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

markSelection("modes", "mode", state.mode);
markSelection("grouping", "order", state.order);
markSelection("ranges", "days", String(state.days));
$("grouping").addEventListener("click", e => {
  const button = e.target.closest("button");
  if (!button || button.dataset.order === state.order) return;
  state.order = button.dataset.order;
  markSelection("grouping", "order", state.order);
  if (state.payload) {
    hideTip();
    renderGantt(state.payload);
    renderCards(state.payload);
  }
});

$("modes").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn || btn.dataset.mode === state.mode) return;
  state.mode = btn.dataset.mode;
  markSelection("modes", "mode", state.mode);
  if (state.payload) {
    renderLegend(state.payload);
    renderGantt(state.payload);
  }
});

$("ranges").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.days = Number(btn.dataset.days);
  markSelection("ranges", "days", btn.dataset.days);
  load();
});

/* 拖动平移 */
(function enablePan() {
  const wrap = $("timelineScroll");
  let down = false, startX = 0, startLeft = 0, moved = 0;

  wrap.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return;
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

const hq = new URLSearchParams(location.search).get("harness");
if (hq) {
  state.harness = hq;
  const sel = document.getElementById("harnSel");
  if (sel) sel.value = hq;
}

const pq = new URLSearchParams(location.search).get("project");
if (pq) state.project = pq;

Promise.all([loadHarnesses(), loadProjects()]).then(load);
