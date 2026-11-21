(function () {
  const KEY = "strong-data:theme";
  const root = document.documentElement;
  const button = document.querySelector("[data-theme-toggle]");
  const query = window.matchMedia("(prefers-color-scheme: dark)");

  function pinned() {
    try {
      const value = window.localStorage.getItem(KEY);
      return value === "dark" || value === "light" ? value : null;
    } catch (error) {
      return null;
    }
  }

  function remember(value) {
    try {
      window.localStorage.setItem(KEY, value);
    } catch (error) {
      return;
    }
  }

  function display() {
    if (!button) return;
    const dark = root.dataset.theme === "dark";
    button.hidden = false;
    button.setAttribute("aria-pressed", dark ? "true" : "false");
    button.title = dark ? "Switch to light theme" : "Switch to dark theme";
  }

  if (button) {
    button.addEventListener("click", function () {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      remember(next);
      display();
    });
  }

  query.addEventListener("change", function (event) {
    if (pinned()) return;
    root.dataset.theme = event.matches ? "dark" : "light";
    display();
  });

  display();
})();
