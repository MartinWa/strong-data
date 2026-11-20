document.querySelectorAll("[data-upload-form]").forEach(function (form) {
  const input = form.querySelector('input[type="file"]');
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
});
