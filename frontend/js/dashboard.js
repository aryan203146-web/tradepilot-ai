/**
 * TradePilot AI — Dashboard JavaScript
 * Handles API calls, signal rendering, real-time clock, paper trade management
 */

const API_BASE = '';  // Same origin
let currentSignal = null;
let autoRefreshTimer = null;
let lastScanResults = null;

// ================================================================
// Clock & Market Status
// ================================================================

function updateClock() {
  const now = new Date();
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));

  const h = String(ist.getHours()).padStart(2, '0');
  const m = String(ist.getMinutes()).padStart(2, '0');
  const s = String(ist.getSeconds()).padStart(2, '0');
  document.getElementById('clock-time').textContent = `${h}:${m}:${s}`;

  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  document.getElementById('clock-date').textContent =
    `${days[ist.getDay()]}, ${ist.getDate()} ${months[ist.getMonth()]} ${ist.getFullYear()}`;

  // Market status
  const badge = document.getElementById('market-status-badge');
  const weekday = ist.getDay();
  const totalMins = ist.getHours() * 60 + ist.getMinutes();
  const marketOpen = 9 * 60 + 15;   // 09:15
  const marketClose = 15 * 60 + 30; // 15:30

  if (weekday === 0 || weekday === 6) {
    badge.textContent = 'CLOSED';
    badge.className = 'market-badge closed';
  } else if (totalMins >= marketOpen && totalMins <= marketClose) {
    badge.textContent = '● OPEN';
    badge.className = 'market-badge open';
  } else if (totalMins >= marketOpen - 15 && totalMins < marketOpen) {
    badge.textContent = 'PRE-OPEN';
    badge.className = 'market-badge pre';
  } else {
    badge.textContent = 'CLOSED';
    badge.className = 'market-badge closed';
  }
}

function selectAllSymbols(check) {
  document.querySelectorAll('.sym-check').forEach(c => c.checked = check);
}

function selectIndicesOnly() {
  document.querySelectorAll('.sym-check').forEach(c => {
    c.checked = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'].includes(c.value);
  });
}

async function inspectSymbolValidation() {
  const sym = document.getElementById('validator-symbol-select').value;
  const outEl = document.getElementById('validator-output');
  const spinner = document.getElementById('validator-loading');
  if (spinner) spinner.classList.remove('hidden');

  try {
    const resp = await fetch(`${API_BASE}/api/signals/${sym}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderValidationAudit(data, outEl);
  } catch (err) {
    outEl.innerHTML = `<div style="color:var(--red);padding:14px;">Failed to inspect ${sym}: ${err.message}</div>`;
  } finally {
    if (spinner) spinner.classList.add('hidden');
  }
}

function renderValidationAudit(data, container) {
  const sym = data.symbol;
  const spot = data.spot_price?.toFixed(2) || '--';
  const ind = data.indicators || {};
  const buy = data.buying_signal;
  const sell = data.selling_signal;

  const activeSig = (buy && !buy.is_no_trade) ? buy : (sell && !sell.is_no_trade) ? sell : buy || sell;
  const isValid = activeSig && activeSig.validation_passed && !activeSig.is_no_trade;

  const notes = activeSig?.validation_notes || [];
  const checklistHtml = notes.map(n => {
    const isPass = n.includes('✅');
    const isFail = n.includes('❌');
    const border = isPass ? 'var(--green)' : isFail ? 'var(--red)' : 'var(--yellow)';
    const bg = isPass ? 'rgba(0,200,150,0.06)' : isFail ? 'rgba(255,77,109,0.06)' : 'rgba(255,209,102,0.06)';
    return `<div style="padding:7px 12px;background:${bg};border-left:3px solid ${border};border-radius:4px;font-size:12px;margin-bottom:6px;">${n}</div>`;
  }).join('') || '<div style="font-size:12px;color:var(--text-muted)">No rule notes available</div>';

  const verdictHtml = isValid
    ? `<div style="padding:10px 14px;background:rgba(0,200,150,0.15);border:1px solid var(--green);border-radius:8px;color:var(--green);font-weight:700;display:flex;justify-content:space-between;align-items:center;">
        <span>✅ VALIDATED SETUP: ${activeSig.option_symbol} @ ₹${activeSig.entry_price?.toFixed(2)}</span>
        <button class="btn-sm" style="background:var(--green);color:#000;font-weight:700;" onclick='openSignalModal(${JSON.stringify(activeSig)})'>Inspect & Trade</button>
       </div>`
    : `<div style="padding:10px 14px;background:rgba(255,77,109,0.12);border:1px solid var(--red);border-radius:8px;color:var(--red);font-weight:700;">
        ⛔ REJECTED: NO TRADE — ${activeSig?.no_trade_reason || 'Failed technical validation'}
       </div>`;

  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px;margin-top:6px;">
      ${verdictHtml}

      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:10px;">
        <div style="background:var(--bg-secondary);padding:8px 12px;border-radius:6px;">
          <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Spot Price</div>
          <div style="font-size:15px;font-weight:700;font-family:var(--font-mono);color:var(--accent);">₹${spot}</div>
        </div>
        <div style="background:var(--bg-secondary);padding:8px 12px;border-radius:6px;">
          <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">VWAP</div>
          <div style="font-size:14px;font-weight:600;font-family:var(--font-mono);">₹${ind.vwap?.toFixed(2) || '--'}</div>
        </div>
        <div style="background:var(--bg-secondary);padding:8px 12px;border-radius:6px;">
          <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">15m Trend</div>
          <div style="font-size:13px;font-weight:600;color:${ind.trend_15m?.includes('BULL') ? 'var(--green)' : ind.trend_15m?.includes('BEAR') ? 'var(--red)' : 'var(--text-secondary)'}">${ind.trend_15m || 'SIDEWAYS'}</div>
        </div>
        <div style="background:var(--bg-secondary);padding:8px 12px;border-radius:6px;">
          <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">RSI (5m / 15m)</div>
          <div style="font-size:13px;font-weight:600;font-family:var(--font-mono);">${ind.rsi_5m?.toFixed(1) || '--'} / ${ind.rsi_15m?.toFixed(1) || '--'}</div>
        </div>
        <div style="background:var(--bg-secondary);padding:8px 12px;border-radius:6px;">
          <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">SuperTrend 5m</div>
          <div style="font-size:13px;font-weight:600;color:${ind.supertrend_5m === 'BULL' ? 'var(--green)' : 'var(--red)'}">${ind.supertrend_5m || '--'}</div>
        </div>
        <div style="background:var(--bg-secondary);padding:8px 12px;border-radius:6px;">
          <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Volume Ratio</div>
          <div style="font-size:13px;font-weight:600;font-family:var(--font-mono);">${ind.volume_ratio_5m?.toFixed(2) || '--'}x avg</div>
        </div>
      </div>

      <div>
        <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
          📋 Rule-By-Rule Audit Checklist:
        </div>
        ${checklistHtml}
      </div>
    </div>
  `;
}

function setupAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  const el = document.getElementById('auto-refresh-interval');
  if (!el) return;
  const interval = parseInt(el.value);
  if (interval > 0) {
    autoRefreshTimer = setInterval(() => runScan(), interval * 1000);
  }
}

// ================================================================
// Scan Markets
// ================================================================

async function runScan() {
  const btn = document.getElementById('btn-scan');
  const statusText = document.getElementById('scan-status-text');
  const spinner = document.getElementById('scan-loading');

  btn.classList.add('loading');
  btn.disabled = true;
  spinner.classList.remove('hidden');
  statusText.textContent = 'Scanning markets... fetching data and computing indicators';

  // Get selected symbols
  const checked = Array.from(document.querySelectorAll('.sym-check:checked')).map(c => c.value);
  if (checked.length === 0) {
    statusText.textContent = 'Please select at least one symbol';
    btn.classList.remove('loading');
    btn.disabled = false;
    spinner.classList.add('hidden');
    return;
  }

  try {
    const resp = await fetch(`${API_BASE}/api/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: checked }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    const data = await resp.json();
    lastScanResults = data;

    renderScanResults(data);
    renderMarketData(data.market_data || {});
    updatePortfolioUI(data.portfolio_summary);

    const sigCount = data.total_valid_signals || 0;
    const timeStr = new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' });
    statusText.textContent = `Last scan: ${timeStr} | ${sigCount} valid signal(s) | ${checked.join(', ')}`;

  } catch (err) {
    console.error('Scan error:', err);
    statusText.textContent = `Scan error: ${err.message}`;
    showError(`Market scan failed: ${err.message}`);
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
    spinner.classList.add('hidden');
  }
}

// ================================================================
// Render Signal Cards
// ================================================================

function renderScanResults(data) {
  const container = document.getElementById('signals-container');
  const countEl = document.getElementById('signals-count');

  container.innerHTML = '';

  const signals = data.signals || [];
  const noTradeSymbols = data.no_trade_symbols || [];

  if (signals.length === 0) {
    countEl.textContent = '⛔ NO TRADE';
    container.innerHTML = buildNoTradeCard(noTradeSymbols, data);
    return;
  }

  countEl.textContent = `${signals.length} signal${signals.length > 1 ? 's' : ''} found`;
  signals.forEach(sig => {
    container.appendChild(buildSignalCard(sig));
  });

  // Show no-trade symbols if any
  if (noTradeSymbols.length > 0) {
    const noTradeDiv = document.createElement('div');
    noTradeDiv.style.gridColumn = '1/-1';
    noTradeDiv.innerHTML = `
      <div style="font-size:12px;color:var(--text-muted);padding:8px 12px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;">
        ⛔ No valid setup for: ${noTradeSymbols.map(n => n.symbol).join(', ')}
      </div>
    `;
    container.appendChild(noTradeDiv);
  }
}

function buildNoTradeCard(symbols, data) {
  const reasons = symbols.flatMap(s =>
    (s.reasons || []).map(r => `<div class="no-trade-reason-item">
      <strong>${s.symbol}:</strong> ${r}
    </div>`)
  );

  const systemMsg = data.system_message ? `<div style="color:var(--yellow);margin-bottom:8px;font-size:13px;">⚠️ ${data.system_message}</div>` : '';

  return `
    <div class="no-trade-card">
      <div class="no-trade-header">⛔ NO TRADE — No Valid Setup Found</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px;">
        No signals passed all validation checks. This is correct behavior — 
        TradePilot AI is protecting your capital by not forcing low-quality trades.
      </p>
      ${systemMsg}
      <div class="no-trade-reasons">
        ${reasons.join('') || '<div class="no-trade-reason-item">Market conditions not conducive to any setup at this time.</div>'}
      </div>
    </div>
  `;
}

function buildSignalCard(sig) {
  const card = document.createElement('div');
  card.className = 'signal-card';

  const isCall = sig.option_type === 'CE';
  const isBuying = sig.trade_type === 'OPTIONS_BUYING';
  const typeClass = isBuying ? 'buying' : 'selling';
  const optBadgeClass = isCall ? 'call' : 'put';
  const optLabel = isCall ? '📈 CALL' : '📉 PUT';
  const tradeLabel = isBuying ? '🔵 BUYING' : '🟣 SELLING';
  const strengthClass = (sig.signal_strength || 'MODERATE').toLowerCase();

  const entryPrice = sig.entry_price?.toFixed(2) || '--';
  const sl = sig.stop_loss?.toFixed(2) || '--';
  const t1 = sig.target_1?.toFixed(2) || '--';
  const t2 = sig.target_2?.toFixed(2) || '--';
  const rr = sig.risk_reward_ratio?.toFixed(1) || '--';

  const indicators = sig.indicators || {};
  const rsi5m = indicators.rsi_5m ? indicators.rsi_5m.toFixed(1) : '--';
  const macd = indicators.macd_hist_5m ? indicators.macd_hist_5m.toFixed(3) : '--';
  const vwap = indicators.vwap ? indicators.vwap.toFixed(0) : '--';
  const volRatio = indicators.volume_ratio ? indicators.volume_ratio.toFixed(2) : '--';
  const st = indicators.supertrend_5m || '--';

  const timeStr = new Date(sig.generated_at).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' });

  card.innerHTML = `
    <div class="signal-card-header ${typeClass}">
      <div class="sh-left">
        <span class="sh-symbol">${sig.symbol}</span>
        <span class="sh-type">${tradeLabel} · ${sig.timeframe || '5m+15m'}</span>
      </div>
      <div class="sh-right">
        <span class="signal-badge ${optBadgeClass}">${optLabel}</span>
        <span class="signal-badge ${strengthClass}">${sig.signal_strength || 'MODERATE'}</span>
      </div>
    </div>
    <div class="signal-card-body">
      <div class="sc-option-symbol">${sig.option_symbol || '--'}</div>
      <div class="sc-price-grid">
        <div class="sc-price-item">
          <span class="sc-price-label">Entry</span>
          <span class="sc-price-value entry">₹${entryPrice}</span>
        </div>
        <div class="sc-price-item">
          <span class="sc-price-label">Stop Loss</span>
          <span class="sc-price-value sl">₹${sl}</span>
        </div>
        <div class="sc-price-item">
          <span class="sc-price-label">Target 1</span>
          <span class="sc-price-value t1">₹${t1}</span>
        </div>
        <div class="sc-price-item">
          <span class="sc-price-label">Target 2</span>
          <span class="sc-price-value t2">₹${t2}</span>
        </div>
      </div>
      <div class="sc-rr">
        Risk/Reward: <span class="rr-value">${rr}:1</span>
        &nbsp;|&nbsp; Lots: <span style="font-family:var(--font-mono);font-weight:600">${sig.position_size_lots}</span>
        &nbsp;|&nbsp; Capital at Risk: <span style="color:var(--orange);font-family:var(--font-mono)">${sig.capital_at_risk_pct?.toFixed(1)}%</span>
      </div>
      <div class="sc-indicators">
        <span class="sc-ind-badge">RSI: ${rsi5m}</span>
        <span class="sc-ind-badge">MACD: ${macd}</span>
        <span class="sc-ind-badge">VWAP: ₹${vwap}</span>
        <span class="sc-ind-badge">Vol: ${volRatio}x</span>
        <span class="sc-ind-badge">ST: ${st}</span>
      </div>
    </div>
    <div class="signal-card-footer">
      <div class="scf-risk">Max loss: <strong>₹${sig.max_loss_per_trade?.toFixed(0) || '--'}</strong> · ${sig.position_size_lots} × ${sig.lot_size} units</div>
      <div class="scf-time">${timeStr}</div>
    </div>
  `;

  card.addEventListener('click', () => openSignalModal(sig));
  return card;
}

// ================================================================
// Signal Modal
// ================================================================

function openSignalModal(sig) {
  currentSignal = sig;
  document.getElementById('modal-title').textContent =
    `${sig.option_symbol} — ${sig.trade_type?.replace('_', ' ')}`;

  const isBuying = sig.trade_type === 'OPTIONS_BUYING';
  const indicators = sig.indicators || {};
  const validNotes = sig.validation_notes || [];

  const validationHtml = validNotes.map(note => {
    const cls = note.includes('✅') ? 'passed' : note.includes('❌') ? 'failed' : 'warning';
    return `<div class="condition-item ${cls}">${note}</div>`;
  }).join('');

  const entryCondHtml = (sig.entry_conditions || []).map(c =>
    `<div class="condition-item passed">${c}</div>`
  ).join('');

  const invalidHtml = (sig.invalidation_conditions || []).map(c =>
    `<div class="condition-item failed">${c}</div>`
  ).join('');

  document.getElementById('modal-body').innerHTML = `
    <div class="modal-signal-grid">
      <div>
        <div class="msg-section">
          <div class="msg-section-title">📋 Trade Details</div>
          <div class="msg-row"><span class="msg-label">Symbol</span><span class="msg-value blue">${sig.symbol}</span></div>
          <div class="msg-row"><span class="msg-label">Option</span><span class="msg-value">${sig.option_symbol}</span></div>
          <div class="msg-row"><span class="msg-label">Underlying</span><span class="msg-value">₹${sig.underlying_price?.toFixed(2)}</span></div>
          <div class="msg-row"><span class="msg-label">Strategy</span><span class="msg-value">${sig.trade_type?.replace('_', ' ')}</span></div>
          <div class="msg-row"><span class="msg-label">Direction</span><span class="msg-value">${sig.direction}</span></div>
          <div class="msg-row"><span class="msg-label">Expiry</span><span class="msg-value">${sig.expiry_date}</span></div>
          <div class="msg-row"><span class="msg-label">Signal Strength</span><span class="msg-value yellow">${sig.signal_strength}</span></div>
        </div>
        <div class="msg-section">
          <div class="msg-section-title">💰 Pricing & Live Broker LTP</div>
          <div class="msg-row" style="background:var(--bg-secondary);padding:6px 8px;border-radius:6px;align-items:center;">
            <span class="msg-label" style="font-weight:600;color:var(--text-primary)">⚡ Live Broker LTP:</span>
            <div style="display:flex;align-items:center;gap:4px;">
              <span style="font-size:12px;color:var(--text-muted)">₹</span>
              <input id="modal-live-ltp" type="number" step="0.05" value="${sig.entry_price?.toFixed(2)}"
                style="width:90px;padding:3px 6px;background:var(--bg-card);border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-family:var(--font-mono);font-weight:700;font-size:13px;"
                oninput="onModalLTPChange(this.value)" />
            </div>
          </div>
          <div class="msg-row"><span class="msg-label">Entry Range</span><span id="modal-entry-range" class="msg-value">₹${sig.entry_price_range?.[0]?.toFixed(2)} – ₹${sig.entry_price_range?.[1]?.toFixed(2)}</span></div>
          <div class="msg-row"><span class="msg-label">Stop Loss (-35%)</span><span id="modal-sl" class="msg-value red">₹${sig.stop_loss?.toFixed(2)} (-35%)</span></div>
          <div class="msg-row"><span class="msg-label">Target 1 (100% gain / 2x)</span><span id="modal-t1" class="msg-value green">₹${sig.target_1?.toFixed(2)}</span></div>
          <div class="msg-row"><span class="msg-label">Target 2 (200% gain / 3x)</span><span id="modal-t2" class="msg-value green">₹${sig.target_2?.toFixed(2)}</span></div>
          <div class="msg-row"><span class="msg-label">Risk/Reward</span><span id="modal-rr" class="msg-value green">${sig.risk_reward_ratio?.toFixed(1)}:1</span></div>
          <div class="msg-row"><span class="msg-label">Position Size</span><span id="modal-pos-size" class="msg-value">${sig.position_size_lots} lot(s) × ${sig.lot_size}</span></div>
          <div class="msg-row"><span class="msg-label">Max Loss (₹)</span><span id="modal-max-loss" class="msg-value red">₹${sig.max_loss_per_trade?.toFixed(0)}</span></div>
          <div class="msg-row"><span class="msg-label">Capital at Risk</span><span id="modal-cap-risk" class="msg-value yellow">${sig.capital_at_risk_pct?.toFixed(2)}%</span></div>
          <div class="msg-row"><span class="msg-label">Validity</span><span class="msg-value">${sig.validity_duration_minutes} minutes</span></div>
        </div>
      </div>
      <div>
        <div class="msg-section">
          <div class="msg-section-title">📊 Indicator Values</div>
          <div class="msg-row"><span class="msg-label">RSI (5m)</span><span class="msg-value">${indicators.rsi_5m?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">RSI (15m)</span><span class="msg-value">${indicators.rsi_15m?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">MACD Hist (5m)</span><span class="msg-value">${indicators.macd_hist_5m?.toFixed(4) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">MACD Hist (15m)</span><span class="msg-value">${indicators.macd_hist_15m?.toFixed(4) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">EMA 9 (5m)</span><span class="msg-value">₹${indicators.ema_9_5m?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">EMA 21 (5m)</span><span class="msg-value">₹${indicators.ema_21_5m?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">VWAP</span><span class="msg-value">₹${indicators.vwap?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">ATR (5m)</span><span class="msg-value">${indicators.atr_5m?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">Volume Ratio</span><span class="msg-value">${indicators.volume_ratio?.toFixed(2) || '--'}x</span></div>
          <div class="msg-row"><span class="msg-label">SuperTrend (5m)</span><span class="msg-value">${indicators.supertrend_5m || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">PCR</span><span class="msg-value">${indicators.pcr?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">IV Percentile</span><span class="msg-value">${indicators.iv_percentile?.toFixed(0) || '--'}%</span></div>
          <div class="msg-row"><span class="msg-label">Support</span><span class="msg-value green">₹${indicators.support_level?.toFixed(2) || '--'}</span></div>
          <div class="msg-row"><span class="msg-label">Resistance</span><span class="msg-value red">₹${indicators.resistance_level?.toFixed(2) || '--'}</span></div>
        </div>
      </div>
    </div>

    <div class="msg-section">
      <div class="msg-section-title">✅ Validation Checks</div>
      <div class="conditions-list">${validationHtml || '<div class="condition-item">No validation data</div>'}</div>
    </div>

    <div class="msg-section">
      <div class="msg-section-title">📌 Entry Conditions</div>
      <div class="conditions-list">${entryCondHtml || '<div class="condition-item">No entry conditions</div>'}</div>
    </div>

    <div class="msg-section">
      <div class="msg-section-title">🚫 Invalidation Conditions</div>
      <div class="conditions-list">${invalidHtml || '<div class="condition-item">No invalidation conditions</div>'}</div>
    </div>

    <div style="padding:10px 14px;background:var(--yellow-bg);border:1px solid rgba(255,209,102,0.2);border-radius:8px;font-size:12px;color:var(--yellow);margin-top:10px;">
      ⚠️ <strong>PAPER TRADING MODE</strong> — Clicking "Execute Paper Trade" will simulate the trade only. 
      No real money will be used. Always validate signals independently before real trading.
    </div>
  `;

  document.getElementById('signal-modal').classList.remove('hidden');
}

function onModalLTPChange(val) {
  const price = parseFloat(val);
  if (isNaN(price) || price <= 0 || !currentSignal) return;

  const isBuying = currentSignal.trade_type === 'OPTIONS_BUYING';
  currentSignal.entry_price = price;

  if (isBuying) {
    currentSignal.stop_loss = Math.round(price * 0.65 * 100) / 100; // -35%
    currentSignal.target_1 = Math.round(price * 2.0 * 100) / 100;   // 2x / +100%
    currentSignal.target_2 = Math.round(price * 3.0 * 100) / 100;   // 3x / +200%
  } else {
    currentSignal.stop_loss = Math.round(price * 2.0 * 100) / 100;  // 2x exit
    currentSignal.target_1 = Math.round(price * 0.50 * 100) / 100;  // 50% decay
    currentSignal.target_2 = Math.round(price * 0.30 * 100) / 100;  // 70% decay
  }

  currentSignal.entry_price_range_low = Math.round(price * 0.98 * 100) / 100;
  currentSignal.entry_price_range_high = Math.round(price * 1.05 * 100) / 100;

  // Recalculate position sizing based on 2% risk of ₹5,00,000 capital (₹10,000)
  const capital = 500000;
  const maxRisk = capital * 0.02; // ₹10,000
  const riskPerShare = Math.abs(price - currentSignal.stop_loss);
  const riskPerLot = riskPerShare * (currentSignal.lot_size || 15);
  const lots = Math.max(1, Math.floor(maxRisk / Math.max(riskPerLot, 1)));
  currentSignal.position_size_lots = lots;
  currentSignal.capital_at_risk = Math.round(lots * riskPerLot);
  currentSignal.capital_at_risk_pct = Math.round((currentSignal.capital_at_risk / capital) * 10000) / 100;
  currentSignal.max_loss_per_trade = currentSignal.capital_at_risk;

  // Update DOM elements
  const slEl = document.getElementById('modal-sl');
  const t1El = document.getElementById('modal-t1');
  const t2El = document.getElementById('modal-t2');
  const rangeEl = document.getElementById('modal-entry-range');
  const posEl = document.getElementById('modal-pos-size');
  const lossEl = document.getElementById('modal-max-loss');
  const capRiskEl = document.getElementById('modal-cap-risk');

  if (slEl) slEl.textContent = `₹${currentSignal.stop_loss.toFixed(2)} (${isBuying ? '-35%' : '+100%'})`;
  if (t1El) t1El.textContent = `₹${currentSignal.target_1.toFixed(2)}`;
  if (t2El) t2El.textContent = `₹${currentSignal.target_2.toFixed(2)}`;
  if (rangeEl) rangeEl.textContent = `₹${currentSignal.entry_price_range_low.toFixed(2)} – ₹${currentSignal.entry_price_range_high.toFixed(2)}`;
  if (posEl) posEl.textContent = `${lots} lot(s) × ${currentSignal.lot_size}`;
  if (lossEl) lossEl.textContent = `₹${currentSignal.max_loss_per_trade.toFixed(0)}`;
  if (capRiskEl) capRiskEl.textContent = `${currentSignal.capital_at_risk_pct.toFixed(2)}%`;
}

function closeModal() {
  document.getElementById('signal-modal').classList.add('hidden');
  currentSignal = null;
}

async function executeTrade() {
  if (!currentSignal) return;

  const btn = document.getElementById('btn-execute-trade');
  btn.disabled = true;
  btn.textContent = 'Executing...';

  try {
    const resp = await fetch(`${API_BASE}/api/paper-trade/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentSignal),
    });

    const data = await resp.json();
    if (data.success) {
      closeModal();
      await loadOpenTrades();
      await loadPortfolio();
      showSuccess(`Paper trade opened: ${data.trade?.option_symbol} @ ₹${data.trade?.entry_price}`);
    } else {
      showError(data.message || 'Trade not executed');
    }
  } catch (err) {
    showError(`Execute failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '📄 Execute Paper Trade';
  }
}

// ================================================================
// Market Data Grid
// ================================================================

function renderMarketData(marketData) {
  const grid = document.getElementById('market-grid');
  grid.innerHTML = '';

  Object.entries(marketData).forEach(([symbol, data]) => {
    if (!data || !data.spot_price) return;

    const indicators = data.indicators || {};
    const trend = indicators.trend_15m || 'SIDEWAYS';
    const trendClass = trend.includes('BULL') ? 'bull' : trend.includes('BEAR') ? 'bear' : 'sideways';
    const rsi = indicators.rsi_5m?.toFixed(1) || '--';
    const macd = indicators.macd_hist_5m ? indicators.macd_hist_5m.toFixed(3) : '--';
    const vwap = indicators.vwap?.toFixed(0) || '--';
    const volR = indicators.volume_ratio_5m?.toFixed(2) || '--';
    const pcr = data.options_chain_summary?.pcr?.toFixed(2) || '--';
    const ivPct = data.options_chain_summary?.iv_percentile?.toFixed(0) || '--';
    const price = data.spot_price?.toFixed(2) || '--';

    const card = document.createElement('div');
    card.className = 'market-card';
    card.innerHTML = `
      <div class="mc-symbol">${symbol}</div>
      <div class="mc-price">₹${price}</div>
      <div class="mc-indicators">
        <div class="mc-ind"><span class="mc-ind-label">RSI 5m</span><span class="mc-ind-value">${rsi}</span></div>
        <div class="mc-ind"><span class="mc-ind-label">MACD</span><span class="mc-ind-value">${macd}</span></div>
        <div class="mc-ind"><span class="mc-ind-label">VWAP</span><span class="mc-ind-value">₹${vwap}</span></div>
        <div class="mc-ind"><span class="mc-ind-label">Vol Ratio</span><span class="mc-ind-value">${volR}x</span></div>
        <div class="mc-ind"><span class="mc-ind-label">PCR</span><span class="mc-ind-value">${pcr}</span></div>
        <div class="mc-ind"><span class="mc-ind-label">IV %ile</span><span class="mc-ind-value">${ivPct}%</span></div>
      </div>
      <div class="mc-trend ${trendClass}">${trend}</div>
    `;
    grid.appendChild(card);
  });
}

// ================================================================
// Portfolio & Risk
// ================================================================

async function loadPortfolio() {
  try {
    const resp = await fetch(`${API_BASE}/api/portfolio`);
    const data = await resp.json();
    updatePortfolioUI(data);
  } catch (err) {
    console.error('Portfolio load error:', err);
  }
}

function updatePortfolioUI(data) {
  if (!data) return;

  // Header PnL
  const todayPnl = data.today_pnl || 0;
  const pnlEl = document.getElementById('header-pnl');
  pnlEl.textContent = formatINR(todayPnl);
  pnlEl.className = `pm-value ${todayPnl > 0 ? 'positive' : todayPnl < 0 ? 'negative' : 'neutral'}`;

  // Risk monitor
  const risk = data.risk_summary || {};
  document.getElementById('rm-capital').textContent = formatINR(data.capital || 500000);
  document.getElementById('rm-trades').textContent = `${risk.daily_trades_used || 0} / ${risk.daily_trades_max || 4}`;

  const dailyPnlEl = document.getElementById('rm-daily-pnl');
  dailyPnlEl.textContent = formatINR(risk.daily_pnl || 0);
  dailyPnlEl.className = `ri-value ${(risk.daily_pnl || 0) > 0 ? 'good' : (risk.daily_pnl || 0) < 0 ? 'danger' : 'neutral'}`;

  document.getElementById('rm-daily-limit').textContent = `-${risk.daily_loss_limit_pct || 3}%`;
  document.getElementById('rm-risk').textContent = `${(risk.total_capital_deployed_pct || 0).toFixed(1)}%`;
  document.getElementById('rm-open').textContent = data.open_trades || 0;

  // Risk bar
  const dailyLossPct = Math.min(100, Math.abs(Math.min(0, risk.daily_pnl || 0)) / (data.capital || 500000) * 100 / (risk.daily_loss_limit_pct || 3) * 100);
  const bar = document.getElementById('risk-bar-fill');
  bar.style.width = `${dailyLossPct}%`;
  bar.className = `risk-bar-fill ${dailyLossPct > 80 ? 'danger' : dailyLossPct > 50 ? 'warning' : ''}`;
  document.getElementById('risk-bar-pct').textContent = `${dailyLossPct.toFixed(0)}%`;

  // Portfolio stats
  const totalPnlEl = document.getElementById('port-total-pnl');
  totalPnlEl.textContent = formatINR(data.total_pnl || 0);
  totalPnlEl.className = `ps-value ${(data.total_pnl || 0) > 0 ? 'positive' : (data.total_pnl || 0) < 0 ? 'negative' : 'neutral'}`;

  const unrealEl = document.getElementById('port-unrealized');
  unrealEl.textContent = formatINR(data.unrealized_pnl || 0);
  unrealEl.className = `ps-value ${(data.unrealized_pnl || 0) > 0 ? 'positive' : (data.unrealized_pnl || 0) < 0 ? 'negative' : 'neutral'}`;

  document.getElementById('port-winrate').textContent = `${data.win_rate_pct || 0}%`;
  document.getElementById('port-total-trades').textContent = data.closed_trades_total || 0;
}

// ================================================================
// Open Trades
// ================================================================

async function loadOpenTrades() {
  try {
    const resp = await fetch(`${API_BASE}/api/trades/open`);
    const data = await resp.json();
    renderOpenTrades(data.trades || []);
  } catch (err) {
    console.error('Open trades error:', err);
  }
}

function renderOpenTrades(trades) {
  const container = document.getElementById('open-trades-container');
  if (trades.length === 0) {
    container.innerHTML = '<div class="empty-state">No open paper trades</div>';
    return;
  }

  container.innerHTML = `
    <table class="trades-table">
      <thead>
        <tr>
          <th>Trade ID</th>
          <th>Option</th>
          <th>Entry</th>
          <th>Current</th>
          <th>SL</th>
          <th>Target</th>
          <th>Qty</th>
          <th>Unrealized P&L</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${trades.map(t => `
          <tr>
            <td class="mono">${t.trade_id}</td>
            <td class="mono" style="color:var(--accent)">${t.option_symbol}</td>
            <td class="mono">₹${t.entry_price?.toFixed(2)}</td>
            <td class="mono">₹${t.current_price?.toFixed(2) || '--'}</td>
            <td class="mono" style="color:var(--red)">₹${t.stop_loss?.toFixed(2)}</td>
            <td class="mono" style="color:var(--green)">₹${t.target_1?.toFixed(2)}</td>
            <td class="mono">${t.quantity} lots</td>
            <td class="mono ${(t.unrealized_pnl || 0) >= 0 ? 'pnl-pos' : 'pnl-neg'}">
              ₹${(t.unrealized_pnl || 0).toFixed(2)}
            </td>
            <td>
              <button class="close-trade-btn" onclick="closeTradeManual('${t.trade_id}', ${t.current_price || t.entry_price})">
                Close
              </button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function closeTradeManual(tradeId, currentPrice) {
  const price = parseFloat(prompt(`Exit price for trade ${tradeId} (current: ₹${currentPrice}):`, currentPrice));
  if (isNaN(price)) return;

  try {
    const resp = await fetch(`${API_BASE}/api/paper-trade/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_id: tradeId, exit_price: price, reason: 'MANUAL CLOSE' }),
    });
    const data = await resp.json();
    if (data.success) {
      showSuccess(`Trade closed. P&L: ₹${data.realized_pnl?.toFixed(2)}`);
      await loadOpenTrades();
      await loadPortfolio();
    }
  } catch (err) {
    showError(`Close failed: ${err.message}`);
  }
}

// ================================================================
// Trade History
// ================================================================

async function loadTradeHistory() {
  try {
    const resp = await fetch(`${API_BASE}/api/trades/history?limit=50`);
    const data = await resp.json();
    renderTradeHistory(data);
  } catch (err) {
    console.error('History error:', err);
  }
}

function renderTradeHistory(data) {
  const container = document.getElementById('trade-history-container');
  const trades = data.trades || [];

  if (trades.length === 0) {
    container.innerHTML = '<div class="empty-state">No trade history</div>';
    return;
  }

  container.innerHTML = `
    <div style="display:flex;gap:20px;margin-bottom:12px;font-size:13px;color:var(--text-secondary)">
      <span>Total: <strong>${data.total_trades}</strong></span>
      <span>Wins: <strong style="color:var(--green)">${data.wins}</strong></span>
      <span>Losses: <strong style="color:var(--red)">${data.losses}</strong></span>
      <span>Win Rate: <strong>${data.win_rate_pct}%</strong></span>
      <span>Total P&L: <strong class="${(data.total_pnl || 0) >= 0 ? 'positive' : 'negative'}">₹${data.total_pnl?.toFixed(2)}</strong></span>
    </div>
    <table class="trades-table">
      <thead>
        <tr>
          <th>Exit Time</th>
          <th>Option</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>Qty</th>
          <th>P&L</th>
          <th>P&L %</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        ${trades.map(t => `
          <tr>
            <td class="mono" style="font-size:11px">${t.exit_time ? new Date(t.exit_time).toLocaleTimeString('en-IN', {timeZone:'Asia/Kolkata'}) : '--'}</td>
            <td class="mono" style="color:var(--accent)">${t.option_symbol}</td>
            <td class="mono">₹${t.entry_price?.toFixed(2)}</td>
            <td class="mono">₹${t.exit_price?.toFixed(2) || '--'}</td>
            <td class="mono">${t.quantity}</td>
            <td class="mono ${(t.pnl || 0) >= 0 ? 'pnl-pos' : 'pnl-neg'}">₹${(t.pnl || 0).toFixed(2)}</td>
            <td class="mono ${(t.pnl_pct || 0) >= 0 ? 'pnl-pos' : 'pnl-neg'}">${(t.pnl_pct || 0).toFixed(1)}%</td>
            <td style="font-size:11px;color:var(--text-muted)">${t.exit_reason || '--'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// ================================================================
// Notifications
// ================================================================

function showSuccess(msg) {
  showToast(msg, 'success');
}
function showError(msg) {
  showToast(msg, 'error');
}

function showToast(msg, type = 'info') {
  const toast = document.createElement('div');
  const bg = type === 'success' ? 'var(--green)' : type === 'error' ? 'var(--red)' : 'var(--accent)';
  toast.style.cssText = `
    position:fixed; bottom:20px; right:20px; z-index:9999;
    background:${bg}; color:#000; padding:12px 20px;
    border-radius:10px; font-size:13px; font-weight:600;
    box-shadow:0 4px 20px rgba(0,0,0,0.5);
    animation: slideIn 0.3s ease;
    max-width: 400px;
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ================================================================
// Utilities
// ================================================================

function formatINR(amount) {
  if (Math.abs(amount) >= 100000) return `₹${(amount / 100000).toFixed(2)}L`;
  if (Math.abs(amount) >= 1000) return `₹${(amount / 1000).toFixed(1)}K`;
  return `₹${amount.toFixed(2)}`;
}

// ================================================================
// Groww Broker Connection
// ================================================================

function openGrowwModal() {
  document.getElementById('groww-modal').classList.remove('hidden');
}

function closeGrowwModal() {
  document.getElementById('groww-modal').classList.add('hidden');
}

async function checkGrowwStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/groww/status`);
    const data = await resp.json();
    const badge = document.getElementById('groww-status-badge');
    if (badge) {
      if (data.is_connected) {
        const balStr = data.fno_balance ? ` | Bal: ₹${data.fno_balance.toFixed(0)}` : '';
        badge.innerHTML = `🟢 GROWW LIVE (${data.ucc || 'CONNECTED'}${balStr})`;
        badge.style.background = 'rgba(0,210,144,0.2)';
        badge.style.color = '#00d290';
        badge.style.borderColor = '#00d290';
      } else {
        badge.innerHTML = '🔌 Connect Groww API';
        badge.style.background = 'rgba(0,210,144,0.1)';
        badge.style.color = '#00d290';
      }
    }
  } catch (err) {
    console.error('Groww status check failed:', err);
  }
}

async function saveGrowwCredentials() {
  const apiKey = document.getElementById('groww-api-key').value.trim();
  const apiSecret = document.getElementById('groww-api-secret').value.trim();
  const msgEl = document.getElementById('groww-connect-msg');
  const btn = document.getElementById('btn-save-groww');

  if (!apiKey) {
    msgEl.style.display = 'block';
    msgEl.style.background = 'rgba(255,77,109,0.15)';
    msgEl.style.color = 'var(--red)';
    msgEl.textContent = 'Please enter your Groww API Key';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Connecting...';
  msgEl.style.display = 'none';

  try {
    const resp = await fetch(`${API_BASE}/api/groww/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey, api_secret: apiSecret, totp_secret: apiSecret }),
    });

    const data = await resp.json();
    msgEl.style.display = 'block';
    if (data.success) {
      msgEl.style.background = 'rgba(0,200,150,0.15)';
      msgEl.style.color = 'var(--green)';
      msgEl.textContent = '✅ Connected to Groww Trading API!';
      showSuccess('Groww API connected! Streaming live exchange prices.');
      await checkGrowwStatus();
      setTimeout(closeGrowwModal, 1500);
    } else {
      msgEl.style.background = 'rgba(255,77,109,0.15)';
      msgEl.style.color = 'var(--red)';
      msgEl.textContent = `❌ ${data.message || 'Connection failed. Check credentials.'}`;
    }
  } catch (err) {
    msgEl.style.display = 'block';
    msgEl.style.background = 'rgba(255,77,109,0.15)';
    msgEl.style.color = 'var(--red)';
    msgEl.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save & Connect';
  }
}

// ================================================================
// Upstox API v2 Live Feed Connection
// ================================================================

function openUpstoxModal() {
  document.getElementById('upstox-modal').classList.remove('hidden');
}

function closeUpstoxModal() {
  document.getElementById('upstox-modal').classList.add('hidden');
}

async function checkUpstoxStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/upstox/status`);
    const data = await resp.json();
    const badge = document.getElementById('upstox-status-badge');
    if (badge) {
      if (data.is_connected) {
        badge.innerHTML = `🟢 UPSTOX LIVE`;
        badge.style.background = 'rgba(88,101,242,0.25)';
        badge.style.color = '#7289da';
        badge.style.borderColor = '#7289da';
        badge.title = 'Upstox v2 API Active — Streaming 100% Real Live Market Quotes';
      } else {
        badge.innerHTML = '⚡ Connect Upstox API';
        badge.style.background = 'rgba(88,101,242,0.15)';
        badge.style.color = '#7289da';
        badge.style.borderColor = 'rgba(88,101,242,0.3)';
        badge.title = 'Click to connect Upstox for live market quotes';
      }
    }
  } catch (err) {
    console.error('Upstox status check failed:', err);
  }
}

async function saveUpstoxCredentials() {
  const token = document.getElementById('upstox-access-token').value.trim();
  const msgEl = document.getElementById('upstox-connect-msg');
  const btn = document.getElementById('btn-save-upstox');

  if (!token) {
    msgEl.style.display = 'block';
    msgEl.style.background = 'rgba(255,77,109,0.15)';
    msgEl.style.color = 'var(--red)';
    msgEl.textContent = 'Please enter your Upstox Access Token';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Connecting to Upstox...';
  msgEl.style.display = 'none';

  try {
    const resp = await fetch(`${API_BASE}/api/upstox/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: token }),
    });

    const data = await resp.json();
    msgEl.style.display = 'block';
    if (data.success) {
      msgEl.style.background = 'rgba(0,200,150,0.15)';
      msgEl.style.color = 'var(--green)';
      msgEl.textContent = '✅ Connected to Upstox API v2 successfully!';
      showSuccess('Upstox API connected! Real live market quotes and option chains active.');
      await checkUpstoxStatus();
      setTimeout(closeUpstoxModal, 1500);
      runScan();
    } else {
      msgEl.style.background = 'rgba(255,77,109,0.15)';
      msgEl.style.color = 'var(--red)';
      msgEl.textContent = `❌ ${data.message || 'Connection failed. Verify your access token.'}`;
    }
  } catch (err) {
    msgEl.style.display = 'block';
    msgEl.style.background = 'rgba(255,77,109,0.15)';
    msgEl.style.color = 'var(--red)';
    msgEl.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save & Connect Upstox';
  }
}

// ================================================================
// Init
// ================================================================

document.addEventListener('DOMContentLoaded', () => {
  updateClock();
  setInterval(updateClock, 1000);
  loadPortfolio();
  checkUpstoxStatus();
  checkGrowwStatus();
  setupAutoRefresh();

  // Keyboard shortcut: Ctrl+S to scan
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      runScan();
    }
    if (e.key === 'Escape') {
      closeModal();
      closeGrowwModal();
      closeUpstoxModal();
    }
  });
});
