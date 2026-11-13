(() => {
  "use strict";
  const slides = Array.from(document.querySelectorAll("[data-deck-slide]"));
  const previous = document.querySelector("[data-deck-prev]");
  const next = document.querySelector("[data-deck-next]");
  const position = document.querySelector("[data-deck-position]");
  const last = slides.length - 1;
  let index = 0;

  function show(target) {
    index = Math.max(0, Math.min(target, last));
    slides.forEach((slide, page) => { slide.hidden = page !== index; });
    previous.disabled = index === 0;
    next.disabled = index === last;
    position.textContent = `${index + 1} / ${slides.length}`;
  }

  previous.addEventListener("click", () => show(index - 1));
  next.addEventListener("click", () => show(index + 1));
  document.addEventListener("keydown", event => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
        event.isComposing || event.target?.closest?.("input,textarea,select,[contenteditable]")) return;
    const targets = {ArrowLeft:index - 1, ArrowRight:index + 1, Home:0, End:last};
    if (!Object.hasOwn(targets,event.key)) return;
    event.preventDefault();
    show(targets[event.key]);
  });
  show(0);
})();
