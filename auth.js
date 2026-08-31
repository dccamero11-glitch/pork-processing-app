function loadSharedReportTools(){if(!document.querySelector('link[href^="print.css"]')){const link=document.createElement('link');link.rel='stylesheet';link.href='print.css?v=20260827';document.head.appendChild(link)}if(!document.querySelector('script[src^="report-actions.js"]')){const script=document.createElement('script');script.src='report-actions.js?v=20260827';document.body.appendChild(script)}}
window.authReady=fetch("/api/me").then(async response=>{if(response.status===401){location.href="/login.html";throw Error("login required")}const user=await response.json();window.currentUser=user;const header=document.querySelector("header");if(header){const nav=header.querySelector('nav');if(nav&&!nav.querySelector('a[href="/order-summary.html"]')){const link=document.createElement('a');link.className='nav-link';link.href='/order-summary.html';link.textContent='สรุปการสั่งสินค้า';const before=nav.querySelector('a[href="/selling-price.html"]');nav.insertBefore(link,before)}if(user.role==='admin'&&nav&&!nav.querySelector('a[href="/admin-users.html"]')){const adminLink=document.createElement('a');adminLink.className='nav-link';adminLink.href='/admin-users.html';adminLink.textContent='จัดการผู้ใช้';nav.appendChild(adminLink)}const panel=document.createElement("div");panel.className="user-panel";panel.innerHTML=`<span>${user.role==="admin"?"Admin":`Manager · ${user.branch}`}</span><button class="logout-button">ออกจากระบบ</button>`;panel.querySelector("button").onclick=async()=>{await fetch("/api/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});location.href="/login.html"};header.appendChild(panel)}const applyAccess=()=>{if(user.role==="manager"){document.querySelectorAll("select").forEach(select=>{if(["priceBranch","overviewBranch","reportBranch","historyBranch","orderBranch","orderHistoryBranch","sellingBranch","sellingHistoryBranch"].includes(select.id)){[...select.options].forEach(option=>option.hidden=option.value!==user.branch&&option.text!==user.branch);select.value=user.branch;select.dispatchEvent(new Event("change"))}});document.querySelectorAll("[data-branch]").forEach(button=>button.hidden=button.dataset.branch!==user.branch)}};applyAccess();setTimeout(applyAccess,300);if(!location.pathname.endsWith('/stock.html')){loadSharedReportTools();}return user});

// RECEIVING_NAV_RESTORE
(function () {
    function ensureReceivingNavigation() {
        document.querySelectorAll("nav").forEach(function (nav) {
            var currentPath = window.location.pathname;

            function addNavLink(href, text) {
                if (nav.querySelector('a[href="' + href + '"]')) return;

                var link = document.createElement("a");
                link.href = href;
                link.textContent = text;
                link.className = "nav-link";

                if (currentPath === href) {
                    link.classList.add("active");
                }

                var before =
                    nav.querySelector('a[href="/order-summary.html"]') ||
                    nav.querySelector('a[href="/selling-price.html"]');

                if (before) {
                    nav.insertBefore(link, before);
                } else {
                    nav.appendChild(link);
                }
            }

            addNavLink("/receiving.html", "รับสินค้าเข้า");
            addNavLink("/receiving-history.html", "ประวัติรับสินค้า");
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", ensureReceivingNavigation);
    } else {
        ensureReceivingNavigation();
    }
})();

// STOCK_NAV_RESTORE
(function () {
    function ensureStockNavigation() {
        document.querySelectorAll("nav").forEach(function (nav) {

            if (nav.querySelector('a[href="/stock.html"]')) {
                return;
            }

            var link = document.createElement("a");
            link.href = "/stock.html";
            link.textContent = "สต๊อก";

            var receivingHistory =
                nav.querySelector('a[href="/receiving-history.html"]');

            var orderSummary =
                nav.querySelector('a[href="/order-summary.html"]');

            if (
                receivingHistory &&
                receivingHistory.nextSibling
            ) {
                nav.insertBefore(
                    link,
                    receivingHistory.nextSibling
                );
            } else if (orderSummary) {
                nav.insertBefore(
                    link,
                    orderSummary.nextSibling
                );
            } else {
                nav.appendChild(link);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            ensureStockNavigation
        );
    } else {
        ensureStockNavigation();
    }
})();
