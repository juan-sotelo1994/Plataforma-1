// Paneles: menú móvil, expandir o contraer el árbol y ventanas de formulario
(() => {
    const boton = document.getElementById('menu-btn');
    const menu = document.getElementById('sidebar');
    if (boton && menu) {
        boton.addEventListener('click', () => {
            const abierto = menu.classList.toggle('abierto');
            boton.setAttribute('aria-expanded', String(abierto));
        });
    }

    const setTodos = (abierto) => {
        document.querySelectorAll('.arbol details').forEach((d) => { d.open = abierto; });
    };

    const expandir = document.getElementById('expandir-todo');
    if (expandir) expandir.addEventListener('click', () => setTodos(true));

    const contraer = document.getElementById('contraer-todo');
    if (contraer) contraer.addEventListener('click', () => setTodos(false));

    // Botones con data-abrir="id" abren la ventana; data-cerrar cierra la ventana que la contiene
    document.querySelectorAll('[data-abrir]').forEach((b) => {
        b.addEventListener('click', () => {
            const ventana = document.getElementById(b.dataset.abrir);
            if (ventana && ventana.showModal) ventana.showModal();
        });
    });

    document.querySelectorAll('dialog').forEach((ventana) => {
        ventana.querySelectorAll('[data-cerrar]').forEach((b) => {
            b.addEventListener('click', () => ventana.close());
        });
        // Cerrar al hacer clic fuera del contenido
        ventana.addEventListener('click', (e) => {
            if (e.target === ventana) ventana.close();
        });
    });
})();
