(function () {
  const items = Array.from(document.querySelectorAll("[data-print-open]"));
  if (!items.length) return;

  let opened = [];

  window.addEventListener("beforeprint", function () {
    opened = items.filter(function (item) {
      return !item.open;
    });
    opened.forEach(function (item) {
      item.open = true;
    });
  });

  window.addEventListener("afterprint", function () {
    opened.forEach(function (item) {
      item.open = false;
    });
    opened = [];
  });
})();
