"""The 6-stage progress stepper shown at the top of every screen."""

STEPS = ["Connect", "Test", "Generate", "Deploy", "Register", "Query"]


def render_stepper(slot, active: int) -> None:
    """Render the 6-stage progress stepper into `slot`.

    Steps before `active` render as done, the one at `active` is highlighted.
    """
    cells = []
    for i, name in enumerate(STEPS):
        state = "done" if i < active else ("active" if i == active else "")
        mark = "✓" if i < active else str(i + 1)
        cells.append(
            f'<div class="step {state}">'
            f'<div class="dot">{mark}</div>'
            f'<div class="label">{name}</div>'
            f'</div>'
        )
    slot.markdown(f'<div class="stepper">{"".join(cells)}</div>', unsafe_allow_html=True)
