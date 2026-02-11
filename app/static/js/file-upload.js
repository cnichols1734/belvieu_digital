/**
 * File upload zone — drag-and-drop, preview, remove.
 * Shared across ticket new, ticket detail (portal + admin).
 */
(function () {
  function iconSvg(type) {
    if (type && type.startsWith("image/")) {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:18px;height:18px;flex-shrink:0;color:var(--gray-500);"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M2.25 18V6a2.25 2.25 0 012.25-2.25h15A2.25 2.25 0 0121.75 6v12A2.25 2.25 0 0119.5 20.25h-15A2.25 2.25 0 012.25 18z"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:18px;height:18px;flex-shrink:0;color:var(--gray-500);"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>';
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  window.initUploadZone = function (zoneId, previewId) {
    var zone = document.getElementById(zoneId);
    if (!zone) return;
    var input = zone.querySelector(".file-upload-input");
    var preview = document.getElementById(previewId);
    var selectedFiles = new DataTransfer();

    function updatePreview() {
      preview.innerHTML = "";
      for (var i = 0; i < selectedFiles.files.length; i++) {
        (function (idx) {
          var file = selectedFiles.files[idx];
          var item = document.createElement("div");
          item.className = "file-preview-item";

          // Icon
          var iconWrap = document.createElement("span");
          iconWrap.innerHTML = iconSvg(file.type);
          item.appendChild(iconWrap);

          // Name + size
          var info = document.createElement("span");
          var shortName =
            file.name.length > 28
              ? file.name.substring(0, 25) + "..."
              : file.name;
          info.textContent = shortName + "  (" + humanSize(file.size) + ")";
          info.style.fontSize = "0.8rem";
          item.appendChild(info);

          // Remove button
          var remove = document.createElement("button");
          remove.type = "button";
          remove.className = "file-preview-remove";
          remove.textContent = "\u00d7";
          remove.addEventListener("click", function (e) {
            e.stopPropagation();
            var dt = new DataTransfer();
            for (var j = 0; j < selectedFiles.files.length; j++) {
              if (j !== idx) dt.items.add(selectedFiles.files[j]);
            }
            selectedFiles = dt;
            input.files = selectedFiles.files;
            updatePreview();
          });
          item.appendChild(remove);
          preview.appendChild(item);
        })(i);
      }
    }

    input.addEventListener("change", function () {
      for (var i = 0; i < this.files.length; i++) {
        selectedFiles.items.add(this.files[i]);
      }
      input.files = selectedFiles.files;
      updatePreview();
    });

    ["dragenter", "dragover"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.remove("dragover");
      });
    });
    zone.addEventListener("drop", function (e) {
      for (var i = 0; i < e.dataTransfer.files.length; i++) {
        selectedFiles.items.add(e.dataTransfer.files[i]);
      }
      input.files = selectedFiles.files;
      updatePreview();
    });
  };

  // Lightbox for ticket attachment images
  window.initLightbox = function () {
    document
      .querySelectorAll(".ticket-attachment-img")
      .forEach(function (link) {
        link.addEventListener("click", function (e) {
          e.preventDefault();
          var overlay = document.createElement("div");
          overlay.className = "lightbox-overlay";
          var close = document.createElement("button");
          close.className = "lightbox-close";
          close.innerHTML = "&times;";
          var img = document.createElement("img");
          img.src = this.href;
          img.alt = this.querySelector("img").alt;
          overlay.appendChild(close);
          overlay.appendChild(img);
          document.body.appendChild(overlay);
          document.body.style.overflow = "hidden";
          function closeLightbox() {
            overlay.remove();
            document.body.style.overflow = "";
          }
          overlay.addEventListener("click", closeLightbox);
          close.addEventListener("click", closeLightbox);
          document.addEventListener("keydown", function esc(ev) {
            if (ev.key === "Escape") {
              closeLightbox();
              document.removeEventListener("keydown", esc);
            }
          });
        });
      });
  };
})();
