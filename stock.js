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

    body.addEventListener("input", event => {
        const input = event.target.closest(".actual-input");

        if (!input) {
            return;
        }

        const key = getActualKey(input.dataset.code);

        if (input.value === "") {
            delete state.actual[key];
        } else {
            state.actual[key] = input.value;
        }

        saveActual();
        render();
    });

    searchInput.addEventListener("input", applyFilters);
    categoryFilter.addEventListener("change", applyFilters);
    branchFilter.addEventListener("change", render);

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
