/* The page's scrollbar stays invisible until the person scrolls (wheel, touch, scroll keys or dragging the bar),
   then shows in the site's colour and fades out about a second after the page rests (style.css: html.scrolling). */
(() => {
  const html = document.documentElement;
  const KEYS = ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "];
  let rest = 0, intent = 0, dragging = false;
  const meant = () => { intent = Date.now(); };
  const hide = () => { if (dragging) rest = setTimeout(hide, 900); else html.classList.remove("scrolling"); };
  addEventListener("wheel", meant, { passive: true });
  addEventListener("touchmove", meant, { passive: true });
  addEventListener("keydown", (e) => { if (KEYS.includes(e.key)) meant(); });
  addEventListener("pointerdown", (e) => { if (e.target === html) { dragging = true; meant(); } }); // the bar itself
  addEventListener("pointerup", () => { dragging = false; });
  addEventListener("scroll", () => {
    if (!dragging && Date.now() - intent > 1000) return;
    html.classList.add("scrolling");
    clearTimeout(rest);
    rest = setTimeout(hide, 900);
  }, { passive: true });
})();
