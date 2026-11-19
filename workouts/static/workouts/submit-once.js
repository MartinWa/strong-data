document.querySelectorAll("[data-submit-once]").forEach(function (button) {
  const form = button.form;
  if (!form) return;

  form.addEventListener("submit", function () {
    button.disabled = true;
    button.textContent = "Importing…";
  });
});
