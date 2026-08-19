// Global state
let currentSymbol = null;
let currentPeriod = "1y";
let historyChartInstance = null;
let isValuesMasked = true;
let hiddenColumns = new Set([2, 3, 4, 5, 6, 8, 9]); // Default hide Investment, Current Value, and Tag columns

// Auth state
let authToken = localStorage.getItem("auth_token");

// Intercept fetch to add token and handle 401
const originalFetch = window.fetch;
window.fetch = async function (...args) {
    let [resource, config] = args;

    // If resource is a Request object, we need to clone it or modify its headers
    if (resource instanceof Request) {
        if (authToken && !resource.headers.has('Authorization')) {
            resource.headers.set('Authorization', `Bearer ${authToken}`);
        }
        const response = await originalFetch(resource, config);
        if (response.status === 401) handleLogout();
        return response;
    }

    // Normal string URL
    if (!config) config = {};
    if (!config.headers) config.headers = {};

    if (config.headers instanceof Headers) {
        if (authToken && !config.headers.has('Authorization')) {
            config.headers.append('Authorization', `Bearer ${authToken}`);
        }
    } else {
        if (authToken && !config.headers['Authorization']) {
            config.headers['Authorization'] = `Bearer ${authToken}`;
        }
    }

    const response = await originalFetch(resource, config);
    if (response.status === 401) {
        handleLogout();
    }
    return response;
};

// Initialize when DOM is fully loaded
document.addEventListener("DOMContentLoaded", () => {
    initAuth();
    if (authToken) {
        document.getElementById("main-app").style.display = "block";
        document.getElementById("auth-container").classList.add("hidden");
        initApp();
    } else {
        document.getElementById("main-app").style.display = "none";
        document.getElementById("auth-container").classList.remove("hidden");
    }
});

let _appInitialized = false;

function initApp() {
    if (_appInitialized) {
        fetchAndRenderStocks();
        return;
    }
    _appInitialized = true;

    initNavigation();
    initStocks();
    initForms();
    initUpload();
    initDetails();
    initMaskToggle();
    initColumnVisibility();
    initValidate();
}

function initMaskToggle() {
    const icon = document.getElementById("toggle-mask-icon");
    if (icon) {
        icon.addEventListener("click", () => {
            isValuesMasked = !isValuesMasked;
            icon.className = isValuesMasked ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";

            if (_currentStocksData && _currentStocksData.length > 0) {
                updateSummaryHeader(_currentStocksData);
            } else {
                document.getElementById("total-investment").textContent = isValuesMasked ? "₹******" : "₹0.00";
                document.getElementById("total-current-value").textContent = isValuesMasked ? "₹******" : "₹0.00";
            }
        });
    }
}

function initColumnVisibility() {
    const btn = document.getElementById("btn-view-options");
    const dropdown = document.getElementById("column-dropdown");
    const list = document.getElementById("column-toggles-list");

    if (!btn || !dropdown || !list) return;

    list.innerHTML = ""; // Clear list to prevent duplicates on re-initialization

    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
        if (!dropdown.contains(e.target) && !btn.contains(e.target)) {
            dropdown.classList.add("hidden");
        }
    });

    const headers = document.querySelectorAll("#stock-list-table th");
    headers.forEach((th, index) => {
        if (index === 0 || index === 1 || index === 10 || index === 11) return;

        let label = th.textContent.replace("SMA Status (20/50/100/200)", "SMA Status").trim();

        const div = document.createElement("div");
        div.style.display = "flex";
        div.style.alignItems = "center";
        div.style.gap = "8px";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = !hiddenColumns.has(index);
        checkbox.dataset.colIndex = index;
        checkbox.style.cursor = "pointer";

        const span = document.createElement("label");
        span.textContent = label;
        span.style.cursor = "pointer";
        span.addEventListener("click", () => checkbox.click());

        checkbox.addEventListener("change", (e) => {
            if (e.target.checked) {
                hiddenColumns.delete(index);
            } else {
                hiddenColumns.add(index);
            }
            applyColumnVisibility();
        });

        div.appendChild(checkbox);
        div.appendChild(span);
        list.appendChild(div);
    });
}

function applyColumnVisibility() {
    const table = document.getElementById("stock-list-table");
    if (!table) return;

    const headers = table.querySelectorAll("thead tr th");
    headers.forEach((th, index) => {
        if (hiddenColumns.has(index)) {
            th.style.display = "none";
        } else {
            th.style.display = "";
        }
    });

    const rows = table.querySelectorAll("tbody tr");
    rows.forEach(row => {
        const cells = row.children;
        if (cells.length === 1 && cells[0].hasAttribute("colspan")) return;

        for (let i = 0; i < cells.length; i++) {
            if (hiddenColumns.has(i)) {
                cells[i].style.display = "none";
            } else {
                cells[i].style.display = "";
            }
        }
    });
}

/* Toast Notification Utility */
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;

    let iconClass = "fa-circle-info";
    if (type === "success") iconClass = "fa-circle-check";
    if (type === "error") iconClass = "fa-triangle-exclamation";

    toast.innerHTML = `
        <i class="fa-solid ${iconClass}"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);

    // Automatically remove toast after 4 seconds
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(10px) scale(0.95)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

/* 1. Tab Navigation System */
function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const views = document.querySelectorAll(".app-view");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetId = item.getAttribute("data-target");
            switchView(targetId);
        });
    });
}

function switchView(viewId) {
    // Update active nav button
    const navItems = document.querySelectorAll(".nav-item");
    navItems.forEach(btn => {
        if (btn.getAttribute("data-target") === viewId) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });

    // Update visible view
    const views = document.querySelectorAll(".app-view");
    views.forEach(view => {
        if (view.id === viewId) {
            view.classList.add("active");
        } else {
            view.classList.remove("active");
        }
    });

    // Auto-reload stock table when returning to dashboard
    if (viewId === "dashboard-view") {
        fetchAndRenderStocks();
    } else if (viewId === "trends-view") {
        fetchAndRenderTrends();
    }
}

/* 2. Portfolio Calculations and Dashboard Loading */
let _currentStocksData = [];
let _currentSortColumn = null;
let _currentSortDirection = "asc";

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

function initStocks() {
    fetchAndRenderStocks();

    // ── Table Sorting ───────────────────────────────────────────────────────
    // Wire up ALL sortable headers (including dual-sort ones).
    document.querySelectorAll("th.sortable").forEach(th => {
        th.addEventListener("click", (e) => {
            // If the click landed on the ₹/% pill, let that handler run instead.
            if (e.target.closest(".sort-mode-pill")) return;

            const column = th.dataset.sort; // always the currently-active field
            if (_currentSortColumn === column) {
                _currentSortDirection = _currentSortDirection === "asc" ? "desc" : "asc";
            } else {
                _currentSortColumn = column;
                _currentSortDirection = "asc";
            }
            applyCurrentSortAndRender();
        });
    });

    // ── Dual-sort ₹/% pill toggles ─────────────────────────────────────────
    document.querySelectorAll(".dual-sort-th").forEach(th => {
        const pill = th.querySelector(".sort-mode-pill");
        if (!pill) return;

        pill.addEventListener("click", (e) => {
            e.stopPropagation(); // don't fire the th click handler

            const isAbsNow = pill.dataset.mode === "abs";
            const newMode = isAbsNow ? "pct" : "abs";
            const newField = isAbsNow ? th.dataset.sortPct : th.dataset.sortAbs;

            // Flip pill appearance
            pill.dataset.mode = newMode;
            pill.textContent = newMode === "abs" ? "₹" : "%";
            pill.classList.toggle("pill-pct", newMode === "pct");

            // Update the header's active sort field
            th.dataset.sort = newField;

            // If this column is currently sorted, re-sort with the new field
            if (_currentSortColumn === (isAbsNow ? th.dataset.sortAbs : th.dataset.sortPct) ||
                _currentSortColumn === newField) {
                _currentSortColumn = newField;
                applyCurrentSortAndRender();
            }
        });
    });


    // Search Bar
    const searchInput = document.getElementById("stock-search");
    if (searchInput) {
        searchInput.addEventListener("input", debounce(applyCurrentSortAndRender, 300));
    }

    // Auto-refresh countdown
    initAutoRefresh();
}

// ── Auto-refresh timer ──────────────────────────────────────────────────────
const AUTO_REFRESH_SECS = 60;
let   _arInterval       = null;
let   _arRemaining      = AUTO_REFRESH_SECS;

function initAutoRefresh() {
    const btn = document.getElementById('refresh-stocks');
    if (!btn) return;

    // Manual click — refresh immediately and reset the countdown
    btn.addEventListener('click', () => {
        fetchAndRenderStocks();
        showToast('Refreshing live market data...', 'info');
        resetAutoRefresh();
    });

    startAutoRefresh();
}

function startAutoRefresh() {
    _arRemaining = AUTO_REFRESH_SECS;
    updateArUI(_arRemaining);

    if (_arInterval) clearInterval(_arInterval);

    _arInterval = setInterval(() => {
        _arRemaining -= 1;
        updateArUI(_arRemaining);

        if (_arRemaining <= 0) {
            // Time's up — fetch and restart
            fetchAndRenderStocks();
            _arRemaining = AUTO_REFRESH_SECS;
            updateArUI(_arRemaining);
        }
    }, 1000);
}

function resetAutoRefresh() {
    _arRemaining = AUTO_REFRESH_SECS;
    updateArUI(_arRemaining);
    if (_arInterval) clearInterval(_arInterval);
    _arInterval = setInterval(() => {
        _arRemaining -= 1;
        updateArUI(_arRemaining);
        if (_arRemaining <= 0) {
            fetchAndRenderStocks();
            _arRemaining = AUTO_REFRESH_SECS;
            updateArUI(_arRemaining);
        }
    }, 1000);
}

function updateArUI(secs) {
    // Countdown label
    const label = document.getElementById('ar-countdown');
    if (label) label.textContent = secs;

    // SVG ring: stroke-dashoffset drives the arc.
    // dasharray=100 means 100 units = full circle.
    // offset 0 = full ring, offset 100 = empty ring.
    const arc = document.getElementById('ar-ring-arc');
    if (!arc) return;

    const pct    = secs / AUTO_REFRESH_SECS;       // 1.0 → 0.0
    const offset = (1 - pct) * 100;                 // 0 → 100
    arc.style.strokeDashoffset = offset.toFixed(2);

    // Colour shifts: green → amber → red as time runs out
    let colour;
    if (pct > 0.5)      colour = 'var(--success)';
    else if (pct > 0.2) colour = 'var(--warning)';
    else                colour = 'var(--danger)';
    arc.style.stroke = colour;

    // Also colour the label
    if (label) label.style.color = colour;
}

async function fetchAndRenderStocks() {
    const tableBody = document.getElementById("stock-table-body");

    try {
        const response = await fetch("/api/stocks");
        if (!response.ok) throw new Error("Could not retrieve stocks data.");

        const stocks = await response.json();
        _currentStocksData = stocks;
        applyCurrentSortAndRender();
        updateSummaryHeader(stocks);
        await fetchMarketIndex();

        // Save the snapshot in the background
        saveDailySnapshot();
    } catch (error) {
        console.error(error);
        tableBody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center loss-val">
                    <i class="fa-solid fa-triangle-exclamation"></i> Error loading portfolio data. Make sure backend is running.
                </td>
            </tr>
        `;
        showToast("Error loading portfolio: " + error.message, "error");
    }
}

function applyCurrentSortAndRender() {
    let data = [..._currentStocksData];

    // Search filtering
    const searchInput = document.getElementById("stock-search");
    if (searchInput && searchInput.value) {
        const query = searchInput.value.toLowerCase().trim();
        data = data.filter(s => {
            const name = (s.company_name || "").toLowerCase();
            const code = (s.stock_code || "").toLowerCase();
            const tag = (s.tag || "").toLowerCase();
            return name.includes(query) || code.includes(query) || tag.includes(query);
        });
    }

    if (_currentSortColumn) {
        data.sort((a, b) => {
            let valA = a[_currentSortColumn];
            let valB = b[_currentSortColumn];

            // If missing fields, fallbacks
            if (valA === undefined || valA === null) valA = "";
            if (valB === undefined || valB === null) valB = "";

            if (typeof valA === "string") valA = valA.toLowerCase();
            if (typeof valB === "string") valB = valB.toLowerCase();

            if (valA < valB) return _currentSortDirection === "asc" ? -1 : 1;
            if (valA > valB) return _currentSortDirection === "asc" ? 1 : -1;
            return 0;
        });
    }
    renderStocksTable(data);
    updateSortIcons();
}

function updateSortIcons() {
    document.querySelectorAll("th.sortable").forEach(th => {
        const icon = th.querySelector("i");
        if (th.dataset.sort === _currentSortColumn) {
            icon.className = _currentSortDirection === "asc" ? "fa-solid fa-sort-up" : "fa-solid fa-sort-down";
            th.classList.add("active-sort");
        } else {
            icon.className = "fa-solid fa-sort";
            th.classList.remove("active-sort");
        }
    });
}

function renderStocksTable(stocks) {
    const tableBody = document.getElementById("stock-table-body");

    if (stocks.length === 0) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center text-muted" style="padding: 3rem 0;">
                    <i class="fa-solid fa-folder-open" style="font-size: 2.5rem; display: block; margin-bottom: 0.75rem; opacity: 0.5;"></i>
                    Your portfolio is empty. Add a stock or upload an Excel sheet to begin!
                </td>
            </tr>
        `;
        return;
    }

    tableBody.innerHTML = "";

    // Compute total portfolio investment and current value for weight % calculation
    const totalPortfolioInvested = stocks.reduce((sum, s) => sum + (s.buying_price * s.quantity), 0);
    const totalPortfolioCurrentValue = stocks.reduce((sum, s) => sum + (s.current_value != null ? s.current_value : s.buying_price * s.quantity), 0);

    stocks.forEach((stock, index) => {
        const row = document.createElement("tr");
        row.setAttribute("data-symbol", stock.symbol);

        // Formatted cells
        const buyPrice = stock.buying_price;
        const qty = stock.quantity;
        const currentPrice = stock.current_price;

        const isError = stock.status === "error";

        let currentPriceText = "—";
        let currentValText = "—";
        let gainLossText = "—";
        let gainLossPctText = "";
        let gainLossClass = "";
        let todayReturnText = "—";
        let todayReturnPctText = "";
        let todayReturnClass = "";

        if (!isError && currentPrice !== null) {
            currentPriceText = `₹${currentPrice.toFixed(2)}`;
            currentValText = `₹${stock.current_value.toFixed(2)}`;

            const gl = stock.gain_loss;
            const glPct = stock.gain_loss_pct;
            gainLossClass = gl >= 0 ? "gain-val" : "loss-val";
            const sign = gl >= 0 ? "+" : "";

            gainLossText = `${sign}₹${gl.toFixed(2)}`;
            gainLossPctText = `(${sign}${glPct.toFixed(2)}%)`;

            const tr = stock.today_return_val;
            const trPct = stock.today_change_pct;
            if (tr !== null && tr !== undefined) {
                todayReturnClass = tr >= 0 ? "gain-val" : "loss-val";
                const trSign = tr >= 0 ? "+" : "";
                todayReturnText = `${trSign}₹${tr.toFixed(2)}`;
                todayReturnPctText = `(${trSign}${trPct.toFixed(2)}%)`;
            }
        } else if (isError) {
            currentPriceText = `<span class="loss-val" title="${stock.error}"><i class="fa-solid fa-circle-exclamation"></i> Failed</span>`;
        }

        const investAmt = buyPrice * qty;
        const investValText = `₹${investAmt.toFixed(2)}`;
        const weightPct = totalPortfolioInvested > 0 ? (investAmt / totalPortfolioInvested * 100).toFixed(1) : '0.0';

        // SMA status badges
        let smaBadges = "";
        const smaIndicators = [
            { name: "20", val: stock.sma20 },
            { name: "50", val: stock.sma50 },
            { name: "100", val: stock.sma100 },
            { name: "200", val: stock.sma200 }
        ];

        if (isError || currentPrice === null) {
            smaBadges = `<span class="tag na">N/A</span>`;
        } else {
            smaIndicators.forEach(sma => {
                if (sma.val === null) {
                    smaBadges += `<span class="tag na">${sma.name} SMA</span> `;
                } else {
                    const diff = currentPrice - sma.val;
                    const statusClass = diff >= 0 ? "above" : "below";
                    const titleStr = `${sma.name} SMA: ₹${sma.val.toFixed(2)}`;
                    smaBadges += `<span class="tag ${statusClass}" title="${titleStr}">${sma.name} SMA</span> `;
                }
            });
        }

        const baseSymbol = stock.symbol.replace('.NS', '').replace('.BO', '');
        const tvExchange = stock.symbol.endsWith(".BO") ? "BSE" : "NSE";
        const tvUrl = `https://in.tradingview.com/chart/?symbol=${tvExchange}%3A${baseSymbol}`;
        const screenerUrl = `https://www.screener.in/company/${baseSymbol}/`;
        const mastertrackerUrl = `https://mastertracker.financiallyfree.in/val/${baseSymbol}`;

        const displayTitle = stock.company_name || stock.symbol;
        row.innerHTML = `
            <td class="text-center seq-num">${index + 1}</td>
            <td>
                <div class="ticker-cell">
                    <div class="symbol-title-row">
                        <div class="editable-cell symbol-editable" data-field="symbol" data-symbol="${stock.symbol}" data-stock-code="${stock.stock_code}" data-exchange="${stock.exchange}" data-company-name="${stock.company_name || stock.stock_code}" data-tag="${stock.tag || ''}" data-row-color="${stock.row_color || ''}" title="Click to edit details">
                            <span class="symbol-text editable-display">${displayTitle}</span>
                            <i class="fa-solid fa-pen-to-square edit-pencil"></i>
                        </div>
                        <div class="stock-icons">
                            <a href="${tvUrl}" target="_blank" class="external-link" title="TradingView">
                                <img src="https://in.tradingview.com/favicon.ico" alt="TV" class="external-icon">
                            </a>
                            <a href="${screenerUrl}" target="_blank" class="external-link" title="Screener">
                                <img src="https://www.screener.in/favicon.ico" alt="Scr" class="external-icon">
                            </a>
                            <a href="${mastertrackerUrl}" target="_blank" class="external-link" title="Master Tracker">
                                <img src="https://images.moneycontrol.com/images/favicon-1/favicon.ico" alt="MT" class="external-icon">
                            </a>
                        </div>
                    </div>
                    <span class="exchange-text">${stock.exchange === "BSE" ? "BSE India" : stock.exchange === "NSE" ? "NSE India" : stock.exchange}</span>
                </div>
            </td>
            <td class="text-right font-bold editable-cell" data-field="quantity" data-symbol="${stock.symbol}" data-value="${qty}" title="Click to edit quantity">
                <span class="editable-display">${qty}</span>
                <i class="fa-solid fa-pen-to-square edit-pencil"></i>
            </td>
            <td class="text-right editable-cell" data-field="price" data-symbol="${stock.symbol}" data-value="${buyPrice.toFixed(4)}" title="Click to edit buy price">
                <span class="editable-display">₹${buyPrice.toFixed(2)}</span>
                <i class="fa-solid fa-pen-to-square edit-pencil"></i>
            </td>
            <td class="text-right">${currentPriceText}</td>
            <td class="text-right">
                <div>${investValText}</div>
                <div style="font-size: 0.78rem; margin-top: 0.15rem; color: var(--text-muted);">(${weightPct}% of portfolio)</div>
            </td>
            <td class="text-right ${gainLossClass}">
                <div>${currentValText}</div>
                <div style="font-size: 0.78rem; margin-top: 0.15rem; color: var(--text-muted);">${(!isError && stock.current_value != null && totalPortfolioCurrentValue > 0) ? '(' + (stock.current_value / totalPortfolioCurrentValue * 100).toFixed(1) + '% of portfolio)' : ''}</div>
            </td>
            <td class="text-right ${todayReturnClass}">
                <div>${todayReturnText}</div>
                <div style="font-size: 0.78rem; margin-top: 0.15rem;">${todayReturnPctText}</div>
            </td>
            <td class="text-right ${gainLossClass}">
                <div>${gainLossText}</div>
                <div style="font-size: 0.78rem; margin-top: 0.15rem;">${gainLossPctText}</div>
            </td>
            <td class="text-center">
                ${stock.tag ? `<span class="tag-pill">${stock.tag}</span>` : `<span class="text-muted" style="opacity: 0.5;">-</span>`}
            </td>
            <td class="text-center">
                <div class="indicator-tags">${smaBadges}</div>
            </td>
            <td class="text-center" style="cursor: default;">
                <button class="btn btn-danger btn-delete-stock" data-symbol="${stock.symbol}">
                    <i class="fa-solid fa-trash"></i> Delete
                </button>
            </td>
        `;

        // Apply row highlight color if set
        if (stock.row_color) {
            row.style.background = `${stock.row_color}22`;
            row.style.borderLeft = `3px solid ${stock.row_color}`;
        }

        // Row redirection to detail panel
        row.addEventListener("click", (e) => {
            // Prevent navigating if user clicked the delete button or an editable cell
            if (e.target.closest(".btn-delete-stock") || e.target.closest(".editable-cell") || e.target.closest(".external-link")) {
                return;
            }
            openStockDetails(stock.symbol);
        });

        // Wire up inline editing so clicking anywhere in the cell triggers it
        row.querySelectorAll("td").forEach(td => {
            const cell = td.classList.contains("editable-cell") ? td : td.querySelector(".editable-cell");
            if (cell) {
                td.addEventListener("click", (e) => {
                    if (e.target.closest("a") || e.target.closest("button")) return;
                    e.stopPropagation();
                    activateInlineEdit(cell);
                });
            }
        });

        tableBody.appendChild(row);
    });

    // Register delete event handlers
    const deleteBtns = tableBody.querySelectorAll(".btn-delete-stock");
    deleteBtns.forEach(btn => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const symbol = btn.getAttribute("data-symbol");
            if (confirm(`Are you sure you want to remove '${symbol}' from your portfolio?`)) {
                await deleteStockHolding(symbol);
            }
        });
    });

    applyColumnVisibility();
}

// ==========================================
// MODAL LOGIC FOR EDITING STOCK DETAILS
// ==========================================
function openEditStockModal(cell) {
    // Extract data from cell
    const symbol = cell.dataset.symbol;
    const stockCode = cell.dataset.stockCode;
    const exchange = cell.dataset.exchange;
    const companyName = cell.dataset.companyName;
    const tag = cell.dataset.tag;
    const rowColor = cell.dataset.rowColor || '';

    // Fill Modal Form
    document.getElementById("edit-original-symbol").value = symbol;
    document.getElementById("edit-company-name").value = companyName || "";
    document.getElementById("edit-stock-code").value = stockCode || "";
    document.getElementById("edit-stock-tag").value = tag || "";
    document.getElementById("edit-row-color").value = rowColor;

    // Reflect swatch selection
    applySwatchSelection(rowColor);

    const exSelect = document.getElementById("edit-exchange");
    if (exchange === "BSE") exSelect.value = "BSE";
    else exSelect.value = "NSE";

    // Show Modal
    document.getElementById("edit-stock-modal").classList.remove("hidden");
}

function closeEditStockModal() {
    document.getElementById("edit-stock-modal").classList.add("hidden");
    document.getElementById("edit-stock-form").reset();
}

document.getElementById("btn-close-edit-modal")?.addEventListener("click", closeEditStockModal);
document.getElementById("btn-cancel-edit-modal")?.addEventListener("click", closeEditStockModal);

document.getElementById("edit-stock-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const originalSymbol = document.getElementById("edit-original-symbol").value;
    const newCompanyName = document.getElementById("edit-company-name").value.trim();
    const newStockCode = document.getElementById("edit-stock-code").value.trim().toUpperCase();
    const newExchange = document.getElementById("edit-exchange").value;

    if (!newStockCode) {
        showToast("Stock Code cannot be empty", "error");
        return;
    }

    // To update, we still need current price and qty because the PUT endpoint requires them.
    // Let's find the row that corresponds to this symbol.
    const symbolCell = document.querySelector(`.editable-cell[data-symbol='${originalSymbol}'][data-field='symbol']`);
    if (!symbolCell) return;

    const row = symbolCell.closest("tr");
    const qtyCell = row.querySelector(".editable-cell[data-field='quantity']");
    const priceCell = row.querySelector(".editable-cell[data-field='price']");

    const currentQty = parseFloat(qtyCell.dataset.value);
    const currentPrice = parseFloat(priceCell.dataset.value);
    const newTag = document.getElementById("edit-stock-tag").value.trim();
    const newRowColor = document.getElementById("edit-row-color").value.trim();

    const requestBody = {
        price: currentPrice,
        quantity: currentQty,
        company_name: newCompanyName,
        stock_code: newStockCode,
        exchange: newExchange,
        tag: newTag || null,
        row_color: newRowColor || null
    };

    const saveBtn = document.getElementById("btn-save-edit-modal");
    const originalText = saveBtn.innerText;
    saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
    saveBtn.disabled = true;

    try {
        const response = await fetch(`/api/stocks/${encodeURIComponent(originalSymbol)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to update.");
        }

        closeEditStockModal();
        showToast("Stock details updated!", "success");
        fetchAndRenderStocks(); // full refresh

    } catch (error) {
        showToast("Update failed: " + error.message, "error");
    } finally {
        saveBtn.innerText = originalText;
        saveBtn.disabled = false;
    }
});


let _lastInvested = 0;
let _lastCurrentVal = 0;
let _lastSmallcap = 0;

// ==========================================
// ROW COLOR SWATCH INITIALISATION
// ==========================================
const ROW_COLOR_PRESETS = [
    { label: 'Indigo',   hex: '#6366f1' },
    { label: 'Violet',   hex: '#8b5cf6' },
    { label: 'Rose',     hex: '#f43f5e' },
    { label: 'Amber',    hex: '#f59e0b' },
    { label: 'Emerald',  hex: '#10b981' },
    { label: 'Sky',      hex: '#0ea5e9' },
    { label: 'Teal',     hex: '#14b8a6' },
    { label: 'Orange',   hex: '#f97316' },
    { label: 'Lime',     hex: '#84cc16' },
    { label: 'Pink',     hex: '#ec4899' },
    { label: 'Cyan',     hex: '#06b6d4' },
    { label: 'Red',      hex: '#ef4444' },
];

function applySwatchSelection(selectedHex) {
    const container = document.getElementById('row-color-swatches');
    if (!container) return;
    container.querySelectorAll('.color-swatch').forEach(sw => {
        if (sw.dataset.hex) {
            const active = sw.dataset.hex === selectedHex;
            sw.style.outline = active ? '2px solid #fff' : 'none';
            sw.style.boxShadow = active ? `0 0 0 3px ${sw.dataset.hex}` : 'none';
        }
    });
    const clearBtn = container.querySelector('.color-swatch-clear');
    if (clearBtn) {
        clearBtn.style.outline = !selectedHex ? '2px solid var(--text-muted)' : 'none';
    }
}

(function initColorSwatches() {
    const container = document.getElementById('row-color-swatches');
    if (!container) return;

    // Clear / None pill
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'color-swatch color-swatch-clear';
    clearBtn.title = 'No color';
    clearBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
    clearBtn.style.cssText = [
        'width:28px', 'height:28px', 'border-radius:50%', 'border:1.5px solid var(--border)',
        'background:var(--surface)', 'color:var(--text-muted)', 'cursor:pointer',
        'display:flex', 'align-items:center', 'justify-content:center',
        'font-size:0.8rem', 'transition:transform 0.15s,box-shadow 0.15s'
    ].join(';');
    clearBtn.addEventListener('mouseenter', () => { clearBtn.style.transform = 'scale(1.15)'; });
    clearBtn.addEventListener('mouseleave', () => { clearBtn.style.transform = 'scale(1)'; });
    clearBtn.addEventListener('click', () => {
        document.getElementById('edit-row-color').value = '';
        applySwatchSelection('');
    });
    container.appendChild(clearBtn);

    // Preset swatches
    ROW_COLOR_PRESETS.forEach(({ label, hex }) => {
        const sw = document.createElement('button');
        sw.type = 'button';
        sw.className = 'color-swatch';
        sw.dataset.hex = hex;
        sw.title = label;
        sw.style.cssText = [
            `width:28px`, `height:28px`, `border-radius:50%`, `border:none`,
            `background:${hex}`, `cursor:pointer`,
            `transition:transform 0.15s,box-shadow 0.15s`, `flex-shrink:0`
        ].join(';');
        sw.addEventListener('mouseenter', () => { sw.style.transform = 'scale(1.2)'; });
        sw.addEventListener('mouseleave', () => { sw.style.transform = 'scale(1)'; });
        sw.addEventListener('click', () => {
            document.getElementById('edit-row-color').value = hex;
            applySwatchSelection(hex);
        });
        container.appendChild(sw);
    });
})();

function updateSummaryHeader(stocks) {
    let totalInvested = 0;
    let totalCurrent = 0;
    let successfulFetches = 0;
    let totalTodayReturn = 0;

    stocks.forEach(stock => {
        const investVal = stock.buying_price * stock.quantity;
        totalInvested += investVal;

        if (stock.status === "success" && stock.current_value !== null) {
            totalCurrent += stock.current_value;
            successfulFetches++;
            if (stock.today_return_val !== null) {
                totalTodayReturn += stock.today_return_val;
            }
        } else {
            // Fallback to investment value for calculation if ticker failed
            totalCurrent += investVal;
        }
    });

    _lastInvested = totalInvested;
    _lastCurrentVal = totalCurrent;

    const totalReturn = totalCurrent - totalInvested;
    const totalReturnPct = totalInvested > 0 ? (totalReturn / totalInvested * 100) : 0.0;
    const prevTotalCurrent = totalCurrent - totalTodayReturn;
    const todayReturnPct = prevTotalCurrent > 0 ? (totalTodayReturn / prevTotalCurrent * 100) : 0.0;

    document.getElementById("total-investment").textContent = isValuesMasked ? "₹******" : `₹${totalInvested.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    document.getElementById("total-current-value").textContent = isValuesMasked ? "₹******" : `₹${totalCurrent.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    // Total Return Formatting
    const returnValEl = document.getElementById("total-return");
    const returnPctEl = document.getElementById("total-return-pct");
    const returnIconWrapper = document.getElementById("return-icon-wrapper");
    const sign = totalReturn >= 0 ? "+" : "-";

    returnValEl.textContent = `${sign}₹${Math.abs(totalReturn).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    returnPctEl.textContent = `(${totalReturn >= 0 ? '+' : ''}${totalReturnPct.toFixed(2)}%)`;

    // Today's Return Formatting
    const todayReturnValEl = document.getElementById("today-return-val");
    const todayReturnPctEl = document.getElementById("today-return-pct");
    const todayReturnIconWrapper = document.getElementById("today-return-icon-wrapper");
    const todaySign = totalTodayReturn >= 0 ? "+" : "-";

    if (todayReturnValEl) {
        todayReturnValEl.textContent = `${todaySign}₹${Math.abs(totalTodayReturn).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        todayReturnPctEl.textContent = `(${totalTodayReturn >= 0 ? '+' : ''}${todayReturnPct.toFixed(2)}%)`;
    }

    // Adjust colors for Total Return
    if (totalReturn >= 0) {
        returnValEl.className = "value gain-val";
        returnPctEl.className = "percentage gain-val";
        returnIconWrapper.parentNode.className = "summary-card return-rate";
        returnIconWrapper.innerHTML = '<i class="fa-solid fa-arrow-trend-up"></i>';
    } else {
        returnValEl.className = "value loss-val";
        returnPctEl.className = "percentage loss-val";
        returnIconWrapper.parentNode.className = "summary-card return-rate loss";
        returnIconWrapper.innerHTML = '<i class="fa-solid fa-arrow-trend-down"></i>';
    }

    // Adjust colors for Today's Return
    if (todayReturnValEl) {
        if (totalTodayReturn >= 0) {
            todayReturnValEl.className = "value gain-val";
            todayReturnPctEl.className = "percentage gain-val";
            todayReturnIconWrapper.parentNode.className = "summary-card today-return";
            todayReturnIconWrapper.innerHTML = '<i class="fa-solid fa-calendar-day"></i>';
        } else {
            todayReturnValEl.className = "value loss-val";
            todayReturnPctEl.className = "percentage loss-val";
            todayReturnIconWrapper.parentNode.className = "summary-card today-return loss";
            todayReturnIconWrapper.innerHTML = '<i class="fa-solid fa-calendar-minus"></i>';
        }
    }
}

async function fetchMarketIndex() {
    const symbol = '^CNXSC';
    try {
        const response = await fetch(`/api/market-index/${encodeURIComponent(symbol)}`);
        if (!response.ok) throw new Error("Failed to fetch index");

        const data = await response.json();

        const valEl = document.getElementById("smallcap-val");
        const pctEl = document.getElementById("smallcap-pct");
        const iconWrapper = document.getElementById("smallcap-icon-wrapper");
        if (!valEl || !pctEl || !iconWrapper) return;

        const currentVal = data.current_value;
        const change = data.change;
        const changePct = data.change_pct;

        _lastSmallcap = currentVal;

        valEl.textContent = currentVal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        pctEl.textContent = `(${change >= 0 ? '+' : ''}${changePct.toFixed(2)}%)`;

        if (change >= 0) {
            valEl.className = "value gain-val";
            pctEl.className = "percentage gain-val";
            iconWrapper.parentNode.className = "summary-card index-smallcap";
        } else {
            valEl.className = "value loss-val";
            pctEl.className = "percentage loss-val";
            iconWrapper.parentNode.className = "summary-card index-smallcap loss";
        }

    } catch (error) {
        console.error("Error fetching Nifty Smallcap:", error);
        const valEl = document.getElementById("smallcap-val");
        if (valEl) valEl.textContent = "Error";
    }
}

async function saveDailySnapshot() {
    if (_lastInvested === 0 || _lastCurrentVal === 0 || _lastSmallcap === 0) return;
    try {
        await fetch("/api/stats/snapshot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                total_invested: _lastInvested,
                current_value: _lastCurrentVal,
                nifty_smallcap_100: _lastSmallcap
            })
        });
    } catch (e) {
        console.error("Failed to save daily snapshot", e);
    }
}

let _trendsChartInstance = null;
// Store raw data for tooltip real-value display
let _trendsRawData = { invested: [], current: [], smallcap: [] };
// Full unfiltered API data cache
let _trendsAllData = [];

async function fetchAndRenderTrends() {
    try {
        const response = await fetch("/api/stats/history");
        if (!response.ok) throw new Error("Failed to fetch historical stats");
        _trendsAllData = await response.json();

        if (_trendsAllData.length === 0) return;

        // Seed date inputs with full range bounds
        const firstDate = _trendsAllData[0].date.slice(0, 10);
        const lastDate  = _trendsAllData[_trendsAllData.length - 1].date.slice(0, 10);
        const fromInput = document.getElementById('trends-date-from');
        const toInput   = document.getElementById('trends-date-to');
        if (fromInput && !fromInput.value) {
            fromInput.min = firstDate;
            fromInput.max = lastDate;
            fromInput.value = firstDate;
        }
        if (toInput && !toInput.value) {
            toInput.min = firstDate;
            toInput.max = lastDate;
            toInput.value = lastDate;
        }

        // Wire up filter controls once
        initTrendsFilter();

        // Default: render ALL
        applyTrendsFilter('ALL');

    } catch (e) {
        console.error("Failed to render trends chart", e);
    }
}

function initTrendsFilter() {
    // Preset buttons
    document.querySelectorAll('.trends-preset-btn').forEach(btn => {
        // Remove old listeners by replacing node clone trick
        const fresh = btn.cloneNode(true);
        btn.parentNode.replaceChild(fresh, btn);
        fresh.addEventListener('click', () => {
            document.querySelectorAll('.trends-preset-btn').forEach(b => b.classList.remove('active'));
            fresh.classList.add('active');
            applyTrendsFilter(fresh.dataset.preset);
        });
    });

    // Apply button for custom date range
    const applyBtn = document.getElementById('trends-apply-btn');
    if (applyBtn) {
        const freshApply = applyBtn.cloneNode(true);
        applyBtn.parentNode.replaceChild(freshApply, applyBtn);
        freshApply.addEventListener('click', () => {
            // Clear preset active state — this is a custom range
            document.querySelectorAll('.trends-preset-btn').forEach(b => b.classList.remove('active'));
            applyTrendsFilter('CUSTOM');
        });
    }
}

function presetDates(preset) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let fromDate = new Date(today);

    switch (preset) {
        case '1W': fromDate.setDate(today.getDate() - 7);   break;
        case '1M': fromDate.setMonth(today.getMonth() - 1); break;
        case '3M': fromDate.setMonth(today.getMonth() - 3); break;
        case '6M': fromDate.setMonth(today.getMonth() - 6); break;
        case '1Y': fromDate.setFullYear(today.getFullYear() - 1); break;
        case 'ALL':
        default:
            fromDate = null; // no lower bound
    }
    return { fromDate, toDate: today };
}

function applyTrendsFilter(preset) {
    if (!_trendsAllData.length) return;

    let filtered;
    const fromInput = document.getElementById('trends-date-from');
    const toInput   = document.getElementById('trends-date-to');
    const rangeEl   = document.getElementById('trends-active-range');

    if (preset === 'CUSTOM') {
        const fromVal = fromInput?.value;
        const toVal   = toInput?.value;
        const from = fromVal ? new Date(fromVal) : null;
        const to   = toVal   ? new Date(toVal)   : null;
        if (to) to.setHours(23, 59, 59);

        filtered = _trendsAllData.filter(d => {
            const dt = new Date(d.date);
            if (from && dt < from) return false;
            if (to   && dt > to)   return false;
            return true;
        });

        // Update date pickers to reflect selection
        if (fromInput && fromVal) fromInput.value = fromVal;
        if (toInput   && toVal)   toInput.value   = toVal;

        if (rangeEl) {
            rangeEl.innerHTML = fromVal && toVal
                ? `Showing: <span>${fmtDateLabel(fromVal)}</span> → <span>${fmtDateLabel(toVal)}</span> (${filtered.length} pts)`
                : '';
        }
    } else {
        const { fromDate, toDate } = presetDates(preset);
        filtered = _trendsAllData.filter(d => {
            const dt = new Date(d.date);
            if (fromDate && dt < fromDate) return false;
            if (dt > toDate) return false;
            return true;
        });

        // Sync date pickers to match preset range
        if (filtered.length) {
            const firstFiltered = filtered[0].date.slice(0, 10);
            const lastFiltered  = filtered[filtered.length - 1].date.slice(0, 10);
            if (fromInput) fromInput.value = firstFiltered;
            if (toInput)   toInput.value   = lastFiltered;
        }

        if (rangeEl) {
            const label = preset === 'ALL'
                ? `All available data <span>(${filtered.length} pts)</span>`
                : `Last <span>${preset}</span> — ${filtered.length} data pts`;
            rangeEl.innerHTML = label;
        }
    }

    if (!filtered.length) {
        if (rangeEl) rangeEl.innerHTML = '<span style="color:var(--danger)">No data in selected range</span>';
        return;
    }

    renderTrendsChart(filtered);
}

function fmtDateLabel(isoStr) {
    return new Date(isoStr).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function renderTrendsChart(data) {
    const labels = data.map(d =>
        new Date(d.date).toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })
    );

    const rawInvested = data.map(d => d.total_invested);
    const rawCurrent  = data.map(d => d.current_value);
    const rawSmallcap = data.map(d => d.nifty_smallcap_100);

    // Store raw for tooltip
    _trendsRawData = { invested: rawInvested, current: rawCurrent, smallcap: rawSmallcap };

    // ── Normalize: rebase to 100 at first non-zero point ────────────────
    function normalize(arr) {
        const base = arr.find(v => v && v !== 0) || 1;
        return arr.map(v => v != null ? parseFloat(((v / base) * 100).toFixed(4)) : null);
    }

    const normInvested = normalize(rawInvested);
    const normCurrent  = normalize(rawCurrent);
    const normSmallcap = normalize(rawSmallcap);

    const ctx = document.getElementById('trendsChart').getContext('2d');

    if (_trendsChartInstance) {
        _trendsChartInstance.destroy();
    }

    _trendsChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Total Invested (₹)',
                    data: normInvested,
                    borderColor: '#94a3b8',
                    backgroundColor: 'rgba(148, 163, 184, 0.08)',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 6,
                    fill: false,
                },
                {
                    label: 'Current Value (₹)',
                    data: normCurrent,
                    borderColor: '#8b5cf6',
                    backgroundColor: 'rgba(139, 92, 246, 0.08)',
                    borderWidth: 2.5,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 6,
                    fill: false,
                },
                {
                    label: 'Nifty SmallCap 100',
                    data: normSmallcap,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.08)',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 6,
                    fill: false,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#e2e8f0',
                        font: { family: "'Inter', sans-serif", size: 12 },
                        usePointStyle: true,
                        padding: 18
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(10, 17, 35, 0.95)',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: '#334155',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: {
                        title(items) {
                            return items[0]?.label ?? '';
                        },
                        label(ctx) {
                            const idx     = ctx.dataIndex;
                            const norm    = ctx.parsed.y;
                            const pct     = (norm - 100).toFixed(2);
                            const sign    = pct >= 0 ? '+' : '';
                            let realVal   = '';
                            if (ctx.datasetIndex === 0) {
                                const v = _trendsRawData.invested[idx];
                                realVal = v != null ? ` | Real: ₹${v.toLocaleString('en-IN', {maximumFractionDigits: 0})}` : '';
                            } else if (ctx.datasetIndex === 1) {
                                const v = _trendsRawData.current[idx];
                                realVal = v != null ? ` | Real: ₹${v.toLocaleString('en-IN', {maximumFractionDigits: 0})}` : '';
                            } else if (ctx.datasetIndex === 2) {
                                const v = _trendsRawData.smallcap[idx];
                                realVal = v != null ? ` | Real: ${v.toLocaleString('en-IN', {maximumFractionDigits: 2})} pts` : '';
                            }
                            return ` ${ctx.dataset.label}: ${norm.toFixed(2)} (${sign}${pct}%)${realVal}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8', font: { size: 11 } }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#94a3b8',
                        font: { size: 11 },
                        callback(val) {
                            const pct = (val - 100).toFixed(1);
                            const sign = val >= 100 ? '+' : '';
                            return `${sign}${pct}%`;
                        }
                    },
                    title: {
                        display: true,
                        text: '% Change from Start (Normalized to 100)',
                        color: '#94a3b8',
                        font: { size: 11 }
                    }
                }
            }
        }
    });
}


async function deleteStockHolding(symbol) {
    try {
        const response = await fetch(`/api/stocks/${symbol}`, {
            method: "DELETE"
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to delete stock");
        }

        showToast(`Successfully deleted ${symbol}`, "success");
        fetchAndRenderStocks();
    } catch (error) {
        showToast("Error deleting stock: " + error.message, "error");
    }
}

/* Inline Editing for Qty and Buy Price */

// Track the currently-active inline editor so we can cancel it on outside clicks
let _activeEditCell = null;

function activateInlineEdit(cell) {
    if (cell.classList.contains("editing")) return; // already active

    const field = cell.dataset.field; // 'quantity' | 'price' | 'symbol'

    if (field === "symbol") {
        // Open dedicated Edit Stock Modal
        openEditStockModal(cell);
        return;
    }

    if (_activeEditCell && _activeEditCell !== cell) {
        cancelInlineEdit(_activeEditCell);
    }

    const symbol = cell.dataset.symbol;
    const isQty = field === "quantity";
    const rawValue = parseFloat(cell.dataset.value);

    // Build the inline input element
    const input = document.createElement("input");
    input.type = "number";
    input.className = "inline-edit-input";
    input.value = isQty ? rawValue : rawValue.toFixed(4);

    input.step = "any";
    input.min = isQty ? "0.0001" : "0.01";
    input.setAttribute("data-original", input.value);

    // Save button
    const saveBtn = document.createElement("button");
    saveBtn.className = "inline-edit-btn save";
    saveBtn.innerHTML = '<i class="fa-solid fa-check"></i>';
    saveBtn.title = "Save";

    // Cancel button
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "inline-edit-btn cancel";
    cancelBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
    cancelBtn.title = "Cancel";

    // Swap cell content
    cell.innerHTML = "";
    const wrapper = document.createElement("div");
    wrapper.className = "inline-edit-wrapper";
    wrapper.appendChild(input);
    wrapper.appendChild(saveBtn);
    wrapper.appendChild(cancelBtn);
    cell.appendChild(wrapper);
    cell.classList.add("editing");
    _activeEditCell = cell;

    input.focus();
    input.select();

    // Commit on Enter / Tab
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); commitInlineEdit(cell, symbol); }
        if (e.key === "Escape") { e.preventDefault(); cancelInlineEdit(cell); }
        if (e.key === "Tab") { commitInlineEdit(cell, symbol); }
    });

    saveBtn.addEventListener("click", (e) => { e.stopPropagation(); commitInlineEdit(cell, symbol); });
    cancelBtn.addEventListener("click", (e) => { e.stopPropagation(); cancelInlineEdit(cell); });
}

function cancelInlineEdit(cell) {
    if (!cell.classList.contains("editing")) return;
    const field = cell.dataset.field;
    const isQty = field === "quantity";

    const rawValue = parseFloat(cell.dataset.value);
    const displayHtml = `<span class="editable-display">${isQty ? rawValue : "\u20B9" + rawValue.toFixed(2)}</span>`;

    cell.classList.remove("editing");
    cell.innerHTML = `${displayHtml}<i class="fa-solid fa-pen-to-square edit-pencil"></i>`;
    _activeEditCell = null;
}

async function commitInlineEdit(cell, symbol) {
    if (!cell.classList.contains("editing")) return;

    const field = cell.dataset.field;
    const isQty = field === "quantity";
    const input = cell.querySelector(".inline-edit-input");

    let newValue = parseFloat(input.value);
    if (isNaN(newValue) || newValue <= 0) {
        input.classList.add("input-error");
        showToast("Please enter a valid positive number.", "error");
        input.focus();
        return;
    }
    const original = parseFloat(input.dataset.original);
    if (newValue === original) {
        cancelInlineEdit(cell);
        return;
    }

    // Get the sibling cell values so we can send both price + qty to the PUT endpoint
    const row = cell.closest("tr");
    const qtyCell = row.querySelector(".editable-cell[data-field='quantity']");
    const priceCell = row.querySelector(".editable-cell[data-field='price']");
    const symbolCell = row.querySelector(".editable-cell[data-field='symbol']");

    let currentQty = parseFloat(qtyCell.dataset.value);
    let currentPrice = parseFloat(priceCell.dataset.value);

    if (isQty) currentQty = newValue;
    else currentPrice = newValue;

    const requestBody = {
        price: currentPrice,
        quantity: currentQty,
        company_name: symbolCell.dataset.companyName,
        stock_code: symbolCell.dataset.stockCode,
        exchange: symbolCell.dataset.exchange
    };

    // Show saving state
    const saveBtn = cell.querySelector(".inline-edit-btn.save");
    if (saveBtn) { saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; saveBtn.disabled = true; }

    try {
        const response = await fetch(`/api/stocks/${encodeURIComponent(symbol)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to update.");
        }

        // Update the data-value attribute so future edits use the new value
        cell.dataset.value = newValue.toString();

        cell.classList.remove("editing");
        _activeEditCell = null;

        // Update display text inline without full table refresh
        let displayHtml = "";
        const displayVal = isQty ? newValue : `\u20B9${newValue.toFixed(2)}`;
        displayHtml = `<span class="editable-display">${displayVal}</span>`;

        cell.innerHTML = `${displayHtml}<i class="fa-solid fa-pen-to-square edit-pencil"></i>`;

        // Re-wire the click event on the updated cell
        cell.addEventListener("click", (e) => { e.stopPropagation(); activateInlineEdit(cell); });

        showToast(`${isQty ? "quantity" : "buy price"} updated!`, "success");

        // Full refresh so calculated columns update
        fetchAndRenderStocks();

    } catch (error) {
        showToast("Update failed: " + error.message, "error");
        if (saveBtn) { saveBtn.innerHTML = '<i class="fa-solid fa-check"></i>'; saveBtn.disabled = false; }
    }
}

// Close any open inline editor when clicking outside the table
document.addEventListener("click", (e) => {
    if (_activeEditCell && !_activeEditCell.contains(e.target)) {
        cancelInlineEdit(_activeEditCell);
    }
});

/* 3. Add/Update Transactions Form */
function initForms() {
    const form = document.getElementById("stock-form");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();

        const companyName = document.getElementById("stock-company-name").value.trim();
        const stockCode = document.getElementById("stock-code").value.trim().toUpperCase();
        const exchange = document.getElementById("stock-exchange").value;
        const price = parseFloat(document.getElementById("stock-price").value);
        const qty = parseFloat(document.getElementById("stock-qty").value);
        const tag = document.getElementById("stock-tag").value.trim();

        const submitBtn = document.getElementById("btn-submit-stock");
        const originalBtnHTML = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:8px;"></div> Saving...';

        try {
            const response = await fetch("/api/stocks", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ company_name: companyName, stock_code: stockCode, exchange: exchange, price, quantity: qty, tag: tag || null })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Failed to save stock holding.");
            }

            const result = await response.json();
            const actionText = result.action === "merged"
                ? "merged (increased quantity & average price updated)"
                : "added as a new holding";

            showToast(`Stock ${result.symbol} successfully ${actionText}!`, "success");

            form.reset();
            switchView("dashboard-view");
        } catch (error) {
            showToast("Error saving stock: " + error.message, "error");
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnHTML;
        }
    });
}

/* 4. Excel Import - Drag and Drop Zone */
function initUpload() {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("excel-file-input");
    const resultBox = document.getElementById("upload-result");

    if (!dropzone) return;

    // Open file browser on dropzone click
    dropzone.addEventListener("click", () => fileInput.click());

    // Visual indicators on dragover
    ["dragenter", "dragover"].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.add("dragover");
        }, false);
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.remove("dragover");
        }, false);
    });

    // Catch files dropped
    dropzone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length) {
            handleFileUpload(files[0]);
        }
    });

    // Catch files selected from browser
    fileInput.addEventListener("change", (e) => {
        if (fileInput.files.length) {
            handleFileUpload(fileInput.files[0]);
        }
    });
}

async function handleFileUpload(file) {
    const resultBox = document.getElementById("upload-result");

    if (!file.name.endsWith(".xlsx") && !file.name.endsWith(".xls")) {
        showToast("Invalid file format. Please upload an Excel sheet (.xlsx, .xls).", "error");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    showToast(`Uploading ${file.name}...`, "info");

    try {
        const response = await fetch("/api/stocks/upload", {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Upload error");
        }

        const stats = await response.json();

        // Populate results template
        let skippedHTML = "";
        if (stats.skipped > 0 && stats.skipped_details.length > 0) {
            skippedHTML = `
                <div class="skipped-items-list">
                    <h5>Skipped Tickers (${stats.skipped}):</h5>
                    <ul>
                        ${stats.skipped_details.map(item => `<li>${item}</li>`).join("")}
                    </ul>
                </div>
            `;
        }

        resultBox.innerHTML = `
            <h4><i class="fa-solid fa-circle-check"></i> File Imported Successfully</h4>
            <div class="upload-stats-summary">
                <div class="upload-stat-item">
                    <div class="label">New Added</div>
                    <div class="val gain-val">${stats.added}</div>
                </div>
                <div class="upload-stat-item">
                    <div class="label">Merged</div>
                    <div class="val text-main" style="color:var(--primary-hover);">${stats.merged}</div>
                </div>
                <div class="upload-stat-item">
                    <div class="label">Errors Skipped</div>
                    <div class="val loss-val">${stats.skipped}</div>
                </div>
            </div>
            ${skippedHTML}
        `;

        resultBox.classList.remove("hidden");
        showToast("Excel spreadsheet merged successfully!", "success");
        fetchAndRenderStocks();

    } catch (error) {
        showToast("Failed to parse Excel: " + error.message, "error");
        resultBox.innerHTML = `
            <h4 class="loss-val"><i class="fa-solid fa-circle-exclamation"></i> Import Failed</h4>
            <p style="font-size:0.85rem;color:var(--text-muted);">${error.message}</p>
        `;
        resultBox.classList.remove("hidden");
    }
}

/* 5. Detail View, Historical Fetch, and Chart.js superimposition */
function initDetails() {
    // Back button
    const backBtn = document.getElementById("btn-back-dashboard");
    if (backBtn) {
        backBtn.addEventListener("click", () => {
            switchView("dashboard-view");
        });
    }

    // Timeframe selector triggers
    const timeBtns = document.querySelectorAll(".time-btn");
    timeBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            timeBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            currentPeriod = btn.getAttribute("data-period");
            if (currentSymbol) {
                loadHistoryChart(currentSymbol, currentPeriod);
            }
        });
    });
}

function openStockDetails(symbol) {
    currentSymbol = symbol;

    // Set headers text
    document.getElementById("detail-symbol").textContent = symbol;
    document.getElementById("detail-exchange").textContent = symbol.endsWith(".BO")
        ? "BSE India Listed"
        : symbol.endsWith(".NS")
            ? "NSE India Listed"
            : "Global / US Market";

    document.getElementById("detail-price").textContent = "Loading...";

    // Reset time selector back to 1 Year default
    const timeBtns = document.querySelectorAll(".time-btn");
    timeBtns.forEach(btn => {
        if (btn.getAttribute("data-period") === "1y") {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
    currentPeriod = "1y";

    switchView("details-view");
    loadHistoryChart(symbol, currentPeriod);
}

async function loadHistoryChart(symbol, period) {
    const canvas = document.getElementById("stockHistoryChart");
    if (!canvas) return;

    // Show spinner in details block or toast
    showToast(`Loading analysis chart for ${symbol}...`, "info");

    try {
        const response = await fetch(`/api/stocks/${symbol}/history?period=${period}`);
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to fetch historical indicators.");
        }

        const data = await response.json();

        // Update Price in Header
        const lastPrice = data.prices[data.prices.length - 1];
        if (lastPrice !== null && lastPrice !== undefined) {
            document.getElementById("detail-price").textContent = `₹${lastPrice.toFixed(2)}`;
        } else {
            document.getElementById("detail-price").textContent = `N/A`;
        }

        // Process UI values for moving averages card
        updateSMACards(data);

        // Render News
        renderNews(data.news);

        // Draw the Chart
        renderChart(data);

        // Render new panels
        renderStockDetails(data.company_info || {});
        renderAboutCompany(data.company_info || {});

    } catch (error) {
        showToast("Error loading chart: " + error.message, "error");
        console.error(error);
    }
}

function updateSMACards(data) {
    const lastPrice = data.prices[data.prices.length - 1];
    const lastSMA20 = data.sma20[data.sma20.length - 1];
    const lastSMA50 = data.sma50[data.sma50.length - 1];
    const lastSMA100 = data.sma100[data.sma100.length - 1];
    const lastSMA200 = data.sma200[data.sma200.length - 1];

    // Elements update helper
    const setSMAInfo = (smaName, smaVal, indicatorEl, valueEl) => {
        if (smaVal === null) {
            valueEl.textContent = "N/A";
            indicatorEl.textContent = "Insufficient Data";
            indicatorEl.className = "status-indicator";
        } else {
            valueEl.textContent = `₹${smaVal.toFixed(2)}`;
            const isAbove = lastPrice >= smaVal;
            indicatorEl.textContent = isAbove ? "Above" : "Below";
            indicatorEl.className = `status-indicator ${isAbove ? "above" : "below"}`;
        }
    };

    setSMAInfo("20", lastSMA20, document.getElementById("sma20-indicator"), document.getElementById("sma20-val"));
    setSMAInfo("50", lastSMA50, document.getElementById("sma50-indicator"), document.getElementById("sma50-val"));
    setSMAInfo("100", lastSMA100, document.getElementById("sma100-indicator"), document.getElementById("sma100-val"));
    setSMAInfo("200", lastSMA200, document.getElementById("sma200-indicator"), document.getElementById("sma200-val"));

    // Verdict calculation
    let verdict = "";
    const name = data.symbol;

    if (lastSMA20 !== null && lastSMA50 !== null && lastSMA100 !== null && lastSMA200 !== null) {
        const above20 = lastPrice >= lastSMA20;
        const above50 = lastPrice >= lastSMA50;
        const above100 = lastPrice >= lastSMA100;
        const above200 = lastPrice >= lastSMA200;

        if (above20 && above50 && above100 && above200) {
            verdict = `<i class="fa-solid fa-circle-check" style="color:var(--success);"></i> <strong>Strong Bullish Trend:</strong> The current market price of ${name} is trading above its 20-day, 50-day, 100-day, and 200-day Simple Moving Averages. This indicates high positive long-term momentum.`;
        } else if (!above20 && !above50 && !above100 && !above200) {
            verdict = `<i class="fa-solid fa-circle-xmark" style="color:var(--danger);"></i> <strong>Bearish Trend:</strong> The current market price of ${name} is trading below its 20-day, 50-day, 100-day, and 200-day Simple Moving Averages. This indicates strong negative momentum.`;
        } else {
            let aboves = [];
            if (above20) aboves.push("20-Day");
            if (above50) aboves.push("50-Day");
            if (above100) aboves.push("100-Day");
            if (above200) aboves.push("200-Day");

            verdict = `<i class="fa-solid fa-circle-half-stroke" style="color:var(--warning);"></i> <strong>Neutral/Consolidating:</strong> The stock is in a mixed phase, trading above its ${aboves.join(", ")} SMA but below the others. This often indicates consolidation.`;
        }
    } else {
        verdict = `<i class="fa-solid fa-circle-question"></i> <strong>Insufficient History:</strong> Not enough historical data to generate a complete moving averages verdict (200 trading days required for long-term SMA).`;
    }

    document.getElementById("sma-summary-verdict").innerHTML = verdict;

    // Update RSI
    const lastRSI = data.rsi && data.rsi.length > 0 ? data.rsi[data.rsi.length - 1] : null;
    const rsiValEl = document.getElementById("rsi-val");
    const rsiIndEl = document.getElementById("rsi-indicator");

    if (lastRSI === null) {
        rsiValEl.textContent = "N/A";
        rsiIndEl.textContent = "Insufficient Data";
        rsiIndEl.className = "status-indicator";
    } else {
        rsiValEl.textContent = lastRSI.toFixed(2);
        if (lastRSI > 60) {
            rsiIndEl.textContent = "Overbought (Bearish) / Buy zone";
            rsiIndEl.className = "status-indicator below"; // red
        } else if (lastRSI < 50) {
            rsiIndEl.textContent = "Sell Now";
            rsiIndEl.className = "status-indicator above"; // green
        } else {
            rsiIndEl.textContent = "Neutral";
            rsiIndEl.className = "status-indicator"; // default
        }
    }

    // Update Bollinger Bands
    const lastBBUpper = data.bb_upper && data.bb_upper.length > 0 ? data.bb_upper[data.bb_upper.length - 1] : null;
    const lastBBLower = data.bb_lower && data.bb_lower.length > 0 ? data.bb_lower[data.bb_lower.length - 1] : null;
    const bbValEl = document.getElementById("bb-val");
    const bbIndEl = document.getElementById("bb-indicator");

    if (lastBBUpper === null || lastBBLower === null) {
        bbValEl.textContent = "N/A";
        bbIndEl.textContent = "Insufficient Data";
        bbIndEl.className = "status-indicator";
    } else {
        bbValEl.innerHTML = `Upper: ₹${lastBBUpper.toFixed(2)}<br>Lower: ₹${lastBBLower.toFixed(2)}`;
        if (lastPrice > lastBBUpper) {
            bbIndEl.textContent = "Upside Breakout";
            bbIndEl.className = "status-indicator above";
        } else if (lastPrice < lastBBLower) {
            bbIndEl.textContent = "Downside Breakout";
            bbIndEl.className = "status-indicator below";
        } else {
            bbIndEl.textContent = "Inside Range";
            bbIndEl.className = "status-indicator";
        }
    }
}

function renderNews(newsItems) {
    const newsContainer = document.getElementById("stock-news-list");
    if (!newsItems || newsItems.length === 0) {
        newsContainer.innerHTML = `<p class="text-muted">No recent news available for this stock.</p>`;
        return;
    }

    let html = '<div class="news-grid">';
    newsItems.forEach(item => {
        // Format the date if available
        let dateStr = "";
        if (item.time) {
            try {
                const dateObj = new Date(item.time);
                dateStr = dateObj.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
            } catch (e) {
                dateStr = item.time;
            }
        }

        html += `
            <a href="${item.link}" target="_blank" class="news-item">
                <div class="news-content">
                    <h5 class="news-title">${item.title}</h5>
                    <div class="news-meta">
                        <span class="news-publisher">${item.publisher}</span>
                        ${dateStr ? `<span class="news-date">${dateStr}</span>` : ''}
                    </div>
                </div>
                <i class="fa-solid fa-arrow-up-right-from-square news-icon"></i>
            </a>
        `;
    });
    html += '</div>';
    newsContainer.innerHTML = html;
}

function renderChart(data) {
    const ctx = document.getElementById("stockHistoryChart").getContext("2d");

    // Destroy previous chart instance if exists to clean memory
    if (historyChartInstance) {
        historyChartInstance.destroy();
    }

    // Premium Chart.js Line configuration
    historyChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: [
                {
                    label: 'Close Price (₹)',
                    data: data.prices,
                    borderColor: '#818cf8',
                    borderWidth: 2.5,
                    pointRadius: 0,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#818cf8',
                    fill: true,
                    // Soft transparent gradient below the main price line
                    backgroundColor: (context) => {
                        const chart = context.chart;
                        const { ctx, chartArea } = chart;
                        if (!chartArea) return null;

                        const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
                        gradient.addColorStop(0, 'rgba(129, 140, 248, 0.15)');
                        gradient.addColorStop(1, 'rgba(129, 140, 248, 0.0)');
                        return gradient;
                    },
                    tension: 0.15
                },
                {
                    label: '20-Day SMA',
                    data: data.sma20,
                    borderColor: '#60a5fa',
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false,
                    tension: 0.1
                },
                {
                    label: '50-Day SMA',
                    data: data.sma50,
                    borderColor: '#2dd4bf',
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false,
                    tension: 0.1
                },
                {
                    label: '100-Day SMA',
                    data: data.sma100,
                    borderColor: '#f59e0b',
                    borderWidth: 1.5,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false,
                    tension: 0.1
                },
                {
                    label: '200-Day SMA',
                    data: data.sma200,
                    borderColor: '#ec4899',
                    borderWidth: 1.8,
                    borderDash: [3, 3],
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false,
                    tension: 0.1
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#9ca3af',
                        font: {
                            family: 'Inter',
                            size: 11
                        },
                        boxWidth: 20
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    titleColor: '#fff',
                    bodyColor: '#f3f4f6',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    padding: 10,
                    bodyFont: {
                        family: 'Inter'
                    },
                    titleFont: {
                        family: 'Outfit',
                        weight: 'bold'
                    },
                    callbacks: {
                        label: function (context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += '₹' + context.parsed.y.toFixed(2);
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.03)',
                        borderColor: 'transparent'
                    },
                    ticks: {
                        color: '#9ca3af',
                        font: {
                            family: 'Inter',
                            size: 10
                        },
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 10
                    }
                },
                y: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.04)',
                        borderColor: 'transparent'
                    },
                    ticks: {
                        color: '#9ca3af',
                        font: {
                            family: 'Inter',
                            size: 10
                        },
                        callback: function (value) {
                            return '₹' + value;
                        }
                    }
                }
            }
        }
    });
}

/* ============================================================
   Stock Details Metrics Panel
   ============================================================ */
function fmtINR(val) {
    if (val === null || val === undefined) return '—';
    if (val >= 1e12) return '₹' + (val / 1e12).toFixed(2) + ' Lakh Cr';
    if (val >= 1e7) return '₹' + (val / 1e7).toFixed(2) + ' Cr';
    if (val >= 1e5) return '₹' + (val / 1e5).toFixed(2) + ' L';
    return '₹' + val.toFixed(2);
}

function fmtVolume(val) {
    if (val === null || val === undefined) return '—';
    if (val >= 1e7) return (val / 1e7).toFixed(2) + ' Cr';
    if (val >= 1e5) return (val / 1e5).toFixed(2) + ' L';
    if (val >= 1e3) return (val / 1e3).toFixed(1) + 'K';
    return String(val);
}

function fmtPct(val) {
    if (val === null || val === undefined) return '—';
    return (val * 100).toFixed(2) + '%';
}

function fmtNum(val, decimals = 2) {
    if (val === null || val === undefined) return '—';
    return Number(val).toFixed(decimals);
}

function renderStockDetails(info) {
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val ?? '—';
    };

    set('metric-52wk-high', info.fiftyTwoWeekHigh != null ? `₹${fmtNum(info.fiftyTwoWeekHigh)}` : '—');
    set('metric-52wk-low', info.fiftyTwoWeekLow != null ? `₹${fmtNum(info.fiftyTwoWeekLow)}` : '—');
    set('metric-market-cap', info.marketCap != null ? fmtINR(info.marketCap) : '—');
    set('metric-pe', info.trailingPE != null ? fmtNum(info.trailingPE) : '—');
    set('metric-eps', info.trailingEps != null ? `₹${fmtNum(info.trailingEps)}` : '—');
    set('metric-dividend', info.dividendYield != null ? fmtPct(info.dividendYield) : 'None');
    set('metric-beta', info.beta != null ? fmtNum(info.beta) : '—');
    set('metric-volume', info.averageVolume != null ? fmtVolume(info.averageVolume) : '—');
    set('metric-pb', info.priceToBook != null ? fmtNum(info.priceToBook) : '—');
    set('metric-profit-margin', info.profitMargins != null ? fmtPct(info.profitMargins) : '—');
    set('metric-roe', info.returnOnEquity != null ? fmtPct(info.returnOnEquity) : '—');
    set('metric-de', info.debtToEquity != null ? fmtNum(info.debtToEquity) : '—');

    // Colour the 52-wk high tile green, low tile red
    const highTile = document.getElementById('metric-52h');
    if (highTile) highTile.querySelector('.metric-icon').style.background = 'var(--success-light)';
    if (highTile) highTile.querySelector('.metric-icon').style.color = 'var(--success)';
}

/* ============================================================
   About Company Panel
   ============================================================ */
function renderAboutCompany(info) {
    // Company name
    const nameEl = document.getElementById('about-company-name');
    if (nameEl) nameEl.textContent = info.longName || '—';

    // Meta pills: sector, industry, location
    const metaEl = document.getElementById('about-company-meta');
    if (metaEl) {
        let pills = '';
        if (info.sector) pills += `<span class="about-pill about-pill-sector"><i class="fa-solid fa-layer-group"></i> ${info.sector}</span>`;
        if (info.industry) pills += `<span class="about-pill about-pill-industry"><i class="fa-solid fa-industry"></i> ${info.industry}</span>`;
        const loc = [info.city, info.country].filter(Boolean).join(', ');
        if (loc) pills += `<span class="about-pill about-pill-location"><i class="fa-solid fa-location-dot"></i> ${loc}</span>`;
        metaEl.innerHTML = pills || '<span class="text-muted" style="font-size:0.85rem;">—</span>';
    }

    // Right-side: employees + website
    const rightEl = document.getElementById('about-company-right');
    if (rightEl) {
        let rightHTML = '';
        if (info.fullTimeEmployees) {
            const emp = Number(info.fullTimeEmployees).toLocaleString('en-IN');
            rightHTML += `<div class="about-stat"><i class="fa-solid fa-users"></i><span>${emp} Employees</span></div>`;
        }
        if (info.website) {
            rightHTML += `<a href="${info.website}" target="_blank" class="about-website-link"><i class="fa-solid fa-globe"></i> ${info.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}</a>`;
        }
        rightEl.innerHTML = rightHTML;
    }

    // Business Summary – split into short preview + full text with toggle
    const bio = info.longBusinessSummary || '';
    const shortEl = document.getElementById('about-bio-short');
    const fullEl = document.getElementById('about-bio-full');
    const readBtn = document.getElementById('about-read-more-btn');

    // Determine truncation threshold (≈3 sentences or 400 chars)
    const truncLen = 450;
    const sentences = bio.split('. ');
    let shortBio = '';
    let fullBio = '';

    if (!bio) {
        if (shortEl) shortEl.textContent = 'No company description available.';
        if (fullEl) fullEl.classList.add('hidden');
        if (readBtn) readBtn.classList.add('hidden');
        return;
    }

    if (bio.length <= truncLen) {
        shortBio = bio;
    } else {
        // Take first ~3 sentences
        let accum = '';
        let cutAt = 0;
        for (let i = 0; i < sentences.length; i++) {
            accum += sentences[i] + '. ';
            if (accum.length > truncLen || i >= 2) { cutAt = i; break; }
        }
        shortBio = sentences.slice(0, cutAt + 1).join('. ').trim();
        fullBio = bio; // will show the full text on expand
    }

    if (shortEl) shortEl.textContent = shortBio;
    if (fullEl) fullEl.textContent = fullBio;

    if (fullBio && readBtn) {
        readBtn.classList.remove('hidden');
        let expanded = false;

        // Remove old listener by cloning
        const freshBtn = readBtn.cloneNode(true);
        readBtn.parentNode.replaceChild(freshBtn, readBtn);

        freshBtn.addEventListener('click', () => {
            expanded = !expanded;
            if (expanded) {
                if (shortEl) shortEl.classList.add('hidden');
                if (fullEl) fullEl.classList.remove('hidden');
                freshBtn.innerHTML = 'Show less <i class="fa-solid fa-chevron-up"></i>';
            } else {
                if (shortEl) shortEl.classList.remove('hidden');
                if (fullEl) fullEl.classList.add('hidden');
                freshBtn.innerHTML = 'Read more <i class="fa-solid fa-chevron-down"></i>';
            }
        });
    } else if (readBtn) {
        readBtn.classList.add('hidden');
    }
}

/* ============================================================
   Portfolio Validator
   ============================================================ */

// Store the full result set so filter tabs can re-render without re-fetching.
let _validateData = null;
let _vSortCol     = 'seq';   // default: original order
let _vSortDir     = 'asc';

function initValidate() {
    const dropzone  = document.getElementById('validate-dropzone');
    const fileInput = document.getElementById('validate-file-input');
    if (!dropzone || !fileInput) return;

    // Drag & drop — accept multiple files
    dropzone.addEventListener('dragover',  e => { e.preventDefault(); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', ()  => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', e => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        const files = [...e.dataTransfer.files].filter(f => f.name.match(/\.(xlsx|xls)$/i));
        if (files.length) {
            showValidateFileChips(files);
            handleValidateUploads(files);
        } else {
            showToast('Please drop .xlsx or .xls files only.', 'error');
        }
    });

    // Browse button — multiple
    fileInput.addEventListener('change', () => {
        const files = [...fileInput.files];
        if (files.length) {
            showValidateFileChips(files);
            handleValidateUploads(files);
        }
        fileInput.value = ''; // reset so same file can be re-selected
    });

    // Filter tabs
    document.querySelectorAll('.vf-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.vf-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            if (_validateData) renderValidateTable(_validateData, tab.dataset.filter);
        });
    });

    // Column sort headers
    document.querySelectorAll('.vs-sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.vsort;
            if (_vSortCol === col) {
                _vSortDir = _vSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                _vSortCol = col;
                _vSortDir = 'asc';
            }
            updateVSortIcons();
            const activeFilter = document.querySelector('.vf-tab.active');
            if (_validateData) renderValidateTable(_validateData, activeFilter ? activeFilter.dataset.filter : 'all');
        });
    });
}

function updateVSortIcons() {
    document.querySelectorAll('.vs-sortable').forEach(th => {
        const icon = th.querySelector('i.fa-solid');
        if (!icon) return;
        icon.className = 'fa-solid fa-sort';    // reset
        if (th.dataset.vsort === _vSortCol) {
            icon.className = `fa-solid ${_vSortDir === 'asc' ? 'fa-sort-up' : 'fa-sort-down'} vs-sort-active`;
        }
        th.classList.toggle('vs-th-active', th.dataset.vsort === _vSortCol);
    });
}

/* Show file chips in the dropzone with per-file status icons */
function showValidateFileChips(files) {
    const container = document.getElementById('validate-file-list');
    if (!container) return;
    container.classList.remove('hidden');
    container.innerHTML = '';
    files.forEach((f, i) => {
        const chip = document.createElement('div');
        chip.className = 'vfc-chip';
        chip.id = `vfc-${i}`;
        chip.innerHTML = `
            <i class="fa-solid fa-file-excel vfc-icon-file"></i>
            <span class="vfc-name">${f.name}</span>
            <i class="fa-solid fa-clock vfc-status" id="vfc-status-${i}" title="Pending"></i>
        `;
        container.appendChild(chip);
    });
}

function setChipStatus(idx, status) {
    const icon = document.getElementById(`vfc-status-${idx}`);
    if (!icon) return;
    icon.className = `fa-solid vfc-status vfc-${status}`;
    const map = { pending: 'fa-clock', loading: 'fa-spinner fa-spin', done: 'fa-circle-check', error: 'fa-circle-xmark' };
    icon.className = `fa-solid ${map[status] || 'fa-clock'} vfc-status vfc-${status}`;
}

/* Upload all files in parallel, merge results */
async function handleValidateUploads(files) {
    const resultsEl = document.getElementById('validate-results');
    resultsEl.classList.add('hidden');
    showToast(`Validating ${files.length} file${files.length > 1 ? 's' : ''}...`, 'info');

    // Launch all requests concurrently
    const promises = files.map((file, idx) => validateSingleFile(file, idx));
    const results  = await Promise.allSettled(promises);

    // Merge all successful results into one unified dataset
    const merged = {
        rows:        [],
        not_in_file: [],
        summary:     { total_in_file: 0, match: 0, mismatch: 0, not_in_db: 0, not_in_file: 0 }
    };

    let anySuccess = false;
    results.forEach((res, idx) => {
        if (res.status === 'fulfilled' && res.value) {
            anySuccess = true;
            const d    = res.value;
            const fname = files[idx].name;

            // Tag every row with source filename and push to raw list
            d.rows.forEach(r => merged.rows.push({ ...r, _source_file: fname }));
            d.not_in_file.forEach(r => merged.not_in_file.push({ ...r, _source: 'not_in_file', _source_file: '(DB only)' }));
        }
    });

    if (!anySuccess) {
        showToast('All files failed validation. Check the column format.', 'error');
        return;
    }

    // ── Deduplicate rows by stock_code ──────────────────────────────────────
    // Same stock across multiple files → one row.
    // qty_file is SUMMED, price_file is WEIGHTED-AVERAGED,
    // then status is RE-EVALUATED against DB values.
    const QTY_TOL   = 0.01;  // absolute units

    const rowMap = new Map(); // stock_code → { row, totalQty, weightedPriceSum }

    merged.rows.forEach(r => {
        const key      = r.stock_code;
        const fileQty  = r.qty_file   != null ? Number(r.qty_file)   : 0;
        const filePrice = r.price_file != null ? Number(r.price_file) : 0;

        if (!rowMap.has(key)) {
            rowMap.set(key, {
                row:               { ...r },
                totalQty:          fileQty,
                weightedPriceSum:  filePrice * fileQty,
            });
        } else {
            const entry = rowMap.get(key);

            // Sum quantities from all files
            entry.totalQty         += fileQty;
            entry.weightedPriceSum += filePrice * fileQty;

            // Merge source file label (e.g. "A.xlsx + B.xlsx")
            if (!entry.row._source_file.includes(r._source_file)) {
                entry.row._source_file += ' + ' + r._source_file;
            }
        }
    });

    // Finalise each merged row: apply summed qty, averaged price, re-evaluate status
    merged.rows = [...rowMap.values()].map(({ row, totalQty, weightedPriceSum }) => {
        row.qty_file = Math.round(totalQty);   // qty is always an integer

        // Weighted-average price (fall back to original if qty is 0)
        row.price_file = totalQty > 0
            ? weightedPriceSum / totalQty
            : row.price_file;

        // Re-evaluate status against DB values
        if (row.price_db != null) {
            const mismatches = [];

            if (row.qty_db != null && Math.abs(row.qty_file - row.qty_db) > QTY_TOL) {
                mismatches.push('qty');
            }

            row.mismatches = mismatches;
            if      (mismatches.length === 0) row.status = 'match';
            else if (mismatches.length === 1) row.status = `${mismatches[0]}_mismatch`;
            else                              row.status = 'multi_mismatch';
        }
        // If price_db is null the stock is not in DB — status stays 'not_in_db'

        return row;
    });

    // ── Deduplicate not_in_file (same DB record from multiple file results) ─
    const seenNIF = new Set();
    merged.not_in_file = merged.not_in_file.filter(r => {
        if (seenNIF.has(r.stock_code)) return false;
        seenNIF.add(r.stock_code);
        return true;
    });

    // ── Recompute summary from deduplicated rows ─────────────────────────────
    merged.summary.total_in_file = merged.rows.length;
    merged.summary.match         = merged.rows.filter(r => r.status === 'match').length;
    merged.summary.mismatch      = merged.rows.filter(r => r.status !== 'match' && r.status !== 'not_in_db').length;
    merged.summary.not_in_db     = merged.rows.filter(r => r.status === 'not_in_db').length;
    merged.summary.not_in_file   = merged.not_in_file.length;

    _validateData = merged;
    renderValidateResults(merged);
    showToast(`Validation complete! Processed ${files.length} file${files.length > 1 ? 's' : ''}.`, 'success');
}

async function validateSingleFile(file, idx) {
    setChipStatus(idx, 'loading');
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch('/api/stocks/validate', { method: 'POST', body: formData });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Validation failed.');
        }
        const data = await resp.json();
        setChipStatus(idx, 'done');
        return data;
    } catch (err) {
        setChipStatus(idx, 'error');
        showToast(`Error in "${file.name}": ${err.message}`, 'error');
        return null;
    }
}


function renderValidateResults(data) {
    const resultsEl = document.getElementById('validate-results');
    resultsEl.classList.remove('hidden');

    // Summary counts
    document.getElementById('vs-match-count').textContent   = data.summary.match;
    document.getElementById('vs-mismatch-count').textContent = data.summary.mismatch;
    document.getElementById('vs-notdb-count').textContent   = data.summary.not_in_db;
    document.getElementById('vs-notfile-count').textContent = data.summary.not_in_file;

    // Reset filter tabs to 'all'
    document.querySelectorAll('.vf-tab').forEach(t => t.classList.remove('active'));
    const allTab = document.querySelector('.vf-tab[data-filter="all"]');
    if (allTab) allTab.classList.add('active');

    renderValidateTable(data, 'all');
}

function renderValidateTable(data, filter) {
    const tbody = document.getElementById('validate-table-body');
    tbody.innerHTML = '';

    // Build the full list to display: rows from file + not_in_file rows
    let rows = [];

    if (filter === 'not_in_file') {
        data.not_in_file.forEach(r => {
            rows.push({ ...r, _source: 'not_in_file' });
        });
    } else {
        data.rows.forEach(r => {
            if (filter === 'all')                                               rows.push(r);
            else if (filter === 'mismatch' && r.status !== 'match' && r.status !== 'not_in_db') rows.push(r);
            else if (filter === 'not_in_db' && r.status === 'not_in_db')       rows.push(r);
        });
    }

    // ── Sort ──────────────────────────────────────────────────────────────────
    if (_vSortCol && _vSortCol !== 'seq') {
        const dir = _vSortDir === 'asc' ? 1 : -1;
        const numericCols = new Set(['price_file', 'price_db', 'qty_file', 'qty_db']);

        rows.sort((a, b) => {
            let va = a[_vSortCol];
            let vb = b[_vSortCol];

            if (numericCols.has(_vSortCol)) {
                va = va != null ? Number(va) : -Infinity;
                vb = vb != null ? Number(vb) : -Infinity;
                return (va - vb) * dir;
            }
            // String sort (stock_code, company_name, status)
            va = String(va ?? '').toLowerCase();
            vb = String(vb ?? '').toLowerCase();
            return va < vb ? -dir : va > vb ? dir : 0;
        });
    }
    // 'seq' (default) keeps the original insertion order.

    if (rows.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="text-center" style="padding:2.5rem;color:var(--text-muted);">
            <i class="fa-solid fa-inbox" style="font-size:2rem;display:block;margin-bottom:0.5rem;opacity:0.4;"></i>
            No records match this filter.
        </td></tr>`;
        return;
    }

    rows.forEach((r, idx) => {
        const tr = document.createElement('tr');

        // Determine status info
        let statusBadge, rowClass = '';
        if (r._source === 'not_in_file') {
            statusBadge = `<span class="validate-badge vb-notfile"><i class="fa-solid fa-file-circle-xmark"></i> Not in File</span>`;
            rowClass = 'vr-notfile';
        } else if (r.status === 'match') {
            statusBadge = `<span class="validate-badge vb-match"><i class="fa-solid fa-circle-check"></i> Match</span>`;
        } else if (r.status === 'not_in_db') {
            statusBadge = `<span class="validate-badge vb-notdb"><i class="fa-solid fa-circle-question"></i> Not in DB</span>`;
            rowClass = 'vr-notdb';
        } else {
            const labels = (r.mismatches || []).map(m => m === 'price' ? 'Price' : 'Qty').join(' + ');
            statusBadge = `<span class="validate-badge vb-mismatch"><i class="fa-solid fa-triangle-exclamation"></i> ${labels} Mismatch</span>`;
            rowClass = 'vr-mismatch';
        }

        // Helper: wrap a cell value in a highlight span if it's a mismatch field
        const h = (val, isMismatch) => isMismatch
            ? `<span class="validate-diff">${val}</span>`
            : val;

        const qtyMismatch   = r.mismatches && r.mismatches.includes('qty');

        const fmt  = v => (v != null ? `₹${Number(v).toFixed(2)}` : '—');
        const fmtQ = v => (v != null ? Math.round(Number(v)) : '—');

        if (r._source === 'not_in_file') {
            // Only DB columns available
            const sfLabel = r._source_file || '(DB only)';
            tr.innerHTML = `
                <td class="text-center">${idx + 1}</td>
                <td><strong>${r.stock_code}</strong></td>
                <td>${r.company_name || '—'}</td>
                <td class="text-center">${statusBadge}</td>
                <td class="text-right text-muted">—</td>
                <td class="text-right">${fmt(r.price_db)}</td>
                <td class="text-right text-muted">—</td>
                <td class="text-right">${fmtQ(r.qty_db)}</td>
                <td class="text-center">${r.exchange_db || '—'}</td>
                <td class="text-center"><span class="vfc-source-tag">${sfLabel}</span></td>
            `;
        } else {
            const sfLabel = r._source_file || '—';
            tr.innerHTML = `
                <td class="text-center">${idx + 1}</td>
                <td><strong>${r.stock_code}</strong></td>
                <td>${r.company_name || '—'}</td>
                <td class="text-center">${statusBadge}</td>
                <td class="text-right">${fmt(r.price_file)}</td>
                <td class="text-right">${fmt(r.price_db)}</td>
                <td class="text-right ${qtyMismatch ? 'vr-mismatch-cell' : ''}">${h(fmtQ(r.qty_file), qtyMismatch)}</td>
                <td class="text-right ${qtyMismatch ? 'vr-mismatch-cell' : ''}">${h(fmtQ(r.qty_db), qtyMismatch)}</td>
                <td class="text-center">${r.exchange_file || r.exchange_db || '—'}</td>
                <td class="text-center"><span class="vfc-source-tag">${sfLabel}</span></td>
            `;
        }

        if (rowClass) tr.classList.add(rowClass);
        tbody.appendChild(tr);
    });
}
