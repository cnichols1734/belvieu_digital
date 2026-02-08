/**
 * WaaS Portal — Minimal vanilla JS
 *
 * - Smooth flash message auto-dismiss
 * - Confirm dialogs for destructive actions
 * - Copy to clipboard utility
 */

document.addEventListener("DOMContentLoaded", () => {
    // Auto-dismiss flash messages after 5 seconds with smooth animation
    document.querySelectorAll(".flash").forEach((el) => {
        setTimeout(() => {
            el.style.transition = "opacity 0.3s ease, transform 0.3s ease";
            el.style.opacity = "0";
            el.style.transform = "translateY(-4px)";
            setTimeout(() => el.remove(), 300);
        }, 5000);
    });

    // Confirm dialogs for forms with data-confirm attribute
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (e) => {
            const message = form.getAttribute("data-confirm");
            if (!confirm(message)) {
                e.preventDefault();
            }
        });
    });
});

/**
 * Copy text to clipboard — used for invite links in admin views.
 * Falls back to input.select() for older browsers.
 */
function copyInviteLink(inputId, btnId) {
    const input = document.getElementById(inputId);
    const btn = document.getElementById(btnId);

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(() => {
            btn.textContent = "Copied!";
            setTimeout(() => { btn.textContent = "Copy"; }, 2000);
        });
    } else {
        input.select();
        document.execCommand("copy");
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 2000);
    }
}
