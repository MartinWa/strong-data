document.querySelectorAll("[data-submit-once]").forEach(function (button) {
  const form = button.form;
  if (!form) return;

  form.addEventListener("submit", function (event) {
    if (event.submitter && event.submitter !== button) return;
    button.disabled = true;
    button.textContent = "Importing…";
  });
});
