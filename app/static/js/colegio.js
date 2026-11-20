// Página de circulares: menú móvil, año del pie y botón de menú
(() => {
    const anio = document.getElementById('anio');
    if (anio) anio.textContent = new Date().getFullYear();

    const boton = document.getElementById('menu-toggle');
    const menu = document.getElementById('menu');
    if (!boton || !menu) return;

    boton.addEventListener('click', () => {
        const abierto = menu.classList.toggle('abierto');
        boton.setAttribute('aria-expanded', String(abierto));
    });
})();
