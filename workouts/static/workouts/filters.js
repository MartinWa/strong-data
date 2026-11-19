(function () {
  const form = document.querySelector("[data-filter-form]");
  if (!form) return;

  const search = form.querySelector('input[name="q"]');
  const submit = form.querySelector('button[type="submit"]');
  const storageKey = "strong-data:filter-focus";
  const debounceMs = 350;
  let timer = null;
  let composing = false;

  function serialize() {
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of Array.from(params)) {
      if (!value.trim()) params.delete(key);
    }
    params.sort();
    return params.toString();
  }

  let last = serialize();

  function apply(origin) {
    if (composing) return;
    const query = serialize();
    if (query === last) return;
    last = query;
    if (origin === "search" && search) {
      sessionStorage.setItem(storageKey, "q");
    }
    window.location.assign(query ? form.action + "?" + query : form.action);
  }

  function scheduleApply() {
    window.clearTimeout(timer);
    timer = window.setTimeout(function () {
      apply("search");
    }, debounceMs);
  }

  if (submit) submit.hidden = true;

  form.addEventListener("change", function (event) {
    if (search && event.target === search) return;
    apply("control");
  });

  if (search) {
    search.addEventListener("compositionstart", function () {
      composing = true;
      window.clearTimeout(timer);
    });
    search.addEventListener("compositionend", function () {
      composing = false;
      scheduleApply();
    });
    search.addEventListener("input", function () {
      if (composing) return;
      scheduleApply();
    });
    search.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || event.isComposing || event.keyCode === 229 || composing)
        return;
      event.preventDefault();
      window.clearTimeout(timer);
      apply("search");
    });
  }

  if (sessionStorage.getItem(storageKey) === "q" && search) {
    sessionStorage.removeItem(storageKey);
    search.focus();
    const end = search.value.length;
    search.setSelectionRange(end, end);
  }
})();
