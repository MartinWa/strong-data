const SCROLL_KEY = "muscles-scroll";
const muscleForm = document.querySelector("[data-muscle-form]");

if (muscleForm) {
  const rows = Array.from(document.querySelectorAll("[data-muscle-row]"));
  const savedScroll = window.sessionStorage.getItem(SCROLL_KEY);

  if (savedScroll !== null) {
    window.sessionStorage.removeItem(SCROLL_KEY);
    const restore = function () {
      window.scrollTo(0, Number(savedScroll));
    };
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(restore);
    });
    window.addEventListener("load", restore, { once: true });
  }

  function refreshSave() {
    let dirty = false;
    rows.forEach(function (row) {
      const select = row.querySelector(".muscle-select");
      const input = row.querySelector(".muscle-custom");
      const value = row.classList.contains("is-custom") ? input.value : select.value;
      const rowDirty = value !== select.dataset.initial;
      row.classList.toggle("is-dirty", rowDirty);
      dirty = dirty || rowDirty;
    });
    muscleForm.classList.toggle("is-dirty", dirty);
  }

  rows.forEach(function (row) {
    const select = row.querySelector(".muscle-select");
    const input = row.querySelector(".muscle-custom");
    const back = row.querySelector("[data-muscle-back]");

    select.addEventListener("change", function () {
      const isCustom = select.value === select.dataset.custom;
      row.classList.toggle("is-custom", isCustom);
      if (isCustom) input.focus();
      refreshSave();
    });

    input.addEventListener("input", refreshSave);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") event.preventDefault();
    });

    if (!back) return;
    back.addEventListener("click", function () {
      row.classList.remove("is-custom");
      select.value = select.dataset.initial;
      select.focus();
      refreshSave();
    });
  });

  muscleForm.addEventListener("reset", function () {
    window.requestAnimationFrame(function () {
      rows.forEach(function (row) {
        const select = row.querySelector(".muscle-select");
        const input = row.querySelector(".muscle-custom");
        row.classList.remove("is-custom");
        select.value = select.dataset.initial;
        input.value = "";
      });
      refreshSave();
    });
  });

  muscleForm.addEventListener("submit", function () {
    window.sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
  });

  refreshSave();
}
