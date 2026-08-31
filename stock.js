(() => {
    "use strict";

    const state = {
        products: [],
        filtered: [],
        actual: {}
    };

    const $ = (id) => document.getElementById(id);

    const body = $("stockBody");
    const searchInput = $("searchInput");
    const categoryFilter = $("categoryFilter");
    const branchFilter = $("branchFilter");
    const stockDate = $("stockDate");
    stockDate.value = todayIso();

    function text(value) {
        return value == null ? "" : String(value);
    }

    function number(value) {
        const n = Number(value);
        return Number.isFinite(n) ? n : 0;
    }

    function formatNumber(value) {
        return number(value).toLocaleString("th-TH", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2
        });
    }

    function escapeHtml(value) {
        return text(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function getActualKey(code) {
        return `${branchFilter.value}:${code}`;
    }

    function getActual(code) {
        const key = getActualKey(code);
        return Object.prototype.hasOwnProperty.call(state.actual, key)
            ? state.actual[key]
            : "";
    }

    function loadSavedActual() {
        try {
            state.actual = JSON.parse(
                localStorage.getItem("stock_actual_counts") || "{}"
            );
        } catch {
            state.actual = {};
        }
    }

    function saveActual() {
        localStorage.setItem(
            "stock_actual_counts",
            JSON.stringify(state.actual)
        );
    }

    function systemStock(product) {
        return (
            number(product.opening) +
            number(product.processed) +
            number(product.received) -
            number(product.sold)
        );
    }

    function variance(product) {
        const actual = getActual(product.code);

        if (actual === "") {
            return null;
        }

        return number(actual) - systemStock(product);
    }

    function statusInfo(product) {
        const diff = variance(product);

        if (diff === null) {
            return {
                label: "รอนับจริง",
                className: "wait"
            };
        }

        if (Math.abs(diff) < 0.000001) {
            return {
                label: "ตรง",
                className: "ok"
            };
        }

        return {
            label: "มีผลต่าง",
            className: "diff"
        };
    }

    function renderCategories() {
        const categories = [
            ...new Set(
                state.products
                    .map(p => text(p.category).trim())
                    .filter(Boolean)
            )
        ].sort((a, b) => a.localeCompare(b, "th"));

        categoryFilter.innerHTML =
            '<option value="">ทั้งหมด</option>' +
            categories.map(category =>
                `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`
            ).join("");
    }

    function applyFilters() {
        const query = searchInput.value.trim().toLowerCase();
        const category = categoryFilter.value;

        state.filtered = state.products.filter(product => {
            const matchQuery =
                !query ||
                text(product.code).toLowerCase().includes(query) ||
                text(product.name).toLowerCase().includes(query);

            const matchCategory =
                !category ||
                text(product.category) === category;

            return matchQuery && matchCategory;
        });

        render();
    }

    function render() {
        const rows = state.filtered;

        body.innerHTML = rows.map(product => {
            const system = systemStock(product);
            const actual = getActual(product.code);
            const diff = variance(product);
            const status = statusInfo(product);

            const diffClass =
                diff === null ? "" :
                diff > 0 ? "variance-positive" :
                diff < 0 ? "variance-negative" : "";

            return `
                <tr>
                    <td><strong>${escapeHtml(product.code)}</strong></td>

                    <td>${escapeHtml(product.name)}</td>

                    <td>${escapeHtml(product.category || "-")}</td>

                    <td>${escapeHtml(product.unit || "-")}</td>

                    <td class="number">${formatNumber(product.opening)}</td>

                    <td class="number">${formatNumber(product.processed)}</td>

                    <td class="number">${formatNumber(product.received)}</td>

                    <td class="number">${formatNumber(product.sold)}</td>

                    <td class="number">
                        <strong>${formatNumber(system)}</strong>
                    </td>

                    <td>
                        <input
                            class="actual-input"
                            type="number"
                            step="0.01"
                            data-code="${escapeHtml(product.code)}"
                            value="${escapeHtml(actual)}"
                            placeholder="นับจริง"
                        >
                    </td>

                    <td class="number ${diffClass}">
                        ${diff === null ? "-" : formatNumber(diff)}
                    </td>

                    <td>
                        <span class="status ${status.className}">
                            ${status.label}
                        </span>
                    </td>
                </tr>
            `;
        }).join("");

        $("totalProducts").textContent =
            state.products.length.toLocaleString("th-TH");

        $("visibleProducts").textContent =
            rows.length.toLocaleString("th-TH");

        const counted = state.products.filter(product =>
            getActual(product.code) !== ""
        ).length;

        const differences = state.products.filter(product => {
            const diff = variance(product);
            return diff !== null && Math.abs(diff) > 0.000001;
        }).length;

        $("countedProducts").textContent =
            counted.toLocaleString("th-TH");

        $("varianceProducts").textContent =
            differences.toLocaleString("th-TH");

        $("resultText").textContent =
            `แสดง ${rows.length.toLocaleString("th-TH")} จาก ${state.products.length.toLocaleString("th-TH")} รายการ`;
    }

    body.addEventListener("change", async event => {
        const input = event.target.closest(".actual-input");

        if (!input) {
            return;
        }

        const product = state.products.find(
            item => item.code === input.dataset.code
        );

        if (!product) {
            return;
        }

        const key = getActualKey(product.code);

        if (input.value === "") {
            delete state.actual[key];
            saveActual();
            render();
            return;
        }

        state.actual[key] = input.value;
        saveActual();
        render();

        input.disabled = true;

        try {
            await saveCount(
                product,
                input.value
            );
        } catch (error) {
            console.error(error);
            alert(error.message);
        } finally {
            input.disabled = false;
        }
    });

    searchInput.addEventListener("input", applyFilters);
    categoryFilter.addEventListener("change", applyFilters);
    stockDate.addEventListener("change", async () => {
        try {
            await loadStockBackend();
        } catch (error) {
            console.error(error);
        }
        render();
    });

    branchFilter.addEventListener("change", async () => {
        try {
            await loadStockBackend();
        } catch (error) {
            console.error(error);
        }
        render();
    });

    $("printBtn").addEventListener("click", () => {
        window.print();
    });

    $("exportBtn").addEventListener("click", () => {
        const headers = [
            "รหัสสินค้า",
            "ชื่อสินค้า",
            "หมวดสินค้า",
            "หน่วย",
            "ตั้งต้น",
            "แปรรูป",
            "รับสินค้า",
            "ขายจาก POS",
            "คงเหลือตามระบบ",
            "นับจริง",
            "ผลต่าง"
        ];

        const lines = [headers];

        state.filtered.forEach(product => {
            const actual = getActual(product.code);
            const diff = variance(product);

            lines.push([
                product.code,
                product.name,
                product.category || "",
                product.unit || "",
                number(product.opening),
                number(product.processed),
                number(product.received),
                number(product.sold),
                systemStock(product),
                actual,
                diff === null ? "" : diff
            ]);
        });

        const csv = lines.map(row =>
            row.map(value =>
                `"${text(value).replaceAll('"', '""')}"`
            ).join(",")
        ).join("\r\n");

        const blob = new Blob(
            ["\ufeff" + csv],
            { type: "text/csv;charset=utf-8" }
        );

        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");

        a.href = url;
        a.download =
            `stock-${branchFilter.value}-${new Date().toISOString().slice(0,10)}.csv`;

        a.click();

        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    $("importBtn").addEventListener("click", () => {
        $("posFile").click();
    });

    $("posFile").addEventListener("change", event => {
        const file = event.target.files?.[0];

        if (!file) {
            return;
        }

        alert(
            "เลือกไฟล์ " + file.name +
            " แล้ว\n\nขั้นนี้หน้า Stock พร้อมแล้ว แต่การอ่านยอดจากไฟล์ POS จะเชื่อมกับ Backend ในขั้นถัดไป"
        );

        event.target.value = "";
    });

    function todayIso() {
        const d = new Date();
        const offset = d.getTimezoneOffset();
        return new Date(
            d.getTime() - offset * 60000
        ).toISOString().slice(0, 10);
    }

    async function loadPosStockData() {
        const response = await fetch(
            "/stock_pos_import.json?ts=" + Date.now(),
            { cache: "no-store" }
        );

        if (!response.ok) {
            throw new Error("ไม่พบข้อมูลนำเข้าจาก POS");
        }

        const data = await response.json();

        const byCode = new Map();

        (data.products || []).forEach(item => {
            byCode.set(String(item.code), item);
        });

        state.products.forEach(product => {
            const pos = byCode.get(String(product.code));

            if (!pos) {
                return;
            }

            product.opening =
                Number(pos.opening || 0);

            product.processed =
                Number(pos.processed || 0);

            product.sold =
                (stockDate.value || todayIso()) === String(data.report_date || "")
                    ? Number(pos.sold || 0)
                    : 0;

            product.posReceived =
                Number(pos.pos_received || 0);

            product.posClosing =
                Number(pos.pos_closing || 0);
        });

        state.posImport = data;
    }

    const RECEIVING_NAME_ALIASES = {
        "เนื้อแดง": "เนื้อแดง (ไหล่)"
    };

    function receivingNameForStock(productName) {
        for (const [receivingName, stockName] of Object.entries(RECEIVING_NAME_ALIASES)) {
            if (stockName === productName) {
                return receivingName;
            }
        }
        return productName;
    }

    async function loadStockBackend() {
        const branch = branchFilter.value;

        const response = await fetch(
            "/api/stock?date=" +
            encodeURIComponent(stockDate.value || todayIso()) +
            "&branch=" +
            encodeURIComponent(branch),
            { cache: "no-store" }
        );

        if (!response.ok) {
            throw new Error(
                "โหลดข้อมูล Stock Backend ไม่สำเร็จ"
            );
        }

        const data = await response.json();

        const received =
            data.received_by_product_name || {};

        const counts =
            data.counts || {};

        state.products.forEach(product => {

            product.received =
                Number(received[receivingNameForStock(product.name)] || 0);

            const saved = counts[product.code];

            if (saved) {
                state.actual[
                    branch + ":" + product.code
                ] = String(saved.actual);
            }
        });

        saveActual();
    }

    async function saveCount(product, actualValue) {

        const payload = {
            date: stockDate.value || todayIso(),
            branch: branchFilter.value,
            product_code: product.code,
            product_name: product.name,
            actual_quantity: Number(actualValue),
            system_quantity: systemStock(product)
        };

        const response = await fetch(
            "/api/stock/count",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.message ||
                "บันทึกนับจริงไม่สำเร็จ"
            );
        }

        return result;
    }

    async function init() {
        loadSavedActual();

        try {
            const response = await fetch(
                "/stock_catalog.json?ts=" + Date.now(),
                { cache: "no-store" }
            );

            if (!response.ok) {
                throw new Error(
                    "โหลด stock_catalog.json ไม่สำเร็จ"
                );
            }

            const catalog = await response.json();

            state.products = (catalog.products || []).map(product => ({
                code: text(product.code),
                name: text(product.name),
                category: text(product.category),
                unit: text(product.unit),

                // Backend/POS will populate these in the next step.
                opening: number(product.opening),
                processed: number(product.processed),
                received: number(product.received),
                sold: number(product.sold)
            }));

            renderCategories();

            try {
                await loadPosStockData();
            } catch (posError) {
                console.error(posError);
            }

            try {
                await loadStockBackend();
            } catch (backendError) {
                console.error(backendError);
            }

            applyFilters();

        } catch (error) {
            console.error(error);

            $("resultText").textContent =
                "โหลดข้อมูลสินค้าไม่สำเร็จ";

            body.innerHTML = `
                <tr>
                    <td colspan="12">
                        ไม่สามารถโหลด stock_catalog.json ได้
                    </td>
                </tr>
            `;
        }
    }

    init();
})();
