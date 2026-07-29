# Admin design and accessibility report

The panel follows the supplied xAI design system: it defaults to the operating system’s light or dark appearance, with explicit Auto, Light, and Dark controls persisted in the browser. Dark mode uses the `#0a0a0a` canvas, white type, compact charcoal surfaces, hairline borders, 8px cards, and outline-pill controls; light mode retains the same contrast and hierarchy. The only additional accent is a contained green revenue treatment, required for data-series readability where the source design has no green semantic token.

The operational layout avoids marketing chrome: a responsive navigation shell, real data tables, an accessible SVG revenue chart, and data-bound detail dialogs. It has no placeholder metrics, decorative charts, gradients, or ambient animation.

Keyboard and motion checks included:

- Skip link, semantic navigation, `aria-current`, visible focus, and no positive `tabindex`.
- Table actions are real buttons; every search input has a label and pagination announces the current page.
- Dialogs provide semantic dialog markup, focus placement and trapping, Escape close, focus restoration, scroll lock, and inert background content.
- Revenue points work with hover, click, and keyboard focus. The highlight ripple is bounded and disabled by `prefers-reduced-motion`.
- The mobile navigation becomes an accessible drawer. Tables scroll intentionally within their region instead of forcing page overflow.
- CSS uses logical layout properties where direction matters and sets document `dir` for Arabic and Persian.

The responsive design uses 270px as its lower bound, one-column metrics on narrow screens, 44px form controls, and overflow-contained tables. Appearance controls and French/Russian language choices are available before sign-in and move into the mobile menu on narrow screens. Production visual review should still be performed at 270, 320, 360, 375, 390, 768, 1024, 1280, and 1440px against real deployment data.
