document.querySelectorAll("[data-upload-form]").forEach(function (form) {
  const input = form.querySelector('input[type="file"]');
  const dropzone = form.querySelector("[data-dropzone]");
  const error = form.querySelector("[data-client-error]");
  const field = input.closest(".field");
  const maxBytes = Number(form.dataset.maxBytes);
  const tooLarge = form.dataset.tooLarge;
  const describedBy = input.getAttribute("aria-describedby") || "";

  function fail(message) {
    field.classList.add("field-invalid");
    input.setAttribute("aria-invalid", "true");
    error.textContent = message;
    error.hidden = false;
    input.setAttribute("aria-describedby", (describedBy + " " + error.id).trim());
    input.focus();
  }

  function recover() {
    field.classList.remove("field-invalid");
    input.removeAttribute("aria-invalid");
    error.textContent = "";
    error.hidden = true;
    input.setAttribute("aria-describedby", describedBy);
  }

  window.addEventListener("pageshow", function () {
    delete form.dataset.submitting;
  });

  input.addEventListener("change", function () {
    if (form.dataset.submitting || !input.files.length) return;
    if (maxBytes && input.files[0].size > maxBytes) {
      fail(tooLarge);
      return;
    }
    recover();
    form.dataset.submitting = "true";
    form.requestSubmit();
  });

  function drop(files) {
    if (!files || !files.length) return;
    const transfer = new DataTransfer();
    transfer.items.add(files[0]);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  if (!dropzone) return;

  function hasFiles(event) {
    return Array.from(event.dataTransfer.types || []).includes("Files");
  }

  function canHandle(event) {
    return hasFiles(event) && typeof DataTransfer === "function";
  }

  ["dragenter", "dragover"].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      if (!canHandle(event)) return;
      event.preventDefault();
      dropzone.classList.add("is-dragging");
    });
  });

  dropzone.addEventListener("dragleave", function (event) {
    if (dropzone.contains(event.relatedTarget)) return;
    dropzone.classList.remove("is-dragging");
  });

  dropzone.addEventListener("drop", function (event) {
    dropzone.classList.remove("is-dragging");
    if (!canHandle(event)) return;
    event.preventDefault();
    drop(event.dataTransfer.files);
  });
});
