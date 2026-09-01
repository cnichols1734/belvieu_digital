/**
 * WaaS Portal — theme, flashes, confirms, clipboard.
 */

(function () {
    var KEY = "bd-theme";
    var html = document.documentElement;

    function apply(theme) {
        html.dataset.theme = theme === "light" ? "light" : "dark";
    }

    function toggle() {
        html.classList.add("bd-theme-transition");
        var next = html.dataset.theme === "dark" ? "light" : "dark";
        apply(next);
        try {
            localStorage.setItem(KEY, next);
        } catch (e) { /* ignore */ }
        window.setTimeout(function () {
            html.classList.remove("bd-theme-transition");
        }, 240);
    }

    ["bdThemeToggle", "bdThemeToggleMobile"].forEach(function (id) {
        var btn = document.getElementById(id);
        if (btn) btn.addEventListener("click", toggle);
    });

    window.addEventListener("storage", function (e) {
        if (e.key === KEY && e.newValue) apply(e.newValue);
    });
})();

(function () {
    var KEY = "bd-sidebar-expanded";
    var html = document.documentElement;

    function persist(expanded) {
        try {
            localStorage.setItem(KEY, expanded ? "true" : "false");
        } catch (e) { /* ignore */ }
    }

    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var isDesktop = window.matchMedia("(min-width: 768px)").matches;
            if (isDesktop) {
                var next = !html.classList.contains("sidebar-expanded");
                html.classList.toggle("sidebar-expanded", next);
                persist(next);
            } else {
                html.classList.toggle("sidebar-open");
            }
        });
    });

    var backdrop = document.getElementById("sidebarBackdrop");
    if (backdrop) {
        backdrop.addEventListener("click", function () {
            html.classList.remove("sidebar-open");
        });
    }
})();

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".flash").forEach(function (el) {
        setTimeout(function () {
            el.classList.add("flash-dismissing");
            el.addEventListener("animationend", function () { el.remove(); }, { once: true });
        }, 5000);
    });

    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            var message = form.getAttribute("data-confirm");
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });
});

function copyInviteLink(inputId, btnId) {
    var input = document.getElementById(inputId);
    var btn = document.getElementById(btnId);

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(function () {
            btn.textContent = "Copied!";
            setTimeout(function () { btn.textContent = "Copy"; }, 2000);
        });
    } else {
        input.select();
        document.execCommand("copy");
        btn.textContent = "Copied!";
        setTimeout(function () { btn.textContent = "Copy"; }, 2000);
    }
}
