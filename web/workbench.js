const ui = Object.fromEntries(Array.from(document.querySelectorAll('[id]'), el => [el.id, el]));
const theme = document.body.dataset.visual;
const state = { data: null, selected: '', lastRequest: 0, generation: 0, busy: false };
const labels = { allocated: '已排入', held: '业务锁定', deferred: '待排额度', manual: '人工复核', monitor: '暂不处理' };
const reasons = {
  CAPACITY_RESERVED: '额度已预留', QUOTA_REACHED: '总额已用完', RESOURCE_CEILING: '组内上限',
  WINDOW_COLLISION: '窗口冲突', PORTFOLIO_CAPACITY: '本轮资源组合未纳入', WINDOW_TOO_SHORT: '可用窗口不足',
  CROSS_SHIFT: '作业跨班', BUSINESS_LOCK: '前置条件锁定', TRUST_REVIEW: '需要人工确认', BELOW_ACTION: '低于处置门限',
  MISSING_DECISION_FIELD: '关键字段缺测', BACKTEST_GATE: '回放核验未通过', REGIME_CHANGED: '分布偏移',
  LOW_SUPPORT: '可比样本不足', OUT_OF_REFERENCE: '读数超出参考',
};
const nfmt = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });

function number(value) {
  return typeof value === 'number' && Number.isFinite(value) ? nfmt.format(value) : '—';
}

function node(tag, text, attrs = {}) {
  const element = document.createElement(tag);
  if (text !== null) element.textContent = text;
  for (const [name, value] of Object.entries(attrs)) element.setAttribute(name, value);
  return element;
}

async function jsonRequest(path, options) {
  const response = await fetch(path, options);
  const content = await response.json();
  if (!response.ok) throw new Error(typeof content.detail === 'string' ? content.detail : '提交内容有误，请检查额度和版本。');
  return content;
}

function setMessage(message, error = false) {
  ui.message.textContent = message;
  ui.message.dataset.tone = error ? 'error' : 'normal';
}

function tickTime(tick) {
  return `${String(Math.floor(tick / 4)).padStart(2, '0')}:${String(tick % 4 * 15).padStart(2, '0')}`;
}

function durationLabel(row) {
  return `${tickTime(row.tick)} · ${number(row.units)}`;
}

function displayValue(row) {
  const unit = state.data.unit;
  if (unit === '概率') return `${number(row.estimate * 100)}%`;
  return `${number(row.estimate)} ${unit}`;
}

function filteredRows() {
  const search = ui.search.value.trim().toLowerCase();
  const group = ui.cohort.value;
  const workflow = ui.disposition.value;
  return state.data.decisions.filter(row => (!search || row.case_id.toLowerCase().includes(search))
    && (!group || row.cohort === group) && (!workflow || row.status === workflow));
}

function showDetails(row) {
  const evidence = state.data.row_evidence[row.case_id];
  ui.detail.replaceChildren();
  ui.detail.classList.add('is-selection');
  const title = node('h3', row.case_id);
  const status = node('span', labels[row.status], {'class': `state-label tag-${row.status}`});
  const action = node('p', `${row.cohort} · ${reasons[row.reason] || row.reason}`);
  const list = node('dl', null, {class: 'ticket-values'});
  const items = [['模型估计', displayValue(row)], ['窗口与额度', durationLabel(row)],
    ['特征参考', evidence.feature_reference], ['采用结果', row.source === 'trained' ? '历史拟合' : '分组基线']];
  if (row.low !== null) items.push(['估计区间', `${number(row.low)} – ${number(row.high)}`]);
  const operation = evidence.operational_check;
  if (operation) items.push([operation.impact_label, number(operation.impact)], [operation.headroom_label, number(operation.headroom)]);
  for (const [key, value] of items) list.append(node('dt', key), node('dd', value));
  ui.detail.append(title, status, action, list);
  const review = [...(row.details || []), ...evidence.trust_reasons].map(reason => reasons[reason] || reason);
  if (review.length) ui.detail.append(node('p', [...new Set(review)].join(' · '), {class: 'decision-note'}));
  const fold = node('details', null);
  fold.append(node('summary', '测量与派生特征'));
  const terms = node('dl', null, {class: 'ticket-values'});
  for (const [key, val] of Object.entries(evidence.features)) terms.append(node('dt', key), node('dd', number(val)));
  fold.append(terms);
  ui.detail.append(fold);
}

function renderQueue() {
  if (!state.data) return;
  const rows = filteredRows();
  ui.queue.replaceChildren();
  ui.result_count.textContent = `${rows.length} 笔单据`;
  if (!rows.length) {
    const tr = node('tr', null);
    tr.append(node('td', '当前筛选没有单据。', {colspan: '5', class: 'empty'}));
    ui.queue.append(tr);
    ui.detail.classList.remove('is-selection');
    ui.detail.replaceChildren(node('p', '调整筛选后可查看逐单证据。'));
    return;
  }
  if (!rows.some(row => row.case_id === state.selected)) state.selected = rows[0].case_id;
  for (const row of rows) {
    const isCurrent = row.case_id === state.selected;
    const tr = node('tr', null, {'data-selected': String(isCurrent)});
    const open = node('button', row.case_id, {type: 'button', class: 'row-button', 'aria-pressed': String(isCurrent)});
    open.addEventListener('click', () => {
      state.selected = row.case_id;
      renderQueue();
      ui.queue.querySelector('button[aria-pressed="true"]')?.focus({preventScroll: true});
    });
    const first = node('td', null);
    first.append(open);
    const progress = node('td', null);
    progress.append(node('span', labels[row.status], {class: `state-label tag-${row.status}`}));
    tr.append(first, node('td', row.cohort), node('td', displayValue(row)), node('td', String(row.units)), progress);
    ui.queue.append(tr);
    if (isCurrent) showDetails(row);
  }
}

function replayEvidence() {
  const { evaluation, drift } = state.data;
  const overall = evaluation.overall;
  ui.model_line.textContent = state.data.model.algorithm;
  ui.replay_loss.textContent = `${number(overall.loss)} / ${number(overall.reference_loss)}`;
  ui.replay_metric.textContent = evaluation.metric;
  ui.replay_count.textContent = `${evaluation.holdout_cases} 笔回放 · ${evaluation.calibration_cases} 笔校准`;
  ui.regimes.replaceChildren();
  for (const [name, meta] of Object.entries(drift.groups)) {
    const status = ({ STABLE: '参考稳定', WATCH: '持续观察', REGIME_CHANGED: '暂停自动', LOW_SUPPORT: '样本不足', NO_BATCH: '空组' })[meta.status];
    ui.regimes.append(node('li', `${name} · ${status}`, {'data-status': meta.status}));
  }
}

function sceneEvidence() {
  const snapshot = state.data;
  const good = snapshot.decisions.filter(row => row.status === 'allocated');
  const ops = good.map(row => snapshot.row_evidence[row.case_id].operational_check);
  const finite = ops.map(row => row.headroom).filter(Number.isFinite);
  const sum = vals => vals.reduce((total, item) => total + item, 0);
  const reserved = label => [`${label}`, finite.length ? number(Math.min(...finite)) : '—'];
  let values;
  if (theme === 'timeline') {
    values = snapshot.schedule.slice(0,3).map(slot => [`第 ${slot.day} 日 · ${slot.resource}`, `${tickTime(slot.tickets[0].window_start)} · ${slot.units} 格`]);
  } else if (theme === 'bridge') {
    values = [['送检位置', `${good.length} 件`], reserved('最小许可余量 / min')];
  } else if (theme === 'matrix') {
    values = [['预估争议暴露 / 元', number(sum(ops.map(row => row.impact)))], ['移交席位', number(snapshot.summary.used)], ['需人工确认', number(snapshot.summary.manual)]];
  } else if (theme === 'humidity') {
    values = [['保全工位', number(snapshot.summary.used)], reserved('最小保护余量 / min'), ['进班展柜', number(good.length)]];
  } else if (theme === 'duplex') {
    values = [['合同锁定与在途',number(snapshot.summary.held)], ['可催确认',number(good.length)], reserved('最少替代灯头')];
  } else if (theme === 'saw') {
    values = [['最大估计磨损 / µm',good.length ? number(Math.max(...good.map(row => row.estimate))) : '—'],reserved('最小换型余量 / min'), ['核验槽',number(snapshot.summary.used)]];
  } else if (theme === 'cohorts') {
    values = Object.entries(snapshot.resource).map(([group,value]) => [group, `${value} 格`]);
  } else {
    values = good.slice(0,3).map(row => [row.case_id, `${number(snapshot.row_evidence[row.case_id].measurements.retained)} g`]);
  }
  ui.scene.replaceChildren();
  if (!values.length) {
    ui.scene.append(node('div','本轮没有已排入单据。',{'data-empty':''}));
  }
  for (const [key,value] of values) {
    const box = node('div', null, {class:'scene-row'});
    box.append(node('dt',key),node('dd',value));
    ui.scene.append(box);
  }
}

function renderRun() {
  const snapshot = state.data;
  ui.metric_cases.textContent = number(snapshot.summary.cases);
  ui.metric_queue.textContent = number(snapshot.summary.proposed);
  ui.metric_held.textContent = number(snapshot.summary.held + snapshot.summary.manual);
  ui.metric_used.textContent = `${snapshot.summary.used} / ${snapshot.summary.capacity}`;
  ui.run_ticket.textContent = `第 ${snapshot.as_of} 日 · ${snapshot.run_id.slice(0, 10)}`;
  ui.export.href = `/api/decisions.csv?capacity=${snapshot.summary.capacity}`;
  const former = ui.cohort.value;
  ui.cohort.replaceChildren(node('option', '全部分组', {value: ''}));
  for (const value of Object.keys(snapshot.summary.groups)) ui.cohort.append(node('option', value, {value}));
  if (Array.from(ui.cohort.options).some(option => option.value === former)) ui.cohort.value = former;
  renderQueue();
  replayEvidence();
  sceneEvidence();
  draw();
}

async function refresh(capacity) {
  const serial = ++state.lastRequest;
  const previous = state.data?.summary.capacity;
  state.busy = true;
  ui.simulate.disabled = true;
  ui.register.disabled = true;
  setMessage('正在核对单据与分派额度…');
  try {
    const data = await jsonRequest(`/api/plan${capacity === undefined ? '' : `?capacity=${capacity}`}`);
    if (serial !== state.lastRequest) return;
    state.data = data;
    ui.capacity.value = data.summary.capacity;
    renderRun();
    if (previous !== undefined && previous !== data.summary.capacity) {
      const comparison = await jsonRequest(`/api/compare?capacity=${data.summary.capacity}&against=${previous}`);
      const delta = comparison.current.proposed - comparison.reference.proposed;
      setMessage(`额度调整为 ${data.summary.capacity}，${comparison.changes.length} 笔状态变化，排入数量 ${delta > 0 ? '+' : ''}${delta}。`);
    } else {
      setMessage(`已核对 ${data.summary.cases} 笔业务单据。`);
    }
  } catch (error) {
    if (serial === state.lastRequest) setMessage(error.message, true);
  } finally {
    if (serial === state.lastRequest) {
      state.busy = false;
      ui.simulate.disabled = false;
      ui.register.disabled = !state.data;
    }
  }
}

async function release() {
  if (!state.data || state.busy) return;
  state.busy = true;
  ui.simulate.disabled = ui.register.disabled = true;
  try {
    const data = state.data;
    const saved = await jsonRequest('/api/releases', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({capacity: data.summary.capacity, as_of: data.as_of,
        expected_generation: state.generation, run_id: data.run_id})});
    state.generation = Math.max(state.generation, saved.generation);
    ui.release_version.textContent = `查看登记版 ${saved.generation}`;
    ui.release_version.href = `/api/releases/${saved.generation}`;
    ui.release_version.hidden = false;
    setMessage(saved.replayed ? `该方案已登记，沿用版本 ${saved.generation}。` : `完成登记，版本 ${saved.generation}。`);
  } catch (error) {
    setMessage(error.message, true);
    await latestRelease();
  } finally {
    state.busy = false;
    ui.simulate.disabled = ui.register.disabled = false;
  }
}

async function latestRelease() {
  try {
    const previous = await jsonRequest('/api/releases?limit=1');
    state.generation = previous[0]?.generation || 0;
    if (state.generation) {
      ui.release_version.href = `/api/releases/${state.generation}`;
      ui.release_version.textContent = `查看登记版 ${state.generation}`;
      ui.release_version.hidden = false;
    }
  } catch {}
}

let palette;
function draw() {
  if (!state.data || !ui.chart) return;
  const canvas = ui.chart;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const context = canvas.getContext('2d');
  context.scale(dpr, dpr);
  const css = getComputedStyle(canvas);
  palette = ['--accent', '--muted', '--line', '--ink', '--accent-soft'].map(key => css.getPropertyValue(key).trim());
  const [accent, muted, grid, ink, light] = palette;
  const rows = state.data.decisions;
  const groups = Object.keys(state.data.summary.groups);
  context.font = '12px system-ui, sans-serif';
  context.textBaseline = 'middle';
  function line(x, y, x2, y2, color = grid) {
    context.strokeStyle = color; context.beginPath(); context.moveTo(x, y); context.lineTo(x2, y2); context.stroke();
  }
  function word(text, x, y, color = muted) {
    context.fillStyle = color; context.fillText(text, x, y);
  }
  function block(x, y, w, h, color = accent) {
    context.fillStyle = color; context.fillRect(x, y, w, h);
  }
  const left = width < 420 ? 85 : 118;
  const area = width-left-22;
  if (area<50) return;
  if (theme === 'timeline') {
    const floor = Math.min(...rows.map(row => row.tick)) - 1;
    const ceiling = Math.max(...rows.map(row => row.tick + row.units)) + 1;
    const axis = slot => left + (slot-floor) / (ceiling-floor) * area;
    for (let tick=Math.ceil(floor/8)*8; tick<=ceiling; tick+=8) {
      word(tickTime(tick),axis(tick),17); line(axis(tick),34,axis(tick),height-15);
    }
    groups.forEach((group,j) => {
      const y=54+j*(height-57)/groups.length;
      word(group,8,y,ink); line(left,y, width-20,y);
      rows.filter(row => row.cohort===group).forEach((row,i) => {
        block(axis(row.tick),y-10+i%3*8,Math.max(4,axis(row.tick+row.units)-axis(row.tick)),6,row.status==='allocated'?accent:light);
      });
    });
  } else if (theme === 'matrix') {
    const hits = state.data.evaluation.groups;
    const size = (area-18)/5;
    for (let i=0;i<5;i++) word(`${i*20}%`,left+i*size,16);
    groups.forEach((group,j) => {
      const y=39+j*(height-47)/groups.length;
      word(group,8,y+12,ink);
      (hits[group]?.reliability || []).forEach((bucket,i) => {
        block(left+i*size,y,size-5,25,bucket.count ? light : grid);
        if (bucket.count) block(left+i*size,y,Math.min(size-5,(size-5)*bucket.event_rate),25,accent);
        word(String(bucket.count),left+i*size+6,y+13,ink);
      });
    });
  } else if (theme === 'cohorts' || theme === 'duplex' || theme === 'roast') {
    const items = groups.map(group => {
      const cohort = rows.filter(row => row.cohort === group);
      return { group, scope: cohort.length, scheduled: cohort.filter(row => row.status === 'allocated').length,
        used: state.data.resource[group] || 0, prior: cohort.filter(row => row.status === 'held' || row.status === 'manual').length };
    });
    const max = Math.max(1,...items.map(row => theme === 'cohorts' ? Math.max(row.scope,row.used) : row.scope));
    items.forEach((row,j) => {
      const y=35+j*(height-36)/groups.length;
      const slot = Math.max(58,area-38);
      word(row.group,8,y+3,ink);
      block(left,y-7,slot,20,grid);
      if (theme === 'duplex') {
        block(left,y-7,slot*row.prior/max,20,light);
        block(left+slot*row.prior/max,y-7,slot*row.scheduled/max,20,accent);
      } else {
        block(left,y-7,slot*row.scope/max,20,light);
        block(left,y-7,slot*(theme==='cohorts'?row.used:row.scheduled)/max,20,accent);
      }
      word(String(theme==='cohorts'?row.used:row.scheduled),width-32,y+4,ink);
    });
  } else {
    const sorted = [...rows].sort((a,b)=>a.calendar_day-b.calendar_day || a.tick-b.tick);
    const max = Math.max(1,...rows.map(row=>row.high ?? row.estimate));
    const usable=height-45;
    const x = i => 46+i/Math.max(1,sorted.length-1)*(width-66);
    const y = value => 17+usable*(1-value/max);
    for (let i=0;i<=4;i++) {const mark=max*i/4; word(number(mark),4,y(mark)); line(47,y(mark),width-10,y(mark));}
    if (theme==='humidity') {
      context.beginPath(); context.moveTo(x(0),y(0));
      sorted.forEach((row,i)=>context.lineTo(x(i),y(row.estimate)));
      context.lineTo(x(sorted.length-1),y(0)); context.closePath(); context.fillStyle=light; context.fill();
    }
    sorted.forEach((row,i) => {
      if (row.low!==null) line(x(i),y(row.low),x(i),y(row.high),grid);
      const size = row.status==='allocated'?7:4;
      block(x(i)-size/2,y(row.estimate)-size/2,size,size,row.status==='allocated'?accent:muted);
    });
    const start=sorted[0]?.calendar_day;
    const end=sorted[sorted.length-1]?.calendar_day;
    if (start) word(`第 ${start} 日`,46,height-10);
    if (end) word(`第 ${end} 日`,width-74,height-10);
  }
}

ui.controls.addEventListener('submit', event => {
  event.preventDefault();
  if (!ui.capacity.reportValidity() || state.busy) return;
  refresh(ui.capacity.valueAsNumber);
});
ui.register.addEventListener('click', release);
ui.search.addEventListener('input', renderQueue);
ui.cohort.addEventListener('change', renderQueue);
ui.disposition.addEventListener('change', renderQueue);
new ResizeObserver(draw).observe(ui.chart);
refresh();
latestRelease();
