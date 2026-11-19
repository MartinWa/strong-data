document.querySelectorAll("[data-delete-zone]").forEach(function (zone) {
  var start = zone.querySelector("[data-delete-start]");
  var form = zone.querySelector("[data-delete-form]");
  if (!start || !form) return;

  start.addEventListener("click", function (event) {
    event.preventDefault();
    start.hidden = true;
    form.hidden = false;
    var submit = form.querySelector('button[type="submit"]');
    if (submit) submit.focus();
  });
});
