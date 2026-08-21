// La CSP interdit style-src 'unsafe-inline', donc un attribut style= ecrit dans
// une template string est ignore par le navigateur. En revanche une ecriture
// JS sur element.style n'est pas concernee : les templates portent leurs
// styles dans data-s, et cet observateur les recopie dans .style a l'insertion.
// L'attribut est retire au passage, donc chaque noeud n'est traite qu'une fois.
// Assouplir la CSP a la place rendrait ce fichier inutile — et l'app injectable.

function apply(el) {
  if (!el || el.nodeType !== 1) return;
  if (el.hasAttribute('data-s')) {
    el.style.cssText = el.getAttribute('data-s');
    el.removeAttribute('data-s');
  }
  if (el.querySelectorAll) {
    for (const k of el.querySelectorAll('[data-s]')) {
      k.style.cssText = k.getAttribute('data-s');
      k.removeAttribute('data-s');
    }
  }
}

const observer = new MutationObserver((mutations) => {
  for (const m of mutations) {
    for (const node of m.addedNodes) apply(node);
  }
});

observer.observe(document.documentElement, { childList: true, subtree: true });
apply(document.documentElement);
